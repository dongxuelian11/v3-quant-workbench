from __future__ import annotations

import unittest

from pydantic import ValidationError

from v3_backend.agents import (
    AgentKind,
    AgentProvenance,
    AlphaMiningRequestIntent,
    PermissionLevel,
    ResearchDraft,
    ResearchPayload,
    decide_permission,
    filter_tools,
)


class PermissionAndContractTests(unittest.TestCase):
    def test_l0_and_l1_allowed_l2_and_l3_denied_unknown_fails_closed(self) -> None:
        self.assertTrue(decide_permission(PermissionLevel.L0_READ).allowed)
        self.assertTrue(decide_permission(PermissionLevel.L1_DRAFT).allowed)
        self.assertEqual(decide_permission(PermissionLevel.L2_EXECUTE).reason, "V0_L2_EXECUTE_DENIED")
        self.assertFalse(decide_permission(PermissionLevel.L2_EXECUTE).allowed)
        self.assertEqual(decide_permission(PermissionLevel.L3_PUBLISH).reason, "V0_L3_PUBLISH_DENIED")
        self.assertFalse(decide_permission(PermissionLevel.L3_PUBLISH).allowed)
        unknown = decide_permission("L9_UNKNOWN")
        self.assertFalse(unknown.allowed)
        self.assertIsNone(unknown.normalized)
        self.assertEqual(unknown.reason, "UNKNOWN_PERMISSION_FAIL_CLOSED")

    def test_tool_filtering_exposes_only_l0_l1_and_never_authority_tools(self) -> None:
        l0 = filter_tools(PermissionLevel.L0_READ)
        self.assertEqual(tuple(item.name for item in l0.visible_tools), ("read_structured_input",))
        l1 = filter_tools(PermissionLevel.L1_DRAFT)
        self.assertEqual(
            tuple(item.name for item in l1.visible_tools),
            (
                "read_structured_input",
                "draft_research_spec",
                "draft_data_findings",
                "draft_reviewer_findings",
            ),
        )
        self.assertEqual(filter_tools(PermissionLevel.L2_EXECUTE).visible_tools, ())
        self.assertEqual(filter_tools(PermissionLevel.L3_PUBLISH).visible_tools, ())
        self.assertEqual(filter_tools("unknown").visible_tools, ())

    def _draft(self) -> ResearchDraft:
        payload = ResearchPayload(
            alpha_mining_request=AlphaMiningRequestIntent(
                hypothesis="Reversal may persist after available-time controls.",
                research_objective="Test a bounded reversal hypothesis.",
                universe_intent="Historical point-in-time liquid equities.",
                factor_intents=("Five-day reversal intent",),
                dataset_intents=("PIT adjusted daily bars",),
                experiment_intent="Draft a walk-forward evaluation intent only.",
            )
        )
        provenance = AgentProvenance(
            agent_kind=AgentKind.RESEARCH,
            sdk_version="2.27.0",
            model_name="test",
            provider_name="test",
            prompt_version="prompt-v1",
            instruction_version="track-d-research-v0.1",
            input_sha256="a" * 64,
        )
        return ResearchDraft(
            permission_decision=decide_permission(PermissionLevel.L1_DRAFT),
            provenance=provenance,
            payload=payload,
        )

    def test_proposal_is_explicitly_noncanonical_and_cannot_admit_publish_or_trigger_worker(self) -> None:
        draft = self._draft()
        self.assertEqual(draft.authority_status, "NON_CANONICAL")
        self.assertEqual(draft.lifecycle_state, "DRAFT")
        self.assertIsNone(draft.canonical_identity)
        self.assertIsNone(draft.admission_decision)
        self.assertFalse(draft.publish_authority)
        self.assertFalse(draft.payload.alpha_mining_request.worker_triggered)

    def test_canonical_object_cannot_masquerade_as_proposal(self) -> None:
        wire = self._draft().model_dump(mode="json")
        wire["canonical_truth_state"] = "FORMAL"
        wire["canonical_admission_state"] = "FORMAL_ADMITTED"
        with self.assertRaises(ValidationError):
            ResearchDraft.model_validate(wire)

    def test_serialization_and_fingerprint_are_deterministic(self) -> None:
        draft = self._draft()
        reparsed = ResearchDraft.model_validate_json(draft.to_deterministic_json())
        self.assertEqual(reparsed.to_deterministic_json(), draft.to_deterministic_json())
        self.assertEqual(reparsed.deterministic_sha256, draft.deterministic_sha256)


if __name__ == "__main__":
    unittest.main()
