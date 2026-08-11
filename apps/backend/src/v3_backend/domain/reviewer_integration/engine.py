from __future__ import annotations

from collections.abc import Callable

from v3_backend.contracts.common.truth_admission import (
    AdmissionState,
    TruthState,
    ValidationState,
)

from .model import (
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


DEFAULT_REVIEW_RULES = (
    ReviewRuleDefinition("O-001", "1.0.0", "EVIDENCE", True, "Evidence must remain inside one exact Research Session."),
    ReviewRuleDefinition("O-002", "1.0.0", "EVIDENCE", True, "IDs, hashes, lineage, provenance, and loaded-scope membership must be exact."),
    ReviewRuleDefinition("O-003", "1.0.0", "EVIDENCE", True, "Validation NOT_RUN must remain visible and validation failures must surface."),
    ReviewRuleDefinition("O-004", "1.0.0", "TRUTH", True, "Review output cannot promote source Truth or Admission."),
    ReviewRuleDefinition("O-010", "1.0.0", "DATASET", True, "Dataset split, purge, and embargo evidence must be present and exactly bound."),
    ReviewRuleDefinition("O-011", "1.0.0", "DATASET", True, "Dataset and FactorEvaluation membership must be exact."),
    ReviewRuleDefinition("O-012", "1.0.0", "EXPERIMENT", True, "Experiment, Run, Attempt, Dataset, and FactorEvaluation bindings must be exact."),
    ReviewRuleDefinition("O-020", "1.0.0", "MODEL", True, "TrainingRequest, TrainingEvidence, Artifact, ModelVersion, and Dataset bindings must be exact."),
    ReviewRuleDefinition("O-021", "1.0.0", "PREDICTION", True, "PredictionRequest and PredictionArtifact must bind the exact model, dataset, and artifact."),
    ReviewRuleDefinition("O-030", "1.0.0", "STRATEGY", True, "Strategy evaluation period and knowledge cutoff evidence must be present."),
    ReviewRuleDefinition("O-031", "1.0.0", "PORTFOLIO", True, "PortfolioIntent semantic policy and target effective timing must be exact."),
    ReviewRuleDefinition("O-032", "1.0.0", "RISK", True, "Risk policy, report, receipt, and adjusted weights must bind the exact target."),
    ReviewRuleDefinition("O-040", "1.0.0", "BACKTEST", True, "Backtest schedule, execution timing, costs, and RunSpec-to-Result lineage must be exact."),
    ReviewRuleDefinition("O-050", "1.0.0", "PIT", True, "PIT PASS requires exact time, period/split, purge/embargo, and source truth evidence."),
    ReviewRuleDefinition("O-060", "1.0.0", "ROBUSTNESS", False, "Overfitting and robustness require formal statistical evidence."),
)

DEFAULT_REVIEWER_RULE_SET = ReviewerRuleSet.create("v3.reviewer-integration/1", DEFAULT_REVIEW_RULES)


def _result(
    rule: ReviewRuleDefinition,
    outcome: ReviewOutcome,
    title: str,
    explanation: str,
    remediation: str,
    refs: tuple[ReviewEvidenceRef, ...] = (),
    severity: ReviewSeverity | None = None,
) -> DeterministicReviewCheck:
    if severity is None:
        severity = ReviewSeverity.BLOCKING if outcome is ReviewOutcome.BLOCKED else ReviewSeverity.WARNING if outcome is ReviewOutcome.FINDING else ReviewSeverity.INFO
    exact_refs = tuple({value.exact_key: value for value in refs}.values())
    return DeterministicReviewCheck.create(
        rule=rule,
        outcome=outcome,
        severity=severity,
        title=title,
        explanation=explanation,
        remediation_suggestion=remediation,
        evidence_refs=exact_refs,
    )


def _all_refs(scope: ResearchReviewScope) -> tuple[ReviewEvidenceRef, ...]:
    return tuple(value.ref for value in scope.evidence_records)


def _check_session(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    refs = (*scope.target_refs, *_all_refs(scope))
    cross = tuple(
        value
        for value in refs
        if value.session_id != scope.session_id
    ) + tuple(
        binding.target
        for record in scope.evidence_records
        for binding in record.bindings
        if binding.target.session_id != scope.session_id
    )
    if cross:
        return _result(rule, ReviewOutcome.BLOCKED, "Cross-session evidence rejected", "At least one target, record, or exact binding belongs to a different Research Session.", "Build a new review scope from evidence explicitly linked to one session.", tuple(cross))
    return _result(rule, ReviewOutcome.PASS, "Research Session scope is exact", "All loaded targets, evidence, and bindings belong to the requested session.", "No remediation required.", tuple(refs))


def _check_lineage(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    if not scope.evidence_records:
        return _result(rule, ReviewOutcome.NOT_RUN, "Exact lineage not run", "No evidence records were loaded, so exact lineage cannot be proven.", "Load exact content-addressed evidence records.")
    records = {value.ref.exact_key: value for value in scope.evidence_records}
    target_keys = {value.exact_key for value in scope.target_refs}
    referenced = {binding.target.exact_key for record in scope.evidence_records for binding in record.bindings} | {value.exact_key for record in scope.evidence_records for value in record.provenance_refs}
    invalid: list[ReviewEvidenceRef] = []
    for record in scope.evidence_records:
        if not record.ref.id_hash_matches:
            invalid.append(record.ref)
        for value in (*record.provenance_refs, *(binding.target for binding in record.bindings)):
            if value.exact_key not in records or not value.id_hash_matches:
                invalid.append(value)
        if record.ref.exact_key not in target_keys and record.ref.exact_key not in referenced and not record.bindings:
            invalid.append(record.ref)
    for target in scope.target_refs:
        if target.exact_key not in records or not target.id_hash_matches:
            invalid.append(target)
    if invalid:
        refs = tuple({value.exact_key: value for value in invalid}.values())
        return _result(rule, ReviewOutcome.FINDING, "Exact lineage mismatch or orphan evidence", "An ID/hash pair is inconsistent, a target is absent, or a binding/provenance reference is not in the loaded exact scope.", "Load the exact object/hash pair and rebuild the immutable report; never repair history in place.", refs)
    return _result(rule, ReviewOutcome.PASS, "Exact lineage is complete within loaded scope", "Every target, ID/hash pair, binding, and provenance reference resolves exactly in the loaded scope.", "No remediation required.", _all_refs(scope))


def _check_validation(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    if not scope.evidence_records:
        return _result(rule, ReviewOutcome.NOT_RUN, "Validation state not run", "No evidence records were loaded.", "Load validation-bearing evidence.")
    failed = tuple(value.ref for value in scope.evidence_records if value.validation_state is ValidationState.FAILED)
    if failed:
        return _result(rule, ReviewOutcome.FINDING, "Validation failures present", "At least one exact source evidence record has validation_state=FAILED.", "Create new validated evidence; do not mutate or waive the failed record.", failed)
    not_run = tuple(value.ref for value in scope.evidence_records if value.validation_state is ValidationState.NOT_RUN)
    if not_run:
        return _result(rule, ReviewOutcome.NOT_RUN, "Validation remains NOT_RUN", "At least one exact source evidence record has validation_state=NOT_RUN; it is not converted to PASS.", "Run the canonical validation owner and re-review the new evidence.", not_run)
    return _result(rule, ReviewOutcome.PASS, "Loaded validation states are PASSED", "All loaded evidence records have canonical validation_state=PASSED.", "No remediation required.", _all_refs(scope))


def _check_truth(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    if not scope.evidence_records:
        return _result(rule, ReviewOutcome.NOT_RUN, "Truth and Admission not reviewable", "No canonical source truth is loaded.", "Load exact source Truth/Admission evidence.")
    insufficient = tuple(
        value.ref
        for value in scope.evidence_records
        if value.truth_admission.truth is not TruthState.FORMAL
        or value.truth_admission.admission is not AdmissionState.FORMAL_ADMITTED
    )
    if insufficient:
        return _result(rule, ReviewOutcome.FINDING, "Source Truth or Admission is insufficient", "One or more source records are below FORMAL/FORMAL_ADMITTED. The review report preserves the meet of those ceilings.", "Use the independent canonical owner to produce new admitted evidence; Reviewer cannot admit or publish.", insufficient)
    return _result(rule, ReviewOutcome.PASS, "Source Truth and Admission are sufficient within scope", "All loaded sources are FORMAL/FORMAL_ADMITTED; the Reviewer still grants no admission authority.", "No remediation required.", _all_refs(scope))


def _binding_check(
    rule: ReviewRuleDefinition,
    scope: ResearchReviewScope,
    requirements: tuple[tuple[str, str, str], ...],
    title: str,
) -> DeterministicReviewCheck:
    applicable_kinds = {kind for requirement in requirements for kind in (requirement[0], requirement[2])}
    applicable = tuple(value for value in scope.evidence_records if value.ref.object_kind in applicable_kinds)
    if not applicable:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, f"{title} not applicable", "No related canonical objects are in the loaded scope.", "No remediation required.")
    failures: list[ReviewEvidenceRef] = []
    for source_kind, relation, target_kind in requirements:
        sources = scope.records_of_kind(source_kind)
        targets = {value.ref.exact_key for value in scope.records_of_kind(target_kind)}
        if not sources:
            continue
        for source in sources:
            bound = source.bindings_for(relation)
            if not bound or any(value.object_kind != target_kind or value.exact_key not in targets for value in bound):
                failures.append(source.ref)
                failures.extend(bound)
    if failures:
        refs = tuple({value.exact_key: value for value in failures}.values())
        return _result(rule, ReviewOutcome.FINDING, f"{title} mismatch", "A required exact object binding is missing, points to the wrong kind, or does not resolve to the loaded exact ID/hash.", "Produce a new canonical object with exact bindings and re-review it.", refs)
    return _result(rule, ReviewOutcome.PASS, f"{title} bindings are exact", "Every applicable binding resolves to the exact loaded object and content hash.", "No remediation required.", tuple(value.ref for value in applicable))


def _check_split(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    datasets = scope.records_of_kind("DatasetVersion")
    if not datasets:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "Dataset split review not applicable", "No DatasetVersion is in scope.", "No remediation required.")
    splits = scope.records_of_kind("SplitSpec")
    if not splits:
        return _result(rule, ReviewOutcome.NOT_RUN, "Split, purge, and embargo evidence not run", "A DatasetVersion is loaded but no exact SplitSpec evidence is available.", "Load the exact SplitSpec and its purge/embargo facts.", tuple(value.ref for value in datasets))
    required_facts = {"train_period", "validation_period", "test_period", "purge_observations", "embargo_observations"}
    missing = tuple(value.ref for value in splits if not required_facts.issubset(value.fact_map()))
    if missing:
        return _result(rule, ReviewOutcome.NOT_RUN, "Split semantics are incomplete", "The loaded SplitSpec does not expose all period, purge, and embargo evidence.", "Add canonical split evidence and re-review; do not infer missing semantics.", missing)
    return _binding_check(rule, scope, (("DatasetVersion", "split_spec", "SplitSpec"),), "Dataset split")


def _check_strategy(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    strategies = scope.records_of_kind("StrategyEvaluation")
    if not strategies:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "Strategy period review not applicable", "No StrategyEvaluation is in scope.", "No remediation required.")
    required = {"period_start", "period_end", "knowledge_cutoff"}
    missing = tuple(value.ref for value in strategies if not required.issubset(value.fact_map()))
    if missing:
        return _result(rule, ReviewOutcome.NOT_RUN, "Strategy period or knowledge cutoff is insufficient", "Exact period/knowledge-cutoff facts are missing.", "Load canonical StrategyEvaluation binding evidence.", missing)
    return _result(rule, ReviewOutcome.PASS, "Strategy period and knowledge cutoff are evidenced", "Every loaded StrategyEvaluation exposes exact period and knowledge-cutoff facts.", "No remediation required.", tuple(value.ref for value in strategies))


def _check_target(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    targets = scope.records_of_kind("TargetWeightVector")
    if not targets:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "Target timing review not applicable", "No TargetWeightVector is in scope.", "No remediation required.")
    missing = tuple(value.ref for value in targets if "effective_at" not in value.fact_map())
    if missing:
        return _result(rule, ReviewOutcome.NOT_RUN, "Target timing evidence is insufficient", "TargetWeightVector effective_at is absent.", "Load exact target timing evidence.", missing)
    policy = _binding_check(rule, scope, (("PortfolioIntent", "semantic_policy", "SemanticPolicy"), ("TargetWeightVector", "portfolio_intent", "PortfolioIntent")), "Portfolio policy and target timing")
    return policy


def _check_pit(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    applicable = tuple(value for value in scope.evidence_records if value.ref.object_kind in {"Snapshot", "DatasetVersion", "SplitSpec", "StrategyEvaluation", "TargetWeightVector"})
    if not applicable:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "PIT review not applicable", "No PIT-bearing research evidence is in scope.", "No remediation required.")
    facts = {name for record in applicable for name in record.fact_map()}
    required = {"available_time", "knowledge_cutoff", "period_start", "period_end", "purge_observations", "embargo_observations", "source_truth"}
    if not required.issubset(facts):
        return _result(rule, ReviewOutcome.NOT_RUN, "PIT evidence is insufficient", "Exact available-time, knowledge-cutoff, period/split, purge/embargo, and source-truth evidence is not all present. PRE_ALPHA alone is not PIT PASS.", "Load the missing canonical PIT evidence and re-review.", tuple(value.ref for value in applicable))
    return _result(rule, ReviewOutcome.PASS, "PIT evidence is present within checked scope", "The required exact PIT facts are present; this contract check does not recompute a financial engine.", "No remediation required.", tuple(value.ref for value in applicable))


def _check_backtest(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    specs = scope.records_of_kind("BacktestRunSpec")
    results = scope.records_of_kind("BacktestRunResult")
    if not specs and not results:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "Backtest review not applicable", "No Backtest RunSpec/Result is in scope.", "No remediation required.")
    required = {"risk_adjusted_only", "execution_timing_profile", "cost_policy", "market_cost_coverage"}
    missing = tuple(value.ref for value in specs if not required.issubset(value.fact_map()))
    if not specs or missing:
        refs = missing or tuple(value.ref for value in results)
        return _result(rule, ReviewOutcome.NOT_RUN, "Backtest contract evidence is incomplete", "The RiskAdjusted-only schedule or execution/cost evidence is absent.", "Load exact BacktestRunSpec contract evidence.", refs)
    if any(value.fact_map()["risk_adjusted_only"] != "true" for value in specs):
        return _result(rule, ReviewOutcome.FINDING, "Backtest schedule is not RiskAdjusted-only", "The RunSpec declares a non-RiskAdjusted schedule.", "Create a new RunSpec from exact RiskAdjustedWeightVector evidence.", tuple(value.ref for value in specs))
    return _binding_check(rule, scope, (("BacktestRunSpec", "scheduled_risk_adjusted", "RiskAdjustedWeightVector"), ("BacktestRunResult", "run_spec", "BacktestRunSpec")), "Backtest RunSpec and Result")


def _check_robustness(rule: ReviewRuleDefinition, scope: ResearchReviewScope) -> DeterministicReviewCheck:
    refs = tuple(value.ref for value in scope.evidence_records if value.ref.object_kind in {"ExperimentResult", "ReviewerEvidence", "RewardVector"})
    return _result(rule, ReviewOutcome.NOT_RUN, "Overfitting and robustness remain non-deterministic", "Current main does not provide formal parameter-sensitivity, regime-stability, or cost-sensitivity evidence in this review scope. No OVERFITTING_PASS/FAIL or ROBUSTNESS_PASS/FAIL is emitted.", "Reviewer Agent may record a non-canonical concern; produce formal statistical evidence before deterministic review.", refs)


RuleFunction = Callable[[ReviewRuleDefinition, ResearchReviewScope], DeterministicReviewCheck]

_RULE_FUNCTIONS: dict[str, RuleFunction] = {
    "O-001": _check_session,
    "O-002": _check_lineage,
    "O-003": _check_validation,
    "O-004": _check_truth,
    "O-010": _check_split,
    "O-011": lambda rule, scope: _binding_check(rule, scope, (("DatasetVersion", "factor_evaluation", "FactorEvaluation"),), "Dataset membership"),
    "O-012": lambda rule, scope: _binding_check(rule, scope, (("ExperimentRun", "dataset", "DatasetVersion"), ("ExperimentRun", "factor_evaluation", "FactorEvaluation"), ("ExperimentAttempt", "experiment_run", "ExperimentRun")), "Experiment Run and Attempt"),
    "O-020": lambda rule, scope: _binding_check(rule, scope, (("TrainingEvidence", "training_request", "ModelTrainingRequest"), ("TrainingEvidence", "dataset", "DatasetVersion"), ("TrainingEvidence", "model_artifact", "ModelArtifact"), ("ModelVersion", "training_request", "ModelTrainingRequest"), ("ModelVersion", "training_evidence", "TrainingEvidence"), ("ModelVersion", "model_artifact", "ModelArtifact")), "Model training"),
    "O-021": lambda rule, scope: _binding_check(rule, scope, (("ModelPredictionRequest", "model_version", "ModelVersion"), ("ModelPredictionRequest", "model_artifact", "ModelArtifact"), ("ModelPredictionRequest", "dataset", "DatasetVersion"), ("PredictionArtifact", "prediction_request", "ModelPredictionRequest"), ("PredictionArtifact", "model_version", "ModelVersion"), ("PredictionArtifact", "dataset", "DatasetVersion")), "Prediction"),
    "O-030": _check_strategy,
    "O-031": _check_target,
    "O-032": lambda rule, scope: _binding_check(rule, scope, (("RiskDecisionReport", "source_target", "TargetWeightVector"), ("RiskApplicationReceipt", "source_target", "TargetWeightVector"), ("RiskAdjustedWeightVector", "source_target", "TargetWeightVector")), "Risk target"),
    "O-040": _check_backtest,
    "O-050": _check_pit,
    "O-060": _check_robustness,
}


def review_research_scope(
    scope: ResearchReviewScope,
    rule_set: ReviewerRuleSet = DEFAULT_REVIEWER_RULE_SET,
) -> ResearchReviewReport:
    checks = tuple(_RULE_FUNCTIONS[rule.rule_id](rule, scope) for rule in rule_set.rules)
    return ResearchReviewReport.create(scope=scope, rule_set=rule_set, checks=checks)


__all__ = ["DEFAULT_REVIEWER_RULE_SET", "DEFAULT_REVIEW_RULES", "review_research_scope"]
