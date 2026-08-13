from __future__ import annotations

from math import isfinite

from v3_backend.agents.contracts import AgentProvenance, PermissionLevel
from v3_backend.agents.permissions import require_permission
from v3_backend.domain.datasets import DatasetVersion, FeatureSetVersion, LabelSpec, SplitSpec
from v3_backend.domain.factors import FactorEvaluation, FeatureMaterialization
from v3_backend.domain.models import ModelEvaluationEvidence, ModelVersion, PredictionArtifact, TrainingSpecVersion
from v3_backend.domain.reviewer_integration import ResearchReviewReport

from .contracts import (
    CompareDraftPayload, ComparisonStatus, EvidenceExplanation, MetricDelta,
    MetricEvidence, ModelAgentDraft, ModelComparison, ModelDraftKind, ModelResearchProposal,
    ModelEvidenceView, ModelResearchContext, PredictDraftPayload,
    ReviewDraftPayload, TrainDraftPayload,
)


class ModelAgentBindingError(ValueError):
    pass


def _truth_wire(dataset: DatasetVersion) -> tuple[str, str]:
    wire = dataset.truth_admission.to_wire()
    return str(wire["canonical_truth_state"]), str(wire["canonical_admission_state"])


def read_dataset_context(*, dataset: DatasetVersion, feature_set: FeatureSetVersion, label: LabelSpec, split: SplitSpec, evaluations: tuple[FactorEvaluation, ...] | None = None, materializations: tuple[FeatureMaterialization, ...] | None = None) -> ModelResearchContext:
    if dataset.feature_set_version_id != feature_set.feature_set_version_id:
        raise ModelAgentBindingError("exact FeatureSetVersion binding required")
    if dataset.factor_evaluation_ids != feature_set.factor_evaluation_ids:
        raise ModelAgentBindingError("exact feature definitions required")
    if dataset.label_spec_id != label.label_spec_id:
        raise ModelAgentBindingError("exact label and horizon binding required")
    if dataset.split_spec_id != split.split_spec_id:
        raise ModelAgentBindingError("exact SplitSpec binding required")
    if evaluations is None or materializations is None:
        raise ModelAgentBindingError("exact feature definitions and materializations required")
    evaluation_by_id = {value.factor_evaluation_id: value for value in evaluations}
    materialization_by_id = {value.feature_materialization_id: value for value in materializations}
    if len(evaluation_by_id) != len(evaluations) or set(evaluation_by_id) != set(feature_set.factor_evaluation_ids):
        raise ModelAgentBindingError("exact FactorEvaluation membership required")
    if len(materialization_by_id) != len(materializations) or set(materialization_by_id) != set(feature_set.feature_materialization_ids):
        raise ModelAgentBindingError("exact FeatureMaterialization membership required")
    ordered_evaluations = tuple(evaluation_by_id[value] for value in feature_set.factor_evaluation_ids)
    ordered_materializations = tuple(materialization_by_id[value.feature_materialization_id] for value in ordered_evaluations)
    for evaluation, materialization in zip(ordered_evaluations, ordered_materializations, strict=True):
        if evaluation.feature_materialization_id != materialization.feature_materialization_id:
            raise ModelAgentBindingError("stale or mismatched FeatureMaterialization")
        if evaluation.factor_definition_version_id != materialization.factor_definition_version_id:
            raise ModelAgentBindingError("feature definition/materialization mismatch")
        if evaluation.context != materialization.context or evaluation.context != ordered_evaluations[0].context:
            raise ModelAgentBindingError("feature context or prediction-time binding mismatch")
    split.validate_for_label(label)
    truth, admission = _truth_wire(dataset)
    return ModelResearchContext(
        dataset_version_id=dataset.dataset_version_id,
        feature_set_version_id=feature_set.feature_set_version_id,
        factor_evaluation_ids=feature_set.factor_evaluation_ids,
        factor_definition_version_ids=tuple(value.factor_definition_version_id for value in ordered_evaluations),
        feature_materialization_ids=feature_set.feature_materialization_ids,
        label_spec_id=label.label_spec_id,
        label_name=label.logical_name,
        label_source_field=label.source_field,
        horizon_observations=label.horizon_observations,
        split_spec_id=split.split_spec_id,
        train_range=(split.train_start, split.train_end),
        validation_range=(split.validation_start, split.validation_end),
        test_range=(split.test_start, split.test_end),
        snapshot_id=dataset.binding.snapshot_id,
        universe_version_id=dataset.binding.universe_version_id,
        knowledge_cutoff=dataset.binding.knowledge_cutoff.isoformat(),
        truth_state=truth,
        admission_state=admission,
        dataset_artifact_id=dataset.dataset_artifact_id,
        provenance_artifact_id=dataset.provenance_artifact_id,
    )


