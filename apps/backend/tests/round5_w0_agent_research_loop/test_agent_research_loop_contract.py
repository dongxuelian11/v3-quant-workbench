from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import hashlib

from v3_backend.adapters.agent_research_loop import ResearchExecutionEvidenceResolver
from v3_backend.control_plane.checkpoint_manager import CheckpointManager, InMemoryCheckpointPort
from v3_backend.control_plane.event_log import CollectingPublisher, DurableEventLog
from v3_backend.control_plane.persistence import InMemoryTaskPersistence
from v3_backend.control_plane.task_supervisor import TaskSupervisor
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
    ResearchSemanticEvidenceValidator,
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
from v3_backend.domain.tasks.state_machine import TaskTransitionContext


def artifact(seed: str) -> str:
    return "art_sha256_" + hashlib.sha256(seed.encode()).hexdigest()


class TEST_ONLY_PERSISTED_CONTROL_PLANE_FIXTURE_IDENTITIES:
    prefixes = {
        "Task": "tsk_", "Run": "run_", "TaskAttempt": "att_", "TaskEvent": "tev_",
    }

    def __init__(self) -> None:
        self.value = 0

    def new(self, object_type: str) -> str:
        self.value += 1
        return self.prefixes[object_type] + str(self.value).zfill(26)


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

    def test_persisted_lifecycle_is_observed_but_exact_action_binding_is_unavailable(self) -> None:
        persistence, supervisor, task, run, attempt = self._persisted_terminal_lifecycle()
        observation = ResearchExecutionEvidenceResolver(persistence).resolve_execution(
            action=self.action,
            task_id=task.task_id,
            run_id=run.run_id,
            attempt_id=attempt.attempt_id,
        )
        self.assertEqual(
            observation.resolution_status,
            "PERSISTED_TASK_OBSERVED_BUT_ACTION_BINDING_UNRESOLVED",
        )
        self.assertEqual(observation.normalized_input_hash, "a" * 64)
        experiment_run, experiment_attempt, reviewer, reward = self._experiment_owner_objects()
        report = self._review_report(experiment_run, experiment_attempt, reviewer, reward)
        semantic_evidence = ResearchSemanticEvidenceValidator.validate(
            experiment_run=experiment_run, experiment_attempt=experiment_attempt,
            reviewer_evidence=reviewer, review_report=report, reward_vector=reward,
            canonical_output_refs=(reward.reward_vector_id,),
        )
        self.assertEqual(semantic_evidence.reward_vector_ref, reward.reward_vector_id)
        with self.assertRaisesRegex(
            ResearchLoopContractError, "RESEARCH_ACTION_EXECUTION_BINDING_NOT_AVAILABLE"
        ):
            ResearchLoopIterationRecord.create(
                iteration_index=0, proposal=self.proposal, action_drafts=(self.action,),
                execution_receipts=(observation,), canonical_output_refs=(),
                review_report_ref=None, reward_vector_ref=None, budget=self.budget,
                budget_consumption=BudgetConsumption(1, 1, 0, 1, 0, 15),
                next_action_proposals=(), status=IterationStatus.COMPLETE,
                completion_evidence=semantic_evidence,
            )

    def test_raw_strings_and_manually_constructed_entities_cannot_complete(self) -> None:
        raw = ExecutionReceiptRef("receipt:forged", "task:x", "run:x", "attempt:x", "V3_CONTROL_PLANE")
        with self.assertRaisesRegex(ResearchLoopContractError, "RESEARCH_ACTION_EXECUTION_BINDING_NOT_AVAILABLE"):
            ResearchLoopIterationRecord.create(
                iteration_index=0, proposal=self.proposal, action_drafts=(self.action,),
                execution_receipts=(raw,), canonical_output_refs=("output:x",),
                review_report_ref="fake-review", reward_vector_ref="fake-reward",
                budget=self.budget, budget_consumption=BudgetConsumption(1, 1, 0, 1, 0, 1),
                next_action_proposals=(), status=IterationStatus.COMPLETE,
            )
        task, run, attempt = self._task_owner_objects()
        resolver = ResearchExecutionEvidenceResolver(InMemoryTaskPersistence())
        with self.assertRaises(TypeError):
            resolver.resolve_execution(  # type: ignore[call-arg]
                action=self.action, task=task, run=run, attempt=attempt
            )
        with self.assertRaisesRegex(ResearchLoopContractError, "CONTROL_PLANE_PERSISTENCE_TASK_NOT_FOUND"):
            resolver.resolve_execution(
                action=self.action, task_id=task.task_id, run_id=run.run_id, attempt_id=attempt.attempt_id
            )
        experiment_run, experiment_attempt, reviewer, reward = self._experiment_owner_objects()
        report = self._review_report(experiment_run, experiment_attempt, reviewer, reward)
        forged_reward = replace(reward, reward_vector_id="rwv_sha256_" + "0" * 64)
        with self.assertRaisesRegex(ResearchLoopContractError, "REWARD_BINDING_MISMATCH"):
            ResearchSemanticEvidenceValidator.validate(
                experiment_run=experiment_run, experiment_attempt=experiment_attempt,
                reviewer_evidence=reviewer, review_report=report, reward_vector=forged_reward,
                canonical_output_refs=(forged_reward.reward_vector_id,),
            )

    def test_persistence_missing_aggregates_fail_closed(self) -> None:
        task, run, attempt = self._task_owner_objects()
        cases = (
            ("task", "CONTROL_PLANE_PERSISTENCE_TASK_NOT_FOUND"),
            ("run", "CONTROL_PLANE_PERSISTENCE_RUN_NOT_FOUND"),
            ("attempt", "CONTROL_PLANE_PERSISTENCE_ATTEMPT_NOT_FOUND"),
        )
        for present, code in cases:
            with self.subTest(present=present):
                persistence = InMemoryTaskPersistence()
                with persistence.begin() as unit:
                    if present != "task": unit.add_task(task)
                    if present == "attempt": unit.add_run(run)
                    unit.commit()
                with self.assertRaisesRegex(ResearchLoopContractError, code):
                    ResearchExecutionEvidenceResolver(persistence).resolve_execution(
                        action=self.action, task_id=task.task_id,
                        run_id=run.run_id, attempt_id=attempt.attempt_id,
                    )

    def test_persisted_relation_state_and_capability_mismatches_fail_closed(self) -> None:
        task, run, attempt = self._task_owner_objects()
        variants = (
            (replace(task, active_run_id="run_" + "8" * 26), run, attempt, "OWNER_EXECUTION_BINDING_MISMATCH"),
            (task, replace(run, state=RunState.ACTIVE), attempt, "OWNER_RUN_NOT_TERMINAL"),
            (replace(task, state=TaskState.RUNNING), run, attempt, "OWNER_TASK_NOT_SUCCEEDED"),
            (task, run, replace(attempt, state=AttemptState.FAILED), "OWNER_ATTEMPT_NOT_SUCCEEDED"),
            (replace(task, operation_id="factor.other"), run, attempt, "RESEARCH_ACTION_CAPABILITY_MISMATCH"),
        )
        for stored_task, stored_run, stored_attempt, code in variants:
            with self.subTest(code=code):
                persistence = InMemoryTaskPersistence()
                with persistence.begin() as unit:
                    unit.add_task(stored_task); unit.add_run(stored_run); unit.add_attempt(stored_attempt); unit.commit()
                with self.assertRaisesRegex(ResearchLoopContractError, code):
                    ResearchExecutionEvidenceResolver(persistence).resolve_execution(
                        action=self.action, task_id=task.task_id,
                        run_id=run.run_id, attempt_id=attempt.attempt_id,
                    )

    def test_correct_shaped_ids_do_not_replace_persisted_identity(self) -> None:
        task, run, attempt = self._task_owner_objects()
        persistence = InMemoryTaskPersistence()
        persistence.tasks[task.task_id] = replace(task, task_id="tsk_" + "9" * 26)
        persistence.runs[run.run_id] = run
        persistence.attempts[attempt.attempt_id] = attempt
        with self.assertRaisesRegex(ResearchLoopContractError, "CONTROL_PLANE_PERSISTENCE_IDENTITY_MISMATCH"):
            ResearchExecutionEvidenceResolver(persistence).resolve_execution(
                action=self.action, task_id=task.task_id,
                run_id=run.run_id, attempt_id=attempt.attempt_id,
            )

    def test_manually_seeded_terminal_store_still_cannot_resolve_action_binding(self) -> None:
        task, run, attempt = self._task_owner_objects()
        persistence = InMemoryTaskPersistence()
        with persistence.begin() as unit:
            unit.add_task(task); unit.add_run(run); unit.add_attempt(attempt); unit.commit()
        observation = ResearchExecutionEvidenceResolver(persistence).resolve_execution(
            action=self.action, task_id=task.task_id,
            run_id=run.run_id, attempt_id=attempt.attempt_id,
        )
        self.assertEqual(
            observation.resolution_status,
            "PERSISTED_TASK_OBSERVED_BUT_ACTION_BINDING_UNRESOLVED",
        )
        with self.assertRaisesRegex(
            ResearchLoopContractError, "RESEARCH_ACTION_EXECUTION_BINDING_NOT_AVAILABLE"
        ):
            ResearchLoopIterationRecord.create(
                iteration_index=0, proposal=self.proposal, action_drafts=(self.action,),
                execution_receipts=(observation,), canonical_output_refs=(),
                review_report_ref="review:string", reward_vector_ref="reward:string",
                budget=self.budget, budget_consumption=BudgetConsumption(1, 1, 0, 0, 0, 1),
                next_action_proposals=(), status=IterationStatus.COMPLETE,
            )

    def _task_owner_objects(self):
        task_id, run_id, attempt_id = "tsk_" + "0" * 26, "run_" + "1" * 26, "att_" + "2" * 26
        task = Task(task_id, "prj_" + "3" * 26, "factor.evaluate", run_id, TaskState.SUCCEEDED)
        identity = RunIdentity("pcr_" + "4" * 26, "a" * 64, "code", "env", "contract")
        run = Run(run_id, task_id, identity, RunState.TERMINAL)
        attempt = TaskAttempt(attempt_id, task_id, run_id, 1, AttemptState.SUCCEEDED)
        return task, run, attempt

    def _persisted_terminal_lifecycle(self):
        persistence = InMemoryTaskPersistence()
        supervisor = TaskSupervisor(
            DurableEventLog(persistence, CollectingPublisher()),
            TEST_ONLY_PERSISTED_CONTROL_PLANE_FIXTURE_IDENTITIES(),
            CheckpointManager(InMemoryCheckpointPort()),
        )
        identity = RunIdentity("pcr_" + "4" * 26, "a" * 64, "code", "env", "contract")
        task, run, attempt = supervisor.accept(
            "prj_" + "3" * 26, self.action.requested_capability, identity
        )
        supervisor.assign_lease(attempt.attempt_id, "lea_" + "5" * 26)
        supervisor.transition_attempt(attempt.attempt_id, "WORKER_DISPATCHED")
        supervisor.transition_attempt(attempt.attempt_id, "WORKER_ACKNOWLEDGED")
        supervisor.mark_task_started_for_attempt(attempt.attempt_id)
        supervisor.transition_attempt(attempt.attempt_id, "ATTEMPT_SUCCEEDED")
        supervisor.transition_task(
            task.task_id, "ALL_REQUIRED_ARTIFACTS_PUBLISHED",
            TaskTransitionContext(successful_attempt=True, publication_committed=True),
        )
        supervisor.finalize_run(task.task_id)
        return persistence, supervisor, task, run, attempt

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
        with self.assertRaisesRegex(ResearchLoopContractError, "RESEARCH_ACTION_EXECUTION_BINDING_NOT_AVAILABLE"):
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
        for status in (IterationStatus.PROPOSED, IterationStatus.PARTIALLY_EXECUTED):
            with self.subTest(status=status):
                record = ResearchLoopIterationRecord.create(
                    iteration_index=0, proposal=self.proposal,
                    action_drafts=(self.action,), execution_receipts=(),
                    canonical_output_refs=(), review_report_ref=None,
                    reward_vector_ref=None, budget=self.budget,
                    budget_consumption=BudgetConsumption(1, 0, 0, 0, 0, 1),
                    next_action_proposals=(), status=status,
                )
                self.assertIs(record.status, status)


if __name__ == "__main__":
    unittest.main()
