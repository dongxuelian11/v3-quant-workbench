from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from enum import StrEnum

from v3_backend.domain.experiments import (
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentRun,
    ReviewerEvidence,
    RewardVector,
)
from v3_backend.domain.reviewer_integration import ResearchReviewReport
from v3_backend.domain.tasks.entities import (
    AttemptState,
    Run,
    RunState,
    Task,
    TaskAttempt,
    TaskState,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


class ResearchLoopContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _text(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise ResearchLoopContractError("INVALID_RESEARCH_CONTRACT", f"{name} is required")
    return value


def _refs(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if any(not value or value != value.strip() for value in values):
        raise ResearchLoopContractError("INVALID_RESEARCH_CONTRACT", f"{name} contains an invalid ref")
    if len(values) != len(set(values)):
        raise ResearchLoopContractError("INVALID_RESEARCH_CONTRACT", f"{name} must be unique")
    return tuple(sorted(values))


class ResearchActionType(StrEnum):
    FACTOR_DRAFT_CREATE = "FACTOR_DRAFT_CREATE"
    FACTOR_IMPORT = "FACTOR_IMPORT"
    FACTOR_EVALUATE = "FACTOR_EVALUATE"
    MODEL_TRAIN = "MODEL_TRAIN"
    MODEL_PREDICT = "MODEL_PREDICT"
    PORTFOLIO_CONSTRUCT = "PORTFOLIO_CONSTRUCT"
    RISK_APPLY = "RISK_APPLY"
    BACKTEST_RUN = "BACKTEST_RUN"
    REVIEW_RUN = "REVIEW_RUN"
    EVIDENCE_QUERY = "EVIDENCE_QUERY"
    RESULT_COMPARE = "RESULT_COMPARE"


class ResearchActionState(StrEnum):
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, slots=True)
class ResearchActionDraft:
    action_draft_id: str
    action_type: ResearchActionType
    exact_input_refs: tuple[str, ...]
    requested_capability: str
    expected_output_kind: str
    resource_profile_ref: str
    budget_version_id: str
    state: ResearchActionState = ResearchActionState.NOT_RUN
    authority_status: str = "NON_CANONICAL"

    def __post_init__(self) -> None:
        if self.state is not ResearchActionState.NOT_RUN or self.authority_status != "NON_CANONICAL":
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION",
                "an action draft is always NON_CANONICAL and NOT_RUN",
            )

    @classmethod
    def create(
        cls,
        *,
        action_type: ResearchActionType | str,
        exact_input_refs: tuple[str, ...],
        requested_capability: str,
        expected_output_kind: str,
        resource_profile_ref: str,
        budget_version_id: str,
    ) -> ResearchActionDraft:
        try:
            normalized = ResearchActionType(action_type)
        except ValueError as error:
            raise ResearchLoopContractError(
                "UNSUPPORTED_RESEARCH_ACTION", str(action_type)
            ) from error
        payload = {
            "action_type": normalized.value,
            "exact_input_refs": list(_refs(exact_input_refs, "exact_input_refs")),
            "requested_capability": _text(requested_capability, "requested_capability"),
            "expected_output_kind": _text(expected_output_kind, "expected_output_kind"),
            "resource_profile_ref": _text(resource_profile_ref, "resource_profile_ref"),
            "budget_version_id": _text(budget_version_id, "budget_version_id"),
            "state": ResearchActionState.NOT_RUN.value,
            "authority_status": "NON_CANONICAL",
        }
        return cls(
            action_draft_id="rad_sha256_" + canonical_sha256(payload),
            action_type=normalized,
            exact_input_refs=tuple(payload["exact_input_refs"]),
            requested_capability=payload["requested_capability"],
            expected_output_kind=payload["expected_output_kind"],
            resource_profile_ref=payload["resource_profile_ref"],
            budget_version_id=payload["budget_version_id"],
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "action_draft_id": self.action_draft_id,
            "action_type": self.action_type.value,
            "exact_input_refs": list(self.exact_input_refs),
            "requested_capability": self.requested_capability,
            "expected_output_kind": self.expected_output_kind,
            "resource_profile_ref": self.resource_profile_ref,
            "budget_version_id": self.budget_version_id,
            "state": self.state.value,
            "authority_status": self.authority_status,
        }


@dataclass(frozen=True, slots=True)
class AgentResearchProposal:
    proposal_id: str
    agent_role: str
    research_goal_ref: str
    proposal_type: str
    rationale: str
    requested_action_draft_ids: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]
    model_runtime_provenance_ref: str | None
    authority_status: str = "NON_CANONICAL"
    lifecycle_state: str = "DRAFT"
    executed: bool = False
    published: bool = False

    def __post_init__(self) -> None:
        if (
            self.authority_status != "NON_CANONICAL"
            or self.lifecycle_state != "DRAFT"
            or self.executed
            or self.published
        ):
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION",
                "proposal cannot claim truth, execution, or publication",
            )

    @classmethod
    def create(
        cls,
        *,
        agent_role: str,
        research_goal_ref: str,
        proposal_type: str,
        rationale: str,
        action_drafts: tuple[ResearchActionDraft, ...],
        source_evidence_ids: tuple[str, ...] = (),
        model_runtime_provenance_ref: str | None = None,
    ) -> AgentResearchProposal:
        action_ids = _refs(
            tuple(value.action_draft_id for value in action_drafts),
            "requested_action_draft_ids",
        )
        if not action_ids:
            raise ResearchLoopContractError(
                "INVALID_RESEARCH_CONTRACT", "proposal requires an action draft"
            )
        payload = {
            "agent_role": _text(agent_role, "agent_role"),
            "research_goal_ref": _text(research_goal_ref, "research_goal_ref"),
            "proposal_type": _text(proposal_type, "proposal_type"),
            "rationale": _text(rationale, "rationale"),
            "requested_action_draft_ids": list(action_ids),
            "source_evidence_ids": list(_refs(source_evidence_ids, "source_evidence_ids")),
            "model_runtime_provenance_ref": model_runtime_provenance_ref,
            "authority_status": "NON_CANONICAL",
            "lifecycle_state": "DRAFT",
        }
        if model_runtime_provenance_ref is not None:
            _text(model_runtime_provenance_ref, "model_runtime_provenance_ref")
        return cls(
            proposal_id="arp_sha256_" + canonical_sha256(payload),
            agent_role=payload["agent_role"],
            research_goal_ref=payload["research_goal_ref"],
            proposal_type=payload["proposal_type"],
            rationale=payload["rationale"],
            requested_action_draft_ids=action_ids,
            source_evidence_ids=tuple(payload["source_evidence_ids"]),
            model_runtime_provenance_ref=model_runtime_provenance_ref,
        )


