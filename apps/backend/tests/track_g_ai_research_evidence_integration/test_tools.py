from __future__ import annotations

import unittest

from v3_backend.agents import (
    PermissionLevel,
    UntrustedToolBindingError,
    filter_tool_bindings,
)
from v3_backend.agents.research_evidence_integration import (
    DatasetEvidence,
    EvidenceToolRequestRejected,
    ExperimentEvidence,
    ProvenanceEvidence,
    ReviewerEvidenceView,
    RewardVectorEvidence,
    SnapshotEvidence,
)

from .fixtures import build_evidence_fixture


class TrustedResearchEvidenceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_evidence_fixture()

    def test_registered_l0_tools_return_exact_typed_owner_metadata(self) -> None:
        expected = (
            ("get_snapshot_evidence", self.fixture.snapshot.snapshot_id),
            ("get_dataset_evidence", self.fixture.dataset.dataset_version_id),
            ("get_experiment_evidence", self.fixture.run.experiment_run_id),
            ("get_reward_vector_evidence", self.fixture.reward.reward_vector_id),
            (
                "get_known_reviewer_evidence",
                self.fixture.reviewer_evidence.reviewer_evidence_id,
            ),
            ("get_provenance_refs", self.fixture.dataset.dataset_version_id),
        )
        self.fixture.composition.begin_trace(expected)
        bindings = self.fixture.composition.registry.resolve(
            tuple(name for name, _ in expected)
        )
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L0_READ,
                bindings,
                registry=self.fixture.composition.registry,
            ),
            bindings,
        )
        results = tuple(
            binding.function(object_id)
            for binding, (_, object_id) in zip(bindings, expected, strict=True)
        )
        trace = self.fixture.composition.complete_trace(
            input_object_ids=tuple(object_id for _, object_id in expected),
            request_wire={"test": "all exact evidence tools"},
        )
        snapshot, dataset, experiment, reward, reviewer, provenance = results
        self.assertIsInstance(snapshot, SnapshotEvidence)
        self.assertIsInstance(dataset, DatasetEvidence)
        self.assertIsInstance(experiment, ExperimentEvidence)
        self.assertIsInstance(reward, RewardVectorEvidence)
        self.assertIsInstance(reviewer, ReviewerEvidenceView)
        self.assertIsInstance(provenance, ProvenanceEvidence)
        self.assertEqual(snapshot.snapshot_id, self.fixture.snapshot.snapshot_id)
        self.assertEqual(dataset.split.split_spec_id, self.fixture.split.split_spec_id)
        self.assertEqual(
            dataset.factor_evaluation_ids,
            (self.fixture.evaluation.factor_evaluation_id,),
        )
        self.assertEqual(experiment.attempts[0].experiment_attempt_id, self.fixture.attempt.experiment_attempt_id)
        self.assertEqual(reward.reward_vector_id, self.fixture.reward.reward_vector_id)
        self.assertEqual(reviewer.reviewer_evidence_id, self.fixture.reviewer_evidence.reviewer_evidence_id)
        self.assertEqual(len(trace.tool_calls), 6)

    def test_tool_responses_carry_exact_truth_and_provenance_without_paths_or_bytes(self) -> None:
        snapshot = self.fixture.adapter.get_snapshot(self.fixture.snapshot.snapshot_id)
        dataset = self.fixture.adapter.get_dataset(self.fixture.dataset.dataset_version_id)
        reward = self.fixture.adapter.get_reward_vector(self.fixture.reward.reward_vector_id)
        self.assertIsInstance(snapshot, SnapshotEvidence)
        self.assertIsInstance(dataset, DatasetEvidence)
        self.assertIsInstance(reward, RewardVectorEvidence)
        self.assertEqual(snapshot.truth_ceiling.canonical_admission_state.value, "PRE_ALPHA")
        self.assertEqual(dataset.truth_admission.canonical_admission_state.value, "PRE_ALPHA")
        self.assertEqual(reward.truth_admission.canonical_admission_state.value, "PRE_ALPHA")
        self.assertIn(self.fixture.dataset.provenance_artifact_id, dataset.provenance_refs)
        wire = "".join(
            value.to_deterministic_json() for value in (snapshot, dataset, reward)
        ).lower()
        for forbidden in ("filesystem", "file_path", "raw_bytes", "subprocess", "network_url"):
            self.assertNotIn(forbidden, wire)

    def test_unregistered_query_callable_and_out_of_scope_object_are_rejected(self) -> None:
        with self.assertRaisesRegex(UntrustedToolBindingError, "not registered"):
            self.fixture.composition.registry.resolve(("query_database",))
        with self.assertRaisesRegex(UntrustedToolBindingError, "not registered"):
            self.fixture.composition.registry.resolve(("execute_task",))

        self.fixture.composition.begin_trace(
            (("get_snapshot_evidence", self.fixture.snapshot.snapshot_id),)
        )
        dataset_binding = self.fixture.composition.registry.resolve(
            ("get_dataset_evidence",)
        )[0]
        with self.assertRaisesRegex(
            EvidenceToolRequestRejected, "outside the exact system input set"
        ):
            dataset_binding.function(self.fixture.dataset.dataset_version_id)
        self.fixture.composition.abort_trace()

    def test_missing_and_large_evidence_are_explicit_and_bounded(self) -> None:
        large = build_evidence_fixture(instrument_count=80)
        response = large.adapter.get_snapshot(large.snapshot.snapshot_id)
        self.assertIsInstance(response, SnapshotEvidence)
        self.assertEqual(response.instrument_count, 80)
        self.assertEqual(len(response.sample_instrument_ids), 64)
        self.assertTrue(response.instruments_truncated)
        self.assertTrue(response.response_truncated)

        missing = large.adapter.get_snapshot("snapshot-missing")
        self.assertEqual(missing.status, "MISSING")
        self.assertEqual(missing.requested_object_id, "snapshot-missing")
        self.assertEqual(missing.warning_code, "REQUESTED_EVIDENCE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
