from __future__ import annotations

import json
import unittest

from apps.backend.tests.model_pipeline_runnability.helpers import (
    build_model_pipeline_development_fixture,
)
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.model_workers import SklearnRidgeSubprocessWorker
from v3_backend.domain.artifacts.exceptions import FormatRejected
from v3_backend.domain.models import (
    ModelPipelineRequest,
    ModelPipelineStatus,
    SAFE_LINEAR_MODEL_MEDIA_TYPE,
    SafeLinearModelArtifact,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes


def request(dataset_id: str) -> ModelPipelineRequest:
    return ModelPipelineRequest(
        dataset_id=dataset_id,
        target_semantics="forward-return/1-observation",
        code_version="v3.model-research-pipeline/1.0.0",
        environment_profile_id="cpu-single-thread-research-v1",
        seed=7,
        alpha=1.0,
    )


class ModelPipelineRunnabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_model_pipeline_development_fixture(SklearnRidgeSubprocessWorker())

    def tearDown(self) -> None:
        self.fixture.close()

    def test_dataset_actual_bytes_materialize_deterministically_and_run(self) -> None:
        first = self.fixture.service.run(request(self.fixture.dataset.dataset_version_id))
        second = self.fixture.service.run(request(self.fixture.dataset.dataset_version_id))
        self.assertEqual(first.status, ModelPipelineStatus.SUCCESS)
        self.assertEqual(first.to_wire(), second.to_wire())
        self.assertEqual(first.dataset_artifact_id, self.fixture.dataset.dataset_descriptor.artifact_id)
        self.assertTrue(first.dataset_resolution_receipt_id.startswith("prr_sha256_"))
        self.assertEqual(first.sample_count, self.fixture.dataset.sample_count)
        self.assertEqual(first.train_sample_count, 2)
        self.assertEqual(first.validation_sample_count, 2)
        self.assertEqual(first.prediction_sample_count, 2)
        self.assertTrue(first.model_version_id.startswith("mdv_sha256_"))
        self.assertTrue(first.prediction_id.startswith("pred_sha256_"))
        self.assertEqual(first.truth, "PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE")

    def test_runnable_entry_has_no_caller_model_samples(self) -> None:
        fields = ModelPipelineRequest.__dataclass_fields__
        self.assertNotIn("samples", fields)
        self.assertNotIn("model_samples", fields)
        self.assertEqual(set(fields) & {"dataset_id", "training_split", "prediction_split"}, {"dataset_id", "training_split", "prediction_split"})

    def test_missing_dataset_owner_fails_before_train(self) -> None:
        missing = self.fixture.service.run(request("fdsv_sha256_" + "0" * 64))
        self.assertEqual(missing.status, ModelPipelineStatus.DATASET_RESOLUTION_FAILED)

    def test_tampered_dataset_bytes_fail_before_train(self) -> None:
        path = self.fixture.store._final_path(self.fixture.dataset.dataset_descriptor.sha256)
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            tampered = self.fixture.service.run(request(self.fixture.dataset.dataset_version_id))
            self.assertEqual(tampered.status, ModelPipelineStatus.DATASET_RESOLUTION_FAILED)
            self.assertIsNone(tampered.model_version_id)
        finally:
            path.write_bytes(original)

    def test_model_and_prediction_artifacts_reopen_from_existing_store(self) -> None:
        result = self.fixture.service.run(request(self.fixture.dataset.dataset_version_id))
        self.assertEqual(result.status, ModelPipelineStatus.SUCCESS)
        reopened = FileSystemArtifactStore(self.fixture.store.root)
        safe_model = SafeLinearModelArtifact.from_bytes(
            SAFE_LINEAR_MODEL_MEDIA_TYPE,
            reopened.read_bytes(result.model_artifact_id),
        )
        prediction = json.loads(reopened.read_bytes(result.prediction_artifact_id))
        self.assertEqual(safe_model.artifact_id, result.model_artifact_id)
        self.assertEqual(prediction["prediction_artifact_id"], result.prediction_id)
        self.assertEqual(prediction["model_version_id"], result.model_version_id)

    def test_model_record_safe_format_accepts_canonical_finite_numbers_only(self) -> None:
        payload = canonical_json_bytes({"integer_float": 1.0, "tiny": 1e-7, "zero": 0.0})
        staged = self.fixture.store.stage_bytes(payload)
        descriptor = self.fixture.store.publish(
            staged.staging_token,
            expected_sha256=staged.sha256,
            expected_byte_size=staged.byte_size,
            media_type="application/json",
            role="MODEL_PIPELINE_RECORD",
            provenance_entity_id="model-pipeline-safe-format-test",
            schema_fingerprint="sch_sha256_" + "1" * 64,
            semantic_fingerprint="model-pipeline-safe-format-test",
        ).descriptor
        self.assertEqual(self.fixture.store.read_bytes(descriptor.artifact_id), payload)

        nonfinite = b'{"value":NaN}'
        staged = self.fixture.store.stage_bytes(nonfinite)
        with self.assertRaises(FormatRejected):
            self.fixture.store.publish(
                staged.staging_token,
                expected_sha256=staged.sha256,
                expected_byte_size=staged.byte_size,
                media_type="application/json",
                role="MODEL_PIPELINE_RECORD",
                provenance_entity_id="model-pipeline-safe-format-test",
                schema_fingerprint="sch_sha256_" + "1" * 64,
                semantic_fingerprint="model-pipeline-safe-format-test",
            )
if __name__ == "__main__":
    unittest.main()