class BudgetLimitMode(StrEnum):
    FINITE = "FINITE"
    UNLIMITED = "UNLIMITED_EXPLICIT"


@dataclass(frozen=True, slots=True)
class BudgetLimit:
    mode: BudgetLimitMode
    value: int | None

    def __post_init__(self) -> None:
        if self.mode is BudgetLimitMode.FINITE:
            if not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 1:
                raise ResearchLoopContractError(
                    "INVALID_RESEARCH_BUDGET", "finite limits must be positive integers"
                )
        elif self.mode is BudgetLimitMode.UNLIMITED:
            if self.value is not None:
                raise ResearchLoopContractError(
                    "INVALID_RESEARCH_BUDGET", "unlimited must use an explicit null value"
                )
        else:
            raise ResearchLoopContractError("INVALID_RESEARCH_BUDGET", "unknown limit mode")

    @classmethod
    def finite(cls, value: int) -> BudgetLimit:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ResearchLoopContractError(
                "INVALID_RESEARCH_BUDGET", "finite limits must be positive integers"
            )
        return cls(BudgetLimitMode.FINITE, value)

    @classmethod
    def unlimited_explicit(cls) -> BudgetLimit:
        return cls(BudgetLimitMode.UNLIMITED, None)

    def to_wire(self) -> dict[str, object]:
        return {"mode": self.mode.value, "value": self.value}

    def admits(self, consumed: int) -> bool:
        if not isinstance(consumed, int) or isinstance(consumed, bool) or consumed < 0:
            return False
        return self.mode is BudgetLimitMode.UNLIMITED or consumed <= self.value  # type: ignore[operator]


