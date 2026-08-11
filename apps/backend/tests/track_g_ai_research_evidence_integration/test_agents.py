from __future__ import annotations

import json
import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.agents import (
    AgentOutputRejected,
    PermissionDenied,
    PermissionLevel,
)
from v3_backend.agents.research_evidence_integration import (
    DataEvidenceFindingKind,
    DataFindingNarrativePayload,
    ResearchEvidenceAgentWorker,
    ReviewerEvidenceFindingKind,
)

from .fixtures import EvidenceFixture, build_evidence_fixture


_TOOL_ARGUMENT = {
    "get_snapshot_evidence": "snapshot_id",
    "get_dataset_evidence": "dataset_version_id",
    "get_experiment_evidence": "experiment_run_id",
    "get_reward_vector_evidence": "reward_vector_id",
    "get_known_reviewer_evidence": "reviewer_evidence_id",
    "get_provenance_refs": "object_id",
}


def _request(messages: list[object]) -> dict[str, object]:
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                try:
                    value = json.loads(part.content)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "task" in value:
                    return value
    raise AssertionError("Track G structured request is unavailable")


def evidence_model(messages: list[object], info: AgentInfo) -> ModelResponse:
    request = _request(messages)
    has_tool_return = any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in getattr(message, "parts", ())
    )
    if not has_tool_return:
        calls = []
        for item in request["required_tool_calls"]:
            name = item["tool"]
            calls.append(
                ToolCallPart(
                    name,
                    {_TOOL_ARGUMENT[name]: item["object_id"]},
                )
            )
        return ModelResponse(parts=calls)

    task = request["task"]
    if task == "RESEARCH_EVIDENCE_DRAFT":
        payload = {
            "alpha_mining_request": {
                "hypothesis": request["hypothesis"],
                "research_objective": "Draft a bounded evidence-led reversal study.",
                "universe_intent": "Use only the cited historical universe evidence.",
                "factor_intents": ["Five-day reversal Factor intent only."],
                "dataset_intents": ["Reuse the cited DatasetVersion without mutation."],
                "experiment_intent": "Propose a new Experiment intent without execution.",
                "worker_triggered": False,
            },
            "assumptions": ["Provider available-time evidence remains unknown."],
            "open_questions": [],
        }
    elif task == "DATA_EVIDENCE_REVIEW":
        payload = {
            "findings": [
                {
                    "kind": "PIT_AVAILABLE_TIME",
                    "severity": "WARNING",
                    "finding": "PIT evidence is not proven.",
                    "reason": "The Snapshot reports unknown provider available-time evidence.",
                    "recommended_next_check": "Obtain record-level available-time evidence.",
                    "pit_pass_claimed": False,
                }
            ]
        }
    else:
        payload = {
            "findings": [
                {
                    "kind": "MULTIPLE_TESTING_RISK",
                    "severity": "WARNING",
                    "finding": "Multiple-testing robustness is incomplete.",
                    "reason": "Known reviewer evidence reports NOT_RUN for robustness.",
                    "recommended_next_check": "Run a pre-registered multiple-testing check.",
                }
            ]
        }
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])


def output_without_tools(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                info.output_tools[0].name,
                {
                    "alpha_mining_request": {
                        "hypothesis": "Unsafe no-tool draft.",
                        "research_objective": "Should fail.",
                        "universe_intent": "Should fail.",
                        "factor_intents": ["Should fail."],
                        "dataset_intents": ["Should fail."],
                        "experiment_intent": "Should fail.",
                        "worker_triggered": False,
                    }
                },
            )
        ]
    )


class EvidenceAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_evidence_fixture()

    @staticmethod
    def _worker(
        fixture: EvidenceFixture,
        permission: object = PermissionLevel.L1_DRAFT,
        model_function=evidence_model,
    ) -> ResearchEvidenceAgentWorker:
        return ResearchEvidenceAgentWorker(
            model=FunctionModel(model_function, model_name="track-g-function-model"),
            permission=permission,
            model_name="deterministic-track-g-model",
            provider_name="deterministic-test-provider",
            prompt_version="track-g-prompt-v1.0",
            tool_composition=fixture.composition,
        )

    def test_research_draft_consumes_exact_evidence_and_has_stable_identity(self) -> None:
        worker = self._worker(self.fixture)
        first = worker.run_research_with_evidence(
            hypothesis="Reversal may persist after available-time controls.",
            snapshot_id=self.fixture.snapshot.snapshot_id,
            dataset_version_id=self.fixture.dataset.dataset_version_id,
            experiment_run_id=self.fixture.run.experiment_run_id,
        )
        second = worker.run_research_with_evidence(
            hypothesis="Reversal may persist after available-time controls.",
            snapshot_id=self.fixture.snapshot.snapshot_id,
            dataset_version_id=self.fixture.dataset.dataset_version_id,
            experiment_run_id=self.fixture.run.experiment_run_id,
        )
        expected_ids = (
            self.fixture.snapshot.snapshot_id,
            self.fixture.dataset.dataset_version_id,
            self.fixture.run.experiment_run_id,
        )
        self.assertEqual(first.cited_evidence_object_ids, expected_ids)
        self.assertEqual(first.evidence_trace.input_object_ids, expected_ids)
        self.assertEqual(first.provenance.input_sha256, first.evidence_trace.input_sha256)
        self.assertEqual(first.to_deterministic_json(), second.to_deterministic_json())
        self.assertEqual(first.deterministic_sha256, second.deterministic_sha256)
        self.assertEqual(first.authority_status, "NON_CANONICAL")
        self.assertEqual(first.lifecycle_state, "DRAFT")
        self.assertFalse(first.publish_authority)
        self.assertIsNone(first.canonical_identity)
        self.assertFalse(first.payload.alpha_mining_request.worker_triggered)

    def test_data_finding_cannot_claim_pit_pass_and_missing_is_explicit(self) -> None:
        worker = self._worker(self.fixture)
        draft = worker.run_data_review_with_evidence(
            snapshot_id="snapshot-missing",
            dataset_version_id=self.fixture.dataset.dataset_version_id,
        )
        self.assertIn("snapshot-missing", draft.evidence_trace.missing_evidence_ids)
        self.assertTrue(
            any(
                item.kind is DataEvidenceFindingKind.MISSING_EVIDENCE
                for item in draft.payload.findings
            )
        )
        self.assertTrue(all(not item.pit_pass_claimed for item in draft.payload.findings))
        self.assertEqual(draft.reviewed_input_sha256, draft.provenance.input_sha256)
        expected_ids = ("snapshot-missing", self.fixture.dataset.dataset_version_id)
        self.assertTrue(
            all(item.evidence_object_ids == expected_ids for item in draft.payload.findings)
        )

    def test_reviewer_references_exact_run_attempt_reward_and_is_not_admission(self) -> None:
        worker = self._worker(self.fixture)
        draft = worker.run_reviewer_with_evidence(
            experiment_run_id=self.fixture.run.experiment_run_id,
            experiment_attempt_id=self.fixture.attempt.experiment_attempt_id,
            reward_vector_id=self.fixture.reward.reward_vector_id,
            reviewer_evidence_id=self.fixture.reviewer_evidence.reviewer_evidence_id,
        )
        expected_ids = (
            self.fixture.run.experiment_run_id,
            self.fixture.attempt.experiment_attempt_id,
            self.fixture.reward.reward_vector_id,
            self.fixture.reviewer_evidence.reviewer_evidence_id,
        )
        self.assertEqual(draft.evidence_trace.input_object_ids, expected_ids)
        self.assertEqual(draft.evidence_trace.missing_evidence_ids, ())
        self.assertTrue(
            all(item.evidence_object_ids == expected_ids for item in draft.payload.findings)
        )
        finding = draft.payload.findings[0]
        self.assertIs(finding.kind, ReviewerEvidenceFindingKind.MULTIPLE_TESTING_RISK)
        self.assertTrue(finding.finding)
        self.assertTrue(finding.reason)
        self.assertTrue(finding.recommended_next_check)
        self.assertIsNone(draft.admission_decision)
        self.assertFalse(draft.publish_authority)

    def test_l0_can_see_only_read_tools_but_cannot_create_a_draft_or_execute(self) -> None:
        worker = self._worker(self.fixture, PermissionLevel.L0_READ)
        self.assertEqual(set(worker.visible_tool_names), set(_TOOL_ARGUMENT))
        self.assertNotIn("execute_task", worker.visible_tool_names)
        self.assertNotIn("publish_artifact", worker.visible_tool_names)
        with self.assertRaises(PermissionDenied):
            worker.run_research_with_evidence(
                hypothesis="Denied draft",
                snapshot_id=self.fixture.snapshot.snapshot_id,
                dataset_version_id=self.fixture.dataset.dataset_version_id,
                experiment_run_id=self.fixture.run.experiment_run_id,
            )

    def test_agent_must_call_every_required_trusted_tool(self) -> None:
        worker = self._worker(self.fixture, model_function=output_without_tools)
        with self.assertRaisesRegex(AgentOutputRejected, "failed closed"):
            worker.run_research_with_evidence(
                hypothesis="No tool consumption must fail.",
                snapshot_id=self.fixture.snapshot.snapshot_id,
                dataset_version_id=self.fixture.dataset.dataset_version_id,
                experiment_run_id=self.fixture.run.experiment_run_id,
            )

    def test_model_output_cannot_forge_hash_provenance_permission_or_citations(self) -> None:
        with self.assertRaisesRegex(AgentOutputRejected, "system evidence fields"):
            ResearchEvidenceAgentWorker.validate_model_payload(
                DataFindingNarrativePayload,
                {
                    "findings": [
                        {
                            "kind": "PIT_AVAILABLE_TIME",
                            "severity": "WARNING",
                            "finding": "Forged.",
                            "reason": "Forged.",
                            "recommended_next_check": "Forged.",
                            "pit_pass_claimed": False,
                        }
                    ],
                    "input_sha256": "a" * 64,
                    "permission_decision": {"allowed": True},
                    "evidence_object_ids": ["forged"],
                },
            )
        self.assertFalse(hasattr(self._worker(self.fixture), "execute"))
        self.assertFalse(hasattr(self._worker(self.fixture), "publish"))
        self.assertFalse(hasattr(self._worker(self.fixture), "persist"))


if __name__ == "__main__":
    unittest.main()