def _draft(*, kind: ModelDraftKind, payload: object, provenance: AgentProvenance) -> ModelAgentDraft:
    decision = require_permission(PermissionLevel.L1_DRAFT, PermissionLevel.L1_DRAFT)
    return ModelAgentDraft(draft_kind=kind, payload=payload, permission_decision=decision, provenance=provenance)


def draft_model_train(*, context: ModelResearchContext, spec: TrainingSpecVersion, requested_metrics: tuple[str, ...], provenance: AgentProvenance) -> ModelAgentDraft:
    if spec.feature_set_version_id != context.feature_set_version_id or spec.factor_evaluation_ids != context.factor_evaluation_ids:
        raise ModelAgentBindingError("training spec feature context mismatch")
    if spec.label_spec_id != context.label_spec_id or spec.split_spec_id != context.split_spec_id:
        raise ModelAgentBindingError("training spec label/horizon/split mismatch")
    if not requested_metrics:
        raise ModelAgentBindingError("requested metrics cannot be empty")
    payload = TrainDraftPayload(
        context=context,
        training_spec_version_id=spec.training_spec_version_id,
        model_family=spec.algorithm_family.value,
        parameters=(("alpha", spec.alpha), ("fit_intercept", spec.fit_intercept), ("solver", spec.solver)),
        seed=spec.seed,
        resource_profile=spec.environment_profile_id,
        dependency_runtime_fingerprint=spec.dependency_runtime_fingerprint,
        requested_metrics=tuple(sorted(requested_metrics)),
        evidence_refs=(context.dataset_artifact_id, context.provenance_artifact_id),
    )
    return _draft(kind=ModelDraftKind.MODEL_TRAIN, payload=payload, provenance=provenance)


def draft_model_predict(*, model: ModelVersion, training_spec: TrainingSpecVersion, prediction_context: ModelResearchContext, target_semantics: str, provenance: AgentProvenance) -> ModelAgentDraft:
    if model.training_spec_version_id != training_spec.training_spec_version_id:
        raise ModelAgentBindingError("exact ModelVersion TrainingSpecVersion required")
    if training_spec.feature_set_version_id != prediction_context.feature_set_version_id:
        raise ModelAgentBindingError("prediction Dataset feature set mismatch")
    if training_spec.factor_evaluation_ids != prediction_context.factor_evaluation_ids:
        raise ModelAgentBindingError("prediction Dataset feature identity mismatch")
    if training_spec.label_spec_id != prediction_context.label_spec_id:
        raise ModelAgentBindingError("prediction Dataset label/horizon mismatch")
    payload = PredictDraftPayload(
        model_version_id=model.model_version_id,
        model_artifact_id=model.model_artifact_id,
        training_dataset_version_id=model.dataset_version_id,
        prediction_context=prediction_context,
        training_spec_version_id=training_spec.training_spec_version_id,
        target_semantics=target_semantics,
        evidence_refs=(model.provenance_artifact_id, prediction_context.provenance_artifact_id),
    )
    return _draft(kind=ModelDraftKind.MODEL_PREDICT, payload=payload, provenance=provenance)


def draft_result_compare(*, left: ModelEvidenceView, right: ModelEvidenceView, objective_metric: str | None, objective_split_role: str | None, objective_direction: str | None, provenance: AgentProvenance) -> ModelAgentDraft:
    payload = CompareDraftPayload(left_evidence_id=left.model_version_id, right_evidence_id=right.model_version_id, objective_metric=objective_metric, objective_split_role=objective_split_role, objective_direction=objective_direction, evidence_refs=(left.provenance_artifact_id, right.provenance_artifact_id))
    return _draft(kind=ModelDraftKind.RESULT_COMPARE, payload=payload, provenance=provenance)


def draft_review_run(*, target_refs: tuple[str, ...], evidence_refs: tuple[str, ...], rule_set_id: str, provenance: AgentProvenance) -> ModelAgentDraft:
    return _draft(kind=ModelDraftKind.REVIEW_RUN, payload=ReviewDraftPayload(target_refs=target_refs, evidence_refs=evidence_refs, requested_rule_set_id=rule_set_id), provenance=provenance)


