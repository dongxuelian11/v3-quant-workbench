# Reviewer Integration V0

## Authority boundary

Reviewer Integration is an immutable review-evidence layer. It is not a Truth, Admission, execution, waiver, or publication owner.

```text
exact current-main evidence
  -> versioned deterministic rules (Layer A)
  -> immutable ResearchReviewReport + ReviewerFinding
  -> optional non-canonical ReviewerAgentDraft (Layer B)
  -> read-only Reviewer UI with exact evidence navigation
```

Layer A has the closed outcomes `PASS`, `FINDING`, `NOT_APPLICABLE`, `NOT_RUN`, and `BLOCKED`. The ruleset identity is:

```text
version: v3.reviewer-integration/1
id: rrs_sha256_e4a3dfcf23fd173b8b0c68c9a897a4f16ebb4a74951eb21e7f8bc3b50f2b2860
rules: 15
```

The same exact scope and ruleset produce the same check IDs, report ID, findings, coverage, status, and Truth ceiling. Changing the ruleset version changes report identity.

## Immutable evidence and lifecycle

Each exact evidence reference binds `session_id`, object kind, object ID, and content SHA-256. Each finding binds its deterministic check and exact `review_report_id`; factual evidence references must resolve inside the loaded report scope.

Historical reports and findings are frozen. Re-review creates a new report. A new finding can link a prior finding only through an immutable `RESOLVES` or `SUPERSEDES` lifecycle record. There is no Agent waive method.

## Coverage and overall status

Every report records counts for all five outcomes. Status priority is:

1. any `BLOCKED` → `BLOCKED`
2. any `FINDING` → `FINDINGS_PRESENT`
3. any required `NOT_RUN` → `INCOMPLETE_REVIEW`
4. otherwise → `CLEAR_WITHIN_CHECKED_SCOPE`

`CLEAR_WITHIN_CHECKED_SCOPE` is not Admission. Optional robustness rule `O-060` remains `NOT_RUN` without formal statistical evidence and does not create an overfitting or robustness PASS/FAIL.

## PIT and leakage

PIT `PASS` requires exact available-time, knowledge-cutoff, period/split, purge/embargo, and source-truth evidence in the loaded scope. Missing fields produce `NOT_RUN`; `PRE_ALPHA` by itself never proves PIT safety.

## Agent boundary

`ReviewerAgentDraft` references one immutable ReviewReport and exact evidence contained by that report. It supports summary, prioritized risks, and research suggestions only, with fixed `L1_DRAFT` and `NON_CANONICAL` state. It has no fields or methods for deterministic outcomes, Truth/Admission, execution, publication, mutation, or waiver.

## UI boundary

The additive Agent Workspace panel visually separates Layer A and Layer B, shows all coverage counts, keeps `NOT_RUN` visible, shows overall review status as “not admission,” and navigates finding citations to exact loaded Evidence Inspector objects.

Current main does not expose a non-protected transport for Track O ReviewReport objects. Until an exact backend report is loaded, the panel honestly renders a `DERIVED_READ_ONLY_UI_PROJECTION`, `BACKEND_REPORT_NOT_LOADED`, and `NOT_RUN` for checks whose separate hashes/bindings are unavailable. It does not fabricate a canonical report or modify the protected Round 3 evidence adapter.
