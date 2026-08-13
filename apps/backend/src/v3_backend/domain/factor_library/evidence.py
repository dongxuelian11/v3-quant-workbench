from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from types import MappingProxyType
from typing import Mapping, Protocol

from v3_backend.domain.datasets import DatasetVersion, LabelSpec, SplitSpec
from v3_backend.domain.experiments import (
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentResult,
    ExperimentRun,
    ExperimentVersion,
    ReviewerEvidence,
    RewardVector,
)
from v3_backend.domain.factors import (
    FactorDefinitionVersion,
    FactorEvaluation,
    FeatureMaterialization,
)
from v3_backend.domain.reviewer_integration import ResearchReviewReport
from v3_backend.provenance.canonical_hash import canonical_sha256


class FactorEvidenceBindingError(ValueError):
    def __init__(self, detail: str) -> None:
        self.code = "EVIDENCE_BINDING_UNAVAILABLE"
        super().__init__(f"{self.code}: {detail}")


def _text(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise FactorEvidenceBindingError(f"invalid {name}")
    return value


def _refs(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if any(not value or value != value.strip() for value in values):
        raise FactorEvidenceBindingError(f"invalid {name}")
    if len(values) != len(set(values)):
        raise FactorEvidenceBindingError(f"duplicate {name}")
    return tuple(sorted(values))


def evaluation_context_ref(evaluation: FactorEvaluation) -> str:
    return "fectx_sha256_" + canonical_sha256(evaluation.context.to_wire())


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    """Untrusted public request/projection. Its fields never confer authority."""

    evaluation_ref: str
    factor_definition_version_id: str
    feature_materialization_ref: str
    dataset_version_ref: str
    label_spec_ref: str
    split_spec_ref: str
    experiment_version_ref: str
    experiment_run_ref: str
    experiment_attempt_ref: str
    experiment_result_ref: str
    reward_vector_ref: str
    reviewer_evidence_ref: str
    review_report_ref: str
    evaluation_context_ref: str
    snapshot_ref: str
    universe_ref: str
    evaluation_period_ref: str
    evaluation_policy_ref: str
    result_refs: tuple[str, ...]
    reviewer_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "evaluation_ref",
            "factor_definition_version_id",
            "feature_materialization_ref",
            "dataset_version_ref",
            "label_spec_ref",
            "split_spec_ref",
            "experiment_version_ref",
            "experiment_run_ref",
            "experiment_attempt_ref",
            "experiment_result_ref",
            "reward_vector_ref",
            "reviewer_evidence_ref",
            "review_report_ref",
            "evaluation_context_ref",
            "snapshot_ref",
            "universe_ref",
            "evaluation_period_ref",
            "evaluation_policy_ref",
        ):
            _text(getattr(self, name), name)
        _refs(self.result_refs, "result_refs")
        _refs(self.reviewer_refs, "reviewer_refs")
        _refs(self.provenance_refs, "provenance_refs")


class CanonicalFactorEvidenceSource(Protocol):
    """Adapter over canonical owners; returned objects are resolved, not caller DTOs."""

    def resolve(self, kind: str, identity: str) -> object | None: ...

    def contains_artifact(self, artifact_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ResolvedEvaluationEvidence:
    evaluation_ref: str
    factor_definition_version_id: str
    dataset_version_ref: str
    evaluation_context_ref: str
    result_refs: tuple[str, ...]
    reviewer_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    exact_context: Mapping[str, object]
    metrics: Mapping[str, float]


class CanonicalEvaluationEvidenceResolver:
    """Resolves and exact-binds canonical Factor evaluation evidence owners."""

    def __init__(self, source: CanonicalFactorEvidenceSource) -> None:
        self._source = source

    def _resolve(self, kind: str, identity: str, expected_type: type[object]) -> object:
        value = self._source.resolve(kind, identity)
        if value is None or type(value) is not expected_type:
            raise FactorEvidenceBindingError(f"{kind}:{identity} was not resolved by its canonical owner")
        return value

    @staticmethod
    def _require(condition: bool, detail: str) -> None:
        if not condition:
            raise FactorEvidenceBindingError(detail)

    def resolve(self, request: EvaluationEvidence) -> ResolvedEvaluationEvidence:
        definition = self._resolve("FactorDefinitionVersion", request.factor_definition_version_id, FactorDefinitionVersion)
        materialization = self._resolve("FeatureMaterialization", request.feature_materialization_ref, FeatureMaterialization)
        evaluation = self._resolve("FactorEvaluation", request.evaluation_ref, FactorEvaluation)
        dataset = self._resolve("DatasetVersion", request.dataset_version_ref, DatasetVersion)
        label = self._resolve("LabelSpec", request.label_spec_ref, LabelSpec)
        split = self._resolve("SplitSpec", request.split_spec_ref, SplitSpec)
        experiment = self._resolve("ExperimentVersion", request.experiment_version_ref, ExperimentVersion)
        run = self._resolve("ExperimentRun", request.experiment_run_ref, ExperimentRun)
        attempt = self._resolve("ExperimentAttempt", request.experiment_attempt_ref, ExperimentAttempt)
        result = self._resolve("ExperimentResult", request.experiment_result_ref, ExperimentResult)
        reward = self._resolve("RewardVector", request.reward_vector_ref, RewardVector)
        reviewer = self._resolve("ReviewerEvidence", request.reviewer_evidence_ref, ReviewerEvidence)
        review_report = self._resolve("ResearchReviewReport", request.review_report_ref, ResearchReviewReport)

        assert isinstance(definition, FactorDefinitionVersion)
        assert isinstance(materialization, FeatureMaterialization)
        assert isinstance(evaluation, FactorEvaluation)
        assert isinstance(dataset, DatasetVersion)
        assert isinstance(label, LabelSpec)
        assert isinstance(split, SplitSpec)
        assert isinstance(experiment, ExperimentVersion)
        assert isinstance(run, ExperimentRun)
        assert isinstance(attempt, ExperimentAttempt)
        assert isinstance(result, ExperimentResult)
        assert isinstance(reward, RewardVector)
        assert isinstance(reviewer, ReviewerEvidence)
        assert isinstance(review_report, ResearchReviewReport)

        self._require(materialization.factor_definition_version_id == definition.factor_definition_version_id, "FeatureMaterialization/FactorDefinitionVersion mismatch")
        self._require(evaluation.factor_definition_version_id == definition.factor_definition_version_id, "FactorEvaluation/FactorDefinitionVersion mismatch")
        self._require(evaluation.feature_materialization_id == materialization.feature_materialization_id, "FactorEvaluation/FeatureMaterialization mismatch")
        self._require(evaluation.context == materialization.context, "FactorEvaluation context mismatch")
        self._require(evaluation.factor_evaluation_id in dataset.factor_evaluation_ids, "DatasetVersion does not contain FactorEvaluation")
        self._require(dataset.label_spec_id == label.label_spec_id, "DatasetVersion/LabelSpec mismatch")
        self._require(dataset.split_spec_id == split.split_spec_id, "DatasetVersion/SplitSpec mismatch")
        dataset_context = dataset.binding
        evaluation_context = evaluation.context
        self._require(
            (
                dataset_context.snapshot_id,
                dataset_context.universe_version_id,
                dataset_context.snapshot_truth_binding,
                dataset_context.universe_truth_binding,
                dataset_context.knowledge_cutoff,
                dataset_context.calendar_version_id,
                dataset_context.schema_version_id,
                dataset_context.environment_fingerprint,
                dataset_context.evaluator_version,
            )
            == (
                evaluation_context.snapshot_id,
                evaluation_context.universe_version_id,
                evaluation_context.snapshot_truth_binding,
                evaluation_context.universe_truth_binding,
                evaluation_context.knowledge_cutoff,
                evaluation_context.calendar_version_id,
                evaluation_context.schema_version_id,
                evaluation_context.environment_fingerprint,
                evaluation_context.evaluator_version,
            ),
            "DatasetVersion/FactorEvaluation context mismatch",
        )
        self._require(run.experiment_version_id == experiment.experiment_version_id, "ExperimentRun/evaluation policy mismatch")
        self._require(run.dataset_version_id == dataset.dataset_version_id, "ExperimentRun/DatasetVersion mismatch")
        self._require(run.factor_evaluation_id == evaluation.factor_evaluation_id, "ExperimentRun/FactorEvaluation mismatch")
        self._require(attempt.experiment_run_id == run.experiment_run_id and attempt.state is ExperimentAttemptState.SUCCEEDED, "ExperimentAttempt is not the successful exact run attempt")
        self._require(result.experiment_run_id == run.experiment_run_id, "ExperimentResult/ExperimentRun mismatch")
        self._require(result.successful_attempt_id == attempt.experiment_attempt_id, "ExperimentResult/ExperimentAttempt mismatch")
        self._require(result.reward_vector_id == reward.reward_vector_id, "ExperimentResult/RewardVector mismatch")
        self._require(result.result_artifact_id == attempt.result_artifact_id, "ExperimentResult/result Artifact mismatch")
        self._require(reward.experiment_run_id == run.experiment_run_id, "RewardVector/ExperimentRun mismatch")
        self._require(reward.experiment_attempt_id == attempt.experiment_attempt_id, "RewardVector/ExperimentAttempt mismatch")
        self._require(reward.reviewer_evidence_id == reviewer.reviewer_evidence_id, "RewardVector/ReviewerEvidence mismatch")
        report_targets = {(ref.object_kind, ref.object_id) for ref in review_report.target_refs}
        self._require(
            {
                ("FactorEvaluation", evaluation.factor_evaluation_id),
                ("DatasetVersion", dataset.dataset_version_id),
                ("ExperimentResult", result.experiment_result_id),
                ("RewardVector", reward.reward_vector_id),
            }.issubset(report_targets),
            "ResearchReviewReport does not target the exact evaluation result chain",
        )

        expected_context_ref = evaluation_context_ref(evaluation)
        expected_results = tuple(sorted((result.experiment_result_id, result.result_artifact_id, reward.reward_vector_id)))
        expected_reviewers = tuple(sorted((reviewer.reviewer_evidence_id, review_report.review_report_id)))
        expected_provenance = tuple(sorted({
            materialization.provenance_artifact_id,
            evaluation.evaluation_provenance_artifact_id,
            dataset.provenance_artifact_id,
            run.run_provenance_artifact_id,
            reward.provenance_artifact_id,
            reviewer.provenance_artifact_id,
            *attempt.evidence_artifact_ids,
        }))
        exact_request = (
            request.factor_definition_version_id == definition.factor_definition_version_id,
            request.feature_materialization_ref == materialization.feature_materialization_id,
            request.dataset_version_ref == dataset.dataset_version_id,
            request.label_spec_ref == label.label_spec_id,
            request.split_spec_ref == split.split_spec_id,
            request.experiment_version_ref == experiment.experiment_version_id,
            request.experiment_run_ref == run.experiment_run_id,
            request.experiment_attempt_ref == attempt.experiment_attempt_id,
            request.experiment_result_ref == result.experiment_result_id,
            request.reward_vector_ref == reward.reward_vector_id,
            request.reviewer_evidence_ref == reviewer.reviewer_evidence_id,
            request.review_report_ref == review_report.review_report_id,
            request.evaluation_context_ref == expected_context_ref,
            request.snapshot_ref == evaluation.context.snapshot_id,
            request.universe_ref == evaluation.context.universe_version_id,
            request.evaluation_period_ref == split.split_spec_id,
            request.evaluation_policy_ref == experiment.experiment_version_id,
            tuple(sorted(request.result_refs)) == expected_results,
            tuple(sorted(request.reviewer_refs)) == expected_reviewers,
            tuple(sorted(request.provenance_refs)) == expected_provenance,
        )
        self._require(all(exact_request), "public EvaluationEvidence does not exactly match the resolved canonical chain")

        artifact_ids = {
            materialization.output_artifact_id,
            materialization.provenance_artifact_id,
            evaluation.evaluation_provenance_artifact_id,
            dataset.dataset_artifact_id,
            dataset.provenance_artifact_id,
            *run.input_artifact_ids,
            run.run_provenance_artifact_id,
            *attempt.evidence_artifact_ids,
            result.result_artifact_id,
            reward.provenance_artifact_id,
            reviewer.provenance_artifact_id,
        }
        missing_artifacts = tuple(sorted(value for value in artifact_ids if not self._source.contains_artifact(value)))
        self._require(not missing_artifacts, f"canonical Artifact resolution failed: {missing_artifacts[:1]}")

        metrics: dict[str, float] = {}
        for name in ("coverage", "ic", "rank_ic", "turnover"):
            value = getattr(reward, name, None)
            self._require(type(value) is float and math.isfinite(value), f"canonical metric {name} is unavailable")
            metrics[name] = value
        context = evaluation.context
        exact_context = MappingProxyType({
            "snapshot_id": context.snapshot_id,
            "universe_version_id": context.universe_version_id,
            "knowledge_cutoff": context.knowledge_cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "calendar_version_id": context.calendar_version_id,
            "schema_version_id": context.schema_version_id,
            "environment_fingerprint": context.environment_fingerprint,
            "evaluator_version": context.evaluator_version,
            "label_spec_id": label.label_spec_id,
            "label": label.logical_name,
            "horizon_observations": label.horizon_observations,
            "split_spec_id": split.split_spec_id,
            "evaluation_period": {"test_start": split.test_start, "test_end": split.test_end},
            "evaluation_policy_id": experiment.experiment_version_id,
            "evaluation_policy_version": experiment.protocol_version,
        })
        return ResolvedEvaluationEvidence(
            evaluation.factor_evaluation_id,
            definition.factor_definition_version_id,
            dataset.dataset_version_id,
            expected_context_ref,
            expected_results,
            expected_reviewers,
            expected_provenance,
            exact_context,
            MappingProxyType(metrics),
        )


__all__ = [
    "CanonicalEvaluationEvidenceResolver",
    "CanonicalFactorEvidenceSource",
    "EvaluationEvidence",
    "FactorEvidenceBindingError",
    "ResolvedEvaluationEvidence",
    "evaluation_context_ref",
]