def build_model_research_proposal(*, research_goal: str, context: ModelResearchContext, action_drafts: tuple[ModelAgentDraft, ...], next_action_proposals: tuple[str, ...] = (), agent_rationale: str | None = None) -> ModelResearchProposal:
    if not research_goal or research_goal != research_goal.strip():
        raise ModelAgentBindingError("research goal is required without edge whitespace")
    return ModelResearchProposal(research_goal=research_goal, agent_rationale=agent_rationale, exact_context=context, action_drafts=action_drafts, next_action_proposals=next_action_proposals)


def read_model_evidence(*, model: ModelVersion, training_spec: TrainingSpecVersion, dataset_context: ModelResearchContext, evaluation: ModelEvaluationEvidence | None = None, prediction: PredictionArtifact | None = None, experiment_refs: tuple[str, ...] = (), reviewer_refs: tuple[str, ...] = ()) -> ModelEvidenceView:
    if model.training_spec_version_id != training_spec.training_spec_version_id or model.dataset_version_id != dataset_context.dataset_version_id:
        raise ModelAgentBindingError("model evidence requires exact training context")
    if training_spec.label_spec_id != dataset_context.label_spec_id or training_spec.split_spec_id != dataset_context.split_spec_id:
        raise ModelAgentBindingError("model evidence label/horizon/split mismatch")
    metrics: tuple[MetricEvidence, ...] = ()
    prediction_id = None
    if evaluation is not None:
        if evaluation.model_version_id != model.model_version_id or evaluation.dataset_version_id != dataset_context.dataset_version_id:
            raise ModelAgentBindingError("evaluation evidence mismatch")
        metrics = (MetricEvidence(name="rmse", split_role=evaluation.evaluated_split_role.value, status="AVAILABLE", value=evaluation.rmse, evidence_ref=evaluation.model_evaluation_evidence_id),)
    else:
        metrics = (MetricEvidence(name="rmse", split_role="VALIDATION_OR_TEST", status="NOT_RUN"),)
    if prediction is not None:
        if prediction.model_version_id != model.model_version_id or prediction.prediction_dataset_version_id != dataset_context.dataset_version_id:
            raise ModelAgentBindingError("prediction evidence mismatch")
        prediction_id = prediction.prediction_artifact_id
    return ModelEvidenceView(
        model_version_id=model.model_version_id, model_family=training_spec.algorithm_family.value,
        training_spec_version_id=training_spec.training_spec_version_id, model_run_id=model.model_run_id,
        model_training_request_id=model.model_training_request_id, training_evidence_id=model.training_evidence_id,
        dataset_version_id=dataset_context.dataset_version_id,
        feature_set_version_id=dataset_context.feature_set_version_id, factor_evaluation_ids=dataset_context.factor_evaluation_ids,
        label_spec_id=dataset_context.label_spec_id, horizon_observations=dataset_context.horizon_observations,
        split_spec_id=dataset_context.split_spec_id, train_range=dataset_context.train_range,
        validation_range=dataset_context.validation_range, test_range=dataset_context.test_range,
        universe_version_id=dataset_context.universe_version_id,
        snapshot_id=dataset_context.snapshot_id, seed=training_spec.seed,
        parameters=(("alpha", training_spec.alpha), ("fit_intercept", training_spec.fit_intercept), ("solver", training_spec.solver)),
        worker_runtime_fingerprint=model.worker_runtime.fingerprint, model_artifact_id=model.model_artifact_id,
        provenance_artifact_id=model.provenance_artifact_id, prediction_artifact_id=prediction_id,
        model_prediction_request_id=prediction.model_prediction_request_id if prediction else None,
        target_semantics=prediction.target_semantics if prediction else None,
        experiment_refs=tuple(sorted(experiment_refs)), reviewer_refs=tuple(sorted(reviewer_refs)), metrics=metrics,
    )


