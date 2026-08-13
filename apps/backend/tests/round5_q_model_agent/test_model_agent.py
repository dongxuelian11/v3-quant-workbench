from __future__ import annotations

import dataclasses
import json
import math
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from v3_backend.agents.contracts import AgentKind, AgentProvenance, PermissionLevel
from v3_backend.agents.model_agent import (
    ComparisonStatus,
    CanonicalModelEvidenceResolver,
    CanonicalModelEvidenceSource,
    EVIDENCE_BINDING_UNAVAILABLE,
    ModelAgentBindingError,
    ModelAgentDraft,
    ModelAgentReadTools,
    ModelAgentWorker,
    ModelDraftApplicationError,
    ModelDraftKind,
    ModelPredictExecutionSpec,
    ModelTrainExecutionSpec,
    build_model_predict_execution_spec,
    build_model_train_execution_spec,
    compare_model_evidence,
    build_model_research_proposal,
    draft_model_predict,
    draft_model_train,
    explain_comparison,
    read_dataset_context,
    read_model_evidence,
    UserConfirmation,
    apply_confirmed_model_train,
    apply_confirmed_model_predict,
    verify_model_predict_execution_binding,
    verify_model_train_execution_binding,
)
from v3_backend.agents.permissions import decide_permission
from v3_backend.agents.pydantic_worker import AgentOutputRejected
from v3_backend.contracts.common.truth_admission import FORMAL_ADMITTED_CEILING, PRE_ALPHA_CEILING
from v3_backend.contracts.common.truth_admission import ValidationState
from v3_backend.domain.datasets import DatasetBinding, DatasetVersion, FeatureSetVersion, LabelSpec, SplitSpec
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.domain.models import (
    FeatureColumn,
    ModelPredictionRequest,
    ModelSample,
    PredictionDatasetView,
    SafeLinearModelArtifact,
    TrainingDatasetView,
    TrainingSpecVersion,
    WorkerPredictionCandidate,
    WorkerRuntimeFingerprint,
    WorkerTrainingCandidate,
    evaluate_prediction,
    predict_model,
    train_model,
)
from v3_backend.domain.experiments import ExperimentAttempt, ExperimentAttemptState, ExperimentRun, ExperimentVersion
from v3_backend.domain.reviewer_integration import (
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    review_research_scope,
)


def artifact(char: str) -> str:
    return "art_sha256_" + char * 64


def provenance() -> AgentProvenance:
    return AgentProvenance(
        agent_kind=AgentKind.RESEARCH,
        sdk_version="2.27.0",
        model_name="deterministic-test-model",
        provider_name="test-provider",
        prompt_version="round5-q/1",
        instruction_version="round5-q/1",
        input_sha256="a" * 64,
    )


def runtime() -> WorkerRuntimeFingerprint:
    return WorkerRuntimeFingerprint.create(
        backend_name="scikit-learn-ridge",
        backend_version="1.9.0",
        protocol_version="v3.model-worker/2",
        python_version="3.14.7",
        platform="test-cpu",
        packages=(("numpy", "2.5.2"), ("scikit-learn", "1.9.0"), ("scipy", "1.18.0")),
        thread_limits=(("OMP_NUM_THREADS", "1"),),
    )


