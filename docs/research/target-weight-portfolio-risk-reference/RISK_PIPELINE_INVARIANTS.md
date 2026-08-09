# Risk pipeline invariants

## Core contract

Risk consumes a published `TargetWeightVector`, pinned risk policies/models and exact risk-state inputs. It returns either:

- a new immutable `RiskAdjustedWeightVector` plus a complete adjustment report;
- `UNCHANGED`, represented by a distinct admitted result that references the identical weights; or
- a typed rejection/infeasibility result.

Risk never edits the original vector, changes StrategyVersion/ModelVersion identity, writes the account, emits broker orders or calls a backtest engine.

## Identity separation

```text
StrategyVersion / ModelVersion / AIRecipeVersion
            |
            v
PortfolioIntent -> TargetWeightVector --immutable source_target_id-->
                                      RiskAdjustedWeightVector
                                      + RiskDecisionReport
```

The risk-adjusted identity includes the original target identity, ordered policy-set version, risk-model versions, state snapshot, time bindings, code/environment and the resulting canonical weights. The upstream strategy remains exactly the same strategy even when risk reduces every weight to zero.

| Invariant | Disposition | Consequence |
|---|---|---|
| RSK-01 Source immutability | **ADOPT** | Never overwrite/alias original target rows |
| RSK-02 Identity non-interference | **ADOPT** | Risk references StrategyVersion but cannot revise it |
| RSK-03 Deterministic composition | **ADOPT** | Ordered policies and conflict semantics are pinned |
| RSK-04 Evidence per adjustment | **ADOPT** | Before/after, rule ID, limit, observed value and reason are recorded |
| RSK-05 No account mutation | **ADOPT** | Account state is a read-only pinned input when required |
| RSK-06 No silent safe fallback | **REJECT** | Cash-only or prior weights require an explicit named policy and new identity |

## Policy composition

Risk constraints do not generally commute. “Cap single-name then sector-project” can differ from “sector-project then cap single-name.” V3 should execute an ordered `RiskPolicySetVersion`.

Each stage receives the prior stage's immutable candidate and produces a new stage result. The final vector references the stage chain. Policies declare one of:

- `VALIDATE`: pass or reject without changing weights;
- `CLIP`: apply local bounds, then require a declared residual/cash rule;
- `SCALE`: multiply an explicitly defined exposure set;
- `PROJECT`: solve a constrained projection/optimization;
- `FREEZE`: retain specified current weights using a pinned portfolio snapshot;
- `REPLACE`: produce a named emergency/safe target under tightly controlled policy.

**REJECT:** a generic callback that mutates an in-memory dictionary without declaring its algebra, inputs or failure behavior.

## Constraint classes

| Constraint | Preferred stage | Disposition | Notes |
|---|---|---|---|
| Per-instrument min/max | construction and/or risk overlay | **ADAPT** | Ownership must be explicit; duplicate limits resolve by named precedence |
| Gross/net exposure | risk | **ADOPT** | Validate against named exposure profile |
| Sector/factor exposure | construction optimizer or risk projection | **ADAPT** | Pin taxonomy/risk model and solver evidence |
| Turnover budget | construction or risk | **ADAPT** | Requires exact current portfolio snapshot and convention |
| Liquidity/ADV participation | risk/pre-trade | **ADOPT** | Exact PIT market-data snapshot and horizon required |
| ST/restricted list | risk/pre-trade | **ADOPT** | Policy and effective timestamp are mandatory |
| Suspension/price limits | execution feasibility, optionally risk | **ADAPT** | Dynamic state may prevent realization after risk approval |
| Drawdown/circuit breaker | stateful risk | **FUTURE** | Needs formal risk-state and event-order contract |

## Cash and residual handling

Every transformation declares where removed exposure goes. For a long-only unlevered target, the default may move clipped weight to cash. Redistribution among remaining instruments is an optimizer/projection decision, not an automatic convenience.

For short/leverage profiles, “move to cash” may not preserve net/gross constraints. The policy must solve against the exposure profile or reject.

| Behavior | Disposition |
|---|---|
| Record original and adjusted cash | **ADOPT** |
| Proportional renormalization after clipping without policy evidence | **REJECT** |
| Allow explicit minimize-distance projection | **ADOPT** |
| Hide small residuals under floating-point tolerance | **REJECT** |

## Infeasibility and degraded inputs

Risk is infeasible when constraints conflict, required data/model inputs are absent/stale, a projection fails, or the result violates the target's exposure profile. The outcome includes minimal conflict evidence where available and never masquerades as “no change.”

Examples:

- sector minimums sum above the total risk budget;
- frozen suspended holdings plus mandatory maximum exposure conflict;
- turnover cap prevents meeting a prohibited-instrument zero bound;
- covariance matrix is stale/non-PSD and the configured repair policy is absent;
- a short target has no locate snapshot;
- a solver returns inaccurate/non-finite weights.

An approved degraded mode is a separately versioned policy. It changes result identity, carries a prominent truth state and is never selected implicitly.

## Risk versus optimizer

Portfolio optimization can incorporate ex-ante risk objectives while the Risk stage enforces portfolio admission policies. The boundary is ownership, not mathematical technique:

- construction optimizer answers “which desired portfolio best expresses the intent under construction constraints?”;
- Risk answers “which desired portfolio is admitted under independent risk policy now?”;
- execution answers “which orders are possible and appropriate now?”

The same optimization library may implement construction and risk projection, but the calls must have distinct operation identities, input manifests and outputs.

## Decisions

| ID | Decision | Disposition |
|---|---|---|
| RP-01 | Persist both pre-risk and post-risk vectors | **ADOPT** |
| RP-02 | Ordered, versioned risk policy composition | **ADOPT** |
| RP-03 | Risk changes Strategy identity | **REJECT** |
| RP-04 | Risk directly writes orders/holdings | **REJECT** |
| RP-05 | Explicit validate/clip/scale/project/freeze/replace algebra | **ADOPT** |
| RP-06 | Implicit proportional redistribution | **REJECT** |
| RP-07 | Stateful circuit-breaker contract in initial slice | **FUTURE** |
| RP-08 | Use optimization inside Risk with solver provenance | **ADAPT** |