@dataclass(frozen=True, slots=True)
class ResearchLoopBudgetVersion:
    budget_version_id: str
    max_iterations: BudgetLimit
    max_actions: BudgetLimit
    max_candidates: BudgetLimit
    max_experiments: BudgetLimit
    max_model_calls: BudgetLimit
    resource_profile_ref: str
    max_wallclock_seconds: BudgetLimit | None = None

    @classmethod
    def create(cls, **values: object) -> ResearchLoopBudgetVersion:
        required = (
            "max_iterations",
            "max_actions",
            "max_candidates",
            "max_experiments",
            "max_model_calls",
        )
        if any(not isinstance(values.get(name), BudgetLimit) for name in required):
            raise ResearchLoopContractError(
                "INVALID_RESEARCH_BUDGET", "all loop bounds must be explicit BudgetLimit values"
            )
        wallclock = values.get("max_wallclock_seconds")
        if wallclock is not None and not isinstance(wallclock, BudgetLimit):
            raise ResearchLoopContractError(
                "INVALID_RESEARCH_BUDGET", "wallclock bound must be explicit"
            )
        resource_ref = _text(str(values.get("resource_profile_ref", "")), "resource_profile_ref")
        payload = {
            name: values[name].to_wire()  # type: ignore[union-attr]
            for name in required
        }
        payload["resource_profile_ref"] = resource_ref
        payload["max_wallclock_seconds"] = None if wallclock is None else wallclock.to_wire()
        return cls(
            budget_version_id="rlb_sha256_" + canonical_sha256(payload),
            max_iterations=values["max_iterations"],  # type: ignore[arg-type]
            max_actions=values["max_actions"],  # type: ignore[arg-type]
            max_candidates=values["max_candidates"],  # type: ignore[arg-type]
            max_experiments=values["max_experiments"],  # type: ignore[arg-type]
            max_model_calls=values["max_model_calls"],  # type: ignore[arg-type]
            resource_profile_ref=resource_ref,
            max_wallclock_seconds=wallclock,
        )


