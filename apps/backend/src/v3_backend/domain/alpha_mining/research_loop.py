"""Research-only Alpha loop over canonical Factor/Dataset/Experiment authorities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Protocol

from v3_backend.contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    ValidationState,
)
from v3_backend.control_plane.resource_governor import ResourceGovernor, ResourceGrant
from v3_backend.domain.artifacts.model import ArtifactDescriptor
from v3_backend.domain.datasets import (
    DATASET_ARTIFACT_ROLE,
    DATASET_SCHEMA_FINGERPRINT,
    FormalDatasetRepository,
    FormalDatasetSample,
    FormalDatasetVersion,
    FormalFeatureMaterializationRepository,
    decode_feature_materialization_payload,
    decode_formal_dataset_payload,
    feature_output_context_identity,
    formal_dataset_context_identity,
)
from v3_backend.domain.experiments import (
    EvidenceStatus,
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentResult,
    ExperimentRun,
    ExperimentVersion,
    FactorSample,
    FindingSeverity,
    ReviewerEvidence,
    ReviewerFinding,
    RewardMetrics,
    RewardVector,
    compute_reward_metrics,
)
from v3_backend.domain.factors import (
    FACTOR_OUTPUT_SCHEMA_FINGERPRINT,
    CanonicalJsonArtifactPublisher,
    FactorDefinitionVersion,
    FormalFeatureMaterialization,
    FormalFactorEvaluationRequest,
    FormalFactorEvaluationService,
    OperatorRegistry,
)
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadResolutionReceipt,
    PayloadResolutionRequest,
    PayloadResolutionResult,
)
from v3_backend.domain.reviewer_integration import (
    ExactEvidenceBinding,
    ResearchReviewReport,
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    ReviewFact,
    ReviewOutcome,
    ReviewSeverity,
    review_research_scope,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .engine import AlphaMiningCandidateGenerator, AlphaMiningEngine
from .model import (
    AlphaMiningContractError,
    AlphaMiningEvaluationEvidence,
    AlphaMiningJobSpec,
    AlphaMiningReward,
    AlphaMiningRewardStatus,
    AlphaMiningRunRecord,
    AlphaResearchFactorEvaluation,
    RewardComponentName,
)


ALPHA_METRICS_SCHEMA = "sch_sha256_" + canonical_sha256(
    {"schema": "v3.alpha-research-metrics/1.0.0", "source": "V3_INTERNAL_RECOMPUTE"}
)
ALPHA_REVIEW_SCHEMA = "sch_sha256_" + canonical_sha256(
    {"schema": "v3.alpha-research-review/1.0.0", "reviewer": "V3_REGISTERED_RULESET"}
)
ALPHA_RUN_SCHEMA = "sch_sha256_" + canonical_sha256(
    {"schema": "v3.alpha-research-run/1.0.0", "deterministic": True}
)
ALPHA_RESULT_SCHEMA = "sch_sha256_" + canonical_sha256(
    {"schema": "v3.alpha-research-result/1.0.0", "maturity": "PRE_ALPHA"}
)


class FactorEvaluationDefinitionBinder(Protocol):
    """Binds generated canonical IR into the existing formal Factor owner seam."""

    def bind_for_dataset(
        self,
        definition: FactorDefinitionVersion,
        dataset: FormalDatasetVersion,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CanonicalAlphaEvaluationRecord:
    definition: FactorDefinitionVersion
    factor_evaluation: AlphaResearchFactorEvaluation
    metrics: RewardMetrics
    metrics_artifact: ArtifactDescriptor
    experiment_run: ExperimentRun
    experiment_attempt: ExperimentAttempt
    reviewer_report: ResearchReviewReport
    reviewer_artifact: ArtifactDescriptor
    reviewer_evidence: ReviewerEvidence
    reward_vector: RewardVector
    experiment_result: ExperimentResult
    evidence: AlphaMiningEvaluationEvidence

    def to_wire(self) -> dict[str, object]:
        return {
            "factor_definition_version_id": self.definition.factor_definition_version_id,
            "factor_evaluation_id": self.factor_evaluation.factor_evaluation_id,
            "feature_materialization_id": self.factor_evaluation.feature_materialization_id,
            "dataset_version_id": self.factor_evaluation.dataset_version_id,
            "metrics": _metrics_wire(self.metrics),
            "metrics_artifact_id": self.metrics_artifact.artifact_id,
            "experiment_run_id": self.experiment_run.experiment_run_id,
            "experiment_attempt_id": self.experiment_attempt.experiment_attempt_id,
            "review_report_id": self.reviewer_report.review_report_id,
            "review_artifact_id": self.reviewer_artifact.artifact_id,
            "reviewer_evidence_id": self.reviewer_evidence.reviewer_evidence_id,
            "reward_vector_id": self.reward_vector.reward_vector_id,
            "experiment_result_id": self.experiment_result.experiment_result_id,
        }


@dataclass(frozen=True, slots=True)
class AlphaResearchLoopResult:
    alpha_research_result_id: str
    job_spec_id: str
    dataset_version_id: str
    dataset_resolution_receipt: PayloadResolutionReceipt
    mining_run: AlphaMiningRunRecord
    evaluations: tuple[CanonicalAlphaEvaluationRecord, ...]
    generation_count: int
    rewarded_count: int
    best_factor_definition_version_id: str | None
    best_reward_id: str | None
    best_reward: str | None
    result_artifact: ArtifactDescriptor
    maturity: str = "RUNNABLE_BACKEND_CANDIDATE / PRE_ALPHA / RESEARCH_ONLY"
    product_connected: bool = False
    production_available: bool = False

    def to_wire(self) -> dict[str, object]:
        return {
            "alpha_research_result_id": self.alpha_research_result_id,
            "job_spec_id": self.job_spec_id,
            "dataset_version_id": self.dataset_version_id,
            "dataset_resolution_receipt_id": self.dataset_resolution_receipt.receipt_identity,
            "alpha_mining_run_id": self.mining_run.alpha_mining_run_id,
            "generation_count": self.generation_count,
            "generated_count": self.mining_run.generated_count,
            "evaluated_count": self.mining_run.evaluated_count,
            "rejected_count": self.mining_run.rejected_count,
            "rewarded_count": self.rewarded_count,
            "best_factor_definition_version_id": self.best_factor_definition_version_id,
            "best_reward_id": self.best_reward_id,
            "best_reward": self.best_reward,
            "result_artifact_id": self.result_artifact.artifact_id,
            "maturity": self.maturity,
            "product_connected": self.product_connected,
            "production_available": self.production_available,
        }


@dataclass(frozen=True, slots=True)
class _FactorEvaluationProducts:
    materialization: FormalFeatureMaterialization
    feature_resolution: PayloadResolutionResult
    samples: tuple[FactorSample, ...]
    metrics: RewardMetrics
    factor_evaluation: AlphaResearchFactorEvaluation


@dataclass(frozen=True, slots=True)
class _ExperimentProducts:
    metrics_artifact: ArtifactDescriptor
    run: ExperimentRun
    attempt: ExperimentAttempt


@dataclass(frozen=True, slots=True)
class _ReviewProducts:
    report: ResearchReviewReport
    artifact: ArtifactDescriptor
    findings: tuple[ReviewerFinding, ...]
    evidence: ReviewerEvidence


def _digest(identity: str) -> str:
    digest = identity.rsplit("_", 1)[-1]
    if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
        raise AlphaMiningContractError("NON_CANONICAL_EVIDENCE_ID", identity)
    return digest


def _ref(session_id: str, kind: str, identity: str) -> ReviewEvidenceRef:
    return ReviewEvidenceRef(session_id, kind, identity, _digest(identity))


def _binding(relation: str, target: ReviewEvidenceRef) -> ExactEvidenceBinding:
    return ExactEvidenceBinding(relation, target)


def _float_wire(value: float) -> str:
    parsed = Decimal(str(value))
    if not parsed.is_finite():
        raise AlphaMiningContractError("NON_FINITE_METRIC", str(value))
    if parsed == 0:
        return "0"
    text = format(parsed.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _metrics_wire(metrics: RewardMetrics) -> dict[str, object]:
    return {
        "coverage": _float_wire(metrics.coverage),
        "ic": _float_wire(metrics.ic),
        "rank_ic": _float_wire(metrics.rank_ic),
        "lower_quantile_return": _float_wire(metrics.lower_quantile_return),
        "upper_quantile_return": _float_wire(metrics.upper_quantile_return),
        "quantile_spread": _float_wire(metrics.quantile_spread),
        "turnover": _float_wire(metrics.turnover),
        "complexity": metrics.complexity,
        "top_sample_ids": list(metrics.top_sample_ids),
        "authority": "V3_INTERNAL_RECOMPUTE_FROM_P1_ACTUAL_BYTES",
    }


def _resource_observation(grant: ResourceGrant) -> str:
    return (
        f"RESOURCE_GOVERNOR_ADMITTED:class={grant.resource_class};cpu={grant.cpu_slots};"
        f"memory={grant.memory_hard_limit_bytes};scratch={grant.scratch_budget_bytes};"
        f"wallclock={grant.wall_clock_seconds};gpu={grant.gpu_device or 'NONE'}"
    )


def _period_time(value: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AlphaMiningContractError(
            "INVALID_EVALUATION_PERIOD", "runnable evaluation requires ISO date bounds"
        ) from exc
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def _status_for(report: ResearchReviewReport, rule_id: str) -> EvidenceStatus:
    check = report.check_by_rule_id(rule_id)
    if check is None or check.outcome in {ReviewOutcome.NOT_RUN, ReviewOutcome.NOT_APPLICABLE}:
        return EvidenceStatus.NOT_RUN
    if check.outcome in {ReviewOutcome.FINDING, ReviewOutcome.BLOCKED}:
        return EvidenceStatus.FAIL
    return EvidenceStatus.PASS


class CanonicalAlphaEvaluationPort:
    """No caller metrics/evidence seam: every value is resolved and recomputed here."""

    def __init__(
        self,
        *,
        job: AlphaMiningJobSpec,
        datasets: FormalDatasetRepository,
        materializations: FormalFeatureMaterializationRepository,
        payload_resolver: CanonicalPayloadResolver,
        factor_service: FormalFactorEvaluationService,
        definition_binder: FactorEvaluationDefinitionBinder,
        artifact_publisher: CanonicalJsonArtifactPublisher,
    ) -> None:
        dataset = datasets.get_dataset(job.dataset_version_id)
        if dataset is None:
            raise AlphaMiningContractError(
                "CANONICAL_DATASET_NOT_AVAILABLE", job.dataset_version_id
            )
        if (
            dataset.snapshot_id != job.evaluation_context.factor_context.snapshot_id
            or dataset.universe_version_id
            != job.evaluation_context.factor_context.universe_version_id
            or dataset.universe_version_id != job.universe_version_id
        ):
            raise AlphaMiningContractError(
                "EVALUATION_CONTEXT_BINDING_MISMATCH", "formal Dataset owner"
            )
        start = date.fromisoformat(job.evaluation_context.period_start)
        end = date.fromisoformat(job.evaluation_context.period_end)
        if start > end:
            raise AlphaMiningContractError("INVALID_EVALUATION_PERIOD", "start exceeds end")
        max_bytes = job.operation_profile.scratch_budget_bytes
        dataset_resolution = payload_resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.datasets.formal",
                owner_id=dataset.dataset_version_id,
                owner_version=dataset.dataset_version_id,
                payload_role=DATASET_ARTIFACT_ROLE,
                context_identity=formal_dataset_context_identity(dataset),
                max_bytes=max_bytes,
            )
        )
        if dataset_resolution.verified_payload.schema_fingerprint != DATASET_SCHEMA_FINGERPRINT:
            raise AlphaMiningContractError(
                "DATASET_SCHEMA_NOT_ADMITTED", dataset.dataset_schema_fingerprint
            )
        samples = decode_formal_dataset_payload(
            dataset_resolution.verified_payload.payload, dataset=dataset
        )
        bounded = tuple(
            value
            for value in samples
            if start <= date.fromisoformat(value.observation_id) <= end
        )
        if len(bounded) < 2:
            raise AlphaMiningContractError(
                "INSUFFICIENT_EVALUATION_SAMPLES", job.dataset_version_id
            )
        self.job = job
        self.dataset = dataset
        self.dataset_resolution = dataset_resolution
        self.samples = bounded
        self._materializations = materializations
        self._resolver = payload_resolver
        self._factor_service = factor_service
        self._binder = definition_binder
        self._publisher = artifact_publisher
        self._previous_top_sample_ids: tuple[str, ...] = ()
        self.records: list[CanonicalAlphaEvaluationRecord] = []

    def _resolve_factor_materialization(
        self, definition: FactorDefinitionVersion
    ) -> tuple[FormalFeatureMaterialization, PayloadResolutionResult]:
        self._binder.bind_for_dataset(definition, self.dataset)
        materialization = self._factor_service.evaluate(
            FormalFactorEvaluationRequest(
                definition.factor_definition_version_id,
                self.dataset.snapshot_id,
                self.dataset.universe_version_id,
                self.job.operation_profile.scratch_budget_bytes,
                PRE_ALPHA_CEILING,
            )
        )
        owned = self._materializations.get_materialization(
            materialization.feature_materialization_id
        )
        if owned != materialization:
            raise AlphaMiningContractError(
                "CANONICAL_FACTOR_MATERIALIZATION_NOT_AVAILABLE",
                materialization.feature_materialization_id,
            )
        resolution = self._resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace="v3.factors.materialization",
                owner_id=materialization.feature_materialization_id,
                owner_version=materialization.feature_materialization_id,
                payload_role="FEATURE_MATERIALIZATION_VALUES",
                context_identity=feature_output_context_identity(materialization),
                max_bytes=self.job.operation_profile.scratch_budget_bytes,
            )
        )
        if resolution.verified_payload.schema_fingerprint != FACTOR_OUTPUT_SCHEMA_FINGERPRINT:
            raise AlphaMiningContractError(
                "FACTOR_OUTPUT_SCHEMA_NOT_ADMITTED",
                materialization.output_schema_fingerprint,
            )
        return materialization, resolution

    def _factor_samples(
        self,
        materialization: FormalFeatureMaterialization,
        resolution: PayloadResolutionResult,
    ) -> tuple[FactorSample, ...]:
        instruments, observations, values = decode_feature_materialization_payload(
            resolution.verified_payload.payload,
            materialization=materialization,
        )
        values_by_coordinate = {
            (instrument, observation): values[
                instrument_index * len(observations) + observation_index
            ]
            for instrument_index, instrument in enumerate(instruments)
            for observation_index, observation in enumerate(observations)
        }
        return tuple(
            FactorSample(
                sample.sample_id,
                values_by_coordinate.get(
                    (sample.instrument_id, sample.observation_id)
                ),
                sample.label,
            )
            for sample in self.samples
        )

    def _compute_factor_evaluation(
        self, definition: FactorDefinitionVersion
    ) -> _FactorEvaluationProducts:
        materialization, feature_resolution = self._resolve_factor_materialization(
            definition
        )
        samples = self._factor_samples(materialization, feature_resolution)
        metrics = compute_reward_metrics(
            samples,
            previous_top_sample_ids=self._previous_top_sample_ids,
            quantiles=2,
            complexity=definition.metadata.complexity,
        )
        self._previous_top_sample_ids = metrics.top_sample_ids
        factor_evaluation = AlphaResearchFactorEvaluation.create(
            definition=definition,
            materialization=materialization,
            dataset=self.dataset,
            context=self.job.evaluation_context.factor_context,
            dataset_resolution_receipt=self.dataset_resolution.receipt,
            feature_resolution_receipt=feature_resolution.receipt,
            proposed_state=PRE_ALPHA_CEILING,
        )
        return _FactorEvaluationProducts(
            materialization,
            feature_resolution,
            samples,
            metrics,
            factor_evaluation,
        )

    def _publish_metrics(
        self, products: _FactorEvaluationProducts
    ) -> ArtifactDescriptor:
        return self._publisher.publish_canonical_json(
            {
                "schema": "v3.alpha-research-metrics/1.0.0",
                "factor_evaluation_id": products.factor_evaluation.factor_evaluation_id,
                "dataset_resolution_receipt_id": (
                    self.dataset_resolution.receipt.receipt_identity
                ),
                "feature_resolution_receipt_id": (
                    products.feature_resolution.receipt.receipt_identity
                ),
                "period_start": self.job.evaluation_context.period_start,
                "period_end": self.job.evaluation_context.period_end,
                "sample_ids": [sample.sample_id for sample in products.samples],
                "metrics": _metrics_wire(products.metrics),
            },
            semantic_role="ALPHA_RESEARCH_METRICS",
            provenance_entity_id=products.factor_evaluation.factor_evaluation_id,
            schema_fingerprint=ALPHA_METRICS_SCHEMA,
        )

    def _create_experiment(
        self,
        products: _FactorEvaluationProducts,
        metrics_artifact: ArtifactDescriptor,
    ) -> _ExperimentProducts:
        run_provenance = self._publish_run_provenance(products, metrics_artifact)
        experiment = ExperimentVersion.create(
            "alpha-research-loop",
            self.job.reward_policy.reward_policy_version_id,
            self.job.evaluation_context.evaluation_policy_version,
        )
        input_artifacts = tuple(
            sorted(
                {
                    self.dataset.dataset_descriptor.artifact_id,
                    products.materialization.output_descriptor.artifact_id,
                    metrics_artifact.artifact_id,
                }
            )
        )
        run = ExperimentRun.create(
            experiment=experiment,
            dataset=self.dataset,
            factor_evaluation=products.factor_evaluation,  # type: ignore[arg-type]
            code_version="v3.alpha-research-loop/1.0.0",
            environment_fingerprint=(
                self.job.evaluation_context.factor_context.environment_fingerprint
            ),
            input_artifact_ids=input_artifacts,
            run_provenance_artifact_id=run_provenance.artifact_id,
            proposed_state=PRE_ALPHA_CEILING,
        )
        stamp = _period_time(self.job.evaluation_context.period_start)
        attempt = ExperimentAttempt.create(
            run=run,
            ordinal=1,
            state=ExperimentAttemptState.SUCCEEDED,
            started_at=stamp,
            ended_at=stamp,
            evidence_artifact_ids=input_artifacts,
            result_artifact_id=metrics_artifact.artifact_id,
        )
        return _ExperimentProducts(metrics_artifact, run, attempt)

    def _publish_run_provenance(
        self,
        products: _FactorEvaluationProducts,
        metrics_artifact: ArtifactDescriptor,
    ) -> ArtifactDescriptor:
        return self._publisher.publish_canonical_json(
            {
                "schema": "v3.alpha-research-run-provenance/1.0.0",
                "job_spec_id": self.job.alpha_mining_job_spec_id,
                "factor_evaluation_id": products.factor_evaluation.factor_evaluation_id,
                "dataset_version_id": self.dataset.dataset_version_id,
                "dataset_resolution_receipt_id": (
                    self.dataset_resolution.receipt.receipt_identity
                ),
                "feature_resolution_receipt_id": (
                    products.feature_resolution.receipt.receipt_identity
                ),
                "metrics_artifact_id": metrics_artifact.artifact_id,
            },
            semantic_role="ALPHA_RESEARCH_RUN",
            provenance_entity_id=products.factor_evaluation.factor_evaluation_id,
            schema_fingerprint=ALPHA_RUN_SCHEMA,
        )

    def _create_review_products(
        self,
        factor_evaluation: AlphaResearchFactorEvaluation,
        experiment: _ExperimentProducts,
    ) -> _ReviewProducts:
        report = self._review(
            factor_evaluation=factor_evaluation,
            run=experiment.run,
            attempt=experiment.attempt,
        )
        reviewer_artifact = self._publisher.publish_canonical_json(
            {"schema": "v3.alpha-research-review/1.0.0", **report.to_wire()},
            semantic_role="ALPHA_RESEARCH_REVIEW",
            provenance_entity_id=experiment.run.experiment_run_id,
            schema_fingerprint=ALPHA_REVIEW_SCHEMA,
        )
        findings = tuple(
            ReviewerFinding.create(
                category=check.rule_id,
                code=check.outcome.value,
                severity=(
                    FindingSeverity.BLOCKING
                    if check.severity is ReviewSeverity.BLOCKING
                    else FindingSeverity.WARNING
                    if check.severity is ReviewSeverity.WARNING
                    else FindingSeverity.INFO
                ),
                status=(
                    EvidenceStatus.FAIL
                    if check.outcome in {ReviewOutcome.FINDING, ReviewOutcome.BLOCKED}
                    else EvidenceStatus.NOT_RUN
                ),
                evidence_artifact_ids=(reviewer_artifact.artifact_id,),
            )
            for check in report.findings
        )
        reviewer = ReviewerEvidence.create(
            lookahead=_status_for(report, "O-050"),
            leakage=_status_for(report, "O-050"),
            split=_status_for(report, "O-010"),
            sample_coverage=EvidenceStatus.NOT_RUN,
            missingness=EvidenceStatus.NOT_RUN,
            turnover=EvidenceStatus.NOT_RUN,
            complexity=EvidenceStatus.NOT_RUN,
            multiple_testing_robustness=_status_for(report, "O-060"),
            findings=findings,
            provenance_artifact_id=reviewer_artifact.artifact_id,
        )
        return _ReviewProducts(report, reviewer_artifact, findings, reviewer)

    def _create_evaluation_record(
        self,
        definition: FactorDefinitionVersion,
        factor: _FactorEvaluationProducts,
        experiment: _ExperimentProducts,
        review: _ReviewProducts,
    ) -> CanonicalAlphaEvaluationRecord:
        reward_vector = RewardVector.create(
            run=experiment.run,
            attempt=experiment.attempt,
            coverage=factor.metrics.coverage,
            ic=factor.metrics.ic,
            rank_ic=factor.metrics.rank_ic,
            lower_quantile_return=factor.metrics.lower_quantile_return,
            upper_quantile_return=factor.metrics.upper_quantile_return,
            quantile_spread=factor.metrics.quantile_spread,
            turnover=factor.metrics.turnover,
            complexity=factor.metrics.complexity,
            reviewer_evidence=review.evidence,
            provenance_artifact_id=experiment.metrics_artifact.artifact_id,
            proposed_state=PRE_ALPHA_CEILING,
        )
        experiment_result = ExperimentResult.create(
            experiment.run, experiment.attempt, reward_vector
        )
        evidence = AlphaMiningEvaluationEvidence(
            evaluation_context=self.job.evaluation_context,
            factor_evaluation=factor.factor_evaluation,
            experiment_run=experiment.run,
            experiment_attempt=experiment.attempt,
            reward_vector=reward_vector,
            reviewer_evidence=review.evidence,
            reviewer_findings=review.findings,
            available_components=tuple(RewardComponentName),
        )
        evidence.validate_exact(definition, self.job)
        return CanonicalAlphaEvaluationRecord(
            definition,
            factor.factor_evaluation,
            factor.metrics,
            experiment.metrics_artifact,
            experiment.run,
            experiment.attempt,
            review.report,
            review.artifact,
            review.evidence,
            reward_vector,
            experiment_result,
            evidence,
        )

    def evaluate_existing(
        self, definition: FactorDefinitionVersion, job: AlphaMiningJobSpec
    ) -> AlphaMiningEvaluationEvidence:
        if job != self.job:
            raise AlphaMiningContractError("ALPHA_RESEARCH_JOB_MISMATCH", job.alpha_mining_job_spec_id)
        factor = self._compute_factor_evaluation(definition)
        metrics_artifact = self._publish_metrics(factor)
        experiment = self._create_experiment(factor, metrics_artifact)
        review = self._create_review_products(factor.factor_evaluation, experiment)
        record = self._create_evaluation_record(
            definition, factor, experiment, review
        )
        self.records.append(record)
        return record.evidence

    def _review(
        self,
        *,
        factor_evaluation: AlphaResearchFactorEvaluation,
        run: ExperimentRun,
        attempt: ExperimentAttempt,
    ) -> ResearchReviewReport:
        session = "ars_sha256_" + canonical_sha256(
            [self.job.alpha_mining_job_spec_id, factor_evaluation.factor_evaluation_id]
        )
        dataset_ref = _ref(session, "DatasetVersion", self.dataset.dataset_version_id)
        evaluation_ref = _ref(session, "FactorEvaluation", factor_evaluation.factor_evaluation_id)
        run_ref = _ref(session, "ExperimentRun", run.experiment_run_id)
        attempt_ref = _ref(session, "ExperimentAttempt", attempt.experiment_attempt_id)
        dataset_receipt_ref = _ref(
            session, "PayloadResolutionReceipt", self.dataset_resolution.receipt.receipt_identity
        )
        feature_receipt_ref = _ref(
            session, "PayloadResolutionReceipt", factor_evaluation.feature_resolution_receipt.receipt_identity
        )
        records = (
            ReviewEvidenceRecord(
                dataset_ref,
                ValidationState.PASSED,
                self.dataset.truth_admission,
                (dataset_receipt_ref,),
                (
                    _binding("factor_evaluation", evaluation_ref),
                    _binding("payload_receipt", dataset_receipt_ref),
                ),
                (
                    ReviewFact("knowledge_cutoff", self.job.evaluation_context.factor_context.knowledge_cutoff.isoformat()),
                    ReviewFact("period_start", self.job.evaluation_context.period_start),
                    ReviewFact("period_end", self.job.evaluation_context.period_end),
                ),
            ),
            ReviewEvidenceRecord(
                evaluation_ref,
                ValidationState.PASSED,
                factor_evaluation.truth_admission,
                (feature_receipt_ref, dataset_ref),
                (
                    _binding("dataset", dataset_ref),
                    _binding("feature_payload_receipt", feature_receipt_ref),
                ),
            ),
            ReviewEvidenceRecord(
                run_ref,
                ValidationState.PASSED,
                run.truth_admission,
                (dataset_ref, evaluation_ref),
                (
                    _binding("dataset", dataset_ref),
                    _binding("factor_evaluation", evaluation_ref),
                ),
            ),
            ReviewEvidenceRecord(
                attempt_ref,
                ValidationState.PASSED,
                run.truth_admission,
                (run_ref,),
                (_binding("experiment_run", run_ref),),
            ),
            ReviewEvidenceRecord(
                dataset_receipt_ref,
                ValidationState.PASSED,
                self.dataset.truth_admission,
                (),
                (_binding("resolved_dataset", dataset_ref),),
            ),
            ReviewEvidenceRecord(
                feature_receipt_ref,
                ValidationState.PASSED,
                factor_evaluation.truth_admission,
                (),
                (_binding("resolved_factor_evaluation", evaluation_ref),),
            ),
        )
        return review_research_scope(
            ResearchReviewScope.create(
                session_id=session,
                target_refs=(attempt_ref,),
                evidence_records=records,
            )
        )


class AlphaResearchLoopService:
    """Backend research entry. Production user-start authority remains separate/denied."""

    def __init__(
        self,
        *,
        registry: OperatorRegistry,
        datasets: FormalDatasetRepository,
        materializations: FormalFeatureMaterializationRepository,
        payload_resolver: CanonicalPayloadResolver,
        factor_service: FormalFactorEvaluationService,
        definition_binder: FactorEvaluationDefinitionBinder,
        artifact_publisher: CanonicalJsonArtifactPublisher,
        resources: ResourceGovernor,
        candidate_generator: AlphaMiningCandidateGenerator | None = None,
    ) -> None:
        self._registry = registry
        self._datasets = datasets
        self._materializations = materializations
        self._resolver = payload_resolver
        self._factor_service = factor_service
        self._binder = definition_binder
        self._publisher = artifact_publisher
        self._resources = resources
        self._candidate_generator = candidate_generator

    def run(self, job: AlphaMiningJobSpec) -> AlphaResearchLoopResult:
        if not isinstance(job, AlphaMiningJobSpec):
            raise TypeError("Alpha research loop requires AlphaMiningJobSpec")
        job.assert_canonical()
        lease_id = "alpha-research:" + job.alpha_mining_job_spec_id
        grant = self._resources.admit(lease_id, job.operation_profile)
        try:
            port = CanonicalAlphaEvaluationPort(
                job=job,
                datasets=self._datasets,
                materializations=self._materializations,
                payload_resolver=self._resolver,
                factor_service=self._factor_service,
                definition_binder=self._binder,
                artifact_publisher=self._publisher,
            )
            engine = AlphaMiningEngine(
                registry=self._registry,
                evaluation_port=port,
                candidate_generator=self._candidate_generator,
                clock=lambda: 0.0,
            )
            mining_run = engine.run(job, resource_observation=_resource_observation(grant))
        finally:
            self._resources.release(lease_id)
        by_evaluation = {
            value.factor_evaluation.factor_evaluation_id: value for value in port.records
        }
        scored: list[tuple[Decimal, str, str, AlphaMiningReward]] = []
        for candidate in mining_run.candidate_records:
            if candidate.factor_evaluation_id is None:
                continue
            record = by_evaluation[candidate.factor_evaluation_id]
            reward = AlphaMiningReward.create(policy=job.reward_policy, evidence=record.evidence)
            if reward.status is AlphaMiningRewardStatus.SCORED and reward.total_reward is not None:
                scored.append(
                    (
                        Decimal(reward.total_reward),
                        record.definition.factor_definition_version_id,
                        candidate.candidate_id,
                        reward,
                    )
                )
        best = sorted(scored, key=lambda value: (-value[0], value[1], value[2]))[0] if scored else None
        generation_count = max(
            (value.generation_index for value in mining_run.candidate_records), default=0
        )
        result_payload = {
            "schema": "v3.alpha-research-result/1.0.0",
            "job_spec": job.to_wire(),
            "dataset_version_id": port.dataset.dataset_version_id,
            "dataset_resolution_receipt_id": port.dataset_resolution.receipt.receipt_identity,
            "alpha_mining_run_id": mining_run.alpha_mining_run_id,
            "generation_count": generation_count,
            "candidate_record_ids": [
                value.candidate_record_id for value in mining_run.candidate_records
            ],
            "evaluations": [value.to_wire() for value in port.records],
            "rewarded_count": len(scored),
            "best_factor_definition_version_id": None if best is None else best[1],
            "best_reward_id": None if best is None else best[3].alpha_mining_reward_id,
            "best_reward": None if best is None else best[3].total_reward,
            "maturity": "RUNNABLE_BACKEND_CANDIDATE / PRE_ALPHA / RESEARCH_ONLY",
            "product_connected": False,
            "production_available": False,
            "user_execution_authority": "NOT_AVAILABLE / NOT_RUN",
            "agent_authority": "L0_READ / L1_DRAFT; L2_EXECUTE / L3_PUBLISH NOT_AVAILABLE",
        }
        result_artifact = self._publisher.publish_canonical_json(
            result_payload,
            semantic_role="ALPHA_RESEARCH_RESULT",
            provenance_entity_id=mining_run.alpha_mining_run_id,
            schema_fingerprint=ALPHA_RESULT_SCHEMA,
        )
        identity_payload = {
            "job_spec_id": job.alpha_mining_job_spec_id,
            "dataset_version_id": port.dataset.dataset_version_id,
            "dataset_resolution_receipt_id": port.dataset_resolution.receipt.receipt_identity,
            "alpha_mining_run_id": mining_run.alpha_mining_run_id,
            "result_artifact_id": result_artifact.artifact_id,
            "result_sha256": result_artifact.sha256,
            "best_reward_id": None if best is None else best[3].alpha_mining_reward_id,
        }
        return AlphaResearchLoopResult(
            "arr_sha256_" + canonical_sha256(identity_payload),
            job.alpha_mining_job_spec_id,
            port.dataset.dataset_version_id,
            port.dataset_resolution.receipt,
            mining_run,
            tuple(port.records),
            generation_count,
            len(scored),
            None if best is None else best[1],
            None if best is None else best[3].alpha_mining_reward_id,
            None if best is None else best[3].total_reward,
            result_artifact,
        )


__all__ = [
    "AlphaResearchLoopResult",
    "AlphaResearchLoopService",
    "CanonicalAlphaEvaluationPort",
    "CanonicalAlphaEvaluationRecord",
    "FactorEvaluationDefinitionBinder",
]
