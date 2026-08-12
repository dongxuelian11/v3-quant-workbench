# Round 5 R Portfolio/Risk Agent Contract

Task: `V3-ROUND5-R-PORTFOLIO-RISK-AGENT-01` (+ same-branch authority/evidence closure)
Branch: `codex/round5-r-portfolio-risk-agent-01` / PR #26
Base: `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`

## Authority boundary

The Portfolio/Risk Agent is L0/L1 only. Its callable inventory is:

- L0 read tools (exact-object projections): `get_portfolio_intent`, `get_target_weight_evidence`,
  `get_risk_policy_set`, `get_risk_adjusted_evidence`, `get_cost_policy`, `get_backtest_result`,
  `get_result_analytics`, `get_reviewer_report`, `get_scenario_bundle`, `compare_scenarios`;
- L1 drafts: `PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `RESULT_COMPARE`, `REVIEW_RUN`.

There is no Agent-callable confirm, execute, review, promote, canonical-ID, Truth, Admission, or
publication tool. L2 EXECUTE and L3 PUBLISH remain denied. Production ResearchLoop `COMPLETE`
remains `NOT_AVAILABLE / NOT_RUN`.

## User-execution authority disposition (Finding R-A)

Current main has **no canonical user-action / approval / application-command authority**
(audited at `f2cd80e`: the only "confirmation" concepts are the artifact-GC plan receipt and
display text; the weight seam marks all caller-asserted references
`UNRESOLVED_CALLER_ASSERTED`). A caller-shaped `UserConfirmation` is not authority and
`agent_issued=False` is not human authority.

Therefore **production R execution is `NOT_AVAILABLE / NOT_RUN`**: the three
`apply_confirmed_*` seams fail closed with the typed
`USER_EXECUTION_AUTHORITY_NOT_AVAILABLE` error before any owner invocation. R does not mint a
second approval authority and does not open Agent L2. The execution-input binding model below
(`verify_*`) is the ready binding layer for a future canonical user-action authority and is
exercised directly by tests.

## Execution-input exact binding model (Finding R-B)

- Portfolio construct: `verify_portfolio_construct_binding` exact-binds the confirmed draft
  to `base_currency`, `as_of`, `decision_time`, `rebalance_time`, `valid_until`,
  construction-spec id + content hash, `PortfolioIntent`, definition and binding ids, and the
  construction spec's embedded `RuntimeIdentity`.
- Risk apply: `verify_risk_apply_binding` exact-binds source target id + content hash,
  `RiskPolicySetVersion` id + content hash, the backend/code/runtime triple, and the exact
  `RuntimeIdentity` fields. **Route A**: `state_inputs` must be empty at the R seam; policies
  requiring external risk state stay unsupported at the seam, and PIT/state validation remains
  delegated to the canonical Risk runtime.
- Backtest run: the draft binds an **exact content-addressed `BacktestRunSpec` identity**
  (`run_spec_id` + `content_sha256`), which covers every execution-changing input (sessions,
  instruments, exact references, schedule). `verify_backtest_binding` additionally checks
  `initial_cash`, engine version, cost/rule/timing profiles, schedule membership of the exact
  `RiskAdjustedWeightVector`, the scheduled effective time, and the scheduled vector content
  hash. No weak partial hash is invented.

## Scenario evidence resolver (Finding R-C)

`resolve_scenario_evidence` is the system-owned production builder: it accepts only actual
canonical owner objects (`PortfolioIntent`/`PortfolioIntentSource`/binding, construction-spec
reference, `RiskPolicySetVersion`, `CostPolicyVersion`, `TargetWeightVector`,
`RiskAdjustedWeightVector` + decision report, `BacktestRunResult` + `BacktestRunSpec`,
`BacktestResultAnalytics`, `ResearchReviewReport`) and validates every chain link before
projecting a `ScenarioEvidenceBundle`. Arbitrary prebuilt projections are never proof.
Links the current owners cannot prove are recorded in `binding_gaps` and the bundle never
becomes `EVIDENCE_BOUND`; explanations then report `EVIDENCE_BINDING_UNAVAILABLE`.

Reviewer binding: the bundle accepts a report only when its exact `target_refs` (projected
verbatim) include the scenario's exact `BacktestRunResult` id + content hash; unrelated
reports fail closed. Backtest binding: the projected result view carries the spec id/hash,
the scheduled risk-adjusted vector ids, and the exact bound vector id. The decision report is
explicitly exact-bound to the scenario `RiskPolicySetVersion` id + content hash.

### Resolver trust boundary (Finding R-C final closure)

`ScenarioEvidenceBundle` is an **explicitly untrusted projection DTO** for rendering and
serialization only. Trust derives from canonical resolution performed **at the trusted
consumer boundary**, never from the pedigree of a caller-supplied Python object.

The bounded public input of every trusted entry point is `ScenarioResolutionRequest`,
which carries only canonical owner objects (PortfolioIntent / PortfolioIntentSource /
binding, exact construction-spec reference, RiskPolicySetVersion, CostPolicyVersion,
TargetWeightVector + decision report, BacktestRunResult + BacktestRunSpec,
BacktestResultAnalytics, ResearchReviewReport). The trusted entry point itself invokes
`resolve_scenario_evidence` and re-establishes the exact canonical chain before any
result is produced:

- `compare_scenarios(left=request, right=request, ...)` resolves both requests inside
  the boundary;
- `explain_scenario(request=...)` resolves inside the boundary;
- `PortfolioRiskReadTools.from_canonical(scenario_requests=...)` builds the scenario
  inventory exclusively through canonical resolution (no parameter accepts
  caller-supplied resolved bundles; duplicate scenario identities fail closed);
- the compare worker accepts `ScenarioResolutionRequest` pairs and resolves them
  system-side before the deterministic comparison is exposed to the model.

`ResolvedScenarioEvidenceBundle` remains only as an internal/intermediate value:
possession of the exact type, deterministic-hash equality, empty `binding_gaps`, or any
explicit import of module internals grant nothing, because **no trusted entry point
accepts caller-supplied resolved bundles**. There is no authority token, no private
origin object, no sentinel, and no caller-settable trust flag anywhere in the package.

## Scenario comparison semantics (Finding R-D)

`compare_scenarios` accepts canonical `ScenarioResolutionRequest` inputs, resolves them
at the trusted boundary, and separates
**comparison invariant** from **scenario treatment**. The invariant is the resolver-derived
`ScenarioComparisonInvariant`, whose `invariant_id` is the deterministic content hash of
every non-treatment execution/evaluation dimension, recomputed and verified on
construction. Dimensions covered: `PortfolioIntent` identity/content; universe
identity/membership; knowledge cutoff; snapshot and calendar references; base currency;
analytics policy id/content; benchmark series; `initial_cash`; `initial_holdings`;
instrument set; exact session dates; exact per-session market-state inputs; exact
corporate-action events; exact pinned data/snapshot/calendar/corporate-action references;
A-share rule profile id/content; execution timing profile id/content and convention;
runtime identity; engine version; valuation mode.

Treatment dimensions (construction spec, risk policy set, cost policy) are deliberately
absent from the invariant: they may differ while scenarios remain `COMPARABLE`, and the
differences are disclosed explicitly in `scenario_differences`.

Comparison order of authority: trusted resolved evidence -> derived comparison invariant ->
invariant equality. Any evidence-binding gap fails closed as `INCOMPARABLE_CONTEXT` with
`EVIDENCE_BINDING_UNAVAILABLE`; any missing analytics/invariant fails closed as
`INCOMPARABLE_CONTEXT`; any invariant mismatch returns the exact mismatched dimension names
and **never** a ranking or metric deltas. Only under exact invariant equality are treatment
differences disclosed and metrics/ranking computed. A higher Sharpe or lower drawdown can
never make incomparable scenarios comparable, and no context-free "best" claim is produced.
Ranking is allowed only with an explicit objective metric + direction whose delta is
`AVAILABLE` on both sides; missing metrics remain `NOT_RUN / NOT_AVAILABLE /
INSUFFICIENT_SAMPLE` with no zero fill.

## PydanticAI worker evidence requirements

Construct proposals require the exact `PortfolioIntent` evidence call. Risk proposals require
`PortfolioIntent` plus exact `TargetWeightVector` and `RiskPolicySetVersion` evidence exposed.
Backtest proposals require the exact `RiskAdjustedWeightVector` and `CostPolicy` evidence
exposed. Compare proposals are system-computed: the worker accepts canonical
`ScenarioResolutionRequest` pairs, resolves them system-side at the trusted boundary,
computes the deterministic comparison, and the model MUST consume the exact
`compare_scenarios` tool result — no evidence tool call fails closed. Narrative output cannot
carry invented metric/exposure values.

## A-share gates (inherited, never waived)

T+1 sellable accounting, buy-lot rounding, limit-up/down blocks, suspended/ST blocks and
explicit costs stay in the J engine; target/risk-adjusted evidence always projects
`LONG_ONLY_UNLEVERED`; no draft field can enable shorting or leverage.

## Naming note

The frozen W0 base has no `RiskModelVersion` class; the canonical risk-model identity is the
exact `RiskPolicySetVersion` plus the exact `(backend, code_version, runtime_profile_id)`
triple (`RISK_V0_BACKEND = "v3-native-decimal"`).

## Test coverage

`apps/backend/tests/round5_r_portfolio_risk_agent/test_portfolio_risk_agent.py` (96 tests)
covers the original 20 R categories plus the correction matrix: R-A confirmation authority
(5), R-B exact construct/risk/backtest binding (17), R-C evidence resolver and binding (7),
R-D evidence-grounded comparison and treatment semantics (7), worker evidence gates, all
existing A-share / no-second-authority regressions, and the final closure matrices:
R-C authority (RC-FINAL-01..10: legacy origin tokens removed and import confers nothing;
manual/exact-type/hash-equal/gap-free wrappers rejected by compare, explain, read tools and
the compare worker; canonical success path through all trusted boundaries; canonical
failure stays fail closed with EVIDENCE_BINDING_UNAVAILABLE) and R-D invariant
negatives/positives (17: initial cash, holdings, instruments, session range, market-state
inputs, data/calendar/corporate-action references, A-share rule profile, execution timing,
runtime identity, engine version, analytics policy, benchmark context ->
`INCOMPARABLE_CONTEXT`; construction spec / risk policy set / cost policy -> `COMPARABLE`
with disclosed treatment differences).
