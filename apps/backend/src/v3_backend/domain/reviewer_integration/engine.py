from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import date, datetime, timezone
from types import MappingProxyType

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
    ReviewerRuleSetAuthorityError,
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
V0_REVIEWER_RULE_SET_ID = "rrs_sha256_e4a3dfcf23fd173b8b0c68c9a897a4f16ebb4a74951eb21e7f8bc3b50f2b2860"
if DEFAULT_REVIEWER_RULE_SET.rule_set_id != V0_REVIEWER_RULE_SET_ID:
    raise ReviewerRuleSetAuthorityError(
        "V0_RULESET_IDENTITY_DRIFT",
        "the V3-owned V0 ruleset no longer matches its registered exact identity",
    )


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
    pit_kinds = {
        "Snapshot",
        "DatasetVersion",
        "SplitSpec",
        "StrategyEvaluation",
        "PortfolioIntent",
        "TargetWeightVector",
    }
    applicable = tuple(
        value for value in scope.evidence_records if value.ref.object_kind in pit_kinds
    )
    if not applicable:
        return _result(rule, ReviewOutcome.NOT_APPLICABLE, "PIT review not applicable", "No PIT-bearing research evidence is in scope.", "No remediation required.")

    kinds = {
        kind: scope.records_of_kind(kind)
        for kind in pit_kinds
    }
    if any(len(kinds[kind]) != 1 for kind in pit_kinds):
        return _result(
            rule,
            ReviewOutcome.NOT_RUN,
            "PIT exact chain is unavailable",
            "PIT PASS requires exactly one loaded Snapshot, DatasetVersion, SplitSpec, StrategyEvaluation, PortfolioIntent, and TargetWeightVector chain.",
            "Load one exact bound PIT chain; unrelated record field unions are not evidence.",
            tuple(value.ref for value in applicable),
        )

    snapshot = kinds["Snapshot"][0]
    dataset = kinds["DatasetVersion"][0]
    split = kinds["SplitSpec"][0]
    strategy = kinds["StrategyEvaluation"][0]
    portfolio = kinds["PortfolioIntent"][0]
    target = kinds["TargetWeightVector"][0]
    chain = (snapshot, dataset, split, strategy, portfolio, target)
    exact_relations = (
        (dataset, "snapshot", snapshot),
        (dataset, "split_spec", split),
        (strategy, "dataset", dataset),
        (portfolio, "strategy", strategy),
        (target, "portfolio_intent", portfolio),
    )
    if any(source.bindings_for(relation) != (bound.ref,) for source, relation, bound in exact_relations):
        return _result(
            rule,
            ReviewOutcome.NOT_RUN,
            "PIT exact binding is incomplete",
            "The loaded PIT-bearing records do not form the exact Snapshot -> DatasetVersion/SplitSpec -> StrategyEvaluation -> PortfolioIntent -> TargetWeightVector chain.",
            "Load exact owner-produced bindings; do not combine facts from unrelated records.",
            tuple(value.ref for value in chain),
        )

    if any(
        value.truth_admission.truth is not TruthState.FORMAL
        or value.truth_admission.admission is not AdmissionState.FORMAL_ADMITTED
        for value in chain
    ) or snapshot.fact_map().get("source_truth") != "FORMAL":
        return _result(
            rule,
            ReviewOutcome.NOT_RUN,
            "PIT source truth is insufficient",
            "The exact chain is below FORMAL/FORMAL_ADMITTED or source_truth is not the allowed FORMAL value. PRE_ALPHA alone never proves PIT.",
            "Produce new owner-admitted temporal evidence and re-review it.",
            tuple(value.ref for value in chain),
        )

    snapshot_facts = snapshot.fact_map()
    dataset_facts = dataset.fact_map()
    split_facts = split.fact_map()
    strategy_facts = strategy.fact_map()
    target_facts = target.fact_map()
    try:
        available_time = _parse_aware_datetime(snapshot_facts["available_time"])
        dataset_cutoff = _parse_aware_datetime(dataset_facts["knowledge_cutoff"])
        strategy_cutoff = _parse_aware_datetime(strategy_facts["knowledge_cutoff"])
        target_time_value = target_facts.get("decision_time")
        if target_time_value is None:
            target_time_value = target_facts["effective_at"]
        target_time = _parse_aware_datetime(target_time_value)
        split_start, split_end = _parse_period_bounds(split_facts)
        strategy_start, strategy_end = _parse_period_bounds(strategy_facts)
        purge = _parse_nonnegative_integer(split_facts["purge_observations"])
        embargo = _parse_nonnegative_integer(split_facts["embargo_observations"])
    except (KeyError, TypeError, ValueError):
        return _result(
            rule,
            ReviewOutcome.NOT_RUN,
            "PIT typed temporal evidence is insufficient",
            "A required datetime, period, purge, embargo, or owner timing fact is missing, unparseable, incomparable, or lacks an explicit timezone.",
            "Load typed and parseable exact temporal evidence; invalid strings cannot PASS.",
            tuple(value.ref for value in chain),
        )

    contradictions: list[ReviewEvidenceRef] = []
    if available_time > dataset_cutoff or available_time > strategy_cutoff:
        contradictions.extend((snapshot.ref, dataset.ref, strategy.ref))
    if (
        available_time > target_time
        or dataset_cutoff > target_time
        or strategy_cutoff > target_time
    ):
        contradictions.extend((snapshot.ref, dataset.ref, strategy.ref, target.ref))
    if split_start > split_end:
        contradictions.append(split.ref)
    if strategy_start > strategy_end:
        contradictions.append(strategy.ref)
    if purge < 0 or embargo < 0:
        contradictions.append(split.ref)
    if contradictions:
        return _result(
            rule,
            ReviewOutcome.FINDING,
            "PIT temporal contradiction",
            "The exact bound chain deterministically contradicts available-time/knowledge-cutoff/target timing, period ordering, or non-negative purge/embargo semantics.",
            "Produce new owner-resolved evidence; Reviewer cannot waive or repair the contradiction.",
            tuple(contradictions),
        )
    return _result(
        rule,
        ReviewOutcome.PASS,
        "PIT relational proof is complete",
        "One exact bound chain has FORMAL truth, timezone-aware temporal facts, ordered periods, non-negative purge/embargo, and verified available-time <= knowledge-cutoff/target timing relations.",
        "No remediation required.",
        tuple(value.ref for value in chain),
    )