@dataclass(frozen=True, slots=True)
class BudgetConsumption:
    iterations: int
    actions: int
    candidates: int
    experiments: int
    model_calls: int
    wallclock_seconds: int | None = None

    def assert_admitted(self, budget: ResearchLoopBudgetVersion) -> None:
        checks = (
            (budget.max_iterations, self.iterations),
            (budget.max_actions, self.actions),
            (budget.max_candidates, self.candidates),
            (budget.max_experiments, self.experiments),
            (budget.max_model_calls, self.model_calls),
        )
        if any(not limit.admits(value) for limit, value in checks):
            raise ResearchLoopContractError("RESEARCH_BUDGET_EXCEEDED", budget.budget_version_id)
        if budget.max_wallclock_seconds is not None:
            if self.wallclock_seconds is None or not budget.max_wallclock_seconds.admits(self.wallclock_seconds):
                raise ResearchLoopContractError("RESEARCH_BUDGET_EXCEEDED", "wallclock")

    def to_wire(self) -> dict[str, object]:
        return {
            "iterations": self.iterations,
            "actions": self.actions,
            "candidates": self.candidates,
            "experiments": self.experiments,
            "model_calls": self.model_calls,
            "wallclock_seconds": self.wallclock_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExecutionReceiptRef:
    authorization_receipt_id: str
    task_id: str
    run_id: str
    attempt_id: str
    issued_by: str
    resolution_status: str = "UNRESOLVED_REF"
    action_draft_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("authorization_receipt_id", "task_id", "run_id", "attempt_id"):
            _text(getattr(self, name), name)
        if self.issued_by != "V3_CONTROL_PLANE":
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION",
                "execution receipts must be issued by the existing V3 Control Plane",
            )
        if self.resolution_status != "UNRESOLVED_REF" or self.action_draft_id is not None:
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION",
                "raw receipt refs are always UNRESOLVED_REF",
            )

    def to_wire(self) -> dict[str, str | None]:
        return {
            "authorization_receipt_id": self.authorization_receipt_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "issued_by": self.issued_by,
            "resolution_status": self.resolution_status,
            "action_draft_id": self.action_draft_id,
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedExecutionEvidence:
    authorization_receipt_id: str
    action_draft_id: str
    task_id: str
    run_id: str
    attempt_id: str
    resolution_status: str

    @classmethod
    def _from_owner_objects(
        cls, action: ResearchActionDraft, task: Task, run: Run, attempt: TaskAttempt
    ) -> ResolvedExecutionEvidence:
        if task.state is not TaskState.SUCCEEDED or run.state is not RunState.TERMINAL or attempt.state is not AttemptState.SUCCEEDED:
            raise ResearchLoopContractError("OWNER_EXECUTION_NOT_COMPLETE", action.action_draft_id)
        if task.active_run_id != run.run_id or run.task_id != task.task_id:
            raise ResearchLoopContractError("OWNER_EXECUTION_BINDING_MISMATCH", action.action_draft_id)
        if attempt.task_id != task.task_id or attempt.run_id != run.run_id:
            raise ResearchLoopContractError("OWNER_EXECUTION_BINDING_MISMATCH", action.action_draft_id)
        payload = {
            "action_draft_id": action.action_draft_id,
            "task_id": task.task_id,
            "run_id": run.run_id,
            "attempt_id": attempt.attempt_id,
            "attempt_ordinal": attempt.ordinal,
            "issuer": "V3_CONTROL_PLANE_OWNER_RESOLVED",
        }
        value = object.__new__(cls)
        object.__setattr__(value, "authorization_receipt_id", "rer_sha256_" + canonical_sha256(payload))
        object.__setattr__(value, "action_draft_id", action.action_draft_id)
        object.__setattr__(value, "task_id", task.task_id)
        object.__setattr__(value, "run_id", run.run_id)
        object.__setattr__(value, "attempt_id", attempt.attempt_id)
        object.__setattr__(value, "resolution_status", "RESOLVED_OWNER_REF")
        return value

    def to_wire(self) -> dict[str, str]:
        return {
            "authorization_receipt_id": self.authorization_receipt_id,
            "action_draft_id": self.action_draft_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "resolution_status": self.resolution_status,
        }


@dataclass(frozen=True, slots=True, init=False)
class ResolvedResearchCompletionEvidence:
    executions: tuple[ResolvedExecutionEvidence, ...]
    review_report_ref: str
    reward_vector_ref: str
    canonical_output_refs: tuple[str, ...]


class ResearchExecutionEvidenceResolver:
    """W0-owned thin resolver; actual owner objects remain the authority."""

    @staticmethod
    def resolve_execution(
        *, action: ResearchActionDraft, task: Task, run: Run, attempt: TaskAttempt
    ) -> ResolvedExecutionEvidence:
        return ResolvedExecutionEvidence._from_owner_objects(action, task, run, attempt)

    @staticmethod
    def resolve_completion(
        *,
        action_drafts: tuple[ResearchActionDraft, ...],
        executions: tuple[ResolvedExecutionEvidence, ...],
        experiment_run: ExperimentRun,
        experiment_attempt: ExperimentAttempt,
        reviewer_evidence: ReviewerEvidence,
        review_report: ResearchReviewReport,
        reward_vector: RewardVector,
        canonical_output_refs: tuple[str, ...],
    ) -> ResolvedResearchCompletionEvidence:
        action_ids = tuple(sorted(value.action_draft_id for value in action_drafts))
        execution_ids = tuple(sorted(value.action_draft_id for value in executions))
        if action_ids != execution_ids or any(value.resolution_status != "RESOLVED_OWNER_REF" for value in executions):
            raise ResearchLoopContractError("ACTION_BINDING_MISMATCH", "resolved executions")
        if experiment_attempt.state is not ExperimentAttemptState.SUCCEEDED or experiment_attempt.experiment_run_id != experiment_run.experiment_run_id:
            raise ResearchLoopContractError("OWNER_EXECUTION_BINDING_MISMATCH", "Experiment Run/Attempt")
        run_basis = {
            "experiment_version_id": experiment_run.experiment_version_id,
            "dataset_version_id": experiment_run.dataset_version_id,
            "factor_evaluation_id": experiment_run.factor_evaluation_id,
            "code_version": experiment_run.code_version,
            "environment_fingerprint": experiment_run.environment_fingerprint,
            "input_artifact_ids": list(experiment_run.input_artifact_ids),
            "run_provenance_artifact_id": experiment_run.run_provenance_artifact_id,
            "truth_admission": experiment_run.truth_admission.to_wire(),
        }
        if experiment_run.experiment_run_id != "exprun_sha256_" + canonical_sha256(run_basis):
            raise ResearchLoopContractError("OWNER_EXECUTION_BINDING_MISMATCH", "ExperimentRun identity")
        attempt_basis = {
            "experiment_run_id": experiment_attempt.experiment_run_id,
            "ordinal": experiment_attempt.ordinal,
            "state": experiment_attempt.state.value,
            "started_at": experiment_attempt.started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "ended_at": experiment_attempt.ended_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "evidence_artifact_ids": list(experiment_attempt.evidence_artifact_ids),
            "result_artifact_id": experiment_attempt.result_artifact_id,
            "error_code": experiment_attempt.error_code,
        }
        if experiment_attempt.experiment_attempt_id != "expatt_sha256_" + canonical_sha256(attempt_basis):
            raise ResearchLoopContractError("OWNER_EXECUTION_BINDING_MISMATCH", "ExperimentAttempt identity")
        reviewer_basis = {
            "lookahead": reviewer_evidence.lookahead.value,
            "leakage": reviewer_evidence.leakage.value,
            "split": reviewer_evidence.split.value,
            "sample_coverage": reviewer_evidence.sample_coverage.value,
            "missingness": reviewer_evidence.missingness.value,
            "turnover": reviewer_evidence.turnover.value,
            "complexity": reviewer_evidence.complexity.value,
            "multiple_testing_robustness": reviewer_evidence.multiple_testing_robustness.value,
            "finding_ids": list(reviewer_evidence.finding_ids),
            "provenance_artifact_id": reviewer_evidence.provenance_artifact_id,
        }
        if reviewer_evidence.reviewer_evidence_id != "rve_sha256_" + canonical_sha256(reviewer_basis):
            raise ResearchLoopContractError("REVIEW_BINDING_MISMATCH", "ReviewerEvidence identity")
        if reward_vector.experiment_run_id != experiment_run.experiment_run_id or reward_vector.experiment_attempt_id != experiment_attempt.experiment_attempt_id or reward_vector.reviewer_evidence_id != reviewer_evidence.reviewer_evidence_id:
            raise ResearchLoopContractError("REWARD_BINDING_MISMATCH", reward_vector.reward_vector_id)
        review_basis = {
            "session_id": review_report.session_id,
            "target_refs": [value.to_wire() for value in review_report.target_refs],
            "rule_set_id": review_report.rule_set_id,
            "rule_set_content_sha256": review_report.rule_set_content_sha256,
            "deterministic_checks": [value.to_wire() for value in review_report.deterministic_checks],
            "source_evidence_refs": [value.to_wire() for value in review_report.source_evidence_refs],
            "truth_ceiling": review_report.truth_ceiling.to_wire(),
        }
        if review_report.review_report_id != "rrp_sha256_" + canonical_sha256(review_basis):
            raise ResearchLoopContractError("REVIEW_BINDING_MISMATCH", "review report identity")
        reward_basis = {
            "experiment_run_id": reward_vector.experiment_run_id,
            "experiment_attempt_id": reward_vector.experiment_attempt_id,
            "coverage": reward_vector.coverage,
            "ic": reward_vector.ic,
            "rank_ic": reward_vector.rank_ic,
            "lower_quantile_return": reward_vector.lower_quantile_return,
            "upper_quantile_return": reward_vector.upper_quantile_return,
            "quantile_spread": reward_vector.quantile_spread,
            "turnover": reward_vector.turnover,
            "complexity": reward_vector.complexity,
            "reviewer_evidence_id": reward_vector.reviewer_evidence_id,
            "provenance_artifact_id": reward_vector.provenance_artifact_id,
            "truth_admission": reward_vector.truth_admission.to_wire(),
        }
        if reward_vector.reward_vector_id != "rwv_sha256_" + canonical_sha256(reward_basis):
            raise ResearchLoopContractError("REWARD_BINDING_MISMATCH", "reward identity")
        report_refs = tuple(review_report.target_refs) + tuple(review_report.source_evidence_refs) + tuple(
            ref for check in review_report.deterministic_checks for ref in check.evidence_refs
        )
        observed = {(value.object_kind, value.object_id) for value in report_refs}
        required = {
            ("ExperimentRun", experiment_run.experiment_run_id),
            ("ExperimentAttempt", experiment_attempt.experiment_attempt_id),
            ("ReviewerEvidence", reviewer_evidence.reviewer_evidence_id),
            ("RewardVector", reward_vector.reward_vector_id),
        }
        if not required.issubset(observed) or any(
            not value.id_hash_matches
            for value in report_refs
            if (value.object_kind, value.object_id) in required
        ):
            raise ResearchLoopContractError("REVIEW_BINDING_MISMATCH", review_report.review_report_id)
        outputs = _refs(canonical_output_refs, "canonical_output_refs")
        if reward_vector.reward_vector_id not in outputs:
            raise ResearchLoopContractError("REWARD_BINDING_MISMATCH", "reward must be a canonical output")
        value = object.__new__(ResolvedResearchCompletionEvidence)
        object.__setattr__(value, "executions", tuple(sorted(executions, key=lambda item: item.action_draft_id)))
        object.__setattr__(value, "review_report_ref", review_report.review_report_id)
        object.__setattr__(value, "reward_vector_ref", reward_vector.reward_vector_id)
        object.__setattr__(value, "canonical_output_refs", outputs)
        return value


class IterationStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    REVIEWED = "REVIEWED"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class NextActionProposal:
    proposal_id: str
    action_draft_ids: tuple[str, ...]
    rationale: str
    authority_status: str = "NON_CANONICAL"
    lifecycle_state: str = "DRAFT"

    def __post_init__(self) -> None:
        if self.authority_status != "NON_CANONICAL" or self.lifecycle_state != "DRAFT":
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION",
                "next action remains a non-canonical draft",
            )

    @classmethod
    def create(cls, action_draft_ids: tuple[str, ...], rationale: str) -> NextActionProposal:
        ids = _refs(action_draft_ids, "action_draft_ids")
        payload = {"action_draft_ids": list(ids), "rationale": _text(rationale, "rationale")}
        return cls("nap_sha256_" + canonical_sha256(payload), ids, payload["rationale"])


