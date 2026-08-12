# Round 5 R Portfolio/Risk Agent Contract

Task: `V3-ROUND5-R-PORTFOLIO-RISK-AGENT-01`
Branch: `codex/round5-r-portfolio-risk-agent-01`
Base: `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`

## Authority boundary

The Portfolio/Risk Agent is L0/L1 only. Its callable inventory is:

- L0 read tools (exact-object projections): `get_portfolio_intent`, `get_target_weight_evidence`,
  `get_risk_policy_set`, `get_risk_adjusted_evidence`, `get_cost_policy`, `get_backtest_result`,
  `get_result_analytics`, `get_reviewer_report`, `get_scenario_bundle`, `compare_scenarios`;
- L1 drafts: `PORTFOLIO_CONSTRUCT`, `RISK_APPLY`, `BACKTEST_RUN`, `RESULT_COMPARE`, `REVIEW_RUN`.

There is no Agent-callable confirm, execute, review, promote, canonical-ID, Truth, Admission, or
publication tool. The user-confirm application seam (`apply_confirmed_portfolio_construct`,
`apply_confirmed_risk_apply`, `apply_confirmed_backtest_run`) is a separate application boundary:
it requires an exact `draft_sha256`, `agent_issued=False`, a timezone-aware `confirmed_at`, and it
re-verifies every canonical binding before calling the deterministic owner. The action drafts
remain `NON_CANONICAL / DRAFT`, with `agent_execution_allowed=False` and
`user_confirmation_required=True` as closed literals.

## Naming note

The frozen W0 base has no `RiskModelVersion` class. The canonical risk-model identity is the exact
`RiskPolicySetVersion` plus the exact `(backend, code_version, runtime_profile_id)` triple its
policies share (`RISK_V0_BACKEND = "v3-native-decimal"`). Every R risk draft binds that triple, and
`build_scenario_context` fails closed when a policy set does not bind the exact
`source_target.runtime_identity`. Unknown/stale/mismatched policy sets, backends, code versions, or
runtime profiles are rejected before any draft is produced.

## Scenario semantics

Scenario drafts bind only **existing canonical object identities**: the construction spec version
reference, the risk policy set version, the cost policy version, the A-share rule/timing profiles,
the exact `TargetWeightVector` / `RiskAdjustedWeightVector`, the engine version, and initial cash.
R has no free-form numeric knobs. Parameters the current deterministic runtime cannot enforce are
rejected as unsupported rather than shadow-computed: sector/industry exposure bounds, turnover
budgets, optimizer/objective selection, shorting, leverage, and fractional lots do not exist in the
R wire shape (`extra="forbid"` closes it). If the current portfolio engine has no requested
optimizer/objective, R reports unsupported; it never calculates weights inside PydanticAI tools or
prompt text.

## A-share gates (inherited, never waived)

- T+1 sellable accounting, buy-lot rounding, limit-up/down buy/sell blocks, suspended/ST blocks and
  explicit commission/stamp-duty/transfer-fee costs come from the J engine and the exact
  `CostPolicyVersion`; R re-runs the J engine and reports its diagnostics verbatim.
- Target/risk-adjusted evidence always projects `LONG_ONLY_UNLEVERED`; no draft field can enable
  shorting or leverage, and the explanation never emits exposure/covariance/causality claims.

## Comparison semantics

`compare_scenarios` compares exact `ScenarioEvidenceBundle` objects. The comparison context key is
`(portfolio_intent_id, universe_version_id, knowledge_cutoff, base_currency,
construction_spec_version_id, risk_policy_set_version_id, cost_policy_id)`. Any mismatch returns
`INCOMPARABLE_CONTEXT` with the exact differing field names, no metric deltas, and no ranking.
Deltas are produced only for metrics that are `AVAILABLE` on both sides; missing metrics remain
`NOT_RUN` / `NOT_AVAILABLE` / `INSUFFICIENT_SAMPLE` with no zero fill. A ranking requires an exact
objective metric and direction, and only from `AVAILABLE` deltas.

## Explainability

`explain_scenario` emits only statements derived from the exact cited objects: risk stage
statuses/reasons, weight/cash changes between target and risk-adjusted rows, cost-policy facts,
analytics metric statuses and values, and Reviewer findings. Missing chain links
(target/risk-adjusted/backtest/analytics) yield `EVIDENCE_MISSING` with the exact absent links.
The `invented_*` literals (`exposure`, `covariance`, `analytics`, `causality`, `optimization`) are
closed to `False`.

## Production state

Production ResearchLoop `COMPLETE` remains `NOT_AVAILABLE / NOT_RUN`. No Track T UI, desktop shell,
shared route, or canonical owner file is changed by R. No second optimizer or risk authority is
introduced; `DeterministicPortfolioConstruction` and `apply_risk` continue to reject any external
solver candidate.

## Test coverage

`apps/backend/tests/round5_r_portfolio_risk_agent/test_portfolio_risk_agent.py` (26 tests) covers
the 20 required categories: proposal NON_CANONICAL/DRAFT; exact PortfolioIntent required; exact
risk policy set required; stale/wrong risk model rejected; unsupported constraint rejected;
leverage/short not silently enabled; deterministic scenario identity; no TargetWeightVector
minting; no RiskAdjustedWeightVector minting; no CostPolicy change by prose; backtest draft exact
inputs; exact comparison context; different CostPolicy visible; Reviewer/evidence exact-bound;
missing analytics NOT_RUN/NOT_AVAILABLE; user command not exposed as Agent L2; L2/L3 denied; no
second optimizer/risk authority; A-share constraints preserved; ResearchLoop COMPLETE remains
NOT_AVAILABLE/NOT_RUN — plus worker adapter, read-tool fail-closed, comparison/explanation, and
end-to-end user-confirmation seam tests.
