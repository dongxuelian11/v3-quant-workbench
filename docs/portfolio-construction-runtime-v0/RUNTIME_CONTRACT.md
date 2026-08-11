# Portfolio Construction Runtime V0 contract

## Boundary

The only implemented flow is:

```text
actual PortfolioIntent + StrategyDefinitionVersion + StrategyEvaluationBindingVersion
  -> merged W0 PortfolioIntentSource.create
  -> PortfolioConstructionSpecVersion
  -> deterministic construction and typed checks
  -> immutable diagnostics + provenance references
  -> merged W0 TargetWeightVector.create
```

The runtime never creates `RiskAdjustedWeightVector`, never invokes Risk or
Backtest, and never accepts a bare PortfolioIntent ID or caller-supplied Universe
membership. W0 and Track F types are imported and consumed without modification.

## Immutable construction specification

`PortfolioConstructionSpecVersion` content identity includes:

- construction method and version;
- long-only unlevered exposure profile;
- method-derived closed intent exposure/cash/rebalance/constraint policies and
  explicit target cash;
- min/max instrument weight and max gross/net exposure;
- selection normalization, tie-break, rounding and residual rules;
- absent-member `ZERO`, 12-place Decimal precision and `1e-12` tolerance;
- optimizer backend/version/settings (`NONE_V3_NATIVE_DECIMAL_BASELINE` in V0);
- diagnostics policy and exact runtime identity.

Changing any semantic field creates a new `pcsv_sha256_...` identity and,
through the W0 seam, a new Target identity.

The V0 intent policy is not caller-extensible. `PortfolioConstructionSpecVersion`
does not accept arbitrary intent semantic strings. Unknown exposure, cash,
rebalance, normalization, or constraint semantics fail closed.

## Closed PortfolioIntent admission

Both methods require `cash_policy=RESIDUAL` and
`rebalance_intent=AT_BOUND_DECISION_TIME`. `UNCHANGED` cash and every other
rebalance value are unsupported in V0. Constraint keys must be exactly:

```text
proposal_only = true
normalization = the method-pinned marker
portfolio_service_required = true
```

Missing or false required flags are rejected. Unknown or extra keys are
`UNSUPPORTED_INTENT_CONSTRAINT`; they are never deferred to Risk.

## Methods

### `EQUAL_WEIGHT_SELECTED`

The exact `PortfolioIntent.items` membership is the selected scope. The pinned
invested budget (`1 - explicit cash`) is divided equally. Inputs are sorted by
canonical instrument ID; original input order never affects output identity.
This method accepts `ABSOLUTE_DESIRED_EXPOSURE` with
`normalization=EQUAL_DESIRED_EXPOSURE`, verifies that item desired exposures are
equal, and explicitly records
`INTENT_DESIRED_EXPOSURE_MAGNITUDES_NOT_PRESERVED` and
`SELECTION_MEMBERSHIP_REWEIGHTED_EQUAL`. Membership is consumed; the upstream
magnitudes are not preserved in the Target.

### `NORMALIZED_DESIRED_EXPOSURE`

Every desired exposure must be a finite, non-negative Decimal string and the
total must be positive. Values are normalized into the pinned invested budget.
Negative, non-finite or zero-total inputs receive typed rejection; there is no
fallback to equal weights.
This method accepts `RELATIVE_DESIRED_EXPOSURE` with the Track H supported
`normalization=RELATIVE_DESIRED_EXPOSURE` marker. Desired exposures are
interpreted as relative construction inputs and normalized into the pinned
invested budget. `ABSOLUTE_DESIRED_EXPOSURE` is not silently normalized.

Both methods floor raw weights to 12 places, then allocate remaining quanta by
largest fractional remainder and canonical instrument ID. Zero rows are omitted,
and all absent exact-Universe members mean absolute target weight zero.

An empty selection is valid only for an all-cash spec. Any invested budget with
an empty selection is `EMPTY_SELECTION_INFEASIBLE`.

## Exact temporal admission

Caller timing must remain timezone-aware and satisfy the W0 self-ordering rule:

```text
as_of <= decision_time <= rebalance_time <= valid_until
```

Track H additionally requires both `as_of` and `decision_time` to be inside the
exact `StrategyEvaluationBindingVersion.period` and not later than its exact
`knowledge_cutoff`. For `AT_BOUND_DECISION_TIME`, `decision_time` is the
portfolio-construction decision/evidence time and `rebalance_time` may be equal
or later.

There is no owner-resolved exact Strategy evaluation decision-time receipt in
the current PortfolioIntent. Track H can only validate caller timing against the
exact StrategyEvaluationBinding period and knowledge cutoff. This remains
`PRE_ALPHA` and is not a `FORMAL` timing receipt.

## Publication and truth

Successful construction records selected/excluded counts, explicit cash,
gross/net exposure, normalization total, allocated rounding residual, exact
source/binding IDs, method and typed constraint checks. Diagnostics and
provenance are immutable content-addressed evidence and are referenced through
the merged W0 contract.

Diagnostics and provenance also bind `as_of`, `decision_time`,
`rebalance_time`, `valid_until`, binding period start/end, knowledge cutoff,
rebalance intent, and the typed timing-validation result. These fields make the
Target timing admission auditable and participate in canonical evidence IDs.

The current W0 external-owner references are unresolved and therefore capped at
`PRE_ALPHA`. Portfolio construction preserves that ceiling; successful checks or
future solver success cannot promote truth. `TargetWeightVector.create` remains
the sole canonical Target ID allocator and final complete-scope validator.

The Target contains no current price, holdings, account, order, status or fill
fields. Those remain execution-planning concerns after the mandatory Risk seam.