@dataclass(frozen=True, slots=True)
class ResearchLoopIterationRecord:
    iteration_record_id: str
    iteration_index: int
    proposal_id: str
    action_draft_ids: tuple[str, ...]
    execution_receipts: tuple[ExecutionReceiptRef | ResolvedExecutionEvidence, ...]
    canonical_output_refs: tuple[str, ...]
    review_report_ref: str | None
    reward_vector_ref: str | None
    budget_version_id: str
    budget_consumption: BudgetConsumption
    next_action_proposal_refs: tuple[str, ...]
    status: IterationStatus

    @classmethod
    def create(
        cls,
        *,
        iteration_index: int,
        proposal: AgentResearchProposal,
        action_drafts: tuple[ResearchActionDraft, ...],
        execution_receipts: tuple[ExecutionReceiptRef | ResolvedExecutionEvidence, ...],
        canonical_output_refs: tuple[str, ...],
        review_report_ref: str | None,
        reward_vector_ref: str | None,
        budget: ResearchLoopBudgetVersion,
        budget_consumption: BudgetConsumption,
        next_action_proposals: tuple[NextActionProposal, ...],
        status: IterationStatus,
        completion_evidence: ResolvedResearchCompletionEvidence | None = None,
    ) -> ResearchLoopIterationRecord:
        if not isinstance(iteration_index, int) or isinstance(iteration_index, bool) or iteration_index < 0:
            raise ResearchLoopContractError("INVALID_ITERATION_INDEX", str(iteration_index))
        action_ids = _refs(tuple(value.action_draft_id for value in action_drafts), "action_draft_ids")
        if action_ids != proposal.requested_action_draft_ids:
            raise ResearchLoopContractError("ACTION_BINDING_MISMATCH", proposal.proposal_id)
        budget_consumption.assert_admitted(budget)
        receipt_ids = tuple(value.authorization_receipt_id for value in execution_receipts)
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ResearchLoopContractError(
                "UNREGISTERED_OR_UNAUTHORIZED_ACTION", "execution receipts must be unique"
            )
        if status is IterationStatus.COMPLETE:
            if completion_evidence is None:
                raise ResearchLoopContractError(
                    "INCOMPLETE_ITERATION_CANNOT_COMPLETE",
                    "COMPLETE requires owner-resolved execution/review/reward evidence",
                )
            execution_receipts = completion_evidence.executions
            canonical_output_refs = completion_evidence.canonical_output_refs
            review_report_ref = completion_evidence.review_report_ref
            reward_vector_ref = completion_evidence.reward_vector_ref
            if tuple(sorted(value.action_draft_id for value in execution_receipts)) != action_ids:
                raise ResearchLoopContractError("ACTION_BINDING_MISMATCH", "completion evidence")
        if status in {IterationStatus.REVIEWED, IterationStatus.COMPLETE} and review_report_ref is None:
            raise ResearchLoopContractError("REVIEW_BINDING_REQUIRED", status.value)
        payload = {
            "iteration_index": iteration_index,
            "proposal_id": proposal.proposal_id,
            "action_draft_ids": list(action_ids),
            "execution_receipts": [value.to_wire() for value in execution_receipts],
            "canonical_output_refs": list(_refs(canonical_output_refs, "canonical_output_refs")),
            "review_report_ref": review_report_ref,
            "reward_vector_ref": reward_vector_ref,
            "budget_version_id": budget.budget_version_id,
            "budget_consumption": budget_consumption.to_wire(),
            "next_action_proposal_refs": list(
                _refs(tuple(value.proposal_id for value in next_action_proposals), "next_action_proposal_refs")
            ),
            "status": status.value,
        }
        return cls(
            iteration_record_id="rli_sha256_" + canonical_sha256(payload),
            iteration_index=iteration_index,
            proposal_id=proposal.proposal_id,
            action_draft_ids=action_ids,
            execution_receipts=execution_receipts,
            canonical_output_refs=tuple(payload["canonical_output_refs"]),
            review_report_ref=review_report_ref,
            reward_vector_ref=reward_vector_ref,
            budget_version_id=budget.budget_version_id,
            budget_consumption=budget_consumption,
            next_action_proposal_refs=tuple(payload["next_action_proposal_refs"]),
            status=status,
        )
