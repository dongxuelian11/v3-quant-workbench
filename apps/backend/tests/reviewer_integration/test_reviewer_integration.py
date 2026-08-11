from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    ValidationState,
)
from v3_backend.domain.reviewer_integration import (
    DEFAULT_REVIEWER_RULE_SET,
    ExactEvidenceBinding,
    FindingLifecycleLink,
    FindingRelation,
    OverallReviewStatus,
    ResearchReviewScope,
    ReviewEvidenceRecord,
    ReviewEvidenceRef,
    ReviewerAgentDraft,
    ReviewerRuleSet,
    ReviewFact,
    ReviewOutcome,
    review_research_scope,
    review_scope_from_round3_bundle,
)
from v3_backend.adapters.round3_evidence.development_runtime import build_development_bundle


SESSION = "research-session-track-o-001"


def ref(kind: str, digit: str, *, session: str = SESSION) -> ReviewEvidenceRef:
    digest = digit * 64
    prefix = "".join(character.lower() for character in kind if character.isalnum())[:8]
    return ReviewEvidenceRef(session, kind, f"{prefix}_sha256_{digest}", digest)


def binding(relation: str, target: ReviewEvidenceRef) -> ExactEvidenceBinding:
    return ExactEvidenceBinding(relation, target)


def facts(**values: str) -> tuple[ReviewFact, ...]:
    return tuple(ReviewFact(name, value) for name, value in values.items())


def record(
    evidence_ref: ReviewEvidenceRef,
    *,
    bindings: tuple[ExactEvidenceBinding, ...] = (),
    facts_value: tuple[ReviewFact, ...] = (),
    validation: ValidationState = ValidationState.PASSED,
    truth=FORMAL_ADMITTED_CEILING,
    provenance: tuple[ReviewEvidenceRef, ...] = (),
) -> ReviewEvidenceRecord:
    return ReviewEvidenceRecord(
        evidence_ref,
        validation,
        truth,
        provenance,
        bindings,
        facts_value,
    )


def complete_scope() -> ResearchReviewScope:
    snapshot = ref("Snapshot", "1")
    factor = ref("FactorEvaluation", "2")
    split = ref("SplitSpec", "3")
    dataset = ref("DatasetVersion", "4")
    run = ref("ExperimentRun", "5")
    attempt = ref("ExperimentAttempt", "6")
    training_request = ref("ModelTrainingRequest", "7")
    model_artifact = ref("ModelArtifact", "8")
    training_evidence = ref("TrainingEvidence", "9")
    model = ref("ModelVersion", "a")
    prediction_request = ref("ModelPredictionRequest", "b")
    prediction = ref("PredictionArtifact", "c")
    strategy = ref("StrategyEvaluation", "d")
    policy = ref("SemanticPolicy", "e")
    intent = ref("PortfolioIntent", "f")
    target = ref("TargetWeightVector", "0")
    report = ref("RiskDecisionReport", "1")
    receipt = ref("RiskApplicationReceipt", "2")
    adjusted = ref("RiskAdjustedWeightVector", "3")
    spec = ref("BacktestRunSpec", "4")
    result = ref("BacktestRunResult", "5")
    records = (
        record(snapshot, facts_value=facts(available_time="2026-01-02T00:00:00Z", source_truth="FORMAL")),
        record(factor, bindings=(binding("snapshot", snapshot),)),
        record(split, facts_value=facts(train_period="1..100", validation_period="110..130", test_period="140..160", period_start="1", period_end="160", purge_observations="9", embargo_observations="9")),
        record(dataset, bindings=(binding("snapshot", snapshot), binding("factor_evaluation", factor), binding("split_spec", split)), facts_value=facts(knowledge_cutoff="2026-01-02T00:00:00Z")),
        record(run, bindings=(binding("dataset", dataset), binding("factor_evaluation", factor))),
        record(attempt, bindings=(binding("experiment_run", run),)),
        record(training_request, bindings=(binding("dataset", dataset),)),
        record(model_artifact, bindings=(binding("training_request", training_request),)),
        record(training_evidence, bindings=(binding("training_request", training_request), binding("dataset", dataset), binding("model_artifact", model_artifact))),
        record(model, bindings=(binding("training_request", training_request), binding("training_evidence", training_evidence), binding("model_artifact", model_artifact), binding("dataset", dataset))),
        record(prediction_request, bindings=(binding("model_version", model), binding("model_artifact", model_artifact), binding("dataset", dataset))),
        record(prediction, bindings=(binding("prediction_request", prediction_request), binding("model_version", model), binding("model_artifact", model_artifact), binding("dataset", dataset))),
        record(strategy, bindings=(binding("dataset", dataset),), facts_value=facts(period_start="2025-01-01", period_end="2025-12-31", knowledge_cutoff="2024-12-31T23:59:59Z")),
        record(policy, bindings=(binding("strategy", strategy),)),
        record(intent, bindings=(binding("semantic_policy", policy), binding("strategy", strategy))),
        record(target, bindings=(binding("portfolio_intent", intent),), facts_value=facts(effective_at="2026-01-05T09:30:00+08:00")),
        record(report, bindings=(binding("source_target", target),)),
        record(receipt, bindings=(binding("source_target", target),)),
        record(adjusted, bindings=(binding("source_target", target), binding("risk_report", report), binding("risk_receipt", receipt))),
        record(spec, bindings=(binding("scheduled_risk_adjusted", adjusted),), facts_value=facts(risk_adjusted_only="true", execution_timing_profile="NEXT_OPEN", cost_policy="A_SHARE_V0", market_cost_coverage="FULL_SCHEDULE")),
        record(result, bindings=(binding("run_spec", spec),)),
    )
    return ResearchReviewScope.create(session_id=SESSION, target_refs=(result,), evidence_records=records)


