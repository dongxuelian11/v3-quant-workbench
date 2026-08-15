from __future__ import annotations

import json
import unittest

from apps.backend.tests.model_pipeline_runnability.helpers import (
    build_model_pipeline_development_fixture,
    model_pipeline_request,
)
from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.model_workers import SklearnRidgeSubprocessWorker
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.artifacts.exceptions import FormatRejected
from v3_backend.domain.datasets import (
    DATASET_ARTIFACT_ROLE,
    formal_dataset_context_identity,
)
from v3_backend.domain.models import (
    ModelPipelineRequest,
    ModelPipelineStatus,
    SAFE_LINEAR_MODEL_MEDIA_TYPE,
    SafeLinearModelArtifact,
)
from v3_backend.domain.payload_authority import (
    PayloadBindingUnavailable,
    PayloadResolutionRequest,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes


class ModelPipelineRunnabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_model_pipeline_development_fixture(SklearnRidgeSubprocessWorker())

    def tearDown(self) -> None:
        self.fixture.close()

    def test_dataset_actual_bytes_materialize_deterministically_and_run(self) -> None:
        first = self.fixture.service.run(model_pipeline_request(self.fixture.dataset.dataset_version_id))
        second = self.fixture.service.run(model_pipeline_request(self.fixture.dataset.dataset_version_id))
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

    def test_canonical_model_and_prediction_truth_stay_pre_alpha(self) -> None:
        fixture = build_model_pipeline_development_fixture(
            SklearnRidgeSubprocessWorker(),
            upstream_proposed_state=FORMAL_ADMITTED_CEILING,
        )
        try:
            self.assertEqual(fixture.dataset.truth_admission, FORMAL_ADMITTED_CEILING)
            result = fixture.service.run(model_pipeline_request(fixture.dataset.dataset_version_id))
            self.assertEqual(result.status, ModelPipelineStatus.SUCCESS)
            model_version = json.loads(fixture.store.read_bytes(result.model_version_artifact_id))
            prediction = json.loads(fixture.store.read_bytes(result.prediction_artifact_id))
            self.assertEqual(model_version["truth_admission"], PRE_ALPHA_CEILING.to_wire())
            self.assertEqual(prediction["truth_admission"], PRE_ALPHA_CEILING.to_wire())
        finally:
            fixture.close()

    def test_pr27_formal_dataset_contract_resolves_actual_bytes(self) -> None:
        owner = self.fixture.dataset
        resolved = self.fixture.payload_resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.datasets.formal",
                owner_id=owner.dataset_version_id,
                owner_version=owner.dataset_version_id,
                payload_role=DATASET_ARTIFACT_ROLE,
                context_identity=formal_dataset_context_identity(owner),
                max_bytes=100_000,
            )
        )
        self.assertEqual(
            resolved.verified_payload.payload,
            self.fixture.store.read_bytes(owner.dataset_descriptor.artifact_id),
        )

    def test_pr27_legacy_namespace_and_wrong_context_do_not_mint_binding(self) -> None:
        owner = self.fixture.dataset
        rejected_contracts = (
            ("v3.datasets", owner.dataset_version_id),
            ("v3.datasets.formal", owner.dataset_version_id),
        )
        for owner_namespace, context_identity in rejected_contracts:
            with self.subTest(owner_namespace=owner_namespace, context_identity=context_identity):
                with self.assertRaises(PayloadBindingUnavailable):
                    self.fixture.payload_resolver.resolve(
                        PayloadResolutionRequest(
                            owner_namespace=owner_namespace,
                            owner_id=owner.dataset_version_id,
                            owner_version=owner.dataset_version_id,
                            payload_role=DATASET_ARTIFACT_ROLE,
                            context_identity=context_identity,
                            max_bytes=100_000,
                        )
                    )

    def test_runnable_entry_has_no_caller_samples_or_truth_elevation(self) -> None:
        fields = ModelPipelineRequest.__dataclass_fields__
        self.assertNotIn("samples", fields)
        self.assertNotIn("model_samples", fields)
        self.assertNotIn("proposed_state", fields)
        self.assertEqual(set(fields) & {"dataset_id", "training_split", "prediction_split"}, {"dataset_id", "training_split", "prediction_split"})

    def test_missing_dataset_owner_fails_before_train(self) -> None:
        missing = self.fixture.service.run(model_pipeline_request("fdsv_sha256_" + "0" * 64))
        self.assertEqual(missing.status, ModelPipelineStatus.DATASET_RESOLUTION_FAILED)

    def test_tampered_dataset_bytes_fail_before_train(self) -> None:
        path = self.fixture.store._final_path(self.fixture.dataset.dataset_descriptor.sha256)
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            tampered = self.fixture.service.run(model_pipeline_request(self.fixture.dataset.dataset_version_id))
            self.assertEqual(tampered.status, ModelPipelineStatus.DATASET_RESOLUTION_FAILED)
            self.assertIsNone(tampered.model_version_id)
        finally:
            path.write_bytes(original)

    def test_model_and_prediction_artifacts_reopen_from_existing_store(self) -> None:
        result = self.fixture.service.run(model_pipeline_request(self.fixture.dataset.dataset_version_id))
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