def compare_model_evidence(left: ModelEvidenceView, right: ModelEvidenceView, *, objective_metric: str | None = None, objective_split_role: str | None = None, objective_direction: str | None = None) -> ModelComparison:
    if len({objective_metric is None, objective_split_role is None, objective_direction is None}) != 1:
        raise ModelAgentBindingError("ranking requires explicit objective metric, split role and direction")
    if objective_direction not in {None, "MINIMIZE", "MAXIMIZE"}:
        raise ModelAgentBindingError("objective direction must be MINIMIZE or MAXIMIZE")
    fields = ("dataset_version_id", "feature_set_version_id", "factor_evaluation_ids", "label_spec_id", "horizon_observations", "split_spec_id", "train_range", "validation_range", "test_range", "universe_version_id", "snapshot_id")
    mismatches = tuple(name for name in fields if getattr(left, name) != getattr(right, name))
    if mismatches:
        return ModelComparison(status=ComparisonStatus.INCOMPARABLE_CONTEXT, left_model_version_id=left.model_version_id, right_model_version_id=right.model_version_id, context_mismatches=mismatches, objective_metric=objective_metric, objective_split_role=objective_split_role, objective_direction=objective_direction)
    left_metrics = {(m.name, m.split_role): m for m in left.metrics}
    right_metrics = {(m.name, m.split_role): m for m in right.metrics}
    deltas = []
    for key in sorted(set(left_metrics) | set(right_metrics)):
        a, b = left_metrics.get(key), right_metrics.get(key)
        if a is None or b is None or a.status != "AVAILABLE" or b.status != "AVAILABLE":
            status = "NOT_RUN" if (a and a.status == "NOT_RUN") or (b and b.status == "NOT_RUN") else "NOT_AVAILABLE"
            deltas.append(MetricDelta(name=key[0], split_role=key[1], status=status))
        else:
            delta = b.value - a.value
            if not isfinite(delta):
                raise ModelAgentBindingError("metric delta must be finite")
            deltas.append(MetricDelta(name=key[0], split_role=key[1], status="AVAILABLE", left_value=a.value, right_value=b.value, delta_right_minus_left=delta))
    ranking = None
    if objective_metric:
        objective = next((d for d in deltas if d.name == objective_metric and d.split_role == objective_split_role and d.status == "AVAILABLE"), None)
        if objective:
            if objective.delta_right_minus_left == 0:
                ranking = "TIE"
            elif objective_direction == "MINIMIZE":
                ranking = "RIGHT" if objective.delta_right_minus_left < 0 else "LEFT"
            else:
                ranking = "RIGHT" if objective.delta_right_minus_left > 0 else "LEFT"
    return ModelComparison(status=ComparisonStatus.COMPARABLE, left_model_version_id=left.model_version_id, right_model_version_id=right.model_version_id, metric_deltas=tuple(deltas), objective_metric=objective_metric, objective_split_role=objective_split_role, objective_direction=objective_direction, ranking=ranking)


def explain_comparison(*, left: ModelEvidenceView, right: ModelEvidenceView, comparison: ModelComparison, review_reports: tuple[ResearchReviewReport, ...] = ()) -> EvidenceExplanation:
    allowed_report_ids = set(left.reviewer_refs) | set(right.reviewer_refs)
    if any(report.review_report_id not in allowed_report_ids for report in review_reports):
        raise ModelAgentBindingError("Reviewer explanation requires an exact bound report ref")
    changed = []
    for name in ("model_family", "parameters", "seed", "training_spec_version_id"):
        if getattr(left, name) != getattr(right, name): changed.append(f"{name} changed")
    metric_statements = tuple(f"{d.name}/{d.split_role}: right-left={d.delta_right_minus_left}" for d in comparison.metric_deltas if d.status == "AVAILABLE")
    reviewer_statements = tuple(f"{r.review_report_id}: {r.overall_status.value}" for r in sorted(review_reports, key=lambda x: x.review_report_id))
    refs = {left.provenance_artifact_id, right.provenance_artifact_id}
    refs.update(ref for view in (left, right) for ref in (*view.experiment_refs, *view.reviewer_refs))
    missing = tuple(f"{d.name}/{d.split_role}={d.status}" for d in comparison.metric_deltas if d.status != "AVAILABLE")
    summary = "Contexts are incomparable; no ranking or metric explanation is permitted." if comparison.status is ComparisonStatus.INCOMPARABLE_CONTEXT else "Explanation is limited to exact bound specs, metrics and Reviewer evidence."
    return EvidenceExplanation(status="EVIDENCE_MISSING" if missing else "EVIDENCE_BOUND", summary=summary, changed_specs=tuple(changed), metric_statements=metric_statements, reviewer_statements=reviewer_statements, missing_evidence=missing, next_action_proposals=("PROPOSAL: run an explicitly user-confirmed comparable experiment with exact evidence bindings.",), cited_evidence_refs=tuple(sorted(refs)))


__all__ = [
    "ModelAgentBindingError",
    "build_model_research_proposal",
    "compare_model_evidence",
    "draft_model_predict",
    "draft_model_train",
    "draft_result_compare",
    "draft_review_run",
    "explain_comparison",
    "read_dataset_context",
    "read_model_evidence",
]