def fixture(*, snapshot: str = "snapshot-1", universe: str = "universe-1", horizon: int = 1):
    registry = default_operator_registry()
    evaluator = DeterministicReferenceEvaluator(registry)
    context = FactorEvaluationContext(
        snapshot_id=snapshot,
        universe_version_id=universe,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(snapshot, PRE_ALPHA_CEILING),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(universe, FORMAL_ADMITTED_CEILING),
        knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
        calendar_version_id="calendar-1",
        schema_version_id="schema-1",
        environment_fingerprint="dataset-python-3.14-track-c-v0",
        evaluator_version=evaluator.evaluator_version,
    )
    evaluations = []
    materializations = []
    for index, (name, op, values) in enumerate((("x", "feature.x/1.0.0", [1.0, 2.0]), ("x2", "feature.x2/1.0.0", [1.0, 4.0]))):
        definition = FactorDefinitionVersion.create(name, FeatureNode(name, op), registry)
        result = evaluator.evaluate(definition, {name: values})
        materialization = FeatureMaterialization.create(definition, result, context, artifact(str(index + 1)), FORMAL_ADMITTED_CEILING)
        materializations.append(materialization)
        evaluations.append(FactorEvaluation.create(definition, materialization, artifact(chr(98 + index)), FORMAL_ADMITTED_CEILING))
    evaluations = tuple(evaluations)
    feature_set = FeatureSetVersion.create(evaluations, artifact("f"))
    label = LabelSpec.create("next_return", "close", horizon, 0)
    split = SplitSpec.create(train_start=0, train_end=9, validation_start=12, validation_end=19, test_start=22, test_end=29, purge_observations=1, embargo_observations=1)
    binding = DatasetBinding(
        snapshot_id=snapshot,
        universe_version_id=universe,
        snapshot_truth_binding=context.snapshot_truth_binding,
        universe_truth_binding=context.universe_truth_binding,
        knowledge_cutoff=context.knowledge_cutoff,
        calendar_version_id=context.calendar_version_id,
        schema_version_id=context.schema_version_id,
        environment_fingerprint=context.environment_fingerprint,
        evaluator_version=context.evaluator_version,
    )
    dataset = DatasetVersion.create(feature_set=feature_set, evaluations=evaluations, label_spec=label, split_spec=split, binding=binding, dataset_artifact_id=artifact("d"), provenance_artifact_id=artifact("e"), proposed_state=FORMAL_ADMITTED_CEILING)
    worker_runtime = runtime()
    spec = TrainingSpecVersion.create(dataset=dataset, feature_schema=tuple(FeatureColumn(value) for value in dataset.factor_evaluation_ids), seed=7, environment_profile_id="cpu-single-thread-v1", dependency_runtime_fingerprint=worker_runtime.fingerprint)
    return dataset, feature_set, label, split, spec, worker_runtime, evaluations, tuple(materializations)


def sample(sample_id: str, ordinal: int, x: float) -> ModelSample:
    when = datetime(2026, 1, 1, ordinal % 24, tzinfo=timezone.utc)
    return ModelSample(sample_id=sample_id, instrument_id="instrument-" + sample_id, observation_ordinal=ordinal, event_time=when, decision_time=when, features=(x, x * x), label=1 + 2 * x - 0.5 * x * x)


class FakeWorker:
    def __init__(self, worker_runtime: WorkerRuntimeFingerprint):
        self.runtime = worker_runtime

    def train(self, request, training_spec, view: TrainingDatasetView):
        return WorkerTrainingCandidate(model_training_request_id=request.model_training_request_id, runtime=self.runtime, feature_order=training_spec.feature_order, coefficients=(2.0, -0.5), intercept=1.0, train_sample_ids=view.train_sample_ids, validation_sample_ids=view.validation_sample_ids, train_rmse=0.0, validation_rmse=0.0, seed=training_spec.seed)

    def predict(self, request: ModelPredictionRequest, training_spec, artifact_value: SafeLinearModelArtifact, view: PredictionDatasetView):
        return WorkerPredictionCandidate.from_wire({"model_prediction_request_id": request.model_prediction_request_id, "runtime": self.runtime.to_wire(), "feature_order": list(training_spec.feature_order), "predictions": [{"sample_id": item.sample_id, "value": artifact_value.intercept + math.fsum(c * f for c, f in zip(artifact_value.coefficients, item.features, strict=True))} for item in view.samples]})


def proposal_model(messages: list[object], info: AgentInfo) -> ModelResponse:
    request = None
    has_return = False
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolReturnPart):
                has_return = True
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                try:
                    candidate = json.loads(part.content)
                except json.JSONDecodeError:
                    continue
                if candidate.get("task") == "MODEL_TRAIN_PROPOSAL":
                    request = candidate
    if request is None:
        raise AssertionError("Q structured request unavailable")
    if not has_return:
        return ModelResponse(parts=[ToolCallPart("get_model_dataset_context", {"dataset_version_id": request["dataset_version_id"]})])
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Exact DatasetVersion supports a bounded baseline draft.", "next_action_proposals": ["review the exact training draft before applying it"], "evidence_claims": ["ignored model-authored evidence claim"]})])


def proposal_without_tool(_messages: list[object], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"rationale": "Unsafe no-tool proposal."})])


def trained_bundle(dataset, split, spec, worker_runtime):
    values = (sample("tr0", 0, 0.0), sample("tr1", 1, 1.0), sample("va0", 12, 2.0))
    return train_model(worker=FakeWorker(worker_runtime), dataset=dataset, split_spec=split, training_spec=spec, samples=values, code_version="q-test", training_evidence_provenance_artifact_id=artifact("7"), model_provenance_artifact_id=artifact("8"), proposed_state=FORMAL_ADMITTED_CEILING)


class ModelAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.feature_set, self.label, self.split, self.spec, self.worker_runtime, self.evaluations, self.materializations = fixture()
        self.context = read_dataset_context(dataset=self.dataset, feature_set=self.feature_set, label=self.label, split=self.split, evaluations=self.evaluations, materializations=self.materializations)
        self.bundle = trained_bundle(self.dataset, self.split, self.spec, self.worker_runtime)
        self.training_samples = (sample("tr0", 0, 0.0), sample("tr1", 1, 1.0), sample("va0", 12, 2.0))
        self.train_execution_spec = build_model_train_execution_spec(
            context=self.context, training_spec=self.spec, worker_runtime=self.worker_runtime,
            samples=self.training_samples, code_version="q-execution-spec-v1",
            training_evidence_provenance_artifact_id=artifact("4"),
            model_provenance_artifact_id=artifact("5"), proposed_state=FORMAL_ADMITTED_CEILING,
        )

    def train_draft(self):
        return draft_model_train(context=self.context, spec=self.spec, execution_spec=self.train_execution_spec, requested_metrics=("rmse",), provenance=provenance())

    def prediction_execution_spec(self):
        return build_model_predict_execution_spec(
            model=self.bundle.model, model_artifact=self.bundle.artifact,
            training_spec=self.spec, prediction_context=self.context,
            worker_runtime=self.worker_runtime, samples=(sample("te0", 22, 3.0),),
            prediction_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
            target_semantics="next_return", provenance_artifact_id=artifact("9"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )

    def prediction_draft(self):
        execution_spec = self.prediction_execution_spec()
        return draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=self.context, execution_spec=execution_spec, target_semantics="next_return", provenance=provenance())

    def evidence_source(self, *, prediction=None, evaluation=None, bundle=None, training_spec=None, evaluation_policy_id="RMSE_TEST_V1"):
        bundle = bundle or self.bundle
        training_spec = training_spec or self.spec
        experiment = ExperimentVersion.create("q-model-evidence", "exact model comparison", "round5-q/1")
        run = ExperimentRun.create(
            experiment=experiment, dataset=self.dataset, factor_evaluation=self.evaluations[0],
            code_version="q-evidence-v1", environment_fingerprint=self.dataset.binding.environment_fingerprint,
            input_artifact_ids=(self.dataset.dataset_artifact_id, bundle.artifact.artifact_id),
            run_provenance_artifact_id=artifact("3"), proposed_state=FORMAL_ADMITTED_CEILING,
        )
        result_artifact = evaluation.provenance_artifact_id if evaluation is not None else bundle.artifact.artifact_id
        attempt = ExperimentAttempt.create(
            run=run, ordinal=1, state=ExperimentAttemptState.SUCCEEDED,
            started_at=datetime(2026, 2, 1, tzinfo=timezone.utc), ended_at=datetime(2026, 2, 1, 1, tzinfo=timezone.utc),
            evidence_artifact_ids=(result_artifact,), result_artifact_id=result_artifact,
        )
        session = "round5-q-model-session"
        objects = [("DatasetVersion", self.dataset.dataset_version_id, self.dataset.truth_admission), ("ModelVersion", bundle.model.model_version_id, bundle.model.truth_admission)]
        if prediction is not None:
            objects.append(("PredictionArtifact", prediction.prediction.prediction_artifact_id, prediction.prediction.truth_admission))
        refs = tuple(ReviewEvidenceRef(session, kind, object_id, object_id[-64:]) for kind, object_id, _truth in objects)
        records = tuple(ReviewEvidenceRecord(ref, ValidationState.PASSED, truth, (), (), ()) for ref, (_kind, _id, truth) in zip(refs, objects, strict=True))
        scope = ResearchReviewScope.create(session_id=session, target_refs=(refs[1],), evidence_records=records)
        report = review_research_scope(scope)
        return CanonicalModelEvidenceSource(
            dataset=self.dataset, feature_set=self.feature_set, label_spec=self.label, split_spec=self.split,
            factor_evaluations=self.evaluations, feature_materializations=self.materializations,
            training_spec=training_spec, trained_model=bundle,
            experiment_version=experiment, experiment_run=run, experiment_attempt=attempt,
            reviewer_reports=(report,), evaluation_policy_id=evaluation_policy_id, benchmark_id="BENCHMARK_NONE_EXPLICIT",
            prediction=prediction, evaluation=evaluation,
        )

    def evaluated_evidence_source(self):
        prediction = predict_model(
            worker=FakeWorker(self.worker_runtime), model=self.bundle.model,
            model_artifact=self.bundle.artifact, prediction_dataset=self.dataset,
            training_spec=self.spec, samples=(sample("te0", 22, 3.0),),
            prediction_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
            target_semantics="next_return", provenance_artifact_id=artifact("9"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        evaluation = evaluate_prediction(
            model_bundle=self.bundle, prediction_bundle=prediction, dataset=self.dataset,
            split_spec=self.split, provenance_artifact_id=artifact("a"),
        )
        return self.evidence_source(prediction=prediction, evaluation=evaluation)

    def test_01_model_proposal_is_non_canonical_draft(self):
        draft = self.train_draft()
        self.assertEqual((draft.authority_status, draft.lifecycle_state, draft.canonical_identity), ("NON_CANONICAL", "DRAFT", None))

    def test_02_exact_dataset_version_required(self):
        bad = self.context.model_copy(update={"dataset_version_id": "wrong"})
        with self.assertRaises(ModelAgentBindingError):
            read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=bad)

    def test_03_missing_label_or_horizon_rejected(self):
        with self.assertRaises(ValidationError):
            self.context.model_copy(update={"horizon_observations": 0}).model_validate(self.context.model_copy(update={"horizon_observations": 0}).model_dump())

    def test_04_overlapping_splits_rejected_by_canonical_owner(self):
        with self.assertRaises(ValueError):
            SplitSpec.create(train_start=0, train_end=10, validation_start=10, validation_end=20, test_start=22, test_end=30, purge_observations=0, embargo_observations=0)

    def test_05_pit_invalid_label_gap_rejected_by_canonical_owner(self):
        label = LabelSpec.create("future", "close", 5, 1)
        with self.assertRaises(ValueError):
            read_dataset_context(dataset=self.dataset, feature_set=self.feature_set, label=label, split=self.split, evaluations=self.evaluations, materializations=self.materializations)

    def test_06_typed_model_family_and_parameters(self):
        draft = self.train_draft()
        self.assertEqual(draft.payload.model_family, "RIDGE_REGRESSION")
        self.assertEqual(dict(draft.payload.parameters)["solver"], "svd")

    def test_07_draft_identity_is_deterministic(self):
        kwargs = dict(context=self.context, spec=self.spec, execution_spec=self.train_execution_spec, requested_metrics=("rmse",), provenance=provenance())
        self.assertEqual(draft_model_train(**kwargs).deterministic_sha256, draft_model_train(**kwargs).deterministic_sha256)

    def test_08_agent_cannot_execute_training(self):
        draft = self.train_draft()
        self.assertFalse(draft.payload.agent_execution_allowed)
        self.assertEqual((draft.payload.canonical_user_execution_authority, draft.payload.production_execution_state), ("NOT_AVAILABLE", "NOT_RUN"))

    def test_09_agent_cannot_mint_model_version(self):
        import v3_backend.agents.model_agent as module
        self.assertFalse(hasattr(module, "train_model"))
        self.assertIsNone(ModelAgentDraft.model_fields["canonical_identity"].default)

    def test_10_prediction_exact_model_binding(self):
        draft = self.prediction_draft()
        self.assertEqual(draft.payload.model_version_id, self.bundle.model.model_version_id)

    def test_11_prediction_dataset_mismatch_rejected(self):
        bad = self.context.model_copy(update={"feature_set_version_id": "other"})
        with self.assertRaises(ModelAgentBindingError):
            draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=bad, execution_spec=self.prediction_execution_spec(), target_semantics="next_return", provenance=provenance())

    def test_12_prediction_horizon_mismatch_rejected(self):
        bad = self.context.model_copy(update={"label_spec_id": "other", "horizon_observations": 5})
        with self.assertRaises(ModelAgentBindingError):
            draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=bad, execution_spec=self.prediction_execution_spec(), target_semantics="next_return", provenance=provenance())

    def test_13_comparable_models_compare_deterministically(self):
        prediction = predict_model(worker=FakeWorker(self.worker_runtime), model=self.bundle.model, model_artifact=self.bundle.artifact, prediction_dataset=self.dataset, training_spec=self.spec, samples=(sample("te0", 22, 3.0),), prediction_timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc), target_semantics="next_return", provenance_artifact_id=artifact("9"), proposed_state=FORMAL_ADMITTED_CEILING)
        evidence = evaluate_prediction(model_bundle=self.bundle, prediction_bundle=prediction, dataset=self.dataset, split_spec=self.split, provenance_artifact_id=artifact("a"))
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context, evaluation=evidence, prediction=prediction.prediction)
        result = compare_model_evidence(view, view, objective_metric="rmse", objective_split_role="TEST", objective_direction="MINIMIZE")
        self.assertEqual((result.status, result.ranking), (ComparisonStatus.COMPARABLE, "TIE"))

    def test_14_incompatible_context_is_not_ranked(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context)
        other = view.model_copy(update={"universe_version_id": "other-universe"})
        result = compare_model_evidence(view, other, objective_metric="rmse", objective_split_role="VALIDATION_OR_TEST", objective_direction="MINIMIZE")
        self.assertEqual(result.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertIsNone(result.ranking)

    def test_15_missing_metric_remains_not_run(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context)
        self.assertEqual((view.metrics[0].status, view.metrics[0].value), ("NOT_RUN", None))

    def test_16_reviewer_refs_are_exact_bound(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context, reviewer_refs=("rrp_sha256_" + "1" * 64,))
        explanation = explain_comparison(left=view, right=view, comparison=compare_model_evidence(view, view))
        self.assertIn(view.reviewer_refs[0], explanation.cited_evidence_refs)

    def test_17_explanation_does_not_invent_evidence(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context)
        explanation = explain_comparison(left=view, right=view, comparison=compare_model_evidence(view, view))
        self.assertFalse(any((explanation.invented_feature_importance, explanation.invented_shap, explanation.invented_ic, explanation.invented_attribution, explanation.invented_robustness, explanation.invented_causality)))

    def test_18_structured_output_failure_is_typed(self):
        with self.assertRaises(ValidationError):
            ModelAgentDraft.model_validate({"draft_kind": "MODEL_TRAIN"})

    def test_19_production_execution_is_explicitly_unavailable_not_run(self):
        draft = self.train_draft()
        self.assertEqual((draft.payload.canonical_user_execution_authority, draft.payload.production_execution_state), ("NOT_AVAILABLE", "NOT_RUN"))
        self.assertFalse(draft.payload.agent_execution_allowed)

    def test_20_l2_l3_remain_denied(self):
        self.assertFalse(decide_permission(PermissionLevel.L2_EXECUTE).allowed)
        self.assertFalse(decide_permission(PermissionLevel.L3_PUBLISH).allowed)

    def test_21_research_loop_complete_remains_not_available_not_run(self):
        from v3_backend.domain.agent_research_loop import ResearchActionDraft
        action = ResearchActionDraft.create(
            action_type="MODEL_TRAIN",
            exact_input_refs=(self.dataset.dataset_version_id,),
            requested_capability="MODEL_TRAIN_DRAFT_ONLY",
            expected_output_kind="MODEL_VERSION",
            resource_profile_ref="cpu-single-thread-v1",
            budget_version_id="budget-q-test",
        )
        self.assertEqual(action.state.value, "NOT_RUN")
        self.assertEqual(action.authority_status, "NON_CANONICAL")

    def test_22_stale_materialization_fails_closed(self):
        with self.assertRaisesRegex(ModelAgentBindingError, "FeatureMaterialization"):
            read_dataset_context(dataset=self.dataset, feature_set=self.feature_set, label=self.label, split=self.split, evaluations=self.evaluations, materializations=(self.materializations[0],))

    def test_23_research_proposal_binds_exact_dataset(self):
        draft = self.train_draft()
        proposal = build_model_research_proposal(research_goal="Compare a bounded ridge baseline.", context=self.context, action_drafts=(draft,))
        self.assertEqual(proposal.exact_context.dataset_version_id, draft.payload.context.dataset_version_id)
        self.assertFalse(proposal.agent_execution_allowed)

    def test_24_unbound_reviewer_report_is_rejected(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context)
        report = type("Report", (), {"review_report_id": "rrp_unbound"})()
        with self.assertRaisesRegex(ModelAgentBindingError, "exact bound report"):
            explain_comparison(left=view, right=view, comparison=compare_model_evidence(view, view), review_reports=(report,))

    def test_25_ranking_requires_explicit_objective_direction(self):
        view = read_model_evidence(model=self.bundle.model, training_spec=self.spec, dataset_context=self.context)
        with self.assertRaisesRegex(ModelAgentBindingError, "metric, split role and direction"):
            compare_model_evidence(view, view, objective_metric="rmse")

    def test_26_pydantic_model_agent_consumes_exact_l0_context(self):
        tools = ModelAgentReadTools(contexts=(self.context,))
        worker = ModelAgentWorker(model=FunctionModel(proposal_model, model_name="q-function-model"), permission=PermissionLevel.L1_DRAFT, model_name="q-test-model", provider_name="test-provider", prompt_version="q-prompt/1", read_tools=tools)
        proposal = worker.run_train_proposal(research_goal="Train a bounded comparable ridge baseline.", context=self.context, spec=self.spec, execution_spec=self.train_execution_spec, requested_metrics=("rmse",))
        self.assertEqual(tools.called, (("get_model_dataset_context", self.context.dataset_version_id),))
        self.assertEqual(proposal.action_drafts[0].draft_kind, ModelDraftKind.MODEL_TRAIN)
        self.assertNotIn("ignored model-authored evidence claim", proposal.to_deterministic_json())
        self.assertNotIn("execute_task", worker.visible_tool_names)

    def test_27_agent_without_exact_read_tool_fails_closed(self):
        tools = ModelAgentReadTools(contexts=(self.context,))
        worker = ModelAgentWorker(model=FunctionModel(proposal_without_tool, model_name="q-no-tool-model"), permission=PermissionLevel.L1_DRAFT, model_name="q-test-model", provider_name="test-provider", prompt_version="q-prompt/1", read_tools=tools)
        with self.assertRaisesRegex(AgentOutputRejected, "failed closed"):
            worker.run_train_proposal(research_goal="Unsafe proposal.", context=self.context, spec=self.spec, execution_spec=self.train_execution_spec, requested_metrics=("rmse",))

    def test_28_caller_confirmation_cannot_start_training(self):
        draft = self.train_draft()
        confirmation = UserConfirmation(action="MODEL_TRAIN", draft_sha256=draft.deterministic_sha256, confirmed_by="user:test-researcher", confirmed_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ModelDraftApplicationError, "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"):
            apply_confirmed_model_train(draft=draft, confirmation=confirmation, execution_spec=self.train_execution_spec)

    def test_29_wrong_confirmation_hash_also_cannot_confer_authority(self):
        draft = self.train_draft()
        confirmation = UserConfirmation(action="MODEL_TRAIN", draft_sha256="0" * 64, confirmed_by="user:test-researcher", confirmed_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ModelDraftApplicationError, "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"):
            apply_confirmed_model_train(draft=draft, confirmation=confirmation, execution_spec=self.train_execution_spec)

    def test_30_application_is_not_an_agent_tool_or_worker_method(self):
        tools = ModelAgentReadTools(contexts=(self.context,))
        worker = ModelAgentWorker(model=FunctionModel(proposal_model, model_name="q-function-model"), permission=PermissionLevel.L1_DRAFT, model_name="q-test-model", provider_name="test-provider", prompt_version="q-prompt/1", read_tools=tools)
        self.assertFalse(hasattr(worker, "apply_confirmed_model_train"))
        self.assertNotIn("apply_confirmed_model_train", tools.visible_tool_names)

    def test_31_exact_train_execution_spec_verifies_deterministically(self):
        self.assertEqual(
            verify_model_train_execution_binding(draft=self.train_draft(), execution_spec=self.train_execution_spec),
            self.train_execution_spec,
        )

    def test_32_every_material_train_execution_mutation_fails_binding(self):
        draft = self.train_draft()
        mutations = {
            "samples": self.train_execution_spec.samples + (self.train_execution_spec.samples[0].model_copy(update={"sample_id": "mutated"}),),
            "code_version": "other-code",
            "training_spec_content_sha256": "1" * 64,
            "feature_schema_fingerprint": "other-feature-schema",
            "worker_runtime_fingerprint": "mrt_sha256_" + "1" * 64,
            "worker_runtime_content_sha256": "2" * 64,
            "training_evidence_provenance_artifact_id": artifact("6"),
            "model_provenance_artifact_id": artifact("7"),
            "proposed_truth_state": "UNKNOWN",
            "proposed_admission_state": "NOT_ADMITTED",
            "training_spec_version_id": "trspec_sha256_" + "2" * 64,
        }
        context_mutations = {
            "dataset_version_id": "dsv_sha256_" + "1" * 64,
            "feature_set_version_id": "fsv_sha256_" + "1" * 64,
            "factor_evaluation_ids": ("fev_sha256_" + "1" * 64,),
            "factor_definition_version_ids": ("fdv_sha256_" + "1" * 64,),
            "feature_materialization_ids": ("fmt_sha256_" + "1" * 64,),
            "label_spec_id": "lbl_sha256_" + "1" * 64,
            "label_name": "other-label",
            "label_source_field": "other-source-field",
            "horizon_observations": self.context.horizon_observations + 1,
            "split_spec_id": "spl_sha256_" + "1" * 64,
            "train_range": (1, 2),
            "validation_range": (3, 4),
            "test_range": (5, 6),
            "purge_observations": self.context.purge_observations + 1,
            "embargo_observations": self.context.embargo_observations + 1,
            "snapshot_id": "other-snapshot",
            "universe_version_id": "other-universe",
            "knowledge_cutoff": "2027-01-01T00:00:00Z",
            "truth_state": "UNKNOWN",
            "admission_state": "NOT_ADMITTED",
            "dataset_artifact_id": artifact("4"),
            "provenance_artifact_id": artifact("5"),
        }
        mutations.update({f"context.{field}": self.context.model_copy(update={field: value}) for field, value in context_mutations.items()})
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = self.train_execution_spec.model_copy(update={"context" if field.startswith("context.") else field: value})
                with self.assertRaisesRegex(ModelDraftApplicationError, "EXECUTION_SPEC_BINDING_MISMATCH"):
                    verify_model_train_execution_binding(draft=draft, execution_spec=changed)

    def test_33_exact_prediction_execution_spec_verifies_deterministically(self):
        spec = self.prediction_execution_spec()
        self.assertEqual(verify_model_predict_execution_binding(draft=self.prediction_draft(), execution_spec=spec), spec)

    def test_34_every_material_prediction_execution_mutation_fails_binding(self):
        spec = self.prediction_execution_spec()
        draft = self.prediction_draft()
        mutations = {
            "samples": spec.samples + (spec.samples[0].model_copy(update={"sample_id": "mutated"}),),
            "prediction_timestamp": datetime(2026, 2, 2, tzinfo=timezone.utc),
            "model_artifact_content_sha256": "1" * 64,
            "model_training_request_id": "mtr_sha256_" + "1" * 64,
            "training_spec_content_sha256": "2" * 64,
            "worker_runtime_fingerprint": "mrt_sha256_" + "1" * 64,
            "worker_runtime_content_sha256": "3" * 64,
            "provenance_artifact_id": artifact("6"),
            "proposed_truth_state": "UNKNOWN",
            "proposed_admission_state": "NOT_ADMITTED",
            "target_semantics": "other-target",
            "model_version_id": "mdv_sha256_" + "2" * 64,
            "model_artifact_id": artifact("3"),
            "training_spec_version_id": "trspec_sha256_" + "4" * 64,
        }
        prediction_context_mutations = {
            "dataset_version_id": "dsv_sha256_" + "1" * 64,
            "feature_set_version_id": "fsv_sha256_" + "1" * 64,
            "factor_evaluation_ids": ("fev_sha256_" + "1" * 64,),
            "factor_definition_version_ids": ("fdv_sha256_" + "1" * 64,),
            "feature_materialization_ids": ("fmt_sha256_" + "1" * 64,),
            "label_spec_id": "lbl_sha256_" + "1" * 64,
            "label_name": "other-label",
            "label_source_field": "other-source-field",
            "horizon_observations": self.context.horizon_observations + 1,
            "split_spec_id": "spl_sha256_" + "1" * 64,
            "train_range": (1, 2),
            "validation_range": (3, 4),
            "test_range": (5, 6),
            "purge_observations": self.context.purge_observations + 1,
            "embargo_observations": self.context.embargo_observations + 1,
            "snapshot_id": "other-snapshot",
            "universe_version_id": "other-universe",
            "knowledge_cutoff": "2027-01-01T00:00:00Z",
            "truth_state": "UNKNOWN",
            "admission_state": "NOT_ADMITTED",
            "dataset_artifact_id": artifact("4"),
            "provenance_artifact_id": artifact("5"),
        }
        mutations.update({f"prediction_context.{field}": self.context.model_copy(update={field: value}) for field, value in prediction_context_mutations.items()})
        for field, value in mutations.items():
            with self.subTest(field=field):
                changed = spec.model_copy(update={"prediction_context" if field.startswith("prediction_context.") else field: value})
                with self.assertRaisesRegex(ModelDraftApplicationError, "EXECUTION_SPEC_BINDING_MISMATCH"):
                    verify_model_predict_execution_binding(draft=draft, execution_spec=changed)

    def test_35_caller_confirmation_cannot_start_prediction(self):
        draft = self.prediction_draft()
        confirmation = UserConfirmation(action="MODEL_PREDICT", draft_sha256=draft.deterministic_sha256, confirmed_by="user:test-researcher", confirmed_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ModelDraftApplicationError, "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"):
            apply_confirmed_model_predict(draft=draft, confirmation=confirmation, execution_spec=self.prediction_execution_spec())

    def test_36_canonical_valid_chain_resolves_and_ranks(self):
        resolver = CanonicalModelEvidenceResolver((self.evaluated_evidence_source(),))
        request = resolver.request_for(self.bundle.model.model_version_id)
        view = resolver.resolve(request)
        comparison = resolver.compare(request, request, objective_metric="rmse", objective_split_role="TEST", objective_direction="MINIMIZE")
        self.assertEqual(view.metrics[0].evidence_ref, request.model_evaluation_evidence_id)
        self.assertEqual((comparison.status, comparison.ranking), (ComparisonStatus.COMPARABLE, "TIE"))

    def test_37_manual_view_exact_type_and_fabricated_metric_are_not_authority(self):
        resolver = CanonicalModelEvidenceResolver((self.evaluated_evidence_source(),))
        request = resolver.request_for(self.bundle.model.model_version_id)
        trusted = resolver.resolve(request)
        fabricated = trusted.model_copy(update={"metrics": (trusted.metrics[0].model_copy(update={"value": -999.0}),)})
        with self.assertRaisesRegex((AttributeError, ValueError), EVIDENCE_BINDING_UNAVAILABLE):
            resolver.compare(fabricated, request, objective_metric="rmse", objective_split_role="TEST", objective_direction="MINIMIZE")
        with self.assertRaises(TypeError):
            ModelAgentReadTools(contexts=(self.context,), evidence=(fabricated,))

    def test_38_fabricated_reviewer_ref_and_deterministic_request_shape_are_rejected(self):
        resolver = CanonicalModelEvidenceResolver((self.evaluated_evidence_source(),))
        request = resolver.request_for(self.bundle.model.model_version_id)
        forged = request.model_copy(update={"reviewer_report_ids": ("rrp_sha256_" + "f" * 64,)})
        with self.assertRaisesRegex(ValueError, EVIDENCE_BINDING_UNAVAILABLE):
            resolver.resolve(forged)

    def test_39_broken_canonical_model_dataset_result_reviewer_and_provenance_links_fail_closed(self):
        source = self.evaluated_evidence_source()
        broken_values = (
            dataclasses.replace(source, dataset=dataclasses.replace(source.dataset, dataset_version_id="dsv_sha256_" + "1" * 64)),
            dataclasses.replace(source, trained_model=dataclasses.replace(source.trained_model, model=dataclasses.replace(source.trained_model.model, provenance_artifact_id=artifact("b")))),
            dataclasses.replace(source, experiment_attempt=dataclasses.replace(source.experiment_attempt, result_artifact_id=artifact("c"))),
            dataclasses.replace(source, reviewer_reports=(dataclasses.replace(source.reviewer_reports[0], review_report_id="rrp_sha256_" + "d" * 64),)),
            dataclasses.replace(source, evaluation=dataclasses.replace(source.evaluation, model_version_id="mdv_sha256_" + "e" * 64)),
        )
        for index, broken in enumerate(broken_values):
            with self.subTest(broken_index=index):
                with self.assertRaisesRegex(ValueError, EVIDENCE_BINDING_UNAVAILABLE):
                    CanonicalModelEvidenceResolver((broken,))

    def test_40_trusted_missing_metric_is_not_run_and_context_invariant_is_exact(self):
        other_spec = TrainingSpecVersion.create(dataset=self.dataset, feature_schema=self.spec.feature_schema, seed=7, environment_profile_id="cpu-single-thread-v1", dependency_runtime_fingerprint=self.worker_runtime.fingerprint, alpha=2.0)
        other_bundle = trained_bundle(self.dataset, self.split, other_spec, self.worker_runtime)
        resolver = CanonicalModelEvidenceResolver((self.evidence_source(), self.evidence_source(bundle=other_bundle, training_spec=other_spec, evaluation_policy_id="OTHER_POLICY")))
        request = resolver.request_for(self.bundle.model.model_version_id)
        other_request = resolver.request_for(other_bundle.model.model_version_id)
        view = resolver.resolve(request)
        self.assertEqual((view.metrics[0].status, view.metrics[0].value), ("NOT_RUN", None))
        comparison = resolver.compare(request, other_request, objective_metric="rmse", objective_split_role="VALIDATION_OR_TEST", objective_direction="MINIMIZE")
        self.assertEqual(comparison.status, ComparisonStatus.INCOMPARABLE_CONTEXT)
        self.assertEqual((comparison.metric_deltas, comparison.ranking), ((), None))

    def test_41_trusted_tools_resolve_internally_and_ignore_no_caller_view(self):
        resolver = CanonicalModelEvidenceResolver((self.evaluated_evidence_source(),))
        request = resolver.request_for(self.bundle.model.model_version_id)
        tools = ModelAgentReadTools(contexts=(self.context,), resolver=resolver, evidence_requests=(request,))
        tools.begin((("get_model_evidence", request.model_version_id),))
        view = tools.get_model_evidence(request.model_version_id)
        self.assertEqual(view.model_version_id, request.model_version_id)


if __name__ == "__main__":
    unittest.main()