def _parse_aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must have an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _parse_period_bounds(facts: Mapping[str, str]) -> tuple[int | date, int | date]:
    start = facts["period_start"]
    end = facts["period_end"]
    try:
        return int(start), int(end)
    except ValueError:
        return date.fromisoformat(start), date.fromisoformat(end)


def _parse_nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if str(parsed) != value and not (value.startswith("+") and str(parsed) == value[1:]):
        raise ValueError("integer fact must use an exact base-10 representation")
    return parsed


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


def validate_reviewer_rule_set_registry(
    registry: Mapping[str, ReviewerRuleSet],
    executable_rule_ids: Collection[str] | None = None,
) -> None:
    """Validate registry identity and exact executable coverage without admitting it."""

    if not registry:
        raise ReviewerRuleSetAuthorityError(
            "EMPTY_RULESET_REGISTRY", "at least one V3-owned ruleset is required"
        )
    executable = set(_RULE_FUNCTIONS if executable_rule_ids is None else executable_rule_ids)
    for registered_id, rule_set in registry.items():
        rule_set.assert_canonical()
        if registered_id != rule_set.rule_set_id:
            raise ReviewerRuleSetAuthorityError(
                "REGISTRY_ID_MISMATCH", "registry key must equal canonical rule_set_id"
            )
        rule_ids = {value.rule_id for value in rule_set.rules}
        if rule_ids != executable:
            raise ReviewerRuleSetAuthorityError(
                "RULE_EXECUTABLE_COVERAGE_MISMATCH",
                "registered rule IDs and executable rule IDs must have exact coverage",
            )


REGISTERED_REVIEWER_RULE_SETS: Mapping[str, ReviewerRuleSet] = MappingProxyType(
    {V0_REVIEWER_RULE_SET_ID: DEFAULT_REVIEWER_RULE_SET}
)
validate_reviewer_rule_set_registry(REGISTERED_REVIEWER_RULE_SETS)


def review_research_scope(
    scope: ResearchReviewScope,
    rule_set: ReviewerRuleSet = DEFAULT_REVIEWER_RULE_SET,
) -> ResearchReviewReport:
    rule_set.assert_canonical()
    registered = REGISTERED_REVIEWER_RULE_SETS.get(rule_set.rule_set_id)
    if registered is None or registered != rule_set:
        raise ReviewerRuleSetAuthorityError(
            "UNREGISTERED_RULESET",
            "review execution is limited to exact V3-owned registered rulesets",
        )
    validate_reviewer_rule_set_registry(REGISTERED_REVIEWER_RULE_SETS)
    checks = tuple(
        _RULE_FUNCTIONS[rule.rule_id](rule, scope) for rule in registered.rules
    )
    return ResearchReviewReport.create(scope=scope, rule_set=registered, checks=checks)


__all__ = [
    "DEFAULT_REVIEWER_RULE_SET",
    "DEFAULT_REVIEW_RULES",
    "REGISTERED_REVIEWER_RULE_SETS",
    "V0_REVIEWER_RULE_SET_ID",
    "review_research_scope",
    "validate_reviewer_rule_set_registry",
]
