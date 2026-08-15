from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from v3_backend.domain.datasets import DatasetVersion, FeatureSetVersion, LabelSpec, SplitSpec
from v3_backend.domain.experiments import ExperimentAttempt, ExperimentRun, ExperimentVersion
from v3_backend.domain.factors import FactorEvaluation, FeatureMaterialization
from v3_backend.domain.models import (
    ModelEvaluationEvidence,
    ModelRun,
    ModelTrainingBinding,
    ModelTrainingRequest,
    ModelVersion,
    PredictionArtifact,
    PredictionBundle,
    PredictionDatasetView,
    SafeLinearModelArtifact,
    TrainedModelBundle,
    TrainingDatasetView,
    TrainingEvidence,
    TrainingSpecVersion,
)
from v3_backend.domain.reviewer_integration import ResearchReviewReport
from v3_backend.provenance.canonical_hash import canonical_sha256

from .contracts import ModelComparison, ModelEvidenceResolutionRequest, ModelEvidenceView
from .service import compare_model_evidence, read_dataset_context, read_model_evidence


EVIDENCE_BINDING_UNAVAILABLE = "EVIDENCE_BINDING_UNAVAILABLE"


class ModelEvidenceResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalModelEvidenceSource:
    dataset: DatasetVersion
    feature_set: FeatureSetVersion
    label_spec: LabelSpec
    split_spec: SplitSpec
    factor_evaluations: tuple[FactorEvaluation, ...]
    feature_materializations: tuple[FeatureMaterialization, ...]
    training_spec: TrainingSpecVersion
    trained_model: TrainedModelBundle
    experiment_version: ExperimentVersion
    experiment_run: ExperimentRun
    experiment_attempt: ExperimentAttempt
    reviewer_reports: tuple[ResearchReviewReport, ...]
    evaluation_policy_id: str
    benchmark_id: str | None = None
    prediction: PredictionBundle | None = None
    evaluation: ModelEvaluationEvidence | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedEvidence:
    request: ModelEvidenceResolutionRequest
    view: ModelEvidenceView


def _fail(message: str) -> ModelEvidenceResolutionError:
    return ModelEvidenceResolutionError(f"{EVIDENCE_BINDING_UNAVAILABLE}: {message}")


def _validate_report(report: ResearchReviewReport, required_ids: frozenset[str]) -> None:
    basis = {
        "session_id": report.session_id,
        "target_refs": [value.to_wire() for value in report.target_refs],
        "rule_set_id": report.rule_set_id,
        "rule_set_content_sha256": report.rule_set_content_sha256,
        "deterministic_checks": [value.to_wire() for value in report.deterministic_checks],
        "source_evidence_refs": [value.to_wire() for value in report.source_evidence_refs],
        "truth_ceiling": report.truth_ceiling.to_wire(),
    }
    if report.review_report_id != "rrp_sha256_" + canonical_sha256(basis):
        raise _fail("Reviewer report canonical identity mismatch")
    observed_ids = {value.object_id for value in (*report.target_refs, *report.source_evidence_refs)}
    if not required_ids.issubset(observed_ids):
        raise _fail("Reviewer report does not bind the exact model evidence chain")


