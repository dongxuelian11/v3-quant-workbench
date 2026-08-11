from __future__ import annotations

import hashlib
from importlib.metadata import version
import unittest

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.agents import (
    AgentOutputRejected,
    DEFAULT_TOOL_CATALOG,
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
    TrustedToolBindings,
    UntrustedToolBindingError,
    filter_tool_bindings,
)


def read_evidence(query: str) -> str:
    return f"read:{query}"


def execute_task(task: str) -> str:
    raise AssertionError(f"execute tool must never be exposed: {task}")


def draft_research_spec(objective: str) -> str:
    return f"draft:{objective}"


def authority_tool(value: str) -> str:
    raise AssertionError(f"authority tool must never be exposed: {value}")


class PydanticWorkerTests(unittest.TestCase):
    @staticmethod
    def _descriptor(name: str) -> ToolDescriptor:
        return next(item for item in DEFAULT_TOOL_CATALOG if item.name == name)

    @classmethod
    def _registry(cls) -> TrustedToolBindings:
        return TrustedToolBindings(
            (
                ToolBinding(cls._descriptor("read_structured_input"), read_evidence),
                ToolBinding(cls._descriptor("draft_research_spec"), draft_research_spec),
                ToolBinding(cls._descriptor("execute_task"), execute_task),
                ToolBinding(cls._descriptor("publish_artifact"), authority_tool),
                ToolBinding(cls._descriptor("allocate_canonical_id"), authority_tool),
                ToolBinding(cls._descriptor("promote_canonical_truth"), authority_tool),
                ToolBinding(cls._descriptor("own_durable_task"), authority_tool),
            )
        )

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
        return PydanticAgentWorker(
            model=FunctionModel(self._model_response, model_name="track-d-function-model"),
            permission=permission,
            model_name="pydantic-test-model",
            provider_name="pydantic-test-provider",
            prompt_version="track-d-prompt-v0.1",
            tool_registry=self._registry(),
            requested_tool_names=("read_structured_input", "execute_task"),
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

    def test_exact_registered_read_binding_is_allowed_at_l0_and_l1(self) -> None:
        registry = self._registry()
        registered_read = registry.resolve(("read_structured_input",))
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L0_READ,
                registered_read,
                registry=registry,
            ),
            registered_read,
        )
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                registered_read,
                registry=registry,
            ),
            registered_read,
        )

    def test_exact_registered_draft_binding_is_allowed_only_at_l1(self) -> None:
        registry = self._registry()
        registered_draft = registry.resolve(("draft_research_spec",))
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L0_READ,
                registered_draft,
                registry=registry,
            ),
            (),
        )
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                registered_draft,
                registry=registry,
            ),
            registered_draft,
        )

    def test_registered_descriptor_with_different_callable_is_rejected(self) -> None:
        registry = self._registry()
        registered = registry.resolve(("read_structured_input",))[0]
        relabeled = ToolBinding(registered.descriptor, execute_task)
        with self.assertRaisesRegex(UntrustedToolBindingError, "canonical V3 registration"):
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                (relabeled,),
                registry=registry,
            )

    def test_worker_cannot_accept_or_invoke_untrusted_callable_relabelled_as_read(self) -> None:
        calls: list[str] = []

        def untrusted_side_effect(value: str) -> str:
            calls.append(value)
            return value

        registry = self._registry()
        registered = registry.resolve(("read_structured_input",))[0]
        relabeled = ToolBinding(registered.descriptor, untrusted_side_effect)
        with self.assertRaisesRegex(UntrustedToolBindingError, "canonical V3 registration"):
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                (relabeled,),
                registry=registry,
            )
        with self.assertRaisesRegex(TypeError, "unexpected keyword argument 'tool_bindings'"):
            PydanticAgentWorker(
                model=FunctionModel(self._model_response, model_name="track-d-function-model"),
                permission=PermissionLevel.L1_DRAFT,
                model_name="pydantic-test-model",
                provider_name="pydantic-test-provider",
                prompt_version="track-d-prompt-v0.1",
                tool_bindings=(relabeled,),
            )
        self.assertEqual(calls, [])

    def test_forged_safe_descriptor_binding_is_rejected_unless_registry_resolved(self) -> None:
        registry = self._registry()
        registered = registry.resolve(("read_structured_input",))[0]
        forged_descriptor = ToolDescriptor(
            name="read_structured_input",
            required_permission=PermissionLevel.L0_READ,
            effect=ToolEffect.READ,
        )
        forged_binding = ToolBinding(forged_descriptor, registered.function)
        with self.assertRaisesRegex(UntrustedToolBindingError, "canonical V3 registration"):
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                (forged_binding,),
                registry=registry,
            )

    def test_unregistered_safe_looking_tool_is_not_exposed(self) -> None:
        with self.assertRaisesRegex(UntrustedToolBindingError, "not registered"):
            self._registry().resolve(("forged_read",))

    def test_duplicate_binding_names_are_rejected(self) -> None:
        descriptor = self._descriptor("read_structured_input")
        with self.assertRaisesRegex(UntrustedToolBindingError, "duplicate tool binding names"):
            TrustedToolBindings(
                (
                    ToolBinding(descriptor, read_evidence),
                    ToolBinding(descriptor, execute_task),
                )
            )
        with self.assertRaisesRegex(UntrustedToolBindingError, "duplicate tool binding names"):
            self._registry().resolve(("read_structured_input", "read_structured_input"))

    def test_authority_bindings_are_never_exposed_at_l1(self) -> None:
        registry = self._registry()
        forbidden_names = (
            "execute_task",
            "publish_artifact",
            "allocate_canonical_id",
            "promote_canonical_truth",
            "own_durable_task",
        )
        resolved = registry.resolve(forbidden_names)
        self.assertEqual(
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                resolved,
                registry=registry,
            ),
            (),
        )

    def test_worker_rejects_unregistered_tool_names(self) -> None:
        with self.assertRaisesRegex(UntrustedToolBindingError, "not registered"):
            PydanticAgentWorker(
                model=FunctionModel(self._model_response, model_name="track-d-function-model"),
                permission=PermissionLevel.L1_DRAFT,
                model_name="pydantic-test-model",
                provider_name="pydantic-test-provider",
                prompt_version="track-d-prompt-v0.1",
                tool_registry=self._registry(),
                requested_tool_names=("forged_read",),
            )

    def test_worker_and_filter_reject_duck_typed_or_subclassed_registries(self) -> None:
        class ForgedRegistry(TrustedToolBindings):
            pass

        forged_registry = ForgedRegistry(())
        with self.assertRaisesRegex(UntrustedToolBindingError, "exact V3 TrustedToolBindings"):
            PydanticAgentWorker(
                model=FunctionModel(self._model_response, model_name="track-d-function-model"),
                permission=PermissionLevel.L1_DRAFT,
                model_name="pydantic-test-model",
                provider_name="pydantic-test-provider",
                prompt_version="track-d-prompt-v0.1",
                tool_registry=forged_registry,
                requested_tool_names=(),
            )
        with self.assertRaisesRegex(UntrustedToolBindingError, "exact V3 TrustedToolBindings"):
            filter_tool_bindings(
                PermissionLevel.L1_DRAFT,
                (),
                registry=forged_registry,
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
