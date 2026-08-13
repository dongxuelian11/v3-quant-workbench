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
    ModelAgentBindingError,
    ModelAgentDraft,
    ModelAgentReadTools,
    ModelAgentWorker,
    ModelDraftApplicationError,
    ModelDraftKind,
    compare_model_evidence,
    build_model_research_proposal,
    draft_model_predict,
    draft_model_train,
    explain_comparison,
    read_dataset_context,
    read_model_evidence,
    UserConfirmation,
    apply_confirmed_model_train,
)
from v3_backend.agents.permissions import decide_permission
from v3_backend.agents.pydantic_worker import AgentOutputRejected
from v3_backend.contracts.common.truth_admission import FORMAL_ADMITTED_CEILING, PRE_ALPHA_CEILING
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

    def test_01_model_proposal_is_non_canonical_draft(self):
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
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
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        self.assertEqual(draft.payload.model_family, "RIDGE_REGRESSION")
        self.assertEqual(dict(draft.payload.parameters)["solver"], "svd")

    def test_07_draft_identity_is_deterministic(self):
        kwargs = dict(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        self.assertEqual(draft_model_train(**kwargs).deterministic_sha256, draft_model_train(**kwargs).deterministic_sha256)

    def test_08_agent_cannot_execute_training(self):
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        self.assertFalse(draft.payload.agent_execution_allowed)
        self.assertTrue(draft.payload.user_confirmation_required)

    def test_09_agent_cannot_mint_model_version(self):
        import v3_backend.agents.model_agent as module
        self.assertFalse(hasattr(module, "train_model"))
        self.assertIsNone(ModelAgentDraft.model_fields["canonical_identity"].default)

    def test_10_prediction_exact_model_binding(self):
        draft = draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=self.context, target_semantics="next_return", provenance=provenance())
        self.assertEqual(draft.payload.model_version_id, self.bundle.model.model_version_id)

    def test_11_prediction_dataset_mismatch_rejected(self):
        bad = self.context.model_copy(update={"feature_set_version_id": "other"})
        with self.assertRaises(ModelAgentBindingError):
            draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=bad, target_semantics="next_return", provenance=provenance())

    def test_12_prediction_horizon_mismatch_rejected(self):
        bad = self.context.model_copy(update={"label_spec_id": "other", "horizon_observations": 5})
        with self.assertRaises(ModelAgentBindingError):
            draft_model_predict(model=self.bundle.model, training_spec=self.spec, prediction_context=bad, target_semantics="next_return", provenance=provenance())

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

    def test_19_user_confirmation_path_is_not_l2_tool(self):
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        self.assertTrue(draft.payload.user_confirmation_required)
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
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
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
        proposal = worker.run_train_proposal(research_goal="Train a bounded comparable ridge baseline.", context=self.context, spec=self.spec, requested_metrics=("rmse",))
        self.assertEqual(tools.called, (("get_model_dataset_context", self.context.dataset_version_id),))
        self.assertEqual(proposal.action_drafts[0].draft_kind, ModelDraftKind.MODEL_TRAIN)
        self.assertNotIn("ignored model-authored evidence claim", proposal.to_deterministic_json())
        self.assertNotIn("execute_task", worker.visible_tool_names)

    def test_27_agent_without_exact_read_tool_fails_closed(self):
        tools = ModelAgentReadTools(contexts=(self.context,))
        worker = ModelAgentWorker(model=FunctionModel(proposal_without_tool, model_name="q-no-tool-model"), permission=PermissionLevel.L1_DRAFT, model_name="q-test-model", provider_name="test-provider", prompt_version="q-prompt/1", read_tools=tools)
        with self.assertRaisesRegex(AgentOutputRejected, "failed closed"):
            worker.run_train_proposal(research_goal="Unsafe proposal.", context=self.context, spec=self.spec, requested_metrics=("rmse",))

    def test_28_user_confirmation_seam_binds_exact_draft_and_canonical_owner(self):
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        confirmation = UserConfirmation(action="MODEL_TRAIN", draft_sha256=draft.deterministic_sha256, confirmed_by="user:test-researcher", confirmed_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc))
        result = apply_confirmed_model_train(draft=draft, confirmation=confirmation, worker=FakeWorker(self.worker_runtime), dataset=self.dataset, split_spec=self.split, training_spec=self.spec, samples=(sample("tr0", 0, 0.0), sample("tr1", 1, 1.0), sample("va0", 12, 2.0)), code_version="q-user-confirm-test", training_evidence_provenance_artifact_id=artifact("4"), model_provenance_artifact_id=artifact("5"), proposed_state=FORMAL_ADMITTED_CEILING)
        self.assertTrue(result.model.model_version_id.startswith("mdv_sha256_"))
        self.assertEqual(result.model.training_spec_version_id, self.spec.training_spec_version_id)

    def test_29_wrong_confirmation_hash_rejects_before_worker(self):
        draft = draft_model_train(context=self.context, spec=self.spec, requested_metrics=("rmse",), provenance=provenance())
        confirmation = UserConfirmation(action="MODEL_TRAIN", draft_sha256="0" * 64, confirmed_by="user:test-researcher", confirmed_at=datetime(2026, 8, 12, 15, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ModelDraftApplicationError, "exact draft hash"):
            apply_confirmed_model_train(draft=draft, confirmation=confirmation, worker=FakeWorker(self.worker_runtime), dataset=self.dataset, split_spec=self.split, training_spec=self.spec, samples=(), code_version="q-test", training_evidence_provenance_artifact_id=artifact("4"), model_provenance_artifact_id=artifact("5"), proposed_state=FORMAL_ADMITTED_CEILING)

    def test_30_application_is_not_an_agent_tool_or_worker_method(self):
        tools = ModelAgentReadTools(contexts=(self.context,))
        worker = ModelAgentWorker(model=FunctionModel(proposal_model, model_name="q-function-model"), permission=PermissionLevel.L1_DRAFT, model_name="q-test-model", provider_name="test-provider", prompt_version="q-prompt/1", read_tools=tools)
        self.assertFalse(hasattr(worker, "apply_confirmed_model_train"))
        self.assertNotIn("apply_confirmed_model_train", tools.visible_tool_names)


if __name__ == "__main__":
    unittest.main()
