from __future__ import annotations

import dataclasses
import math
import unittest
from datetime import datetime, timezone

from v3_backend.adapters.model_workers import (
    ModelWorkerError,
    SklearnRidgeSubprocessWorker,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.datasets import (
    DatasetBinding,
    DatasetVersion,
    FeatureSetVersion,
    LabelSpec,
    SplitSpec,
)
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.domain.models import (
    DatasetSplitRole,
    FeatureColumn,
    ModelSample,
    ModelTrainingBinding,
    ModelVersion,
    PredictionArtifact,
    PredictionDatasetView,
    SAFE_LINEAR_MODEL_MEDIA_TYPE,
    SafeLinearModelArtifact,
    TrainingDatasetView,
    TrainingEvidence,
    TrainingSpecVersion,
    WorkerPredictionCandidate,
    WorkerRuntimeFingerprint,
    WorkerTrainingCandidate,
    evaluate_prediction,
    predict_model,
    train_model,
)


def artifact(character: str) -> str:
    return "art_sha256_" + character * 64


def runtime(version: str = "1.9.0") -> WorkerRuntimeFingerprint:
    return WorkerRuntimeFingerprint.create(
        backend_name="scikit-learn-ridge",
        backend_version=version,
        protocol_version="v3.model-worker/1",
        python_version="3.14.7",
        platform="test-cpu",
        packages=(
            ("joblib", "1.5.3"),
            ("narwhals", "2.24.0"),
            ("numpy", "2.5.2"),
            ("scikit-learn", version),
            ("scipy", "1.18.0"),
            ("threadpoolctl", "3.6.0"),
        ),
        thread_limits=(
            ("MKL_NUM_THREADS", "1"),
            ("NUMEXPR_NUM_THREADS", "1"),
            ("OMP_NUM_THREADS", "1"),
            ("OPENBLAS_NUM_THREADS", "1"),
        ),
    )


def build_dataset(snapshot_id: str = "snapshot-1") -> tuple[DatasetVersion, SplitSpec]:
    registry = default_operator_registry()
    x_definition = FactorDefinitionVersion.create(
        "feature-x", FeatureNode("x", "feature.x/1.0.0"), registry
    )
    squared_definition = FactorDefinitionVersion.create(
        "feature-x-squared",
        FeatureNode("x_squared", "feature.x-squared/1.0.0"),
        registry,
    )
    evaluator = DeterministicReferenceEvaluator(registry)
    context = FactorEvaluationContext(
        snapshot_id=snapshot_id,
        universe_version_id="universe-1",
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            "universe-1", FORMAL_ADMITTED_CEILING
        ),
        knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
        calendar_version_id="calendar-1",
        schema_version_id="schema-1",
        environment_fingerprint="dataset-python-3.14-track-c-v0",
        evaluator_version=evaluator.evaluator_version,
    )
    x_result = evaluator.evaluate(x_definition, {"x": [1.0, 2.0, 3.0, 4.0]})
    squared_result = evaluator.evaluate(
        squared_definition, {"x_squared": [1.0, 4.0, 9.0, 16.0]}
    )
    x_materialization = FeatureMaterialization.create(
        x_definition, x_result, context, artifact("a"), FORMAL_ADMITTED_CEILING
    )
    squared_materialization = FeatureMaterialization.create(
        squared_definition,
        squared_result,
        context,
        artifact("2"),
        FORMAL_ADMITTED_CEILING,
    )
    x_evaluation = FactorEvaluation.create(
        x_definition, x_materialization, artifact("b"), FORMAL_ADMITTED_CEILING
    )
    squared_evaluation = FactorEvaluation.create(
        squared_definition,
        squared_materialization,
        artifact("3"),
        FORMAL_ADMITTED_CEILING,
    )
    evaluations = (x_evaluation, squared_evaluation)
    feature_set = FeatureSetVersion.create(evaluations, artifact("c"))
    label = LabelSpec.create("next_return", "close", 1, 0)
    split = SplitSpec.create(
        train_start=0,
        train_end=9,
        validation_start=12,
        validation_end=19,
        test_start=22,
        test_end=29,
        purge_observations=1,
        embargo_observations=1,
    )
    binding = DatasetBinding(
        snapshot_id=context.snapshot_id,
        universe_version_id=context.universe_version_id,
        snapshot_truth_binding=context.snapshot_truth_binding,
        universe_truth_binding=context.universe_truth_binding,
        knowledge_cutoff=context.knowledge_cutoff,
        calendar_version_id=context.calendar_version_id,
        schema_version_id=context.schema_version_id,
        environment_fingerprint=context.environment_fingerprint,
        evaluator_version=context.evaluator_version,
    )
    dataset = DatasetVersion.create(
        feature_set=feature_set,
        evaluations=evaluations,
        label_spec=label,
        split_spec=split,
        binding=binding,
        dataset_artifact_id=artifact("d"),
        provenance_artifact_id=artifact("e"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    return dataset, split


def feature_schema(dataset: DatasetVersion) -> tuple[FeatureColumn, ...]:
    return tuple(FeatureColumn(value) for value in dataset.factor_evaluation_ids)


def spec_for(
    dataset: DatasetVersion,
    worker_runtime: WorkerRuntimeFingerprint,
    *,
    seed: int = 7,
    environment_profile_id: str = "cpu-single-thread-v1",
    schema: tuple[FeatureColumn, ...] | None = None,
) -> TrainingSpecVersion:
    return TrainingSpecVersion.create(
        dataset=dataset,
        feature_schema=schema or feature_schema(dataset),
        seed=seed,
        environment_profile_id=environment_profile_id,
        dependency_runtime_fingerprint=worker_runtime.fingerprint,
        alpha=1.0,
    )


def sample(sample_id: str, ordinal: int, x: float) -> ModelSample:
    event = datetime(2026, 1, 1, ordinal % 24, tzinfo=timezone.utc)
    return ModelSample(
        sample_id=sample_id,
        instrument_id=f"instrument-{sample_id}",
        observation_ordinal=ordinal,
        event_time=event,
        decision_time=event,
        features=(x, x * x),
        label=1.0 + 2.0 * x - 0.5 * x * x,
    )


def training_samples() -> tuple[ModelSample, ...]:
    return (
        sample("train-0", 0, 0.0),
        sample("train-1", 1, 1.0),
        sample("train-2", 2, 2.0),
        sample("train-3", 3, 3.0),
        sample("validation-0", 12, 4.0),
        sample("validation-1", 13, 5.0),
    )


def test_samples() -> tuple[ModelSample, ...]:
    return (sample("test-0", 22, 6.0), sample("test-1", 23, 7.0))


class FakeWorker:
    def __init__(self, worker_runtime: WorkerRuntimeFingerprint) -> None:
        self.runtime = worker_runtime

    def train(
        self, training_spec: TrainingSpecVersion, view: TrainingDatasetView
    ) -> WorkerTrainingCandidate:
        return WorkerTrainingCandidate(
            runtime=self.runtime,
            feature_order=training_spec.feature_order,
            coefficients=(2.0, -0.5),
            intercept=1.0,
            train_sample_ids=view.train_sample_ids,
            validation_sample_ids=view.validation_sample_ids,
            train_rmse=0.0,
            validation_rmse=0.0,
            seed=training_spec.seed,
        )

    def predict(
        self,
        training_spec: TrainingSpecVersion,
        artifact_value: SafeLinearModelArtifact,
        view: PredictionDatasetView,
    ) -> WorkerPredictionCandidate:
        return WorkerPredictionCandidate.from_wire(
            {
                "runtime": self.runtime.to_wire(),
                "feature_order": list(training_spec.feature_order),
                "predictions": [
                    {
                        "sample_id": value.sample_id,
                        "value": artifact_value.intercept
                        + math.fsum(
                            coefficient * feature
                            for coefficient, feature in zip(
                                artifact_value.coefficients,
                                value.features,
                                strict=True,
                            )
                        ),
                    }
                    for value in view.samples
                ],
            }
        )


def train_fake(
    dataset: DatasetVersion,
    split: SplitSpec,
    training_spec: TrainingSpecVersion,
    worker: FakeWorker,
):
    return train_model(
        worker=worker,
        dataset=dataset,
        split_spec=split,
        training_spec=training_spec,
        samples=training_samples(),
        code_version="track-e-v0/1",
        training_evidence_provenance_artifact_id=artifact("f"),
        model_provenance_artifact_id=artifact("g"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )


class IdentityAndBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset, self.split = build_dataset()
        self.runtime = runtime()
        self.worker = FakeWorker(self.runtime)
        self.spec = spec_for(self.dataset, self.runtime)

    def test_training_spec_identity_is_deterministic(self) -> None:
        repeated = spec_for(self.dataset, self.runtime)
        self.assertEqual(
            self.spec.training_spec_version_id, repeated.training_spec_version_id
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.spec.seed = 8  # type: ignore[misc]

    def test_dataset_version_binding_is_exact(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        other_dataset, _ = build_dataset("snapshot-2")
        with self.assertRaisesRegex(ValueError, "exact DatasetVersion"):
            ModelVersion.create(
                dataset=other_dataset,
                run=trained.run,
                training_spec=self.spec,
                artifact=trained.artifact,
                training_evidence=trained.training_evidence,
                provenance_artifact_id=artifact("g"),
                proposed_state=FORMAL_ADMITTED_CEILING,
            )

    def test_seed_and_environment_change_model_identity(self) -> None:
        base = train_fake(self.dataset, self.split, self.spec, self.worker)
        changed_seed = train_fake(
            self.dataset,
            self.split,
            spec_for(self.dataset, self.runtime, seed=8),
            self.worker,
        )
        changed_environment = train_fake(
            self.dataset,
            self.split,
            spec_for(
                self.dataset,
                self.runtime,
                environment_profile_id="cpu-single-thread-v2",
            ),
            self.worker,
        )
        self.assertEqual(
            len(
                {
                    base.model.model_version_id,
                    changed_seed.model.model_version_id,
                    changed_environment.model.model_version_id,
                }
            ),
            3,
        )

    def test_feature_order_changes_identity_and_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly match DatasetVersion"):
            spec_for(
                self.dataset,
                self.runtime,
                schema=tuple(reversed(feature_schema(self.dataset))),
            )

    def test_final_test_leakage_is_rejected_before_worker_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "final-test"):
            TrainingDatasetView.create(
                dataset=self.dataset,
                split_spec=self.split,
                training_spec=self.spec,
                samples=training_samples() + test_samples(),
            )

    def test_worker_candidate_cannot_assign_canonical_model_identity(self) -> None:
        valid = {
            "runtime": self.runtime.to_wire(),
            "feature_order": list(self.spec.feature_order),
            "coefficients": [2.0, -0.5],
            "intercept": 1.0,
            "train_sample_ids": ["a", "b"],
            "validation_sample_ids": ["c"],
            "train_rmse": 0.0,
            "validation_rmse": 0.0,
            "seed": 7,
            "model_version_id": "worker-controlled",
        }
        with self.assertRaisesRegex(ValueError, "keys must be exactly"):
            WorkerTrainingCandidate.from_wire(valid)

    def test_nonfinite_prediction_is_rejected_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            WorkerPredictionCandidate.from_wire(
                {
                    "runtime": self.runtime.to_wire(),
                    "feature_order": list(self.spec.feature_order),
                    "predictions": [{"sample_id": "test-0", "value": float("nan")}],
                }
            )

    def test_prediction_rows_bind_exact_sample_view(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        view = PredictionDatasetView.create(
            dataset=self.dataset,
            model=trained.model,
            training_spec=self.spec,
            samples=test_samples(),
        )
        incomplete = WorkerPredictionCandidate.from_wire(
            {
                "runtime": self.runtime.to_wire(),
                "feature_order": list(self.spec.feature_order),
                "predictions": [{"sample_id": "test-0", "value": 1.0}],
            }
        )
        with self.assertRaisesRegex(ValueError, "exactly match"):
            PredictionArtifact.create(
                model=trained.model,
                dataset=self.dataset,
                training_spec=self.spec,
                view=view,
                candidate=incomplete,
                prediction_timestamp=datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
                target_semantics="next_return",
                provenance_artifact_id=artifact("h"),
                proposed_state=FORMAL_ADMITTED_CEILING,
            )

    def test_prediction_dataset_must_preserve_exact_label_binding(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        incompatible = dataclasses.replace(
            self.dataset, label_spec_id="lbl_sha256_incompatible"
        )
        with self.assertRaisesRegex(ValueError, "LabelSpec"):
            PredictionDatasetView.create(
                dataset=incompatible,
                model=trained.model,
                training_spec=self.spec,
                samples=test_samples(),
            )

    def test_model_and_prediction_truth_ceiling_cannot_exceed_dataset(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        prediction = predict_model(
            worker=self.worker,
            model=trained.model,
            model_artifact=trained.artifact,
            prediction_dataset=self.dataset,
            training_spec=self.spec,
            samples=test_samples(),
            prediction_timestamp=datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
            target_semantics="next_return",
            provenance_artifact_id=artifact("h"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.assertEqual(self.dataset.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(trained.model.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(prediction.prediction.truth_admission, PRE_ALPHA_CEILING)

    def test_same_exact_inputs_and_runtime_produce_same_identities(self) -> None:
        first = train_fake(self.dataset, self.split, self.spec, self.worker)
        second = train_fake(self.dataset, self.split, self.spec, self.worker)
        self.assertEqual(first.run.model_run_id, second.run.model_run_id)
        self.assertEqual(first.artifact.artifact_id, second.artifact.artifact_id)
        self.assertEqual(first.model.model_version_id, second.model.model_version_id)

    def test_runtime_version_drift_changes_model_identity(self) -> None:
        first = train_fake(self.dataset, self.split, self.spec, self.worker)
        drifted_runtime = runtime("1.9.1")
        drifted_worker = FakeWorker(drifted_runtime)
        drifted = train_fake(
            self.dataset,
            self.split,
            spec_for(self.dataset, drifted_runtime),
            drifted_worker,
        )
        self.assertNotEqual(
            first.model.model_version_id, drifted.model.model_version_id
        )

    def test_worker_failure_is_explicit_and_has_no_fallback(self) -> None:
        worker = SklearnRidgeSubprocessWorker(
            python_executable="definitely-missing-python-executable"
        )
        with self.assertRaisesRegex(ModelWorkerError, "failed to execute"):
            _ = worker.runtime

    def test_worker_environment_strips_credentials_and_fixes_threads(self) -> None:
        worker = SklearnRidgeSubprocessWorker()
        observed = worker.sanitized_environment(
            {
                "PATH": "fixed",
                "TEMP": "scratch",
                "AWS_SECRET_ACCESS_KEY": "secret",
                "OPENAI_API_KEY": "secret",
            }
        )
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", observed)
        self.assertNotIn("OPENAI_API_KEY", observed)
        self.assertEqual(observed["PATH"], "fixed")
        self.assertEqual(observed["OMP_NUM_THREADS"], "1")

    def test_unsafe_artifact_is_not_trusted_by_core(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        restored = SafeLinearModelArtifact.from_bytes(
            SAFE_LINEAR_MODEL_MEDIA_TYPE, trained.artifact.to_bytes()
        )
        self.assertEqual(restored, trained.artifact)
        with self.assertRaisesRegex(ValueError, "unsafe or unsupported"):
            SafeLinearModelArtifact.from_bytes(
                "application/python-pickle", b"cos\nsystem\n(S'echo unsafe'\ntR."
            )
        with self.assertRaisesRegex(ValueError, "coefficient count"):
            dataclasses.replace(restored, coefficients=())

    def test_evaluation_evidence_binds_splits_counts_and_diagnostics(self) -> None:
        trained = train_fake(self.dataset, self.split, self.spec, self.worker)
        prediction = predict_model(
            worker=self.worker,
            model=trained.model,
            model_artifact=trained.artifact,
            prediction_dataset=self.dataset,
            training_spec=self.spec,
            samples=test_samples(),
            prediction_timestamp=datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
            target_semantics="next_return",
            provenance_artifact_id=artifact("h"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        evidence = evaluate_prediction(
            model_bundle=trained,
            prediction_bundle=prediction,
            dataset=self.dataset,
            split_spec=self.split,
            provenance_artifact_id=artifact("i"),
        )
        self.assertEqual(evidence.evaluated_split_role, DatasetSplitRole.TEST)
        self.assertEqual(evidence.train_sample_count, 4)
        self.assertEqual(evidence.validation_sample_count, 2)
        self.assertEqual(evidence.evaluated_sample_count, 2)
        self.assertEqual(evidence.prediction_coverage, 1.0)
        self.assertEqual(evidence.nonfinite_count, 0)
        self.assertAlmostEqual(evidence.rmse, 0.0)


class IsolatedSklearnWorkerTests(unittest.TestCase):
    def test_real_sklearn_1_9_worker_runs_end_to_end(self) -> None:
        dataset, split = build_dataset()
        worker = SklearnRidgeSubprocessWorker()
        self.assertEqual(worker.runtime.backend_version, "1.9.0")
        self.assertEqual(
            dict(worker.runtime.packages),
            {
                "joblib": "1.5.3",
                "narwhals": "2.24.0",
                "numpy": "2.5.2",
                "scikit-learn": "1.9.0",
                "scipy": "1.18.0",
                "threadpoolctl": "3.6.0",
            },
        )
        training_spec = spec_for(dataset, worker.runtime)
        first = train_model(
            worker=worker,
            dataset=dataset,
            split_spec=split,
            training_spec=training_spec,
            samples=training_samples(),
            code_version="track-e-v0/1",
            training_evidence_provenance_artifact_id=artifact("f"),
            model_provenance_artifact_id=artifact("g"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        second = train_model(
            worker=worker,
            dataset=dataset,
            split_spec=split,
            training_spec=training_spec,
            samples=training_samples(),
            code_version="track-e-v0/1",
            training_evidence_provenance_artifact_id=artifact("f"),
            model_provenance_artifact_id=artifact("g"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.assertEqual(first.model.model_version_id, second.model.model_version_id)
        prediction = predict_model(
            worker=worker,
            model=first.model,
            model_artifact=first.artifact,
            prediction_dataset=dataset,
            training_spec=training_spec,
            samples=test_samples(),
            prediction_timestamp=datetime(2026, 1, 5, 9, tzinfo=timezone.utc),
            target_semantics="next_return",
            provenance_artifact_id=artifact("h"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.assertEqual(
            tuple(value.sample_id for value in prediction.prediction.values),
            ("test-0", "test-1"),
        )
        self.assertTrue(
            all(math.isfinite(value.value) for value in prediction.prediction.values)
        )


if __name__ == "__main__":
    unittest.main()
