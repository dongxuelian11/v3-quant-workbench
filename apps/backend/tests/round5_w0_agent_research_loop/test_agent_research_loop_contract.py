from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib

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
    ResearchExecutionEvidenceResolver,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.experiments import (
    EvidenceStatus,
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentRun,
    ReviewerEvidence,
    RewardVector,
)
from v3_backend.domain.reviewer_integration import ReviewEvidenceRef, ResearchReviewScope
from v3_backend.domain.reviewer_integration.engine import review_research_scope
from v3_backend.domain.tasks.entities import (
    AttemptState, Run, RunIdentity, RunState, Task, TaskAttempt, TaskState,
)


def artifact(seed: str) -> str:
    return "art_sha256_" + hashlib.sha256(seed.encode()).hexdigest()


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
        self.assertEqual(receipt.resolution_status, "UNRESOLVED_REF")

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
        task, run, attempt = self._task_owner_objects()
        receipt = ResearchExecutionEvidenceResolver.resolve_execution(
            action=self.action, task=task, run=run, attempt=attempt
        )
        experiment_run, experiment_attempt, reviewer, reward = self._experiment_owner_objects()
        report = self._review_report(experiment_run, experiment_attempt, reviewer, reward)
        completion = ResearchExecutionEvidenceResolver.resolve_completion(
            action_drafts=(self.action,), executions=(receipt,),
            experiment_run=experiment_run, experiment_attempt=experiment_attempt,
            reviewer_evidence=reviewer, review_report=report, reward_vector=reward,
            canonical_output_refs=(reward.reward_vector_id,),
        )
        consumption = BudgetConsumption(1, 1, 0, 1, 0, 15)
        next_action = NextActionProposal.create((self.action.action_draft_id,), "Await owner review.")
        record = ResearchLoopIterationRecord.create(
            iteration_index=0,
            proposal=self.proposal,
            action_drafts=(self.action,),
            execution_receipts=(receipt,),
            canonical_output_refs=(),
            review_report_ref=None,
            reward_vector_ref=None,
            budget=self.budget,
            budget_consumption=consumption,
            next_action_proposals=(next_action,),
            status=IterationStatus.COMPLETE,
            completion_evidence=completion,
        )
        clone = ResearchLoopIterationRecord.create(
            iteration_index=0,
            proposal=self.proposal,
            action_drafts=(self.action,),
            execution_receipts=(receipt,),
            canonical_output_refs=(),
            review_report_ref=None,
            reward_vector_ref=None,
            budget=self.budget,
            budget_consumption=consumption,
            next_action_proposals=(next_action,),
            status=IterationStatus.COMPLETE,
            completion_evidence=completion,
        )
        self.assertEqual(record, clone)
        self.assertEqual(record.iteration_index, 0)
        self.assertEqual(record.canonical_output_refs, (reward.reward_vector_id,))
        self.assertEqual(next_action.authority_status, "NON_CANONICAL")
        self.assertEqual(next_action.lifecycle_state, "DRAFT")

    def test_raw_strings_and_unrelated_owner_receipts_cannot_complete(self) -> None:
        raw = ExecutionReceiptRef("receipt:forged", "task:x", "run:x", "attempt:x", "V3_CONTROL_PLANE")
        with self.assertRaisesRegex(ResearchLoopContractError, "INCOMPLETE_ITERATION_CANNOT_COMPLETE"):
            ResearchLoopIterationRecord.create(
                iteration_index=0, proposal=self.proposal, action_drafts=(self.action,),
                execution_receipts=(raw,), canonical_output_refs=("output:x",),
                review_report_ref="fake-review", reward_vector_ref="fake-reward",
                budget=self.budget, budget_consumption=BudgetConsumption(1, 1, 0, 1, 0, 1),
                next_action_proposals=(), status=IterationStatus.COMPLETE,
            )
        task, run, attempt = self._task_owner_objects()
        other = ResearchActionDraft.create(
            action_type=ResearchActionType.EVIDENCE_QUERY, exact_input_refs=("evidence:x",),
            requested_capability="evidence.read", expected_output_kind="Evidence",
            resource_profile_ref="resource-profile:test", budget_version_id=self.budget.budget_version_id,
        )
        unrelated = ResearchExecutionEvidenceResolver.resolve_execution(action=other, task=task, run=run, attempt=attempt)
        experiment_run, experiment_attempt, reviewer, reward = self._experiment_owner_objects()
        report = self._review_report(experiment_run, experiment_attempt, reviewer, reward)
        with self.assertRaisesRegex(ResearchLoopContractError, "ACTION_BINDING_MISMATCH"):
            ResearchExecutionEvidenceResolver.resolve_completion(
                action_drafts=(self.action,), executions=(unrelated,), experiment_run=experiment_run,
                experiment_attempt=experiment_attempt, reviewer_evidence=reviewer,
                review_report=report, reward_vector=reward,
                canonical_output_refs=(reward.reward_vector_id,),
            )
        forged_reward = replace(reward, reward_vector_id="rwv_sha256_" + "0" * 64)
        with self.assertRaisesRegex(ResearchLoopContractError, "REWARD_BINDING_MISMATCH"):
            ResearchExecutionEvidenceResolver.resolve_completion(
                action_drafts=(self.action,), executions=(ResearchExecutionEvidenceResolver.resolve_execution(action=self.action, task=task, run=run, attempt=attempt),),
                experiment_run=experiment_run, experiment_attempt=experiment_attempt,
                reviewer_evidence=reviewer, review_report=report, reward_vector=forged_reward,
                canonical_output_refs=(forged_reward.reward_vector_id,),
            )

    def _task_owner_objects(self):
        task_id, run_id, attempt_id = "tsk_" + "0" * 26, "run_" + "1" * 26, "att_" + "2" * 26
        task = Task(task_id, "prj_" + "3" * 26, "factor.evaluate", run_id, TaskState.SUCCEEDED)
        identity = RunIdentity("pcr_" + "4" * 26, "a" * 64, "code", "env", "contract")
        run = Run(run_id, task_id, identity, RunState.TERMINAL)
        attempt = TaskAttempt(attempt_id, task_id, run_id, 1, AttemptState.SUCCEEDED)
        return task, run, attempt

    def _experiment_owner_objects(self):
        run_basis = {
            "experiment_version_id": "expv_sha256_" + "b" * 64,
            "dataset_version_id": "dsv_sha256_" + "c" * 64,
            "factor_evaluation_id": "fev_sha256_" + "d" * 64,
            "code_version": "code", "environment_fingerprint": "env",
            "input_artifact_ids": [artifact("input")],
            "run_provenance_artifact_id": artifact("run"),
            "truth_admission": PRE_ALPHA_CEILING.to_wire(),
        }
        from v3_backend.provenance.canonical_hash import canonical_sha256
        run = ExperimentRun("exprun_sha256_" + canonical_sha256(run_basis), run_basis["experiment_version_id"], run_basis["dataset_version_id"], run_basis["factor_evaluation_id"], "code", "env", tuple(run_basis["input_artifact_ids"]), artifact("run"), PRE_ALPHA_CEILING)
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        attempt = ExperimentAttempt.create(
            run=run, ordinal=1, state=ExperimentAttemptState.SUCCEEDED,
            started_at=started, ended_at=started + timedelta(seconds=1),
            evidence_artifact_ids=(artifact("attempt"),), result_artifact_id=artifact("result"),
        )
        reviewer = ReviewerEvidence.create(
            lookahead=EvidenceStatus.PASS, leakage=EvidenceStatus.PASS, split=EvidenceStatus.PASS,
            sample_coverage=EvidenceStatus.PASS, missingness=EvidenceStatus.PASS,
            turnover=EvidenceStatus.PASS, complexity=EvidenceStatus.PASS,
            multiple_testing_robustness=EvidenceStatus.NOT_RUN, findings=(),
            provenance_artifact_id=artifact("reviewer"),
        )
        reward = RewardVector.create(
            run=run, attempt=attempt, coverage=.8, ic=.1, rank_ic=.1,
            lower_quantile_return=.01, upper_quantile_return=.03, quantile_spread=.02,
            turnover=.2, complexity=1, reviewer_evidence=reviewer,
            provenance_artifact_id=artifact("reward"), proposed_state=PRE_ALPHA_CEILING,
        )
        return run, attempt, reviewer, reward

    def _review_report(self, run, attempt, reviewer, reward):
        session = "session:w0-owner-review"
        values = (
            ("ExperimentRun", run.experiment_run_id),
            ("ExperimentAttempt", attempt.experiment_attempt_id),
            ("ReviewerEvidence", reviewer.reviewer_evidence_id),
            ("RewardVector", reward.reward_vector_id),
        )
        refs = tuple(ReviewEvidenceRef(session, kind, object_id, object_id.rsplit("_", 1)[-1]) for kind, object_id in values)
        return review_research_scope(ResearchReviewScope.create(session_id=session, target_refs=refs, evidence_records=()))

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
