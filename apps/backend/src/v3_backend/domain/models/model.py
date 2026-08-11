from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from v3_backend.contracts.common.truth_admission import (
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.datasets import DatasetVersion, SplitSpec
from v3_backend.provenance.canonical_hash import (
    canonical_artifact_id,
    canonical_json,
    canonical_sha256,
)


SAFE_LINEAR_MODEL_MEDIA_TYPE = "application/vnd.v3.safe-linear-model+json;version=1"
SAFE_LINEAR_MODEL_SCHEMA_VERSION = "v3.safe-linear-model/1"
MODEL_WORKER_PROTOCOL_VERSION = "v3.model-worker/1"


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _require_artifact(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.startswith("art_sha256_"):
        raise ValueError(f"{name} must be a content-addressed Artifact")


def _require_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _wire_time(value: datetime) -> str:
    _require_aware(value, "timestamp")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _strict_object(
    payload: object, expected: frozenset[str], name: str
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    if set(payload) != expected:
        raise ValueError(f"{name} keys must be exactly {sorted(expected)}")
    return payload


class ModelAlgorithmFamily(StrEnum):
    RIDGE_REGRESSION = "RIDGE_REGRESSION"


class FeatureDtype(StrEnum):
    FLOAT64 = "FLOAT64"


class MissingValuePolicy(StrEnum):
    REJECT = "REJECT"


class DatasetSplitRole(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class FeatureColumn:
    column_id: str
    dtype: FeatureDtype = FeatureDtype.FLOAT64

    def __post_init__(self) -> None:
        _require_text(self.column_id, "column_id")
        if not isinstance(self.dtype, FeatureDtype):
            raise TypeError("dtype must be FeatureDtype")

    def to_wire(self) -> dict[str, str]:
        return {"column_id": self.column_id, "dtype": self.dtype.value}


@dataclass(frozen=True, slots=True)
class WorkerRuntimeFingerprint:
    backend_name: str
    backend_version: str
    protocol_version: str
    python_version: str
    platform: str
    packages: tuple[tuple[str, str], ...]
    thread_limits: tuple[tuple[str, str], ...]
    fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        backend_name: str,
        backend_version: str,
        protocol_version: str,
        python_version: str,
        platform: str,
        packages: tuple[tuple[str, str], ...],
        thread_limits: tuple[tuple[str, str], ...],
    ) -> WorkerRuntimeFingerprint:
        for name, value in (
            ("backend_name", backend_name),
            ("backend_version", backend_version),
            ("protocol_version", protocol_version),
            ("python_version", python_version),
            ("platform", platform),
        ):
            _require_text(value, name)
        ordered_packages = tuple(sorted(packages))
        ordered_limits = tuple(sorted(thread_limits))
        if not ordered_packages:
            raise ValueError("worker runtime requires exact package versions")
        if len({name for name, _ in ordered_packages}) != len(ordered_packages):
            raise ValueError("worker package names must be unique")
        for name, version in (*ordered_packages, *ordered_limits):
            _require_text(name, "runtime key")
            _require_text(version, "runtime value")
        payload = {
            "backend_name": backend_name,
            "backend_version": backend_version,
            "protocol_version": protocol_version,
            "python_version": python_version,
            "platform": platform,
            "packages": [list(item) for item in ordered_packages],
            "thread_limits": [list(item) for item in ordered_limits],
        }
        return cls(
            backend_name=backend_name,
            backend_version=backend_version,
            protocol_version=protocol_version,
            python_version=python_version,
            platform=platform,
            packages=ordered_packages,
            thread_limits=ordered_limits,
            fingerprint="mrt_sha256_" + canonical_sha256(payload),
        )

    @classmethod
    def from_wire(cls, payload: object) -> WorkerRuntimeFingerprint:
        observed = _strict_object(
            payload,
            frozenset(
                {
                    "backend_name",
                    "backend_version",
                    "protocol_version",
                    "python_version",
                    "platform",
                    "packages",
                    "thread_limits",
                    "fingerprint",
                }
            ),
            "worker runtime",
        )
        packages = observed["packages"]
        limits = observed["thread_limits"]
        if not isinstance(packages, list) or not isinstance(limits, list):
            raise ValueError("worker runtime packages/thread_limits must be arrays")

        def pairs(values: list[object], name: str) -> tuple[tuple[str, str], ...]:
            result: list[tuple[str, str]] = []
            for value in values:
                if (
                    not isinstance(value, list)
                    or len(value) != 2
                    or not all(isinstance(item, str) for item in value)
                ):
                    raise ValueError(f"{name} entries must be [name, version] strings")
                result.append((value[0], value[1]))
            return tuple(result)

        runtime = cls.create(
            backend_name=observed["backend_name"],
            backend_version=observed["backend_version"],
            protocol_version=observed["protocol_version"],
            python_version=observed["python_version"],
            platform=observed["platform"],
            packages=pairs(packages, "packages"),
            thread_limits=pairs(limits, "thread_limits"),
        )
        if observed["fingerprint"] != runtime.fingerprint:
            raise ValueError("worker runtime fingerprint does not match its descriptor")
        return runtime

    def to_wire(self) -> dict[str, object]:
        return {
            "backend_name": self.backend_name,
            "backend_version": self.backend_version,
            "protocol_version": self.protocol_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "packages": [list(item) for item in self.packages],
            "thread_limits": [list(item) for item in self.thread_limits],
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class TrainingSpecVersion:
    training_spec_version_id: str
    algorithm_family: ModelAlgorithmFamily
    alpha: float
    fit_intercept: bool
    solver: str
    feature_schema: tuple[FeatureColumn, ...]
    feature_schema_fingerprint: str
    feature_set_version_id: str
    factor_evaluation_ids: tuple[str, ...]
    label_spec_id: str
    split_spec_id: str
    training_split_ref: DatasetSplitRole
    validation_split_ref: DatasetSplitRole
    seed: int
    environment_profile_id: str
    dependency_runtime_fingerprint: str
    missing_value_policy: MissingValuePolicy

    @classmethod
    def create(
        cls,
        *,
        dataset: DatasetVersion,
        feature_schema: tuple[FeatureColumn, ...],
        seed: int,
        environment_profile_id: str,
        dependency_runtime_fingerprint: str,
        alpha: float = 1.0,
        fit_intercept: bool = True,
    ) -> TrainingSpecVersion:
        if not feature_schema:
            raise ValueError("TrainingSpecVersion requires ordered feature schema")
        if any(not isinstance(value, FeatureColumn) for value in feature_schema):
            raise TypeError("feature_schema must contain FeatureColumn values")
        feature_ids = tuple(value.column_id for value in feature_schema)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature_schema column IDs must be unique")
        if feature_ids != dataset.factor_evaluation_ids:
            raise ValueError(
                "feature schema must exactly match DatasetVersion factor evaluation order"
            )
        _require_text(environment_profile_id, "environment_profile_id")
        _require_text(
            dependency_runtime_fingerprint, "dependency_runtime_fingerprint"
        )
        if not dependency_runtime_fingerprint.startswith("mrt_sha256_"):
            raise ValueError("dependency runtime must use a verified worker fingerprint")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        alpha = _require_finite(alpha, "alpha")
        if alpha < 0:
            raise ValueError("alpha must be non-negative")
        if not isinstance(fit_intercept, bool):
            raise TypeError("fit_intercept must be bool")
        schema_wire = [value.to_wire() for value in feature_schema]
        schema_fingerprint = "mfs_sha256_" + canonical_sha256(schema_wire)
        payload = {
            "algorithm_family": ModelAlgorithmFamily.RIDGE_REGRESSION.value,
            "hyperparameters": {
                "alpha": alpha,
                "fit_intercept": fit_intercept,
                "solver": "svd",
            },
            "feature_schema": schema_wire,
            "feature_schema_fingerprint": schema_fingerprint,
            "feature_set_version_id": dataset.feature_set_version_id,
            "factor_evaluation_ids": list(dataset.factor_evaluation_ids),
            "label_spec_id": dataset.label_spec_id,
            "split_spec_id": dataset.split_spec_id,
            "training_split_ref": DatasetSplitRole.TRAIN.value,
            "validation_split_ref": DatasetSplitRole.VALIDATION.value,
            "seed": seed,
            "environment_profile_id": environment_profile_id,
            "dependency_runtime_fingerprint": dependency_runtime_fingerprint,
            "missing_value_policy": MissingValuePolicy.REJECT.value,
        }
        return cls(
            training_spec_version_id="trspec_sha256_" + canonical_sha256(payload),
            algorithm_family=ModelAlgorithmFamily.RIDGE_REGRESSION,
            alpha=alpha,
            fit_intercept=fit_intercept,
            solver="svd",
            feature_schema=feature_schema,
            feature_schema_fingerprint=schema_fingerprint,
            feature_set_version_id=dataset.feature_set_version_id,
            factor_evaluation_ids=dataset.factor_evaluation_ids,
            label_spec_id=dataset.label_spec_id,
            split_spec_id=dataset.split_spec_id,
            training_split_ref=DatasetSplitRole.TRAIN,
            validation_split_ref=DatasetSplitRole.VALIDATION,
            seed=seed,
            environment_profile_id=environment_profile_id,
            dependency_runtime_fingerprint=dependency_runtime_fingerprint,
            missing_value_policy=MissingValuePolicy.REJECT,
        )

    @property
    def feature_order(self) -> tuple[str, ...]:
        return tuple(value.column_id for value in self.feature_schema)

    def to_wire(self) -> dict[str, object]:
        return {
            "training_spec_version_id": self.training_spec_version_id,
            "algorithm_family": self.algorithm_family.value,
            "hyperparameters": {
                "alpha": self.alpha,
                "fit_intercept": self.fit_intercept,
                "solver": self.solver,
            },
            "feature_schema": [value.to_wire() for value in self.feature_schema],
            "feature_schema_fingerprint": self.feature_schema_fingerprint,
            "feature_set_version_id": self.feature_set_version_id,
            "factor_evaluation_ids": list(self.factor_evaluation_ids),
            "label_spec_id": self.label_spec_id,
            "split_spec_id": self.split_spec_id,
            "training_split_ref": self.training_split_ref.value,
            "validation_split_ref": self.validation_split_ref.value,
            "seed": self.seed,
            "environment_profile_id": self.environment_profile_id,
            "dependency_runtime_fingerprint": self.dependency_runtime_fingerprint,
            "missing_value_policy": self.missing_value_policy.value,
        }


@dataclass(frozen=True, slots=True)
class ModelSample:
    sample_id: str
    instrument_id: str
    observation_ordinal: int
    event_time: datetime
    decision_time: datetime
    features: tuple[float, ...]
    label: float | None = None

    def __post_init__(self) -> None:
        _require_text(self.sample_id, "sample_id")
        _require_text(self.instrument_id, "instrument_id")
        if (
            not isinstance(self.observation_ordinal, int)
            or isinstance(self.observation_ordinal, bool)
            or self.observation_ordinal < 0
        ):
            raise ValueError("observation_ordinal must be a non-negative integer")
        _require_aware(self.event_time, "event_time")
        _require_aware(self.decision_time, "decision_time")
        if self.decision_time < self.event_time:
            raise ValueError("decision_time cannot precede event_time")
        if not self.features:
            raise ValueError("model sample requires features")
        for index, value in enumerate(self.features):
            _require_finite(value, f"features[{index}]")
        if self.label is not None:
            _require_finite(self.label, "label")

    def feature_wire(self) -> list[float]:
        return [float(value) for value in self.features]

    def prediction_identity_wire(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "instrument_id": self.instrument_id,
            "observation_ordinal": self.observation_ordinal,
            "event_time": _wire_time(self.event_time),
            "decision_time": _wire_time(self.decision_time),
            "features": self.feature_wire(),
        }


def split_role(split_spec: SplitSpec, ordinal: int) -> DatasetSplitRole:
    if split_spec.train_start <= ordinal <= split_spec.train_end:
        return DatasetSplitRole.TRAIN
    if split_spec.validation_start <= ordinal <= split_spec.validation_end:
        return DatasetSplitRole.VALIDATION
    if split_spec.test_start <= ordinal <= split_spec.test_end:
        return DatasetSplitRole.TEST
    raise ValueError("sample ordinal is outside the exact DatasetVersion split ranges")


def _ordered_samples(samples: tuple[ModelSample, ...]) -> tuple[ModelSample, ...]:
    if not samples:
        raise ValueError("at least one model sample is required")
    if any(not isinstance(value, ModelSample) for value in samples):
        raise TypeError("samples must contain ModelSample values")
    ordered = tuple(
        sorted(
            samples,
            key=lambda value: (
                value.observation_ordinal,
                value.instrument_id,
                value.sample_id,
            ),
        )
    )
    sample_ids = tuple(value.sample_id for value in ordered)
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("sample IDs must be unique")
    return ordered


@dataclass(frozen=True, slots=True)
class TrainingDatasetView:
    dataset_version_id: str
    training_spec_version_id: str
    split_spec_id: str
    train_samples: tuple[ModelSample, ...]
    validation_samples: tuple[ModelSample, ...]
    train_row_set_hash: str
    validation_row_set_hash: str

    @classmethod
    def create(
        cls,
        *,
        dataset: DatasetVersion,
        split_spec: SplitSpec,
        training_spec: TrainingSpecVersion,
        samples: tuple[ModelSample, ...],
    ) -> TrainingDatasetView:
        if dataset.split_spec_id != split_spec.split_spec_id:
            raise ValueError("SplitSpec must bind the exact DatasetVersion")
        if training_spec.split_spec_id != dataset.split_spec_id:
            raise ValueError("TrainingSpec must bind the exact DatasetVersion SplitSpec")
        if training_spec.label_spec_id != dataset.label_spec_id:
            raise ValueError("TrainingSpec must bind the exact DatasetVersion LabelSpec")
        if training_spec.feature_set_version_id != dataset.feature_set_version_id:
            raise ValueError("TrainingSpec must bind the exact DatasetVersion FeatureSet")
        if training_spec.factor_evaluation_ids != dataset.factor_evaluation_ids:
            raise ValueError("TrainingSpec must bind exact DatasetVersion factor evaluations")
        ordered = _ordered_samples(samples)
        train: list[ModelSample] = []
        validation: list[ModelSample] = []
        for sample in ordered:
            if len(sample.features) != len(training_spec.feature_schema):
                raise ValueError("sample feature count does not match ordered feature schema")
            if sample.label is None:
                raise ValueError("training and validation samples require explicit labels")
            role = split_role(split_spec, sample.observation_ordinal)
            if role is DatasetSplitRole.TEST:
                raise ValueError("final-test rows are forbidden from model training/tuning")
            (train if role is DatasetSplitRole.TRAIN else validation).append(sample)
        if len(train) < 2:
            raise ValueError("training view requires at least two TRAIN rows")
        if not validation:
            raise ValueError("training view requires explicit VALIDATION rows")

        def row_wire(value: ModelSample) -> dict[str, object]:
            return {**value.prediction_identity_wire(), "label": float(value.label)}

        return cls(
            dataset_version_id=dataset.dataset_version_id,
            training_spec_version_id=training_spec.training_spec_version_id,
            split_spec_id=split_spec.split_spec_id,
            train_samples=tuple(train),
            validation_samples=tuple(validation),
            train_row_set_hash="mrs_sha256_"
            + canonical_sha256([row_wire(value) for value in train]),
            validation_row_set_hash="mrs_sha256_"
            + canonical_sha256([row_wire(value) for value in validation]),
        )

    @property
    def train_sample_ids(self) -> tuple[str, ...]:
        return tuple(value.sample_id for value in self.train_samples)

    @property
    def validation_sample_ids(self) -> tuple[str, ...]:
        return tuple(value.sample_id for value in self.validation_samples)


@dataclass(frozen=True, slots=True)
class PredictionDatasetView:
    dataset_version_id: str
    model_version_id: str
    training_spec_version_id: str
    samples: tuple[ModelSample, ...]
    row_set_hash: str

    @classmethod
    def create(
        cls,
        *,
        dataset: DatasetVersion,
        model: ModelVersion,
        training_spec: TrainingSpecVersion,
        samples: tuple[ModelSample, ...],
    ) -> PredictionDatasetView:
        if model.training_spec_version_id != training_spec.training_spec_version_id:
            raise ValueError("prediction must use the exact ModelVersion TrainingSpec")
        if training_spec.feature_schema_fingerprint != model.feature_schema_fingerprint:
            raise ValueError("prediction feature schema does not match ModelVersion")
        if training_spec.feature_set_version_id != dataset.feature_set_version_id:
            raise ValueError("prediction DatasetVersion FeatureSet does not match model")
        if training_spec.factor_evaluation_ids != dataset.factor_evaluation_ids:
            raise ValueError(
                "prediction DatasetVersion factor evaluations do not match model"
            )
        if training_spec.label_spec_id != dataset.label_spec_id:
            raise ValueError("prediction DatasetVersion LabelSpec does not match model")
        ordered = _ordered_samples(samples)
        for sample in ordered:
            if len(sample.features) != len(training_spec.feature_schema):
                raise ValueError("prediction feature count does not match ordered schema")
        payload = [value.prediction_identity_wire() for value in ordered]
        return cls(
            dataset_version_id=dataset.dataset_version_id,
            model_version_id=model.model_version_id,
            training_spec_version_id=training_spec.training_spec_version_id,
            samples=ordered,
            row_set_hash="mrs_sha256_" + canonical_sha256(payload),
        )

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(value.sample_id for value in self.samples)


@dataclass(frozen=True, slots=True)
class ModelTrainingBinding:
    model_training_binding_id: str
    dataset_version_id: str
    training_spec_version_id: str
    code_version: str
    worker_runtime: WorkerRuntimeFingerprint
    seed: int
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        dataset: DatasetVersion,
        training_spec: TrainingSpecVersion,
        code_version: str,
        worker_runtime: WorkerRuntimeFingerprint,
        proposed_state: TruthAdmissionState,
    ) -> ModelTrainingBinding:
        _require_text(code_version, "code_version")
        if training_spec.label_spec_id != dataset.label_spec_id:
            raise ValueError("training binding requires exact DatasetVersion LabelSpec")
        if training_spec.feature_set_version_id != dataset.feature_set_version_id:
            raise ValueError("training binding requires exact DatasetVersion FeatureSet")
        if training_spec.factor_evaluation_ids != dataset.factor_evaluation_ids:
            raise ValueError("training binding requires exact DatasetVersion factor evaluations")
        if training_spec.split_spec_id != dataset.split_spec_id:
            raise ValueError("training binding requires exact DatasetVersion SplitSpec")
        if (
            training_spec.dependency_runtime_fingerprint
            != worker_runtime.fingerprint
        ):
            raise ValueError("TrainingSpec runtime fingerprint must match exact worker")
        truth_admission = propagate_downstream_ceiling(
            proposed_state,
            (UpstreamRequirement(dataset.dataset_version_id, dataset.truth_admission),),
        )
        payload = {
            "dataset_version_id": dataset.dataset_version_id,
            "training_spec_version_id": training_spec.training_spec_version_id,
            "code_version": code_version,
            "worker_runtime": worker_runtime.to_wire(),
            "seed": training_spec.seed,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            model_training_binding_id="mtb_sha256_" + canonical_sha256(payload),
            dataset_version_id=dataset.dataset_version_id,
            training_spec_version_id=training_spec.training_spec_version_id,
            code_version=code_version,
            worker_runtime=worker_runtime,
            seed=training_spec.seed,
            truth_admission=truth_admission,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "model_training_binding_id": self.model_training_binding_id,
            "dataset_version_id": self.dataset_version_id,
            "training_spec_version_id": self.training_spec_version_id,
            "code_version": self.code_version,
            "worker_runtime": self.worker_runtime.to_wire(),
            "seed": self.seed,
            "truth_admission": self.truth_admission.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class ModelRun:
    model_run_id: str
    binding: ModelTrainingBinding
    train_row_set_hash: str
    validation_row_set_hash: str

    @classmethod
    def create(
        cls, binding: ModelTrainingBinding, view: TrainingDatasetView
    ) -> ModelRun:
        if binding.dataset_version_id != view.dataset_version_id:
            raise ValueError("ModelRun must bind exact training DatasetVersion")
        if binding.training_spec_version_id != view.training_spec_version_id:
            raise ValueError("ModelRun must bind exact TrainingSpecVersion")
        payload = {
            "binding": binding.to_wire(),
            "train_row_set_hash": view.train_row_set_hash,
            "validation_row_set_hash": view.validation_row_set_hash,
        }
        return cls(
            model_run_id="mdrun_sha256_" + canonical_sha256(payload),
            binding=binding,
            train_row_set_hash=view.train_row_set_hash,
            validation_row_set_hash=view.validation_row_set_hash,
        )


@dataclass(frozen=True, slots=True)
class WorkerTrainingCandidate:
    runtime: WorkerRuntimeFingerprint
    feature_order: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    train_sample_ids: tuple[str, ...]
    validation_sample_ids: tuple[str, ...]
    train_rmse: float
    validation_rmse: float
    seed: int

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, WorkerRuntimeFingerprint):
            raise TypeError("worker training runtime must be typed")
        if not self.feature_order or any(
            not isinstance(value, str) or not value for value in self.feature_order
        ):
            raise ValueError("worker feature order must contain non-empty strings")
        if len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("worker feature order must be unique")
        if len(self.coefficients) != len(self.feature_order):
            raise ValueError("worker coefficient count must match feature order")
        for index, value in enumerate(self.coefficients):
            _require_finite(value, f"coefficients[{index}]")
        _require_finite(self.intercept, "intercept")
        _require_finite(self.train_rmse, "train_rmse")
        _require_finite(self.validation_rmse, "validation_rmse")
        for name, values in (
            ("train_sample_ids", self.train_sample_ids),
            ("validation_sample_ids", self.validation_sample_ids),
        ):
            if not values or any(not isinstance(value, str) or not value for value in values):
                raise ValueError(f"{name} must contain non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("worker candidate seed must be non-negative integer")

    @classmethod
    def from_wire(cls, payload: object) -> WorkerTrainingCandidate:
        observed = _strict_object(
            payload,
            frozenset(
                {
                    "runtime",
                    "feature_order",
                    "coefficients",
                    "intercept",
                    "train_sample_ids",
                    "validation_sample_ids",
                    "train_rmse",
                    "validation_rmse",
                    "seed",
                }
            ),
            "worker training candidate",
        )
        for name in (
            "feature_order",
            "coefficients",
            "train_sample_ids",
            "validation_sample_ids",
        ):
            if not isinstance(observed[name], list):
                raise ValueError(f"{name} must be an array")
        feature_order = tuple(observed["feature_order"])
        train_ids = tuple(observed["train_sample_ids"])
        validation_ids = tuple(observed["validation_sample_ids"])
        if any(not isinstance(value, str) for value in (*feature_order, *train_ids, *validation_ids)):
            raise ValueError("worker candidate identity arrays must contain strings")
        coefficients = tuple(
            _require_finite(value, "coefficient") for value in observed["coefficients"]
        )
        seed = observed["seed"]
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ValueError("worker candidate seed must be non-negative integer")
        return cls(
            runtime=WorkerRuntimeFingerprint.from_wire(observed["runtime"]),
            feature_order=feature_order,
            coefficients=coefficients,
            intercept=_require_finite(observed["intercept"], "intercept"),
            train_sample_ids=train_ids,
            validation_sample_ids=validation_ids,
            train_rmse=_require_finite(observed["train_rmse"], "train_rmse"),
            validation_rmse=_require_finite(
                observed["validation_rmse"], "validation_rmse"
            ),
            seed=seed,
        )


@dataclass(frozen=True, slots=True)
class TrainingEvidence:
    training_evidence_id: str
    model_run_id: str
    dataset_version_id: str
    split_spec_id: str
    train_sample_count: int
    validation_sample_count: int
    train_rmse: float
    validation_rmse: float
    seed: int
    worker_runtime_fingerprint: str
    provenance_artifact_id: str

    @classmethod
    def create(
        cls,
        *,
        run: ModelRun,
        view: TrainingDatasetView,
        candidate: WorkerTrainingCandidate,
        provenance_artifact_id: str,
    ) -> TrainingEvidence:
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        if candidate.runtime != run.binding.worker_runtime:
            raise ValueError("training candidate runtime must match ModelRun")
        if candidate.seed != run.binding.seed:
            raise ValueError("training candidate seed must match ModelRun")
        if candidate.train_sample_ids != view.train_sample_ids:
            raise ValueError("training candidate must bind exact TRAIN rows")
        if candidate.validation_sample_ids != view.validation_sample_ids:
            raise ValueError("training candidate must bind exact VALIDATION rows")
        payload = {
            "model_run_id": run.model_run_id,
            "dataset_version_id": view.dataset_version_id,
            "split_spec_id": view.split_spec_id,
            "train_sample_count": len(view.train_samples),
            "validation_sample_count": len(view.validation_samples),
            "train_rmse": candidate.train_rmse,
            "validation_rmse": candidate.validation_rmse,
            "seed": candidate.seed,
            "worker_runtime_fingerprint": candidate.runtime.fingerprint,
            "provenance_artifact_id": provenance_artifact_id,
        }
        return cls(
            training_evidence_id="mte_sha256_" + canonical_sha256(payload),
            model_run_id=run.model_run_id,
            dataset_version_id=view.dataset_version_id,
            split_spec_id=view.split_spec_id,
            train_sample_count=len(view.train_samples),
            validation_sample_count=len(view.validation_samples),
            train_rmse=candidate.train_rmse,
            validation_rmse=candidate.validation_rmse,
            seed=candidate.seed,
            worker_runtime_fingerprint=candidate.runtime.fingerprint,
            provenance_artifact_id=provenance_artifact_id,
        )


@dataclass(frozen=True, slots=True)
class SafeLinearModelArtifact:
    artifact_id: str
    media_type: str
    schema_version: str
    training_spec_version_id: str
    feature_order: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float

    def __post_init__(self) -> None:
        _require_artifact(self.artifact_id, "artifact_id")
        if self.media_type != SAFE_LINEAR_MODEL_MEDIA_TYPE:
            raise ValueError("unsafe or unsupported model artifact media type")
        if self.schema_version != SAFE_LINEAR_MODEL_SCHEMA_VERSION:
            raise ValueError("unsupported safe model artifact schema")
        _require_text(self.training_spec_version_id, "training_spec_version_id")
        if not self.training_spec_version_id.startswith("trspec_sha256_"):
            raise ValueError("safe model must bind a TrainingSpecVersion")
        if not self.feature_order:
            raise ValueError("safe model feature_order must be non-empty")
        for value in self.feature_order:
            _require_text(value, "feature_order entry")
        if len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("safe model feature_order must be unique")
        if len(self.coefficients) != len(self.feature_order):
            raise ValueError("safe model coefficient count must match feature_order")
        for index, value in enumerate(self.coefficients):
            _require_finite(value, f"coefficients[{index}]")
        _require_finite(self.intercept, "intercept")
        if self.artifact_id != canonical_artifact_id(self.payload()):
            raise ValueError("safe model artifact ID must match canonical payload")

    @classmethod
    def create(
        cls,
        training_spec: TrainingSpecVersion,
        candidate: WorkerTrainingCandidate,
    ) -> SafeLinearModelArtifact:
        if candidate.feature_order != training_spec.feature_order:
            raise ValueError("worker feature order must exactly match TrainingSpec")
        if len(candidate.coefficients) != len(training_spec.feature_schema):
            raise ValueError("worker coefficient count must match feature schema")
        payload = {
            "schema_version": SAFE_LINEAR_MODEL_SCHEMA_VERSION,
            "training_spec_version_id": training_spec.training_spec_version_id,
            "feature_order": list(candidate.feature_order),
            "coefficients": list(candidate.coefficients),
            "intercept": candidate.intercept,
        }
        return cls(
            artifact_id=canonical_artifact_id(payload),
            media_type=SAFE_LINEAR_MODEL_MEDIA_TYPE,
            schema_version=SAFE_LINEAR_MODEL_SCHEMA_VERSION,
            training_spec_version_id=training_spec.training_spec_version_id,
            feature_order=candidate.feature_order,
            coefficients=candidate.coefficients,
            intercept=candidate.intercept,
        )

    @classmethod
    def from_bytes(
        cls, media_type: str, payload_bytes: bytes
    ) -> SafeLinearModelArtifact:
        if media_type != SAFE_LINEAR_MODEL_MEDIA_TYPE:
            raise ValueError("unsafe or unsupported model artifact media type")
        try:
            text = payload_bytes.decode("utf-8")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("safe model artifact must be UTF-8 JSON") from error
        observed = _strict_object(
            payload,
            frozenset(
                {
                    "schema_version",
                    "training_spec_version_id",
                    "feature_order",
                    "coefficients",
                    "intercept",
                }
            ),
            "safe model artifact",
        )
        if observed["schema_version"] != SAFE_LINEAR_MODEL_SCHEMA_VERSION:
            raise ValueError("unsupported safe model artifact schema")
        feature_order = observed["feature_order"]
        coefficients = observed["coefficients"]
        if not isinstance(feature_order, list) or not isinstance(coefficients, list):
            raise ValueError("safe model feature_order/coefficients must be arrays")
        if any(not isinstance(value, str) for value in feature_order):
            raise ValueError("safe model feature_order must contain strings")
        coefficient_values = tuple(
            _require_finite(value, "coefficient") for value in coefficients
        )
        canonical = canonical_json(observed)
        if text != canonical:
            raise ValueError("safe model artifact JSON must be canonical")
        return cls(
            artifact_id=canonical_artifact_id(observed),
            media_type=media_type,
            schema_version=observed["schema_version"],
            training_spec_version_id=observed["training_spec_version_id"],
            feature_order=tuple(feature_order),
            coefficients=coefficient_values,
            intercept=_require_finite(observed["intercept"], "intercept"),
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "training_spec_version_id": self.training_spec_version_id,
            "feature_order": list(self.feature_order),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
        }

    def to_bytes(self) -> bytes:
        return canonical_json(self.payload()).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ModelVersion:
    model_version_id: str
    dataset_version_id: str
    model_run_id: str
    training_spec_version_id: str
    model_artifact_id: str
    model_artifact_media_type: str
    feature_schema_fingerprint: str
    worker_runtime: WorkerRuntimeFingerprint
    seed: int
    training_evidence_id: str
    provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        dataset: DatasetVersion,
        run: ModelRun,
        training_spec: TrainingSpecVersion,
        artifact: SafeLinearModelArtifact,
        training_evidence: TrainingEvidence,
        provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> ModelVersion:
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        if run.binding.dataset_version_id != dataset.dataset_version_id:
            raise ValueError("ModelVersion must bind exact DatasetVersion")
        if run.binding.training_spec_version_id != training_spec.training_spec_version_id:
            raise ValueError("ModelVersion must bind exact TrainingSpecVersion")
        if artifact.training_spec_version_id != training_spec.training_spec_version_id:
            raise ValueError("model Artifact must bind exact TrainingSpecVersion")
        if training_evidence.model_run_id != run.model_run_id:
            raise ValueError("training evidence must bind exact ModelRun")
        if training_evidence.dataset_version_id != dataset.dataset_version_id:
            raise ValueError("training evidence must bind exact DatasetVersion")
        truth_admission = propagate_downstream_ceiling(
            proposed_state,
            (UpstreamRequirement(dataset.dataset_version_id, dataset.truth_admission),),
        )
        payload = {
            "dataset_version_id": dataset.dataset_version_id,
            "model_run_id": run.model_run_id,
            "training_spec_version_id": training_spec.training_spec_version_id,
            "model_artifact_id": artifact.artifact_id,
            "model_artifact_media_type": artifact.media_type,
            "feature_schema_fingerprint": training_spec.feature_schema_fingerprint,
            "worker_runtime": run.binding.worker_runtime.to_wire(),
            "seed": training_spec.seed,
            "training_evidence_id": training_evidence.training_evidence_id,
            "provenance_artifact_id": provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            model_version_id="mdv_sha256_" + canonical_sha256(payload),
            dataset_version_id=dataset.dataset_version_id,
            model_run_id=run.model_run_id,
            training_spec_version_id=training_spec.training_spec_version_id,
            model_artifact_id=artifact.artifact_id,
            model_artifact_media_type=artifact.media_type,
            feature_schema_fingerprint=training_spec.feature_schema_fingerprint,
            worker_runtime=run.binding.worker_runtime,
            seed=training_spec.seed,
            training_evidence_id=training_evidence.training_evidence_id,
            provenance_artifact_id=provenance_artifact_id,
            truth_admission=truth_admission,
        )


@dataclass(frozen=True, slots=True)
class WorkerPredictionValue:
    sample_id: str
    value: float

    def __post_init__(self) -> None:
        _require_text(self.sample_id, "sample_id")
        _require_finite(self.value, "prediction")


@dataclass(frozen=True, slots=True)
class WorkerPredictionCandidate:
    runtime: WorkerRuntimeFingerprint
    feature_order: tuple[str, ...]
    predictions: tuple[WorkerPredictionValue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.runtime, WorkerRuntimeFingerprint):
            raise TypeError("worker prediction runtime must be typed")
        if not self.feature_order or any(
            not isinstance(value, str) or not value for value in self.feature_order
        ):
            raise ValueError("worker prediction feature order is required")
        if len(self.feature_order) != len(set(self.feature_order)):
            raise ValueError("worker prediction feature order must be unique")
        if not self.predictions or any(
            not isinstance(value, WorkerPredictionValue) for value in self.predictions
        ):
            raise ValueError("worker prediction values are required")
        sample_ids = tuple(value.sample_id for value in self.predictions)
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("worker prediction sample IDs must be unique")

    @classmethod
    def from_wire(cls, payload: object) -> WorkerPredictionCandidate:
        observed = _strict_object(
            payload,
            frozenset({"runtime", "feature_order", "predictions"}),
            "worker prediction candidate",
        )
        if not isinstance(observed["feature_order"], list):
            raise ValueError("feature_order must be an array")
        feature_order = tuple(observed["feature_order"])
        if any(not isinstance(value, str) for value in feature_order):
            raise ValueError("feature_order must contain strings")
        prediction_payload = observed["predictions"]
        if not isinstance(prediction_payload, list):
            raise ValueError("predictions must be an array")
        predictions: list[WorkerPredictionValue] = []
        for value in prediction_payload:
            item = _strict_object(
                value, frozenset({"sample_id", "value"}), "worker prediction"
            )
            _require_text(item["sample_id"], "sample_id")
            predictions.append(
                WorkerPredictionValue(
                    sample_id=item["sample_id"],
                    value=_require_finite(item["value"], "prediction"),
                )
            )
        sample_ids = tuple(value.sample_id for value in predictions)
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("worker prediction sample IDs must be unique")
        return cls(
            runtime=WorkerRuntimeFingerprint.from_wire(observed["runtime"]),
            feature_order=feature_order,
            predictions=tuple(predictions),
        )


@dataclass(frozen=True, slots=True)
class PredictionValue:
    sample_id: str
    instrument_id: str
    observation_ordinal: int
    event_time: datetime
    decision_time: datetime
    value: float

    def __post_init__(self) -> None:
        _require_text(self.sample_id, "sample_id")
        _require_text(self.instrument_id, "instrument_id")
        if (
            not isinstance(self.observation_ordinal, int)
            or isinstance(self.observation_ordinal, bool)
            or self.observation_ordinal < 0
        ):
            raise ValueError("observation_ordinal must be a non-negative integer")
        _require_aware(self.event_time, "event_time")
        _require_aware(self.decision_time, "decision_time")
        if self.decision_time < self.event_time:
            raise ValueError("decision_time cannot precede event_time")
        _require_finite(self.value, "prediction")

    def to_wire(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "instrument_id": self.instrument_id,
            "observation_ordinal": self.observation_ordinal,
            "event_time": _wire_time(self.event_time),
            "decision_time": _wire_time(self.decision_time),
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class PredictionArtifact:
    prediction_artifact_id: str
    model_version_id: str
    prediction_dataset_version_id: str
    prediction_row_set_hash: str
    feature_schema_fingerprint: str
    label_spec_id: str
    prediction_timestamp: datetime
    target_semantics: str
    values: tuple[PredictionValue, ...]
    missing_count: int
    nonfinite_count: int
    worker_runtime_fingerprint: str
    provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        model: ModelVersion,
        dataset: DatasetVersion,
        training_spec: TrainingSpecVersion,
        view: PredictionDatasetView,
        candidate: WorkerPredictionCandidate,
        prediction_timestamp: datetime,
        target_semantics: str,
        provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> PredictionArtifact:
        _require_aware(prediction_timestamp, "prediction_timestamp")
        _require_text(target_semantics, "target_semantics")
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        if view.dataset_version_id != dataset.dataset_version_id:
            raise ValueError("PredictionArtifact must bind exact prediction DatasetVersion")
        if view.model_version_id != model.model_version_id:
            raise ValueError("PredictionArtifact view must bind exact ModelVersion")
        if training_spec.training_spec_version_id != model.training_spec_version_id:
            raise ValueError("PredictionArtifact must use exact TrainingSpecVersion")
        if candidate.runtime != model.worker_runtime:
            raise ValueError("prediction worker runtime must match ModelVersion runtime")
        if candidate.feature_order != training_spec.feature_order:
            raise ValueError("prediction worker feature order must exactly match model")
        candidate_by_id = {value.sample_id: value.value for value in candidate.predictions}
        if set(candidate_by_id) != set(view.sample_ids):
            raise ValueError("prediction rows must exactly match DatasetVersion sample view")
        values = tuple(
            PredictionValue(
                sample_id=sample.sample_id,
                instrument_id=sample.instrument_id,
                observation_ordinal=sample.observation_ordinal,
                event_time=sample.event_time,
                decision_time=sample.decision_time,
                value=candidate_by_id[sample.sample_id],
            )
            for sample in view.samples
        )
        truth_admission = propagate_downstream_ceiling(
            proposed_state,
            (
                UpstreamRequirement(model.model_version_id, model.truth_admission),
                UpstreamRequirement(dataset.dataset_version_id, dataset.truth_admission),
            ),
        )
        payload = {
            "model_version_id": model.model_version_id,
            "prediction_dataset_version_id": dataset.dataset_version_id,
            "prediction_row_set_hash": view.row_set_hash,
            "feature_schema_fingerprint": training_spec.feature_schema_fingerprint,
            "label_spec_id": training_spec.label_spec_id,
            "prediction_timestamp": _wire_time(prediction_timestamp),
            "target_semantics": target_semantics,
            "values": [value.to_wire() for value in values],
            "missing_count": 0,
            "nonfinite_count": 0,
            "worker_runtime_fingerprint": candidate.runtime.fingerprint,
            "provenance_artifact_id": provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            prediction_artifact_id="pred_sha256_" + canonical_sha256(payload),
            model_version_id=model.model_version_id,
            prediction_dataset_version_id=dataset.dataset_version_id,
            prediction_row_set_hash=view.row_set_hash,
            feature_schema_fingerprint=training_spec.feature_schema_fingerprint,
            label_spec_id=training_spec.label_spec_id,
            prediction_timestamp=prediction_timestamp,
            target_semantics=target_semantics,
            values=values,
            missing_count=0,
            nonfinite_count=0,
            worker_runtime_fingerprint=candidate.runtime.fingerprint,
            provenance_artifact_id=provenance_artifact_id,
            truth_admission=truth_admission,
        )


@dataclass(frozen=True, slots=True)
class ModelEvaluationEvidence:
    model_evaluation_evidence_id: str
    model_version_id: str
    dataset_version_id: str
    prediction_artifact_id: str
    split_spec_id: str
    evaluated_split_role: DatasetSplitRole
    train_sample_count: int
    validation_sample_count: int
    evaluated_sample_count: int
    prediction_coverage: float
    rmse: float
    missing_count: int
    nonfinite_count: int
    stability_digest: str
    seed: int
    worker_runtime_fingerprint: str
    provenance_artifact_id: str

    @classmethod
    def create(
        cls,
        *,
        model: ModelVersion,
        dataset: DatasetVersion,
        training_evidence: TrainingEvidence,
        prediction: PredictionArtifact,
        prediction_view: PredictionDatasetView,
        split_spec: SplitSpec,
        provenance_artifact_id: str,
    ) -> ModelEvaluationEvidence:
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        if model.training_evidence_id != training_evidence.training_evidence_id:
            raise ValueError("evaluation must bind exact ModelVersion training evidence")
        if prediction.model_version_id != model.model_version_id:
            raise ValueError("evaluation prediction must bind exact ModelVersion")
        if prediction.prediction_dataset_version_id != dataset.dataset_version_id:
            raise ValueError("evaluation prediction must bind exact DatasetVersion")
        if dataset.split_spec_id != split_spec.split_spec_id:
            raise ValueError("evaluation SplitSpec must bind exact DatasetVersion")
        if prediction_view.sample_ids != tuple(value.sample_id for value in prediction.values):
            raise ValueError("evaluation prediction rows must match exact sample view")
        roles = {
            split_role(split_spec, sample.observation_ordinal)
            for sample in prediction_view.samples
        }
        if len(roles) != 1:
            raise ValueError("model evaluation must target exactly one split role")
        evaluated_role = next(iter(roles))
        if evaluated_role is DatasetSplitRole.TRAIN:
            raise ValueError("ModelEvaluation evidence cannot use TRAIN as evaluation split")
        labels: dict[str, float] = {}
        for sample in prediction_view.samples:
            if sample.label is None:
                raise ValueError("model evaluation requires explicit labels")
            labels[sample.sample_id] = float(sample.label)
        squared_errors = tuple(
            (value.value - labels[value.sample_id]) ** 2 for value in prediction.values
        )
        rmse = math.sqrt(math.fsum(squared_errors) / len(squared_errors))
        stability_digest = "mpd_sha256_" + canonical_sha256(
            [value.to_wire() for value in prediction.values]
        )
        payload = {
            "model_version_id": model.model_version_id,
            "dataset_version_id": dataset.dataset_version_id,
            "prediction_artifact_id": prediction.prediction_artifact_id,
            "split_spec_id": split_spec.split_spec_id,
            "evaluated_split_role": evaluated_role.value,
            "train_sample_count": training_evidence.train_sample_count,
            "validation_sample_count": training_evidence.validation_sample_count,
            "evaluated_sample_count": len(prediction.values),
            "prediction_coverage": 1.0,
            "rmse": rmse,
            "missing_count": prediction.missing_count,
            "nonfinite_count": prediction.nonfinite_count,
            "stability_digest": stability_digest,
            "seed": model.seed,
            "worker_runtime_fingerprint": model.worker_runtime.fingerprint,
            "provenance_artifact_id": provenance_artifact_id,
        }
        return cls(
            model_evaluation_evidence_id="mev_sha256_" + canonical_sha256(payload),
            model_version_id=model.model_version_id,
            dataset_version_id=dataset.dataset_version_id,
            prediction_artifact_id=prediction.prediction_artifact_id,
            split_spec_id=split_spec.split_spec_id,
            evaluated_split_role=evaluated_role,
            train_sample_count=training_evidence.train_sample_count,
            validation_sample_count=training_evidence.validation_sample_count,
            evaluated_sample_count=len(prediction.values),
            prediction_coverage=1.0,
            rmse=rmse,
            missing_count=prediction.missing_count,
            nonfinite_count=prediction.nonfinite_count,
            stability_digest=stability_digest,
            seed=model.seed,
            worker_runtime_fingerprint=model.worker_runtime.fingerprint,
            provenance_artifact_id=provenance_artifact_id,
        )


__all__ = [
    "DatasetSplitRole",
    "FeatureColumn",
    "FeatureDtype",
    "MissingValuePolicy",
    "ModelAlgorithmFamily",
    "ModelEvaluationEvidence",
    "ModelRun",
    "ModelSample",
    "ModelTrainingBinding",
    "ModelVersion",
    "PredictionArtifact",
    "PredictionDatasetView",
    "PredictionValue",
    "SAFE_LINEAR_MODEL_MEDIA_TYPE",
    "SafeLinearModelArtifact",
    "TrainingDatasetView",
    "TrainingEvidence",
    "TrainingSpecVersion",
    "WorkerPredictionCandidate",
    "WorkerRuntimeFingerprint",
    "WorkerTrainingCandidate",
    "split_role",
]
