from __future__ import annotations

import hashlib
from importlib.metadata import version
import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.agents import (
    AgentOutputRejected,
    DataFindingsPayload,
    PermissionDenied,
    PermissionLevel,
    PydanticAgentWorker,
    PYDANTIC_AI_VERIFIED_VERSION,
    ResearchDraft,
    ResearchPayload,
    ReviewerReviewDraft,
    ToolBinding,
    ToolDescriptor,
    ToolEffect,
    filter_tool_bindings,
)


def read_evidence(query: str) -> str:
    return f"read:{query}"


def execute_task(task: str) -> str:
    raise AssertionError(f"execute tool must never be exposed: {task}")


class PydanticWorkerTests(unittest.TestCase):
    @staticmethod
    def _model_response(_messages: list[object], info: AgentInfo) -> ModelResponse:
        instructions = info.instructions or ""
        if "research intent" in instructions:
            payload = {
                "alpha_mining_request": {
                    "hypothesis": "Bounded reversal hypothesis.",
                    "research_objective": "Draft a PIT-safe research specification.",
                    "universe_intent": "Historical liquid equities.",
                    "factor_intents": ["Five-day reversal intent."],
                    "dataset_intents": ["PIT adjusted daily bars."],
                    "experiment_intent": "Walk-forward evaluation intent only.",
                    "worker_triggered": False,
                },
                "assumptions": [],
                "open_questions": [],
            }
        elif "data-quality findings" in instructions:
            payload = {
                "findings": [
                    {
                        "kind": "PIT_AVAILABLE_TIME",
                        "severity": "WARNING",
                        "summary": "Available-time evidence requires review.",
                        "evidence": ["The input declares an available_at timestamp."],
                    }
                ],
            }
        else:
            payload = {
                "findings": [
                    {
                        "kind": "ROBUSTNESS_CONCERN",
                        "severity": "WARNING",
                        "summary": "Robustness evidence is incomplete.",
                        "evidence": ["The proposal contains no completed robustness result."],
                    }
                ],
            }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    def _worker(self, permission: object = PermissionLevel.L1_DRAFT) -> PydanticAgentWorker:
        bindings = (
            ToolBinding(
                ToolDescriptor(
                    name="read_structured_input",
                    required_permission=PermissionLevel.L0_READ,
                    effect=ToolEffect.READ,
                ),
                read_evidence,
            ),
            ToolBinding(
                ToolDescriptor(
                    name="execute_task",
                    required_permission=PermissionLevel.L2_EXECUTE,
                    effect=ToolEffect.EXECUTE,
                ),
                execute_task,
            ),
        )
        return PydanticAgentWorker(
            model=FunctionModel(self._model_response, model_name="track-d-function-model"),
            permission=permission,
            model_name="pydantic-test-model",
            provider_name="pydantic-test-provider",
            prompt_version="track-d-prompt-v0.1",
            tool_bindings=bindings,
        )

    def test_exact_verified_sdk_is_installed(self) -> None:
        self.assertEqual(PYDANTIC_AI_VERIFIED_VERSION, "2.27.0")
        self.assertEqual(version("pydantic-ai-slim"), PYDANTIC_AI_VERIFIED_VERSION)

    def test_l0_read_is_deterministic_but_cannot_draft(self) -> None:
        worker = self._worker(PermissionLevel.L0_READ)
        self.assertEqual(worker.inspect_structured_input({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(worker.visible_tool_names, ("read_structured_input",))
        with self.assertRaises(PermissionDenied):
            worker.run_research("Draft this")

    def test_l1_worker_filters_execute_tool_and_returns_typed_research_draft(self) -> None:
        worker = self._worker()
        self.assertEqual(worker.visible_tool_names, ("read_structured_input",))
        draft = worker.run_research("Test a bounded hypothesis")
        self.assertIsInstance(draft, ResearchDraft)
        self.assertIsInstance(draft.payload, ResearchPayload)
        self.assertEqual(draft.provenance.sdk_version, "2.27.0")
        self.assertEqual(draft.provenance.model_name, "pydantic-test-model")
        self.assertEqual(draft.provenance.provider_name, "pydantic-test-provider")
        self.assertFalse(draft.payload.alpha_mining_request.worker_triggered)

    def test_data_and_reviewer_agents_return_typed_findings(self) -> None:
        worker = self._worker()
        structured_input = {"available_at": "2026-01-02T00:00:00Z", "value": 1}
        serialized_input = worker.inspect_structured_input(structured_input)
        data = worker.run_data_review(structured_input)
        self.assertIsInstance(data.payload, DataFindingsPayload)
        self.assertEqual(
            data.reviewed_input_sha256,
            hashlib.sha256(serialized_input.encode("utf-8")).hexdigest(),
        )
        serialized_proposal = data.to_deterministic_json()
        review = worker.run_reviewer(data)
        self.assertIsInstance(review, ReviewerReviewDraft)
        self.assertEqual(
            review.reviewed_proposal_sha256,
            hashlib.sha256(serialized_proposal.encode("utf-8")).hexdigest(),
        )
        self.assertGreaterEqual(len(data.payload.findings), 1)
        self.assertGreaterEqual(len(review.payload.findings), 1)

    def test_invalid_structured_output_fails_closed_without_repair(self) -> None:
        with self.assertRaises(AgentOutputRejected):
            PydanticAgentWorker.validate_payload(
                ResearchPayload,
                {
                    "alpha_mining_request": {
                        "hypothesis": "x",
                        "research_objective": "x",
                        "universe_intent": "x",
                        "factor_intents": [],
                        "dataset_intents": [],
                        "experiment_intent": "x",
                        "worker_triggered": True,
                    },
                    "canonical_truth_state": "FORMAL",
                },
            )

    def test_worker_has_no_execution_publication_or_durable_task_authority(self) -> None:
        worker = self._worker()
        for forbidden in ("execute", "publish", "admit", "allocate_canonical_id", "accept", "persist"):
            self.assertFalse(hasattr(worker, forbidden))

    def test_duplicate_tool_names_fail_closed_before_registration(self) -> None:
        safe = ToolDescriptor(
            name="shared_name",
            required_permission=PermissionLevel.L0_READ,
            effect=ToolEffect.READ,
        )
        unsafe = ToolDescriptor(
            name="shared_name",
            required_permission=PermissionLevel.L2_EXECUTE,
            effect=ToolEffect.EXECUTE,
        )
        with self.assertRaisesRegex(ValueError, "duplicate tool binding names fail closed"):
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                (ToolBinding(safe, read_evidence), ToolBinding(unsafe, execute_task)),
            )

    def test_unregistered_safe_looking_tool_is_not_exposed(self) -> None:
        forged = ToolDescriptor(
            name="forged_read",
            required_permission=PermissionLevel.L0_READ,
            effect=ToolEffect.READ,
        )
        self.assertEqual(
            filter_tool_bindings(PermissionLevel.L1_DRAFT, (ToolBinding(forged, read_evidence),)),
            (),
        )

    def test_reviewer_rejects_non_proposal_models(self) -> None:
        with self.assertRaisesRegex(AgentOutputRejected, "non-canonical proposal"):
            self._worker().run_reviewer(ResearchPayload.model_validate({
                "alpha_mining_request": {
                    "hypothesis": "x",
                    "research_objective": "x",
                    "universe_intent": "x",
                    "factor_intents": ["x"],
                    "dataset_intents": ["x"],
                    "experiment_intent": "x",
                }
            }))


if __name__ == "__main__":
    unittest.main()
