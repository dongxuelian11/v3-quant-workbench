from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    UNKNOWN_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.domain.datasets import DatasetVersion, FormalDatasetVersion
from v3_backend.domain.factors import FactorEvaluation
from v3_backend.provenance.canonical_hash import canonical_sha256


def _require_text(value: str, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _require_artifact(value: str, name: str) -> None:
    if not value.startswith("art_sha256_"):
        raise ValueError(f"{name} must be a content-addressed Artifact")


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("experiment timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


class ExperimentAttemptState(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


@dataclass(frozen=True, slots=True)
class ExperimentVersion:
    experiment_version_id: str
    logical_name: str
    objective: str
    protocol_version: str

    @classmethod
    def create(
        cls, logical_name: str, objective: str, protocol_version: str
    ) -> ExperimentVersion:
        for name, value in (
            ("logical_name", logical_name),
            ("objective", objective),
            ("protocol_version", protocol_version),
        ):
            _require_text(value, name)
        payload = {
            "logical_name": logical_name,
            "objective": objective,
            "protocol_version": protocol_version,
        }
        return cls(
            experiment_version_id="expv_sha256_" + canonical_sha256(payload),
            **payload,
        )


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    experiment_run_id: str
    experiment_version_id: str
    dataset_version_id: str
    factor_evaluation_id: str
    code_version: str
    environment_fingerprint: str
    input_artifact_ids: tuple[str, ...]
    run_provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        experiment: ExperimentVersion,
        dataset: DatasetVersion | FormalDatasetVersion,
        factor_evaluation: FactorEvaluation,
        code_version: str,
        environment_fingerprint: str,
        input_artifact_ids: tuple[str, ...],
        run_provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> ExperimentRun:
        _require_text(code_version, "code_version")
        _require_text(environment_fingerprint, "environment_fingerprint")
        if factor_evaluation.context.environment_fingerprint != environment_fingerprint:
            raise ValueError("ExperimentRun environment must match FactorEvaluation")
        if isinstance(dataset, FormalDatasetVersion):
            if (
                factor_evaluation.context.snapshot_id != dataset.snapshot_id
                or factor_evaluation.context.universe_version_id != dataset.universe_version_id
            ):
                raise ValueError("ExperimentRun FactorEvaluation must match formal Dataset context")
            if dataset.dataset_descriptor.artifact_id not in input_artifact_ids:
                raise ValueError("ExperimentRun requires the formal Dataset actual-payload Artifact")
        else:
            if environment_fingerprint != dataset.binding.environment_fingerprint:
                raise ValueError("ExperimentRun environment must match DatasetVersion")
            if factor_evaluation.factor_evaluation_id not in dataset.factor_evaluation_ids:
                raise ValueError(
                    "ExperimentRun FactorEvaluation must belong to the exact DatasetVersion"
                )
        if not input_artifact_ids:
            raise ValueError("ExperimentRun requires immutable input Artifact linkage")
        ordered_artifacts = tuple(sorted(input_artifact_ids))
        if len(ordered_artifacts) != len(set(ordered_artifacts)):
            raise ValueError("ExperimentRun input Artifacts must be unique")
        for artifact_id in ordered_artifacts:
            _require_artifact(artifact_id, "input_artifact_id")
        _require_artifact(run_provenance_artifact_id, "run_provenance_artifact_id")
        truth_admission = propagate_downstream_ceiling(
            proposed_state,
            (
                UpstreamRequirement(
                    dataset.dataset_version_id, dataset.truth_admission
                ),
                UpstreamRequirement(
                    factor_evaluation.factor_evaluation_id,
                    factor_evaluation.truth_admission,
                ),
            ),
        )
        payload = {
            "experiment_version_id": experiment.experiment_version_id,
            "dataset_version_id": dataset.dataset_version_id,
            "factor_evaluation_id": factor_evaluation.factor_evaluation_id,
            "code_version": code_version,
            "environment_fingerprint": environment_fingerprint,
            "input_artifact_ids": list(ordered_artifacts),
            "run_provenance_artifact_id": run_provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            experiment_run_id="exprun_sha256_" + canonical_sha256(payload),
            experiment_version_id=experiment.experiment_version_id,
            dataset_version_id=dataset.dataset_version_id,
            factor_evaluation_id=factor_evaluation.factor_evaluation_id,
            code_version=code_version,
            environment_fingerprint=environment_fingerprint,
            input_artifact_ids=ordered_artifacts,
            run_provenance_artifact_id=run_provenance_artifact_id,
            truth_admission=truth_admission,
        )


@dataclass(frozen=True, slots=True)
class ExperimentAttempt:
    experiment_attempt_id: str
    experiment_run_id: str
    ordinal: int
    state: ExperimentAttemptState
    started_at: datetime
    ended_at: datetime
    evidence_artifact_ids: tuple[str, ...]
    result_artifact_id: str | None
    error_code: str | None

    @classmethod
    def create(
        cls,
        *,
        run: ExperimentRun,
        ordinal: int,
        state: ExperimentAttemptState,
        started_at: datetime,
        ended_at: datetime,
        evidence_artifact_ids: tuple[str, ...],
        result_artifact_id: str | None = None,
        error_code: str | None = None,
    ) -> ExperimentAttempt:
        if ordinal < 1:
            raise ValueError("ExperimentAttempt ordinal starts at one")
        if not isinstance(state, ExperimentAttemptState):
            raise TypeError("state must be ExperimentAttemptState")
        started_wire = _wire_time(started_at)
        ended_wire = _wire_time(ended_at)
        if ended_at < started_at:
            raise ValueError("ExperimentAttempt ended_at cannot precede started_at")
        ordered_evidence = tuple(sorted(evidence_artifact_ids))
        for artifact_id in ordered_evidence:
            _require_artifact(artifact_id, "evidence_artifact_id")
        if state is ExperimentAttemptState.SUCCEEDED:
            if result_artifact_id is None or error_code is not None:
                raise ValueError("successful Attempt requires a result and no error")
            _require_artifact(result_artifact_id, "result_artifact_id")
        else:
            if result_artifact_id is not None:
                raise ValueError("non-successful Attempt cannot publish a result Artifact")
            if state is ExperimentAttemptState.FAILED and not error_code:
                raise ValueError("failed Attempt requires an explicit error_code")
        payload = {
            "experiment_run_id": run.experiment_run_id,
            "ordinal": ordinal,
            "state": state.value,
            "started_at": started_wire,
            "ended_at": ended_wire,
            "evidence_artifact_ids": list(ordered_evidence),
            "result_artifact_id": result_artifact_id,
            "error_code": error_code,
        }
        return cls(
            experiment_attempt_id="expatt_sha256_" + canonical_sha256(payload),
            experiment_run_id=run.experiment_run_id,
            ordinal=ordinal,
            state=state,
            started_at=started_at,
            ended_at=ended_at,
            evidence_artifact_ids=ordered_evidence,
            result_artifact_id=result_artifact_id,
            error_code=error_code,
        )


@dataclass(frozen=True, slots=True)
class ReviewerFinding:
    finding_id: str
    category: str
    code: str
    severity: FindingSeverity
    status: EvidenceStatus
    evidence_artifact_ids: tuple[str, ...]

    @classmethod
    def create(
        cls,
        *,
        category: str,
        code: str,
        severity: FindingSeverity,
        status: EvidenceStatus,
        evidence_artifact_ids: tuple[str, ...],
    ) -> ReviewerFinding:
        _require_text(category, "category")
        _require_text(code, "code")
        if not isinstance(severity, FindingSeverity) or not isinstance(
            status, EvidenceStatus
        ):
            raise TypeError("review finding severity/status must use canonical enums")
        ordered = tuple(sorted(evidence_artifact_ids))
        if not ordered:
            raise ValueError("ReviewerFinding requires structured evidence linkage")
        for artifact_id in ordered:
            _require_artifact(artifact_id, "evidence_artifact_id")
        payload = {
            "category": category,
            "code": code,
            "severity": severity.value,
            "status": status.value,
            "evidence_artifact_ids": list(ordered),
        }
        return cls(
            finding_id="rvf_sha256_" + canonical_sha256(payload),
            category=category,
            code=code,
            severity=severity,
            status=status,
            evidence_artifact_ids=ordered,
        )


@dataclass(frozen=True, slots=True)
class ReviewerEvidence:
    reviewer_evidence_id: str
    lookahead: EvidenceStatus
    leakage: EvidenceStatus
    split: EvidenceStatus
    sample_coverage: EvidenceStatus
    missingness: EvidenceStatus
    turnover: EvidenceStatus
    complexity: EvidenceStatus
    multiple_testing_robustness: EvidenceStatus
    finding_ids: tuple[str, ...]
    provenance_artifact_id: str

    @property
    def canonical_ceiling(self) -> TruthAdmissionState:
        statuses = (
            self.lookahead,
            self.leakage,
            self.split,
            self.sample_coverage,
            self.missingness,
            self.turnover,
            self.complexity,
            self.multiple_testing_robustness,
        )
        if any(value is EvidenceStatus.FAIL for value in statuses):
            return UNKNOWN_CEILING
        if all(value is EvidenceStatus.PASS for value in statuses):
            return FORMAL_ADMITTED_CEILING
        return PRE_ALPHA_CEILING

    @classmethod
    def create(
        cls,
        *,
        lookahead: EvidenceStatus,
        leakage: EvidenceStatus,
        split: EvidenceStatus,
        sample_coverage: EvidenceStatus,
        missingness: EvidenceStatus,
        turnover: EvidenceStatus,
        complexity: EvidenceStatus,
        multiple_testing_robustness: EvidenceStatus,
        findings: tuple[ReviewerFinding, ...],
        provenance_artifact_id: str,
    ) -> ReviewerEvidence:
        statuses = {
            "lookahead": lookahead,
            "leakage": leakage,
            "split": split,
            "sample_coverage": sample_coverage,
            "missingness": missingness,
            "turnover": turnover,
            "complexity": complexity,
            "multiple_testing_robustness": multiple_testing_robustness,
        }
        if any(not isinstance(value, EvidenceStatus) for value in statuses.values()):
            raise TypeError("review evidence statuses must be EvidenceStatus")
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        finding_ids = tuple(sorted(value.finding_id for value in findings))
        payload = {
            **{name: value.value for name, value in statuses.items()},
            "finding_ids": list(finding_ids),
            "provenance_artifact_id": provenance_artifact_id,
        }
        return cls(
            reviewer_evidence_id="rve_sha256_" + canonical_sha256(payload),
            finding_ids=finding_ids,
            provenance_artifact_id=provenance_artifact_id,
            **statuses,
        )


@dataclass(frozen=True, slots=True)
class RewardVector:
    reward_vector_id: str
    experiment_run_id: str
    experiment_attempt_id: str
    coverage: float
    ic: float
    rank_ic: float
    lower_quantile_return: float
    upper_quantile_return: float
    quantile_spread: float
    turnover: float
    complexity: int
    reviewer_evidence_id: str
    provenance_artifact_id: str
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        run: ExperimentRun,
        attempt: ExperimentAttempt,
        coverage: float,
        ic: float,
        rank_ic: float,
        lower_quantile_return: float,
        upper_quantile_return: float,
        quantile_spread: float,
        turnover: float,
        complexity: int,
        reviewer_evidence: ReviewerEvidence,
        provenance_artifact_id: str,
        proposed_state: TruthAdmissionState,
    ) -> RewardVector:
        if attempt.experiment_run_id != run.experiment_run_id:
            raise ValueError("RewardVector Attempt must bind the exact ExperimentRun")
        if attempt.state is not ExperimentAttemptState.SUCCEEDED:
            raise ValueError("RewardVector cannot be published from a failed Attempt")
        for name, value in (
            ("coverage", coverage),
            ("ic", ic),
            ("rank_ic", rank_ic),
            ("lower_quantile_return", lower_quantile_return),
            ("upper_quantile_return", upper_quantile_return),
            ("quantile_spread", quantile_spread),
            ("turnover", turnover),
        ):
            _finite(value, name)
        if not 0 <= coverage <= 1:
            raise ValueError("coverage must be in [0, 1]")
        if not -1 <= ic <= 1 or not -1 <= rank_ic <= 1:
            raise ValueError("IC and Rank IC must be in [-1, 1]")
        if not 0 <= turnover <= 1:
            raise ValueError("turnover must be in [0, 1]")
        if not math.isclose(
            quantile_spread,
            upper_quantile_return - lower_quantile_return,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("quantile_spread must equal upper minus lower return")
        if not isinstance(complexity, int) or isinstance(complexity, bool) or complexity < 1:
            raise ValueError("complexity must be a positive integer")
        _require_artifact(provenance_artifact_id, "provenance_artifact_id")
        truth_admission = propagate_downstream_ceiling(
            proposed_state,
            (
                UpstreamRequirement(run.experiment_run_id, run.truth_admission),
                UpstreamRequirement(
                    reviewer_evidence.reviewer_evidence_id,
                    reviewer_evidence.canonical_ceiling,
                ),
            ),
        )
        payload = {
            "experiment_run_id": run.experiment_run_id,
            "experiment_attempt_id": attempt.experiment_attempt_id,
            "coverage": float(coverage),
            "ic": float(ic),
            "rank_ic": float(rank_ic),
            "lower_quantile_return": float(lower_quantile_return),
            "upper_quantile_return": float(upper_quantile_return),
            "quantile_spread": float(quantile_spread),
            "turnover": float(turnover),
            "complexity": complexity,
            "reviewer_evidence_id": reviewer_evidence.reviewer_evidence_id,
            "provenance_artifact_id": provenance_artifact_id,
            "truth_admission": truth_admission.to_wire(),
        }
        return cls(
            reward_vector_id="rwv_sha256_" + canonical_sha256(payload),
            experiment_run_id=run.experiment_run_id,
            experiment_attempt_id=attempt.experiment_attempt_id,
            coverage=float(coverage),
            ic=float(ic),
            rank_ic=float(rank_ic),
            lower_quantile_return=float(lower_quantile_return),
            upper_quantile_return=float(upper_quantile_return),
            quantile_spread=float(quantile_spread),
            turnover=float(turnover),
            complexity=complexity,
            reviewer_evidence_id=reviewer_evidence.reviewer_evidence_id,
            provenance_artifact_id=provenance_artifact_id,
            truth_admission=truth_admission,
        )


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    experiment_result_id: str
    experiment_run_id: str
    successful_attempt_id: str
    reward_vector_id: str
    result_artifact_id: str

    @classmethod
    def create(
        cls,
        run: ExperimentRun,
        attempt: ExperimentAttempt,
        reward_vector: RewardVector,
    ) -> ExperimentResult:
        if attempt.state is not ExperimentAttemptState.SUCCEEDED:
            raise ValueError("ExperimentResult requires a successful Attempt")
        if attempt.experiment_run_id != run.experiment_run_id:
            raise ValueError("ExperimentResult Attempt/Run mismatch")
        if reward_vector.experiment_attempt_id != attempt.experiment_attempt_id:
            raise ValueError("ExperimentResult RewardVector/Attempt mismatch")
        assert attempt.result_artifact_id is not None
        payload = {
            "experiment_run_id": run.experiment_run_id,
            "successful_attempt_id": attempt.experiment_attempt_id,
            "reward_vector_id": reward_vector.reward_vector_id,
            "result_artifact_id": attempt.result_artifact_id,
        }
        return cls(
            experiment_result_id="expres_sha256_" + canonical_sha256(payload),
            **payload,
        )


__all__ = [
    "EvidenceStatus",
    "ExperimentAttempt",
    "ExperimentAttemptState",
    "ExperimentResult",
    "ExperimentRun",
    "ExperimentVersion",
    "FindingSeverity",
    "ReviewerEvidence",
    "ReviewerFinding",
    "RewardVector",
]
