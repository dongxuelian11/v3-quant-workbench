from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from v3_backend.adapters.tdx_formula import TdxTranslator, registered_tdx_data_semantic_profile
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    ValidationState,
)
from v3_backend.domain.datasets import DatasetBinding, DatasetVersion, FeatureSetVersion, LabelSpec, SplitSpec
from v3_backend.domain.experiments import (
    EvidenceStatus,
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentResult,
    ExperimentRun,
    ExperimentVersion,
    ReviewerEvidence,
    RewardVector,
)
from v3_backend.domain.factor_assets import (
    FactorAssetLifecycle,
    FactorAssetVersion,
    FactorCatalogSnapshotVersion,
    FactorDraftProposal,
    FactorImportReceipt,
)
from v3_backend.domain.factor_library import (
    CanonicalEvaluationEvidenceResolver,
    EvaluationEvidence,
    FactorEvidenceBindingError,
    FactorLibraryService,
    evaluation_context_ref,
)
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    signal_compatible_operator_registry,
)
from v3_backend.domain.reviewer_integration import (
    DeterministicReviewCheck,
    ResearchReviewReport,
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    ReviewerRuleSet,
    ReviewOutcome,
    ReviewRuleDefinition,
    ReviewSeverity,
)


def artifact(character: str) -> str:
    return "art_sha256_" + character * 64


class CanonicalSource:
    def __init__(self, objects: tuple[object, ...], artifacts: set[str]) -> None:
        self._objects: dict[tuple[str, str], object] = {}
        for value in objects:
            kind = type(value).__name__
            identity_name = {
                "FactorDefinitionVersion": "factor_definition_version_id",
                "FeatureMaterialization": "feature_materialization_id",
                "FactorEvaluation": "factor_evaluation_id",
                "DatasetVersion": "dataset_version_id",
                "LabelSpec": "label_spec_id",
                "SplitSpec": "split_spec_id",
                "ExperimentVersion": "experiment_version_id",
                "ExperimentRun": "experiment_run_id",
                "ExperimentAttempt": "experiment_attempt_id",
                "ExperimentResult": "experiment_result_id",
                "RewardVector": "reward_vector_id",
                "ReviewerEvidence": "reviewer_evidence_id",
                "ResearchReviewReport": "review_report_id",
            }[kind]
            self._objects[(kind, getattr(value, identity_name))] = value
        self._artifacts = frozenset(artifacts)

    def resolve(self, kind: str, identity: str) -> object | None:
        return self._objects.get((kind, identity))

    def contains_artifact(self, artifact_id: str) -> bool:
        return artifact_id in self._artifacts


class CanonicalEvidenceResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = signal_compatible_operator_registry()
        translator = TdxTranslator(registry)
        profile = registered_tdx_data_semantic_profile()
        proposal = FactorDraftProposal.create(
            natural_language_intent="Draft close factor",
            draft_kind="TDX",
            draft_payload="CLOSE_FACTOR:CLOSE;",
            rationale="canonical resolver fixture",
            expected_inputs=("close",),
            expected_output="FLOAT_SERIES",
        )
        from v3_backend.domain.factor_library import FactorTranslationPreview

        preview = FactorTranslationPreview.from_proposal(
            proposal,
            translator=translator,
            data_profile=profile,
            provenance_ref="test:canonical-factor-source",
        )
        translated = preview.translation.output("CLOSE_FACTOR")  # type: ignore[union-attr]
        self.definition = translated.definition
        receipt = FactorImportReceipt.create_from_user_formula(
            translation=preview.translation,
            compatibility_profile=translator.compatibility,
            data_profile=profile,
            definition=self.definition,
        )
        self.asset = FactorAssetVersion.create(
            asset_key="canonical.close-factor",
            definition=self.definition,
            source_family="TDX_USER_FORMULA",
            output_binding=translated.binding,
            display_name="Canonical Close Factor",
            tags=("fixture",),
            categories=("test",),
            frequency="1d",
            lifecycle=FactorAssetLifecycle.DRAFT,
            import_receipt=receipt,
            formula_document=preview.translation.document,  # type: ignore[union-attr]
        )
        self.document = preview.translation.document  # type: ignore[union-attr]

        evaluator = DeterministicReferenceEvaluator(registry)
        context = FactorEvaluationContext(
            snapshot_id="snapshot:canonical",
            universe_version_id="universe:canonical",
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot("snapshot:canonical", PRE_ALPHA_CEILING),
            universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe("universe:canonical", FORMAL_ADMITTED_CEILING),
            knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
            calendar_version_id="calendar:canonical",
            schema_version_id="schema:canonical",
            environment_fingerprint="round5-p-canonical-evidence",
            evaluator_version=evaluator.evaluator_version,
        )
        materialized_result = evaluator.evaluate(self.definition, {"close": [1.0, 2.0, 3.0]})
        self.materialization = FeatureMaterialization.create(
            self.definition, materialized_result, context, artifact("a"), FORMAL_ADMITTED_CEILING
        )
        self.evaluation = FactorEvaluation.create(
            self.definition, self.materialization, artifact("b"), FORMAL_ADMITTED_CEILING
        )
        feature_set = FeatureSetVersion.create((self.evaluation,), artifact("c"))
        self.label = LabelSpec.create("next_return", "close", 1, 0)
        self.split = SplitSpec.create(
            train_start=0,
            train_end=9,
            validation_start=12,
            validation_end=19,
            test_start=22,
            test_end=29,
            purge_observations=1,
            embargo_observations=1,
        )
        binding = DatasetBinding(
            context.snapshot_id,
            context.universe_version_id,
            context.snapshot_truth_binding,
            context.universe_truth_binding,
            context.knowledge_cutoff,
            context.calendar_version_id,
            context.schema_version_id,
            context.environment_fingerprint,
            context.evaluator_version,
        )
        self.dataset = DatasetVersion.create(
            feature_set=feature_set,
            evaluations=(self.evaluation,),
            label_spec=self.label,
            split_spec=self.split,
            binding=binding,
            dataset_artifact_id=artifact("d"),
            provenance_artifact_id=artifact("e"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.experiment = ExperimentVersion.create("factor-evaluation", "canonical evidence", "policy/1")
        self.run = ExperimentRun.create(
            experiment=self.experiment,
            dataset=self.dataset,
            factor_evaluation=self.evaluation,
            code_version="round5-p/1",
            environment_fingerprint=context.environment_fingerprint,
            input_artifact_ids=(self.dataset.dataset_artifact_id, self.materialization.output_artifact_id),
            run_provenance_artifact_id=artifact("f"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        started = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
        self.attempt = ExperimentAttempt.create(
            run=self.run,
            ordinal=1,
            state=ExperimentAttemptState.SUCCEEDED,
            started_at=started,
            ended_at=started + timedelta(minutes=1),
            evidence_artifact_ids=(artifact("1"),),
            result_artifact_id=artifact("2"),
        )
        self.reviewer = ReviewerEvidence.create(
            lookahead=EvidenceStatus.PASS,
            leakage=EvidenceStatus.PASS,
            split=EvidenceStatus.PASS,
            sample_coverage=EvidenceStatus.PASS,
            missingness=EvidenceStatus.PASS,
            turnover=EvidenceStatus.PASS,
            complexity=EvidenceStatus.PASS,
            multiple_testing_robustness=EvidenceStatus.NOT_RUN,
            findings=(),
            provenance_artifact_id=artifact("3"),
        )
        self.reward = RewardVector.create(
            run=self.run,
            attempt=self.attempt,
            coverage=1.0,
            ic=0.15,
            rank_ic=0.12,
            lower_quantile_return=-0.01,
            upper_quantile_return=0.02,
            quantile_spread=0.03,
            turnover=0.4,
            complexity=1,
            reviewer_evidence=self.reviewer,
            provenance_artifact_id=artifact("4"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.result = ExperimentResult.create(self.run, self.attempt, self.reward)
        def review_ref(kind: str, identity: str) -> ReviewEvidenceRef:
            return ReviewEvidenceRef(
                "round5-p-canonical-session",
                kind,
                identity,
                identity.rsplit("_", 1)[-1],
            )

        target_refs = (
            review_ref("FactorEvaluation", self.evaluation.factor_evaluation_id),
            review_ref("DatasetVersion", self.dataset.dataset_version_id),
            review_ref("ExperimentResult", self.result.experiment_result_id),
            review_ref("RewardVector", self.reward.reward_vector_id),
        )
        scope = ResearchReviewScope.create(
            session_id="round5-p-canonical-session",
            target_refs=target_refs,
            evidence_records=tuple(
                ReviewEvidenceRecord(
                    ref,
                    ValidationState.PASSED,
                    PRE_ALPHA_CEILING,
                    (),
                )
                for ref in target_refs
            ),
        )
        rule = ReviewRuleDefinition("P-C-EXACT-CHAIN", "1", "binding", True, "Exact factor evaluation evidence chain")
        ruleset = ReviewerRuleSet.create("round5-p-evidence/1", (rule,))
        check = DeterministicReviewCheck.create(
            rule=rule,
            outcome=ReviewOutcome.PASS,
            severity=ReviewSeverity.INFO,
            title="Exact chain resolved",
            explanation="All canonical owners and bindings were resolved.",
            remediation_suggestion="Re-run the canonical resolver when any identity changes.",
            evidence_refs=target_refs,
        )
        self.review_report = ResearchReviewReport.create(scope=scope, rule_set=ruleset, checks=(check,))
        self.objects = (
            self.definition,
            self.materialization,
            self.evaluation,
            self.dataset,
            self.label,
            self.split,
            self.experiment,
            self.run,
            self.attempt,
            self.result,
            self.reward,
            self.reviewer,
            self.review_report,
        )
        self.artifacts = {
            self.materialization.output_artifact_id,
            self.materialization.provenance_artifact_id,
            self.evaluation.evaluation_provenance_artifact_id,
            self.dataset.dataset_artifact_id,
            self.dataset.provenance_artifact_id,
            *self.run.input_artifact_ids,
            self.run.run_provenance_artifact_id,
            *self.attempt.evidence_artifact_ids,
            self.result.result_artifact_id,
            self.reward.provenance_artifact_id,
            self.reviewer.provenance_artifact_id,
        }
        self.request = EvaluationEvidence(
            evaluation_ref=self.evaluation.factor_evaluation_id,
            factor_definition_version_id=self.definition.factor_definition_version_id,
            feature_materialization_ref=self.materialization.feature_materialization_id,
            dataset_version_ref=self.dataset.dataset_version_id,
            label_spec_ref=self.label.label_spec_id,
            split_spec_ref=self.split.split_spec_id,
            experiment_version_ref=self.experiment.experiment_version_id,
            experiment_run_ref=self.run.experiment_run_id,
            experiment_attempt_ref=self.attempt.experiment_attempt_id,
            experiment_result_ref=self.result.experiment_result_id,
            reward_vector_ref=self.reward.reward_vector_id,
            reviewer_evidence_ref=self.reviewer.reviewer_evidence_id,
            review_report_ref=self.review_report.review_report_id,
            evaluation_context_ref=evaluation_context_ref(self.evaluation),
            snapshot_ref=self.evaluation.context.snapshot_id,
            universe_ref=self.evaluation.context.universe_version_id,
            evaluation_period_ref=self.split.split_spec_id,
            evaluation_policy_ref=self.experiment.experiment_version_id,
            result_refs=tuple(sorted((self.result.experiment_result_id, self.result.result_artifact_id, self.reward.reward_vector_id))),
            reviewer_refs=tuple(sorted((self.reviewer.reviewer_evidence_id, self.review_report.review_report_id))),
            provenance_refs=tuple(sorted({
                self.materialization.provenance_artifact_id,
                self.evaluation.evaluation_provenance_artifact_id,
                self.dataset.provenance_artifact_id,
                self.run.run_provenance_artifact_id,
                self.reward.provenance_artifact_id,
                self.reviewer.provenance_artifact_id,
                *self.attempt.evidence_artifact_ids,
            })),
        )

    def resolver(self, *, objects: tuple[object, ...] | None = None, artifacts: set[str] | None = None):
        return CanonicalEvaluationEvidenceResolver(
            CanonicalSource(self.objects if objects is None else objects, self.artifacts if artifacts is None else artifacts)
        )

    def test_canonical_valid_chain_yields_contextual_evaluated_state(self) -> None:
        library = FactorLibraryService(
            snapshot=FactorCatalogSnapshotVersion.create((self.asset,)),
            assets=(self.asset,),
            definitions=(self.definition,),
            formula_documents=(self.document,),
            evaluations=(self.request,),
            evidence_resolver=self.resolver(),
        )
        detail = library.read(self.asset.asset_key)
        explanation = library.explain_evidence(self.asset.asset_key)
        self.assertEqual(detail.evaluation_status, "EVALUATED_IN_EXACT_CONTEXTS")
        self.assertEqual(explanation.exact_evaluation_refs, (self.evaluation.factor_evaluation_id,))
        self.assertEqual(detail.contextual_metrics[0]["ic"], 0.15)
        self.assertEqual(detail.exact_evaluation_contexts[0]["universe_version_id"], "universe:canonical")
        self.assertEqual(detail.exact_evaluation_contexts[0]["horizon_observations"], 1)

    def test_fabricated_refs_and_context_are_rejected(self) -> None:
        mutations = (
            {"result_refs": (artifact("9"),)},
            {"reviewer_refs": ("rve_sha256_" + "9" * 64,)},
            {"review_report_ref": "rrp_sha256_" + "9" * 64},
            {"provenance_refs": (artifact("9"),)},
            {"factor_definition_version_id": "fdv_sha256_" + "9" * 64},
            {"evaluation_ref": "fev_sha256_" + "9" * 64},
            {"dataset_version_ref": "dsv_sha256_" + "9" * 64},
            {"universe_ref": "universe:wrong"},
            {"evaluation_context_ref": "fectx_sha256_" + "9" * 64},
            {"evaluation_period_ref": "spl_sha256_" + "9" * 64},
            {"evaluation_policy_ref": "expv_sha256_" + "9" * 64},
        )
        for changes in mutations:
            with self.subTest(changes=changes):
                with self.assertRaises(FactorEvidenceBindingError):
                    self.resolver().resolve(replace(self.request, **changes))

    def test_exact_shaped_hash_without_canonical_owner_does_not_confer_trust(self) -> None:
        without_result = tuple(value for value in self.objects if value is not self.result)
        with self.assertRaisesRegex(FactorEvidenceBindingError, "canonical owner"):
            self.resolver(objects=without_result).resolve(self.request)

    def test_broken_owner_relations_and_artifact_resolution_fail_closed(self) -> None:
        wrong_run = replace(self.run, factor_evaluation_id="fev_sha256_" + "9" * 64)
        objects = tuple(wrong_run if value is self.run else value for value in self.objects)
        with self.assertRaises(FactorEvidenceBindingError):
            self.resolver(objects=objects).resolve(self.request)
        missing = set(self.artifacts)
        missing.remove(self.result.result_artifact_id)
        with self.assertRaisesRegex(FactorEvidenceBindingError, "Artifact resolution failed"):
            self.resolver(artifacts=missing).resolve(self.request)

    def test_missing_metric_is_unavailable_never_zero(self) -> None:
        missing_ic = replace(self.reward, ic=None)
        objects = tuple(missing_ic if value is self.reward else value for value in self.objects)
        with self.assertRaisesRegex(FactorEvidenceBindingError, "metric ic is unavailable"):
            self.resolver(objects=objects).resolve(self.request)


if __name__ == "__main__":
    unittest.main()
