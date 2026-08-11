from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.factors import (
    CoreUpstreamAuthority,
    FactorEvaluation,
    UnresolvedIdUpstreamTruthBinding,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


def _require_text(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _require_artifact(value: str, name: str) -> None:
    if not value.startswith("art_sha256_"):
        raise ValueError(f"{name} must be a content-addressed Artifact")


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class LabelMissingSemantics(StrEnum):
    EXCLUDE_SAMPLE = "EXCLUDE_SAMPLE"


@dataclass(frozen=True, slots=True)
class FeatureSetVersion:
    feature_set_version_id: str
    factor_evaluation_ids: tuple[str, ...]
    feature_materialization_ids: tuple[str, ...]
    provenance_artifact_id: str

    @classmethod
    def create(
        cls,
        evaluations: tuple[FactorEvaluation, ...],
        provenance_artifact_id: str,
    ) -> FeatureSetVersion:
        if not evaluations:
            raise ValueError("FeatureSetVersion requires at least one FactorEvaluation")
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        evaluation_ids = tuple(
            sorted(value.factor_evaluation_id for value in evaluations)
        )
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("FeatureSetVersion cannot contain duplicate evaluations")
        materialization_ids = tuple(
            sorted(value.feature_materialization_id for value in evaluations)
        )
        payload = {
            "factor_evaluation_ids": list(evaluation_ids),
            "feature_materialization_ids": list(materialization_ids),
            "provenance_artifact_id": provenance_artifact_id,
        }
        return cls(
            feature_set_version_id="fsv_sha256_" + canonical_sha256(payload),
            factor_evaluation_ids=evaluation_ids,
            feature_materialization_ids=materialization_ids,
            provenance_artifact_id=provenance_artifact_id,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "feature_set_version_id": self.feature_set_version_id,
            "factor_evaluation_ids": list(self.factor_evaluation_ids),
            "feature_materialization_ids": list(self.feature_materialization_ids),
            "provenance_artifact_id": self.provenance_artifact_id,
        }


@dataclass(frozen=True, slots=True)
class LabelSpec:
    label_spec_id: str
    logical_name: str
    source_field: str
    horizon_observations: int
    availability_lag_observations: int
    missing_semantics: LabelMissingSemantics

    @classmethod
    def create(
        cls,
        logical_name: str,
        source_field: str,
        horizon_observations: int,
        availability_lag_observations: int,
        missing_semantics: LabelMissingSemantics = LabelMissingSemantics.EXCLUDE_SAMPLE,
    ) -> LabelSpec:
        _require_text(logical_name, "logical_name")
        _require_text(source_field, "source_field")
        if horizon_observations < 1:
            raise ValueError("label horizon must be positive")
        if availability_lag_observations < 0:
            raise ValueError("label availability lag cannot be negative")
        if not isinstance(missing_semantics, LabelMissingSemantics):
            raise TypeError("missing_semantics must be LabelMissingSemantics")
        payload = {
            "logical_name": logical_name,
            "source_field": source_field,
            "horizon_observations": horizon_observations,
            "availability_lag_observations": availability_lag_observations,
            "missing_semantics": missing_semantics.value,
        }
        return cls(
            label_spec_id="lbl_sha256_" + canonical_sha256(payload),
            logical_name=logical_name,
            source_field=source_field,
            horizon_observations=horizon_observations,
            availability_lag_observations=availability_lag_observations,
            missing_semantics=missing_semantics,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "label_spec_id": self.label_spec_id,
            "logical_name": self.logical_name,
            "source_field": self.source_field,
            "horizon_observations": self.horizon_observations,
            "availability_lag_observations": self.availability_lag_observations,
            "missing_semantics": self.missing_semantics.value,
        }


@dataclass(frozen=True, slots=True)
class SplitSpec:
    split_spec_id: str
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int
    purge_observations: int
    embargo_observations: int

    @classmethod
    def create(
        cls,
        *,
        train_start: int,
        train_end: int,
        validation_start: int,
        validation_end: int,
        test_start: int,
        test_end: int,
        purge_observations: int,
        embargo_observations: int,
    ) -> SplitSpec:
        boundaries = (
            train_start,
            train_end,
            validation_start,
            validation_end,
            test_start,
            test_end,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in boundaries):
            raise TypeError("split boundaries must be integer observation ordinals")
        if not (
            0 <= train_start <= train_end < validation_start <= validation_end < test_start <= test_end
        ):
            raise ValueError("split ranges must be chronological and non-overlapping")
        if purge_observations < 0 or embargo_observations < 0:
            raise ValueError("purge and embargo must be non-negative")
        payload = {
            "train_start": train_start,
            "train_end": train_end,
            "validation_start": validation_start,
            "validation_end": validation_end,
            "test_start": test_start,
            "test_end": test_end,
            "purge_observations": purge_observations,
            "embargo_observations": embargo_observations,
        }
        return cls(
            split_spec_id="spl_sha256_" + canonical_sha256(payload),
            **payload,
        )

    def validate_for_label(self, label: LabelSpec) -> None:
        required_train_gap = (
            label.horizon_observations
            + label.availability_lag_observations
            + self.purge_observations
        )
        required_validation_gap = (
            label.horizon_observations
            + label.availability_lag_observations
            + self.embargo_observations
        )
        train_gap = self.validation_start - self.train_end - 1
        validation_gap = self.test_start - self.validation_end - 1
        if train_gap < required_train_gap:
            raise ValueError("train/validation split is not purge-safe for the label")
        if validation_gap < required_validation_gap:
            raise ValueError("validation/test split is not embargo-safe for the label")

    def to_wire(self) -> dict[str, int | str]:
        return {
            "split_spec_id": self.split_spec_id,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "purge_observations": self.purge_observations,
            "embargo_observations": self.embargo_observations,
        }


@dataclass(frozen=True, slots=True)
class DatasetBinding:
    snapshot_id: str
    universe_version_id: str
    snapshot_truth_binding: UnresolvedIdUpstreamTruthBinding
    universe_truth_binding: UnresolvedIdUpstreamTruthBinding
    knowledge_cutoff: datetime
    calendar_version_id: str
    schema_version_id: str
    environment_fingerprint: str
    evaluator_version: str

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "universe_version_id",
            "calendar_version_id",
            "schema_version_id",
            "environment_fingerprint",
            "evaluator_version",
        ):
            _require_text(getattr(self, name), name)
        _wire_time(self.knowledge_cutoff)
        if self.snapshot_id == self.universe_version_id:
            raise ValueError("Snapshot and Universe upstream identities must be distinct")
        self._require_core_binding(
            self.snapshot_truth_binding,
            CoreUpstreamAuthority.SNAPSHOT,
            self.snapshot_id,
        )
        self._require_core_binding(
            self.universe_truth_binding,
            CoreUpstreamAuthority.UNIVERSE,
            self.universe_version_id,
        )

    @staticmethod
    def _require_core_binding(
        binding: UnresolvedIdUpstreamTruthBinding,
        authority: CoreUpstreamAuthority,
        expected_source_id: str,
    ) -> None:
        if not isinstance(binding, UnresolvedIdUpstreamTruthBinding):
            raise TypeError("Dataset core upstream truth binding must be typed")
        if binding.authority is not authority:
            raise ValueError(f"Dataset {authority.value} binding has the wrong authority type")
        if binding.source_id != expected_source_id:
            raise ValueError(
                f"Dataset {authority.value} truth binding must match the exact bound identity"
            )

    @property
    def upstream_requirements(self) -> tuple[UpstreamRequirement, ...]:
        return (
            self.snapshot_truth_binding.to_requirement(),
            self.universe_truth_binding.to_requirement(),
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "universe_version_id": self.universe_version_id,
            "snapshot_truth_binding": self.snapshot_truth_binding.to_wire(),
            "universe_truth_binding": self.universe_truth_binding.to_wire(),
            "knowledge_cutoff": _wire_time(self.knowledge_cutoff),
            "calendar_version_id": self.calendar_version_id,
            "schema_version_id": self.schema_version_id,
            "environment_fingerprint": self.environment_fingerprint,
            "evaluator_version": self.evaluator_version,
        }


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_version_id: str
    feature_set_version_id: str
    factor_evaluation_ids: tuple[str, ...]
    label_spec_id: str
    split_spec_id: str
    binding: DatasetBinding
    dataset_artifact_id: str
    provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        feature_set: FeatureSetVersion,
        evaluations: tuple[FactorEvaluation, ...],
        label_spec: LabelSpec,
        split_spec: SplitSpec,
        binding: DatasetBinding,
        dataset_artifact_id: str,
        provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> DatasetVersion:
        _require_artifact(dataset_artifact_id, "dataset_artifact_id")
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        if not evaluations:
            raise ValueError("DatasetVersion requires exact FactorEvaluation bindings")
        exact_evaluation_ids = tuple(
            sorted(value.factor_evaluation_id for value in evaluations)
        )
        if exact_evaluation_ids != feature_set.factor_evaluation_ids:
            raise ValueError("FeatureSetVersion/evaluation bindings do not match")
        split_spec.validate_for_label(label_spec)
        for evaluation in evaluations:
            context = evaluation.context
            observed = (
                context.snapshot_id,
                context.universe_version_id,
                context.snapshot_truth_binding,
                context.universe_truth_binding,
                context.knowledge_cutoff,
                context.calendar_version_id,
                context.schema_version_id,
                context.environment_fingerprint,
                context.evaluator_version,
            )
            expected = (
                binding.snapshot_id,
                binding.universe_version_id,
                binding.snapshot_truth_binding,
                binding.universe_truth_binding,
                binding.knowledge_cutoff,
                binding.calendar_version_id,
                binding.schema_version_id,
                binding.environment_fingerprint,
                binding.evaluator_version,
            )
            if observed != expected:
                raise ValueError("Dataset binding must match every FactorEvaluation context")
        upstreams = (
            *binding.upstream_requirements,
            *(
                UpstreamRequirement(value.factor_evaluation_id, value.truth_admission)
                for value in evaluations
            ),
        )
        truth_admission = propagate_downstream_ceiling(proposed_state, upstreams)
        payload = {
            "feature_set_version_id": feature_set.feature_set_version_id,
            "factor_evaluation_ids": list(exact_evaluation_ids),
            "label_spec_id": label_spec.label_spec_id,
            "split_spec_id": split_spec.split_spec_id,
            "binding": binding.to_wire(),
            "dataset_artifact_id": dataset_artifact_id,
            "provenance_artifact_id": provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            dataset_version_id="dsv_sha256_" + canonical_sha256(payload),
            feature_set_version_id=feature_set.feature_set_version_id,
            factor_evaluation_ids=exact_evaluation_ids,
            label_spec_id=label_spec.label_spec_id,
            split_spec_id=split_spec.split_spec_id,
            binding=binding,
            dataset_artifact_id=dataset_artifact_id,
            provenance_artifact_id=provenance_artifact_id,
            truth_admission=truth_admission,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "dataset_version_id": self.dataset_version_id,
            "feature_set_version_id": self.feature_set_version_id,
            "factor_evaluation_ids": list(self.factor_evaluation_ids),
            "label_spec_id": self.label_spec_id,
            "split_spec_id": self.split_spec_id,
            "binding": self.binding.to_wire(),
            "dataset_artifact_id": self.dataset_artifact_id,
            "provenance_artifact_id": self.provenance_artifact_id,
            "truth_admission": self.truth_admission.to_wire(),
        }


__all__ = [
    "DatasetBinding",
    "DatasetVersion",
    "FeatureSetVersion",
    "LabelMissingSemantics",
    "LabelSpec",
    "SplitSpec",
]