def _resolve(source: CanonicalModelEvidenceSource) -> _ResolvedEvidence:
    context = read_dataset_context(
        dataset=source.dataset,
        feature_set=source.feature_set,
        label=source.label_spec,
        split=source.split_spec,
        evaluations=source.factor_evaluations,
        materializations=source.feature_materializations,
    )
    bundle = source.trained_model
    rebuilt_view = TrainingDatasetView.create(
        dataset=source.dataset,
        split_spec=source.split_spec,
        training_spec=source.training_spec,
        samples=(*bundle.view.train_samples, *bundle.view.validation_samples),
    )
    rebuilt_binding = ModelTrainingBinding.create(
        dataset=source.dataset,
        training_spec=source.training_spec,
        code_version=bundle.binding.code_version,
        worker_runtime=bundle.binding.worker_runtime,
        proposed_state=bundle.binding.truth_admission,
    )
    rebuilt_run = ModelRun.create(rebuilt_binding, rebuilt_view)
    rebuilt_request = ModelTrainingRequest.create(
        dataset=source.dataset, training_spec=source.training_spec, run=rebuilt_run
    )
    rebuilt_evidence = TrainingEvidence.create(
        dataset=source.dataset,
        training_spec=source.training_spec,
        run=rebuilt_run,
        view=rebuilt_view,
        training_request=rebuilt_request,
        candidate=bundle.candidate,
        provenance_artifact_id=bundle.training_evidence.provenance_artifact_id,
    )
    rebuilt_artifact = SafeLinearModelArtifact.create(
        source.training_spec, rebuilt_request, bundle.candidate
    )
    rebuilt_model = ModelVersion.create(
        dataset=source.dataset,
        run=rebuilt_run,
        training_spec=source.training_spec,
        training_request=rebuilt_request,
        artifact=rebuilt_artifact,
        training_evidence=rebuilt_evidence,
        provenance_artifact_id=bundle.model.provenance_artifact_id,
        proposed_state=bundle.model.truth_admission,
    )
    if (rebuilt_view, rebuilt_binding, rebuilt_run, rebuilt_request, rebuilt_evidence, rebuilt_artifact, rebuilt_model) != (
        bundle.view, bundle.binding, bundle.run, bundle.request, bundle.training_evidence, bundle.artifact, bundle.model
    ):
        raise _fail("ModelVersion/training/request/artifact/provenance chain mismatch")

    prediction_artifact: PredictionArtifact | None = None
    if source.prediction is not None:
        prediction_view = PredictionDatasetView.create(
            dataset=source.dataset,
            model=bundle.model,
            training_spec=source.training_spec,
            samples=source.prediction.view.samples,
        )
        prediction_request = source.prediction.request.create(
            model=bundle.model,
            model_artifact=bundle.artifact,
            dataset=source.dataset,
            training_spec=source.training_spec,
            view=prediction_view,
            target_semantics=source.prediction.prediction.target_semantics,
        )
        prediction_artifact = PredictionArtifact.create(
            model=bundle.model,
            model_artifact=bundle.artifact,
            dataset=source.dataset,
            training_spec=source.training_spec,
            view=prediction_view,
            prediction_request=prediction_request,
            candidate=source.prediction.candidate,
            prediction_timestamp=source.prediction.prediction.prediction_timestamp,
            target_semantics=source.prediction.prediction.target_semantics,
            provenance_artifact_id=source.prediction.prediction.provenance_artifact_id,
            proposed_state=source.prediction.prediction.truth_admission,
        )
        if (prediction_view, prediction_request, prediction_artifact) != (
            source.prediction.view, source.prediction.request, source.prediction.prediction
        ):
            raise _fail("PredictionArtifact/request/row/provenance chain mismatch")
    if (source.evaluation is None) != (source.prediction is None):
        raise _fail("evaluation and prediction evidence must be jointly present or absent")
    if source.evaluation is not None:
        rebuilt_evaluation = ModelEvaluationEvidence.create(
            model=bundle.model,
            dataset=source.dataset,
            training_evidence=bundle.training_evidence,
            prediction=source.prediction.prediction,
            prediction_view=source.prediction.view,
            split_spec=source.split_spec,
            provenance_artifact_id=source.evaluation.provenance_artifact_id,
        )
        if rebuilt_evaluation != source.evaluation:
            raise _fail("model evaluation/result metric chain mismatch")

    if source.experiment_run.experiment_version_id != source.experiment_version.experiment_version_id:
        raise _fail("ExperimentVersion/Run mismatch")
    if source.experiment_run.dataset_version_id != source.dataset.dataset_version_id:
        raise _fail("ExperimentRun/DatasetVersion mismatch")
    if source.experiment_run.factor_evaluation_id not in source.dataset.factor_evaluation_ids:
        raise _fail("ExperimentRun feature evidence mismatch")
    if source.experiment_attempt.experiment_run_id != source.experiment_run.experiment_run_id:
        raise _fail("ExperimentAttempt/Run mismatch")
    if source.experiment_attempt.result_artifact_id is None:
        raise _fail("successful canonical ExperimentAttempt result Artifact unavailable")
    if source.evaluation is not None and source.experiment_attempt.result_artifact_id != source.evaluation.provenance_artifact_id:
        raise _fail("ExperimentAttempt result Artifact/model evaluation mismatch")
    if bundle.artifact.artifact_id not in source.experiment_run.input_artifact_ids:
        raise _fail("ExperimentRun does not bind exact model Artifact")

    required_report_ids = {bundle.model.model_version_id, source.dataset.dataset_version_id}
    if prediction_artifact is not None:
        required_report_ids.add(prediction_artifact.prediction_artifact_id)
    for report in source.reviewer_reports:
        _validate_report(report, frozenset(required_report_ids))

    request = ModelEvidenceResolutionRequest(
        model_version_id=bundle.model.model_version_id,
        dataset_version_id=source.dataset.dataset_version_id,
        training_spec_version_id=source.training_spec.training_spec_version_id,
        model_artifact_id=bundle.artifact.artifact_id,
        training_evidence_id=bundle.training_evidence.training_evidence_id,
        prediction_artifact_id=prediction_artifact.prediction_artifact_id if prediction_artifact else None,
        model_evaluation_evidence_id=source.evaluation.model_evaluation_evidence_id if source.evaluation else None,
        experiment_version_id=source.experiment_version.experiment_version_id,
        experiment_run_id=source.experiment_run.experiment_run_id,
        experiment_attempt_id=source.experiment_attempt.experiment_attempt_id,
        result_artifact_id=source.experiment_attempt.result_artifact_id,
        reviewer_report_ids=tuple(sorted(value.review_report_id for value in source.reviewer_reports)),
        evaluation_policy_id=source.evaluation_policy_id,
        benchmark_id=source.benchmark_id,
    )
    view = read_model_evidence(
        model=bundle.model,
        training_spec=source.training_spec,
        dataset_context=context,
        evaluation=source.evaluation,
        prediction=prediction_artifact,
        experiment_refs=(source.experiment_version.experiment_version_id, source.experiment_run.experiment_run_id, source.experiment_attempt.experiment_attempt_id, source.experiment_attempt.result_artifact_id),
        reviewer_refs=request.reviewer_report_ids,
        evaluation_policy_id=source.evaluation_policy_id,
        benchmark_id=source.benchmark_id,
    )
    return _ResolvedEvidence(request=request, view=view)


