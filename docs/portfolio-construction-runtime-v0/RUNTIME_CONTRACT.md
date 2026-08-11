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
- accepted intent exposure/cash policies and explicit target cash;
- min/max instrument weight and max gross/net exposure;
- selection normalization, tie-break, rounding and residual rules;
- absent-member `ZERO`, 12-place Decimal precision and `1e-12` tolerance;
- optimizer backend/version/settings (`NONE_V3_NATIVE_DECIMAL_BASELINE` in V0);
- diagnostics policy and exact runtime identity.

Changing any semantic field creates a new `pcsv_sha256_...` identity and,
through the W0 seam, a new Target identity.

## Methods

### `EQUAL_WEIGHT_SELECTED`

The exact `PortfolioIntent.items` membership is the selected scope. The pinned
invested budget (`1 - explicit cash`) is divided equally. Inputs are sorted by
canonical instrument ID; original input order never affects output identity.

### `NORMALIZED_DESIRED_EXPOSURE`

Every desired exposure must be a finite, non-negative Decimal string and the
total must be positive. Values are normalized into the pinned invested budget.
Negative, non-finite or zero-total inputs receive typed rejection; there is no
fallback to equal weights.

Both methods floor raw weights to 12 places, then allocate remaining quanta by
largest fractional remainder and canonical instrument ID. Zero rows are omitted,
and all absent exact-Universe members mean absolute target weight zero.

An empty selection is valid only for an all-cash spec. Any invested budget with
an empty selection is `EMPTY_SELECTION_INFEASIBLE`.

## Publication and truth

Successful construction records selected/excluded counts, explicit cash,
gross/net exposure, normalization total, allocated rounding residual, exact
source/binding IDs, method and typed constraint checks. Diagnostics and
provenance are immutable content-addressed evidence and are referenced through
the merged W0 contract.

The current W0 external-owner references are unresolved and therefore capped at
`PRE_ALPHA`. Portfolio construction preserves that ceiling; successful checks or
future solver success cannot promote truth. `TargetWeightVector.create` remains
the sole canonical Target ID allocator and final complete-scope validator.

The Target contains no current price, holdings, account, order, status or fill
fields. Those remain execution-planning concerns after the mandatory Risk seam.
