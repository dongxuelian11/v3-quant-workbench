# Reviewer Integration V0

## Authority boundary

Reviewer Integration is an immutable review-evidence layer. It is not a Truth, Admission, execution, waiver, or publication owner.

```text
exact current-main evidence
  -> V3-registered deterministic rules (Layer A)
  -> immutable ResearchReviewReport + ReviewerFinding
  -> optional non-canonical ReviewerAgentDraft (Layer B)
  -> read-only Reviewer UI with exact evidence navigation
```

Layer A has the closed outcomes `PASS`, `FINDING`, `NOT_APPLICABLE`, `NOT_RUN`, and `BLOCKED`. The only V0 execution-authorized ruleset is:

```text
version: v3.reviewer-integration/1
id: rrs_sha256_e4a3dfcf23fd173b8b0c68c9a897a4f16ebb4a74951eb21e7f8bc3b50f2b2860
rules: 15
```

`ReviewerRuleSet.assert_canonical()` recomputes the versioned content digest and verifies the exact ID, content hash, unique rule IDs, and canonical order. The immutable `REGISTERED_REVIEWER_RULE_SETS` registry contains only the exact V0 ruleset. Registry admission also requires exact coverage between registered rule IDs and executable rule functions. A content-addressed but unregistered caller ruleset fails closed with a typed authority error; runtime callers cannot change `required`, rule versions, or execution coverage.

The same exact scope and registered ruleset produce the same check IDs, report ID, findings, coverage, status, and Truth ceiling. Future ruleset versions require an explicit V3 code and registry change.

## Immutable evidence and lifecycle

Each exact evidence reference binds `session_id`, object kind, object ID, and content SHA-256. Each finding binds its deterministic check and exact `review_report_id`; factual evidence references must resolve inside the loaded report scope.

Historical reports and findings are frozen. Re-review creates a new report. Lifecycle links validate exact finding membership, the same session, identical target references, and the same rule subject:

- `RESOLVES` requires `current_finding=None` and the current same-rule deterministic check to be `PASS` or explicitly `NOT_APPLICABLE`. `FINDING`, `BLOCKED`, and `NOT_RUN` cannot resolve a finding.
- `SUPERSEDES` requires a new exact current-report finding for the same `rule_id`.

Target changes are rejected in V0 rather than guessed as the same subject. There is no Agent waive method and no in-place history mutation.

## Coverage and overall status

Every report records counts for all five outcomes. Status priority is:

1. any `BLOCKED` -> `BLOCKED`
2. any `FINDING` -> `FINDINGS_PRESENT`
3. any required `NOT_RUN` -> `INCOMPLETE_REVIEW`
4. otherwise -> `CLEAR_WITHIN_CHECKED_SCOPE`

`CLEAR_WITHIN_CHECKED_SCOPE` is not Admission. Optional robustness rule `O-060` remains `NOT_RUN` without formal statistical evidence and does not create an overfitting or robustness PASS/FAIL.

## PIT relational proof

PIT rule `O-050` never treats a global union of fact names as proof. `PASS` requires one exact loaded and bound chain:

```text
Snapshot -> DatasetVersion + SplitSpec -> StrategyEvaluation
         -> PortfolioIntent -> TargetWeightVector
```

The chain must provide FORMAL/FORMAL_ADMITTED source truth, an allowed `source_truth=FORMAL` fact, timezone-aware parseable `available_time`, `knowledge_cutoff`, and target `decision_time` or `effective_at`, comparable ordered periods, and exact non-negative integer purge/embargo values. The reviewer verifies upstream availability does not exceed downstream knowledge cutoffs and that availability/cutoffs do not exceed target decision/effective timing.

Outcome discipline is conservative:

- `PASS`: the complete exact chain, typed facts, truth, and all required relations are proven.
- `FINDING`: a parseable exact chain contains a deterministic temporal, period, purge, or embargo contradiction.
- `NOT_RUN`: a binding, fact, type, timezone, truth, or owner timing authority is missing or insufficient.
- `NOT_APPLICABLE`: no PIT-bearing evidence exists.

Invalid strings cannot PASS. `PRE_ALPHA` alone never proves PIT safety. The protected current-main Round 3 projection remains read-only and its `O-050` result stays `NOT_RUN` when it does not expose this full proof.

## Agent boundary

`ReviewerAgentDraft` references one immutable ReviewReport and exact evidence contained by that report. It supports summary, prioritized risks, and research suggestions only, with fixed `L1_DRAFT` and `NON_CANONICAL` state. It has no fields or methods for deterministic outcomes, Truth/Admission, execution, publication, mutation, promotion, or waiver.

## UI boundary

The additive Agent Workspace panel visually separates Layer A and Layer B, shows all coverage counts, keeps `NOT_RUN` visible, shows overall review status as “not admission,” and navigates finding citations to exact loaded Evidence Inspector objects.

Current main does not expose a non-protected transport for Track O ReviewReport objects. Until an exact backend report is loaded, the panel honestly renders `DERIVED_READ_ONLY_UI_PROJECTION`, `BACKEND_REPORT_NOT_LOADED`, and `NOT_RUN` for checks whose separate hashes/bindings are unavailable. Its provisional finding keeps `reviewReportId=null`; it is not a canonical `ReviewerFinding` and cannot create canonical lifecycle links. The UI does not modify the protected Round 3 evidence adapter.
