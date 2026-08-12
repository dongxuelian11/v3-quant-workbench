from __future__ import annotations

import unittest

from v3_backend.domain.agent_research_loop import (
    AgentResearchProposal,
    BudgetConsumption,
    BudgetLimit,
    ExecutionReceiptRef,
    IterationStatus,
    NextActionProposal,
    ResearchActionDraft,
    ResearchActionType,
    ResearchLoopBudgetVersion,
    ResearchLoopContractError,
    ResearchLoopIterationRecord,
)


class AgentResearchLoopContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = ResearchLoopBudgetVersion.create(
            max_iterations=BudgetLimit.finite(2),
            max_actions=BudgetLimit.finite(2),
            max_candidates=BudgetLimit.finite(3),
            max_experiments=BudgetLimit.finite(1),
            max_model_calls=BudgetLimit.unlimited_explicit(),
            max_wallclock_seconds=BudgetLimit.finite(60),
            resource_profile_ref="resource-profile:test",
        )
        self.action = ResearchActionDraft.create(
            action_type=ResearchActionType.FACTOR_EVALUATE,
            exact_input_refs=("fdv:test",),
            requested_capability="factor.evaluate",
            expected_output_kind="FactorEvaluation",
            resource_profile_ref="resource-profile:test",
            budget_version_id=self.budget.budget_version_id,
        )
        self.proposal = AgentResearchProposal.create(
            agent_role="FactorAgent",
            research_goal_ref="goal:test",
            proposal_type="EVALUATE_FACTOR",
            rationale="Evaluate the exact canonical factor definition.",
            action_drafts=(self.action,),
            source_evidence_ids=("evidence:source",),
            model_runtime_provenance_ref="model-runtime:test",
        )

    def test_proposal_and_actions_are_noncanonical_drafts_and_not_run(self) -> None:
        self.assertEqual(self.proposal.authority_status, "NON_CANONICAL")
        self.assertEqual(self.proposal.lifecycle_state, "DRAFT")
        self.assertFalse(self.proposal.executed)
        self.assertFalse(self.proposal.published)
        self.assertEqual(self.action.state.value, "NOT_RUN")
        self.assertEqual(self.action.authority_status, "NON_CANONICAL")
        with self.assertRaisesRegex(ResearchLoopContractError, "UNREGISTERED_OR_UNAUTHORIZED_ACTION"):
            AgentResearchProposal(
                proposal_id="forged",
                agent_role="FactorAgent",
                research_goal_ref="goal:test",
                proposal_type="FORGED",
                rationale="forged",
                requested_action_draft_ids=(self.action.action_draft_id,),
                source_evidence_ids=(),
                model_runtime_provenance_ref=None,
                authority_status="FORMAL",
                executed=True,
                published=True,
            )

    def test_closed_action_vocabulary_rejects_unknown_actions(self) -> None:
        self.assertEqual(len(ResearchActionType), 11)
        with self.assertRaisesRegex(ResearchLoopContractError, "UNSUPPORTED_RESEARCH_ACTION"):
            ResearchActionDraft.create(
                action_type="PROMOTE_FACTOR",
                exact_input_refs=("fdv:test",),
                requested_capability="publish",
                expected_output_kind="Truth",
                resource_profile_ref="resource-profile:test",
                budget_version_id=self.budget.budget_version_id,
            )

    def test_only_existing_control_plane_can_issue_execution_receipt_refs(self) -> None:
        with self.assertRaisesRegex(ResearchLoopContractError, "UNREGISTERED_OR_UNAUTHORIZED_ACTION"):
            ExecutionReceiptRef("receipt:forged", "task:test", "run:test", "attempt:test", "AGENT")
        receipt = ExecutionReceiptRef(
            "receipt:authorized",
            "existing-task:test",
            "existing-run:test",
            "existing-attempt:test",
            "V3_CONTROL_PLANE",
        )
        self.assertEqual(receipt.run_id, "existing-run:test")

    def test_budget_is_deterministic_explicit_and_fail_closed(self) -> None:
        clone = ResearchLoopBudgetVersion.create(
            max_iterations=BudgetLimit.finite(2),
            max_actions=BudgetLimit.finite(2),
            max_candidates=BudgetLimit.finite(3),
            max_experiments=BudgetLimit.finite(1),
            max_model_calls=BudgetLimit.unlimited_explicit(),
            max_wallclock_seconds=BudgetLimit.finite(60),
            resource_profile_ref="resource-profile:test",
        )
        self.assertEqual(clone.budget_version_id, self.budget.budget_version_id)
        with self.assertRaises(ResearchLoopContractError):
            BudgetLimit.finite(0)
        with self.assertRaisesRegex(ResearchLoopContractError, "RESEARCH_BUDGET_EXCEEDED"):
            BudgetConsumption(3, 1, 0, 0, 0, 10).assert_admitted(self.budget)

    def test_iteration_binds_exact_existing_receipts_outputs_reviewer_and_reward(self) -> None:
        receipt = ExecutionReceiptRef(
            "receipt:authorized",
            "existing-task:test",
            "existing-run:test",
            "existing-attempt:test",
            "V3_CONTROL_PLANE",
        )
        consumption = BudgetConsumption(1, 1, 0, 1, 0, 15)
        next_action = NextActionProposal.create((self.action.action_draft_id,), "Await owner review.")
        record = ResearchLoopIterationRecord.create(
            iteration_index=0,
            proposal=self.proposal,
            action_drafts=(self.action,),
            execution_receipts=(receipt,),
            canonical_output_refs=("factor-evaluation:test",),
            review_report_ref="reviewer-report:test",
            reward_vector_ref="reward-vector:test",
            budget=self.budget,
            budget_consumption=consumption,
            next_action_proposals=(next_action,),
            status=IterationStatus.COMPLETE,
        )
        clone = ResearchLoopIterationRecord.create(
            iteration_index=0,
            proposal=self.proposal,
            action_drafts=(self.action,),
            execution_receipts=(receipt,),
            canonical_output_refs=("factor-evaluation:test",),
            review_report_ref="reviewer-report:test",
            reward_vector_ref="reward-vector:test",
            budget=self.budget,
            budget_consumption=consumption,
            next_action_proposals=(next_action,),
            status=IterationStatus.COMPLETE,
        )
        self.assertEqual(record, clone)
        self.assertEqual(record.iteration_index, 0)
        self.assertEqual(record.canonical_output_refs, ("factor-evaluation:test",))
        self.assertEqual(next_action.authority_status, "NON_CANONICAL")
        self.assertEqual(next_action.lifecycle_state, "DRAFT")

    def test_incomplete_or_blocked_history_cannot_masquerade_as_complete(self) -> None:
        with self.assertRaisesRegex(ResearchLoopContractError, "INCOMPLETE_ITERATION_CANNOT_COMPLETE"):
            ResearchLoopIterationRecord.create(
                iteration_index=0,
                proposal=self.proposal,
                action_drafts=(self.action,),
                execution_receipts=(),
                canonical_output_refs=(),
                review_report_ref=None,
                reward_vector_ref=None,
                budget=self.budget,
                budget_consumption=BudgetConsumption(1, 0, 0, 0, 0, 1),
                next_action_proposals=(),
                status=IterationStatus.COMPLETE,
            )
        blocked = ResearchLoopIterationRecord.create(
            iteration_index=0,
            proposal=self.proposal,
            action_drafts=(self.action,),
            execution_receipts=(),
            canonical_output_refs=(),
            review_report_ref=None,
            reward_vector_ref=None,
            budget=self.budget,
            budget_consumption=BudgetConsumption(1, 0, 0, 0, 0, 1),
            next_action_proposals=(),
            status=IterationStatus.BLOCKED,
        )
        self.assertIs(blocked.status, IterationStatus.BLOCKED)


if __name__ == "__main__":
    unittest.main()