def with_record(scope: ResearchReviewScope, kind: str, transform) -> ResearchReviewScope:
    values = tuple(transform(value) if value.ref.object_kind == kind else value for value in scope.evidence_records)
    return ResearchReviewScope.create(session_id=scope.session_id, target_refs=scope.target_refs, evidence_records=values)


def check(report, rule_id: str):
    return next(value for value in report.deterministic_checks if value.rule_id == rule_id)


class ReviewerIntegrationTests(unittest.TestCase):
    def test_deterministic_lineage_pass_and_stable_identity(self) -> None:
        first = review_research_scope(complete_scope())
        second = review_research_scope(complete_scope())
        self.assertEqual(first, second)
        self.assertEqual(check(first, "O-002").outcome, ReviewOutcome.PASS)
        self.assertEqual(first.overall_status, OverallReviewStatus.CLEAR_WITHIN_CHECKED_SCOPE)

    def test_missing_lineage_creates_exact_finding(self) -> None:
        scope = complete_scope()
        values = tuple(value for value in scope.evidence_records if value.ref.object_kind != "RiskAdjustedWeightVector")
        report = review_research_scope(ResearchReviewScope.create(session_id=SESSION, target_refs=scope.target_refs, evidence_records=values))
        lineage = check(report, "O-002")
        self.assertEqual(lineage.outcome, ReviewOutcome.FINDING)
        self.assertTrue(lineage.evidence_refs)
        self.assertTrue(any(value.check_id == lineage.check_id and value.review_report_id == report.review_report_id for value in report.findings))

    def test_validation_not_run_remains_not_run_and_prevents_clear(self) -> None:
        scope = with_record(complete_scope(), "DatasetVersion", lambda value: replace(value, validation_state=ValidationState.NOT_RUN))
        report = review_research_scope(scope)
        self.assertEqual(check(report, "O-003").outcome, ReviewOutcome.NOT_RUN)
        self.assertEqual(report.overall_status, OverallReviewStatus.INCOMPLETE_REVIEW)
        self.assertEqual(report.coverage.NOT_RUN, 2)  # validation plus optional robustness

    def test_truth_insufficiency_is_finding_and_cannot_be_promoted(self) -> None:
        scope = with_record(complete_scope(), "PredictionArtifact", lambda value: replace(value, truth_admission=PRE_ALPHA_CEILING))
        report = review_research_scope(scope)
        self.assertEqual(check(report, "O-004").outcome, ReviewOutcome.FINDING)
        self.assertEqual(report.truth_ceiling, PRE_ALPHA_CEILING)

    def test_dataset_membership_mismatch_is_finding(self) -> None:
        wrong = ref("FactorEvaluation", "9")
        scope = with_record(complete_scope(), "DatasetVersion", lambda value: replace(value, bindings=tuple(binding("factor_evaluation", wrong) if item.relation == "factor_evaluation" else item for item in value.bindings)))
        self.assertEqual(check(review_research_scope(scope), "O-011").outcome, ReviewOutcome.FINDING)

    def test_experiment_attempt_mismatch_is_finding(self) -> None:
        wrong = ref("ExperimentRun", "9")
        scope = with_record(complete_scope(), "ExperimentAttempt", lambda value: replace(value, bindings=(binding("experiment_run", wrong),)))
        self.assertEqual(check(review_research_scope(scope), "O-012").outcome, ReviewOutcome.FINDING)

    def test_model_training_mismatch_is_finding(self) -> None:
        wrong = ref("ModelTrainingRequest", "0")
        scope = with_record(complete_scope(), "TrainingEvidence", lambda value: replace(value, bindings=tuple(binding("training_request", wrong) if item.relation == "training_request" else item for item in value.bindings)))
        self.assertEqual(check(review_research_scope(scope), "O-020").outcome, ReviewOutcome.FINDING)

    def test_prediction_mismatch_is_finding(self) -> None:
        wrong = ref("ModelVersion", "0")
        scope = with_record(complete_scope(), "PredictionArtifact", lambda value: replace(value, bindings=tuple(binding("model_version", wrong) if item.relation == "model_version" else item for item in value.bindings)))
        self.assertEqual(check(review_research_scope(scope), "O-021").outcome, ReviewOutcome.FINDING)

    def test_target_timing_absence_is_not_run(self) -> None:
        scope = with_record(complete_scope(), "TargetWeightVector", lambda value: replace(value, facts=()))
        self.assertEqual(check(review_research_scope(scope), "O-031").outcome, ReviewOutcome.NOT_RUN)

    def test_risk_receipt_mismatch_is_finding(self) -> None:
        wrong = ref("TargetWeightVector", "9")
        scope = with_record(complete_scope(), "RiskApplicationReceipt", lambda value: replace(value, bindings=(binding("source_target", wrong),)))
        self.assertEqual(check(review_research_scope(scope), "O-032").outcome, ReviewOutcome.FINDING)

    def test_backtest_runspec_result_mismatch_is_finding(self) -> None:
        wrong = ref("BacktestRunSpec", "9")
        scope = with_record(complete_scope(), "BacktestRunResult", lambda value: replace(value, bindings=(binding("run_spec", wrong),)))
        self.assertEqual(check(review_research_scope(scope), "O-040").outcome, ReviewOutcome.FINDING)

    def test_agent_narrative_cannot_change_layer_a(self) -> None:
        report = review_research_scope(complete_scope())
        first = ReviewerAgentDraft.create(report=report, summary="Review summary one.", prioritized_risks=("Monitor the research boundary.",), research_suggestions=("Collect additional evidence.",), cited_evidence_refs=(report.source_evidence_refs[0],))
        second = ReviewerAgentDraft.create(report=report, summary="Review summary two.", prioritized_risks=("Different draft ordering.",), research_suggestions=("Run another bounded experiment.",), cited_evidence_refs=(report.source_evidence_refs[0],))
        self.assertNotEqual(first.draft_id, second.draft_id)
        self.assertEqual(first.review_report_id, second.review_report_id)
        self.assertEqual(report, review_research_scope(complete_scope()))

    def test_agent_is_l0_l1_only_and_has_no_authority_surface(self) -> None:
        report = review_research_scope(complete_scope())
        draft = ReviewerAgentDraft.create(report=report, summary="Bounded interpretation.", prioritized_risks=("No canonical risk change.",), research_suggestions=("Re-review new evidence.",), cited_evidence_refs=(report.source_evidence_refs[0],))
        self.assertEqual((draft.permission, draft.authority_status), ("L1_DRAFT", "NON_CANONICAL"))
        for forbidden in ("truth_admission", "admission", "publish", "waive", "execute"):
            self.assertFalse(hasattr(draft, forbidden))

    def test_findings_and_reports_are_immutable(self) -> None:
        scope = with_record(complete_scope(), "PredictionArtifact", lambda value: replace(value, truth_admission=PRE_ALPHA_CEILING))
        report = review_research_scope(scope)
        with self.assertRaises(FrozenInstanceError):
            report.findings[0].title = "mutated"
        with self.assertRaises(FrozenInstanceError):
            report.overall_status = OverallReviewStatus.CLEAR_WITHIN_CHECKED_SCOPE

    def test_rereview_uses_resolves_or_supersedes_link(self) -> None:
        prior_scope = with_record(complete_scope(), "PredictionArtifact", lambda value: replace(value, truth_admission=PRE_ALPHA_CEILING))
        prior = review_research_scope(prior_scope)
        current_scope = with_record(prior_scope, "PredictionArtifact", lambda value: replace(value, truth_admission=FORMAL_ADMITTED_CEILING))
        current = review_research_scope(current_scope)
        link = FindingLifecycleLink.create(relation=FindingRelation.RESOLVES, current_report=current, current_finding=None, prior_report=prior, prior_finding=prior.findings[0])
        self.assertEqual(link.current_review_report_id, current.review_report_id)
        self.assertIsNone(link.current_finding_id)
        self.assertEqual(link.prior_review_report_id, prior.review_report_id)
        self.assertNotEqual(current.review_report_id, prior.review_report_id)

    def test_current_main_round3_bundle_is_consumed_read_only(self) -> None:
        bundle = build_development_bundle()
        before = bundle.to_wire()
        report = review_research_scope(review_scope_from_round3_bundle(bundle))
        self.assertEqual(bundle.to_wire(), before)
        self.assertEqual(check(report, "O-001").outcome, ReviewOutcome.PASS)
        self.assertEqual(check(report, "O-002").outcome, ReviewOutcome.PASS)
        self.assertEqual(check(report, "O-003").outcome, ReviewOutcome.NOT_RUN)
        self.assertEqual(check(report, "O-004").outcome, ReviewOutcome.FINDING)
        self.assertEqual(check(report, "O-040").outcome, ReviewOutcome.NOT_RUN)

    def test_exact_evidence_links_are_report_bound(self) -> None:
        scope = with_record(complete_scope(), "PredictionArtifact", lambda value: replace(value, truth_admission=PRE_ALPHA_CEILING))
        report = review_research_scope(scope)
        loaded = {value.exact_key for value in report.source_evidence_refs}
        for finding in report.findings:
            self.assertEqual(finding.review_report_id, report.review_report_id)
            self.assertTrue(finding.factual_evidence_refs)
            self.assertTrue(all(value.exact_key in loaded for value in finding.factual_evidence_refs))

    def test_cross_session_evidence_is_blocked(self) -> None:
        scope = complete_scope()
        cross = ref("DatasetVersion", "4", session="other-session")
        altered = with_record(scope, "ExperimentRun", lambda value: replace(value, bindings=tuple(binding("dataset", cross) if item.relation == "dataset" else item for item in value.bindings)))
        report = review_research_scope(altered)
        self.assertEqual(check(report, "O-001").outcome, ReviewOutcome.BLOCKED)
        self.assertEqual(report.overall_status, OverallReviewStatus.BLOCKED)

    def test_pit_insufficient_evidence_is_not_run(self) -> None:
        scope = with_record(complete_scope(), "Snapshot", lambda value: replace(value, facts=()))
        self.assertEqual(check(review_research_scope(scope), "O-050").outcome, ReviewOutcome.NOT_RUN)

    def test_overfitting_without_formal_evidence_has_no_deterministic_pass_fail(self) -> None:
        outcome = check(review_research_scope(complete_scope()), "O-060")
        self.assertEqual(outcome.outcome, ReviewOutcome.NOT_RUN)
        self.assertEqual(outcome.severity.value, "INFO")
        self.assertIn("No OVERFITTING_PASS/FAIL", outcome.explanation)

    def test_ruleset_version_changes_report_identity(self) -> None:
        changed = ReviewerRuleSet.create("v3.reviewer-integration/2", DEFAULT_REVIEWER_RULE_SET.rules)
        first = review_research_scope(complete_scope())
        second = review_research_scope(complete_scope(), changed)
        self.assertNotEqual(first.rule_set_id, second.rule_set_id)
        self.assertNotEqual(first.review_report_id, second.review_report_id)
        self.assertEqual(tuple(value.outcome for value in first.deterministic_checks), tuple(value.outcome for value in second.deterministic_checks))


if __name__ == "__main__":
    unittest.main()
