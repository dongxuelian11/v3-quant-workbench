# TargetWeightVector contract recommendation

## Explicit conclusion

**ADOPT:** `TargetWeightVector` should become the stable V3 contract published by PortfolioService/Portfolio Construction for Risk and, after an explicit Risk stage, Backtest/Execution planning. Strategy, Model and AI never publish a formal `TargetWeightVector` directly.

This is a qualified yes. The contract is a content-addressed, immutable, complete-scope description of a desired portfolio at a stated time. It is not a bare map, not an order list, not current holdings, not a fill promise and not a mutable account view. Producers that express ranks, scores, selected instruments or an optimization objective first emit `SignalArtifact` or `PortfolioIntent`; Portfolio Construction resolves those into the vector.

```text
Strategy / Model / AI
  -> SignalArtifact and/or PortfolioIntent (proposed weights allowed here)
  -> PortfolioService / Portfolio Construction
  -> validation: scope + completeness + cash/exposure + constraints + provenance
  -> TargetWeightVector
  -> explicit RiskPolicySetVersion
  -> RiskAdjustedWeightVector
  -> Backtest or Execution planning
  -> TargetQuantityVector -> Orders -> Fills -> Holdings
```

The formal publisher boundary is singular: PortfolioService/Portfolio Construction owns admission and publication of `TargetWeightVector`. A strategy/model/AI producer may express proposed weights only inside `PortfolioIntent`; those weights remain proposals until the Portfolio owner validates and canonicalizes the complete target. **ADOPT:** no alternate direct-publication path.

The formal consumer boundary is also singular: Backtest/Execution planning consumes `RiskAdjustedWeightVector`, never a raw `TargetWeightVector`. When no additional factor risk model or transform is required, an explicit `RiskPolicySetVersion` containing `PASS_THROUGH` / `NO_ADDITIONAL_RISK_TRANSFORM` still publishes a new immutable `RiskAdjustedWeightVector` referencing the source target and recording the no-transform evidence. **ADOPT:** absence of an extra factor RiskModel never means bypassing the Risk domain.

Earlier shorthand can be read only as the following ownership chain:

```text
SignalArtifact
  -> PortfolioIntent
  -> PortfolioService / Portfolio Construction / admitted Optimizer
  -> TargetWeightVector
  -> explicit RiskPolicySetVersion
  -> RiskAdjustedWeightVector
  -> Backtest or Execution planning
  -> TargetQuantityVector -> Orders -> Fills -> Holdings
```

## Why this is the stable seam

Weights preserve the economic desire while avoiding broker-specific quantities. LEAN demonstrates that percentage-to-quantity conversion needs portfolio value, prices, lot sizes and buying power; WonderTrader demonstrates that target-position realization belongs to execution; FinRL-X and Qlib demonstrate that weight handoffs can connect strategy to downstream systems. V3 adds the missing identity and provenance rigor.

Tradeoffs:

- weights cannot by themselves express alpha confidence, optimizer objective or execution urgency, so those remain upstream intent or downstream policy;
- weights require explicit semantics for cash, leverage, shorts and universe omissions;
- an exact target can become infeasible after market state changes, so execution must report residuals rather than rewrite it;
- quantity-based engines require a deterministic adapter;
- full vectors are larger than sparse commands, but their meaning and identity are unambiguous.

## Conceptual envelope

This is an implementation input, not a formal ASL/schema modification.

| Field | Requirement | Semantic rule |
|---|---|---|
| `schema_version` | required | Determines canonicalization and compatibility rules |
| `target_weight_vector_id` | required | V3-owned immutable ID; content hash is also stored |
| `content_sha256` | required | Hash of all semantic fields and canonical rows, excluding mutable storage metadata |
| `publisher_service` | required | Normatively `PortfolioService` / Portfolio Construction for formal targets |
| `truth_state` and admission evidence | required | Computed ceiling from every required upstream identity/input/policy; never producer-selected |
| `target_kind` | required | `ABSOLUTE_COMPLETE`; sparse delta/patch must be another type |
| `weight_basis` | required | For example `NAV`; defines the denominator, not merely units |
| `exposure_profile` | required | Pinned profile defining long/short, leverage, budget and cash equations |
| `base_currency` | required | Currency used for NAV/cash semantics |
| `as_of` | required | Information cutoff used to decide the target |
| `decision_time` | required | When the producer completed the decision |
| `rebalance_time` | required | First intended effective time |
| `valid_until` | required/nullable by profile | Latest time a consumer may admit the target |
| `universe_version_id` and hash | required | Exact eligible decision universe, including membership provenance |
| `portfolio_intent_id` | required | Immediate upstream intent |
| `source_refs` | required | StrategyVersion/ModelVersion/AI recipe, SignalArtifact and all other semantic inputs |
| `constraints_context_id` and hash | required | Exact construction constraints, policy versions and PIT-safe eligibility inputs |
| `optimizer_run_ref` | conditional | Solver/version/settings/status/tolerance/objective/data refs when optimization was used |
| `cash_weight` | required | Explicit, even when zero; interpreted by exposure profile |
| `rows_artifact_ref` | required | Content-addressed rows sorted by canonical `instrument_id` |
| `diagnostics_ref` | required | Feasibility, normalization, exclusions and warnings; empty artifact is valid |
| `provenance_manifest_ref` | required | Complete lineage and code/environment identity |

## Truth and admission ceiling

`TargetWeightVector.truth_state` cannot exceed the least-admitted required source SignalArtifact/PortfolioIntent, bound DatasetVersion/DataSnapshotVersion/UniverseVersion, or Portfolio construction input/policy. Portfolio validation can reject or preserve truth; it cannot upgrade it. **ADOPT**.