class CanonicalModelEvidenceResolver:
    """System-owned registry that rebuilds canonical provenance before exposing a DTO."""

    __slots__ = ("_resolved",)

    def __init__(self, sources: tuple[CanonicalModelEvidenceSource, ...]) -> None:
        try:
            resolved = tuple(_resolve(value) for value in sources)
        except ModelEvidenceResolutionError:
            raise
        except Exception as exc:
            raise _fail("canonical owner object reconstruction failed") from exc
        values = {value.request.model_version_id: value for value in resolved}
        if not values or len(values) != len(resolved):
            raise _fail("canonical evidence inventory must be non-empty with unique ModelVersion IDs")
        self._resolved = MappingProxyType(values)

    def request_for(self, model_version_id: str) -> ModelEvidenceResolutionRequest:
        try:
            return self._resolved[model_version_id].request
        except KeyError as exc:
            raise _fail("canonical ModelVersion evidence is unavailable") from exc

    def resolve(self, request: ModelEvidenceResolutionRequest) -> ModelEvidenceView:
        try:
            resolved = self._resolved[request.model_version_id]
        except KeyError as exc:
            raise _fail("canonical ModelVersion evidence is unavailable") from exc
        if request != resolved.request:
            raise _fail("resolution request does not match exact canonical refs")
        return resolved.view

    def compare(
        self,
        left: ModelEvidenceResolutionRequest,
        right: ModelEvidenceResolutionRequest,
        *,
        objective_metric: str | None = None,
        objective_split_role: str | None = None,
        objective_direction: str | None = None,
    ) -> ModelComparison:
        return compare_model_evidence(
            self.resolve(left), self.resolve(right),
            objective_metric=objective_metric,
            objective_split_role=objective_split_role,
            objective_direction=objective_direction,
        )


__all__ = [
    "CanonicalModelEvidenceResolver",
    "CanonicalModelEvidenceSource",
    "EVIDENCE_BINDING_UNAVAILABLE",
    "ModelEvidenceResolutionError",
]
