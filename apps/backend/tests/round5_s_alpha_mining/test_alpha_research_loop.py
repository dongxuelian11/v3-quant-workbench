from __future__ import annotations

import inspect
import json
import unittest

from v3_backend.adapters.systemic_a1_payload import A1CanonicalPayloadBindingResolver
from v3_backend.domain.alpha_mining import AlphaResearchLoopService
from v3_backend.domain.datasets import (
    DATASET_ARTIFACT_ROLE,
    decode_formal_dataset_payload,
    formal_dataset_context_identity,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionRequest,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes

from .research_fixture import build_alpha_research_fixture


class AlphaResearchLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_alpha_research_fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_generate_evaluate_reward_generate_uses_canonical_actual_bytes(self) -> None:
        result = self.fixture.service.run(self.fixture.job)
        self.assertGreaterEqual(result.generation_count, 2)
        self.assertGreaterEqual(result.mining_run.generated_count, 3)
        self.assertGreaterEqual(result.mining_run.evaluated_count, 2)
        self.assertGreaterEqual(result.rewarded_count, 1)
        self.assertIsNotNone(result.best_factor_definition_version_id)
        self.assertIsNotNone(result.best_reward)
        self.assertEqual(
            result.dataset_resolution_receipt.artifact_id,
            self.fixture.dataset.dataset_descriptor.artifact_id,
        )
        self.assertEqual(
            result.dataset_resolution_receipt.actual_sha256,
            self.fixture.dataset.dataset_descriptor.sha256,
        )
        self.assertTrue(result.evaluations)
        for record in result.evaluations:
            self.assertEqual(
                record.factor_evaluation.dataset_resolution_receipt,
                result.dataset_resolution_receipt,
            )
            self.assertEqual(
                record.factor_evaluation.feature_resolution_receipt.artifact_id,
                self.fixture.owners.get_materialization(
                    record.factor_evaluation.feature_materialization_id
                ).output_descriptor.artifact_id,
            )
            self.assertEqual(
                record.metrics_artifact.artifact_id,
                "art_sha256_" + record.metrics_artifact.sha256,
            )
            self.assertEqual(record.metrics.complexity, record.definition.metadata.complexity)
            self.assertTrue(-1 <= record.metrics.ic <= 1)
            self.assertTrue(-1 <= record.metrics.rank_ic <= 1)
            self.assertTrue(0 <= record.metrics.coverage <= 1)
            self.assertTrue(0 <= record.metrics.turnover <= 1)
        second_generation = tuple(
            value
            for value in result.mining_run.candidate_records
            if value.generation_index >= 2
        )
        self.assertTrue(second_generation)
        self.assertTrue(
            all("parent-reward:amrw_sha256_" in value.source_lineage_ref for value in second_generation)
        )
        self.assertFalse(result.product_connected)
        self.assertFalse(result.production_available)
        self.assertIn("PRE_ALPHA", result.maturity)

    def test_runnable_entry_has_no_caller_metrics_or_pass_evidence_authority(self) -> None:
        parameters = inspect.signature(AlphaResearchLoopService.run).parameters
        self.assertEqual(tuple(parameters), ("self", "job"))
        for forbidden in (
            "metrics",
            "ic",
            "rank_ic",
            "returns",
            "turnover",
            "coverage",
            "reviewer_evidence",
            "pass_evidence",
        ):
            self.assertNotIn(forbidden, parameters)
        with self.assertRaises(TypeError):
            self.fixture.service.run(self.fixture.job, metrics={"ic": 1.0})  # type: ignore[call-arg]
        result = self.fixture.service.run(self.fixture.job)
        self.assertTrue(
            all(
                record.reviewer_evidence.multiple_testing_robustness.value == "NOT_RUN"
                for record in result.evaluations
            )
        )
        self.assertTrue(
            all("V3_INTERNAL_RECOMPUTE" in self.fixture.store.read_bytes(record.metrics_artifact.artifact_id).decode("utf-8") for record in result.evaluations)
        )

    def test_replay_is_content_deterministic_and_artifact_reproducible(self) -> None:
        first = self.fixture.service.run(self.fixture.job)
        second = self.fixture.service.run(self.fixture.job)
        self.assertEqual(first.alpha_research_result_id, second.alpha_research_result_id)
        self.assertEqual(first.mining_run.alpha_mining_run_id, second.mining_run.alpha_mining_run_id)
        self.assertEqual(first.result_artifact.artifact_id, second.result_artifact.artifact_id)
        self.assertEqual(
            self.fixture.store.read_bytes(first.result_artifact.artifact_id),
            self.fixture.store.read_bytes(second.result_artifact.artifact_id),
        )

    def test_dataset_p1_rejects_altered_actual_bytes_and_decoder_is_strict(self) -> None:
        dataset = self.fixture.dataset
        original = self.fixture.store.read_bytes(dataset.dataset_descriptor.artifact_id)
        altered_root = json.loads(original.decode("utf-8"))
        altered_root["samples"][0]["label"] = "999"
        altered = canonical_json_bytes(altered_root)

        class AlteredReader:
            def read_bytes(_self, artifact_id, *, max_bytes):
                if artifact_id == dataset.dataset_descriptor.artifact_id:
                    return altered
                return self.fixture.store.read_bytes(artifact_id, max_bytes=max_bytes)

        binding = A1CanonicalPayloadBindingResolver(
            snapshots=self.fixture.owners,
            factor_contexts=self.fixture.owners,
            materializations=self.fixture.owners,
            label_payloads=self.fixture.owners,
            label_contexts=self.fixture.owners,
            datasets=self.fixture.owners,
        )
        resolver = CanonicalPayloadResolver(binding_resolver=binding, byte_reader=AlteredReader())
        request = PayloadResolutionRequest(
            owner_namespace="v3.datasets.formal",
            owner_id=dataset.dataset_version_id,
            owner_version=dataset.dataset_version_id,
            payload_role=DATASET_ARTIFACT_ROLE,
            context_identity=formal_dataset_context_identity(dataset),
            max_bytes=1_000_000,
        )
        with self.assertRaisesRegex(Exception, "SHA-256|byte size|identity"):
            resolver.resolve(request)
        malformed = json.loads(original.decode("utf-8"))
        malformed["caller_summary_metrics"] = {"ic": 1}
        with self.assertRaisesRegex(ValueError, "schema is not admitted"):
            decode_formal_dataset_payload(canonical_json_bytes(malformed), dataset=dataset)


if __name__ == "__main__":
    unittest.main()