`RiskAdjustedWeightVector.truth_state` cannot exceed its source `TargetWeightVector.truth_state` or any required Risk-stage input. A risk model, optimizer result or constraint-validation PASS never promotes upstream truth. **ADOPT**.

Any PRE_ALPHA or NOT_FORMAL required upstream input caps both TargetWeightVector and RiskAdjustedWeightVector at NOT_FORMAL. A FORMAL Target requires, at minimum, exact upstream identities, exact UniverseVersion, every required Data Truth admission state, complete provenance, Portfolio construction validation and all relevant policy/admission gates. `PUBLISHED`, `STRICT_PIT`, optimizer success or constraint validation alone is insufficient. **ADOPT**.

## Canonical row

| Field | Requirement | Notes |
|---|---|---|
| `instrument_id` | required | Canonical security master identity, not display ticker |
| `target_weight` | required | Signed canonical decimal; no NaN/Infinity/negative zero |
| `sleeve_id` | optional | Allowed only when aggregation rules are pinned and deterministic |
| `source_contribution_ref` | optional | Explainability link; must not alter weight semantics |

Market status, current price, current holdings and order state do not belong in an original target row. They are time-varying planning inputs. If a construction constraint excludes a security, the exclusion and its PIT input belong in diagnostics/provenance.

## Completeness and absent members

**ADOPT:** a published vector uses `ABSOLUTE_COMPLETE` semantics over its pinned universe. Every universe member is either represented by a row, or the schema normatively defines absent as zero; V3 should prefer explicit nonzero rows plus a mandatory `absent_member_policy = ZERO` and a universe hash. Instruments outside the universe are out of scope, not implicitly unchanged.

**REJECT:** interpreting omission sometimes as zero and sometimes as “keep current holding.” If sparse instructions are needed, define `PortfolioIntentPatch` with explicit `SET`, `ADD`, `LIQUIDATE` or `UNCHANGED` operations; never publish it under `TargetWeightVector`.

## Exposure profiles and cash equations

### `LONG_ONLY_UNLEVERED`

- every instrument weight is `>= 0`;
- `cash_weight >= 0`;
- `sum(instrument weights) + cash_weight = 1` within the profile's published tolerance;
- gross exposure equals net invested exposure.

### `LONG_SHORT_NAV`

- signed instrument weights are allowed within pinned lower/upper bounds;
- `net_exposure = sum(weights)` and `gross_exposure = sum(abs(weights))` are independently constrained;
- `cash_weight` and financing semantics are defined by the profile, not guessed as a universal `1 - sum(weights)`;
- borrow availability, margin and locate state remain risk/execution inputs unless pinned construction constraints explicitly include them.

### Leveraged profiles

Leverage limit, collateral/cash treatment and whether derivatives use notional or delta-adjusted exposure must be distinct named profiles. **FUTURE:** do not enable these until accounting and engine adapters have golden tests.

## Deterministic identity

Canonicalization must specify:

1. Unicode and identifier normalization;
2. rows sorted by canonical `instrument_id` and then `sleeve_id`;
3. fixed decimal syntax/scale and rounding mode;
4. UTC timestamp representation with declared exchange-calendar references;
5. canonical object key ordering and absence/null rules;
6. inclusion of all semantic refs, policies and tolerances in the hash;
7. exclusion of storage location, created-by display name and mutable validation status from the content hash.

The same semantic input must produce the same vector bytes and identity. A change in signal version, universe, constraints, optimizer configuration, source code, time binding or any target weight must produce a new identity.

## Relationship to PortfolioIntent

`PortfolioIntent` expresses what a strategy/model/AI wants: selected assets, scores/preferences, objective, desired exposure, cash policy, rebalance request and construction constraints. It may contain proposed weights, but only PortfolioService/Portfolio Construction can admit and publish them as a `TargetWeightVector` after normalization, scope, completeness, cash/exposure, constraints and provenance checks succeed.

This avoids two bad extremes:

- forcing ranking or AI systems to pretend they already solved portfolio construction;
- letting downstream systems reinterpret the same untyped signal differently without provenance.

## Contract decisions

| ID | Decision | Disposition |
|---|---|---|
| T-01 | Stable V3 boundary is an immutable target-weight artifact published only by PortfolioService/Portfolio Construction | **ADOPT** |
| T-02 | Keep `PortfolioIntent` as an upstream, possibly under-specified artifact | **ADOPT** |
| T-03 | Include explicit cash and a named exposure profile | **ADOPT** |
| T-04 | Include prices/current holdings/orders in vector identity | **REJECT** |
| T-05 | Convert weights to quantity in strategy/model code | **REJECT** |
| T-06 | Canonicalize decimals, ordering, timestamps and semantic references | **ADOPT** |
| T-07 | Allow arbitrary DataFrame/dictionary as the persisted public contract | **REJECT** |
| T-08 | Represent sparse updates with a separate typed intent | **ADAPT** |
| T-09 | Support derivatives/notional/delta profiles in the first slice | **FUTURE** |
| T-10 | Leave exact decimal scale and tolerance to schema design with golden vectors | **ADAPT** |
| T-11 | Strategy/Model/AI publishes formal TargetWeightVector directly | **REJECT** |
| T-12 | Execution consumes raw TargetWeightVector when no factor RiskModel is configured | **REJECT** |
| T-13 | Explicit PASS_THROUGH Risk policy emits a separately identified RiskAdjustedWeightVector | **ADOPT** |
| T-14 | Target/RiskAdjusted truth is capped by required upstream admission | **ADOPT** |
