# Deterministic Strategy runtime V0

## Ownership

Track F is the canonical owner of:

- `StrategyDefinitionVersion`
- `StrategyEvaluationBindingVersion`
- the closed Strategy component registry/compiler/evaluator
- `SignalArtifact`
- `SelectionArtifact`
- `PortfolioIntent`

It consumes, but does not redefine, A0 truth/admission and Track C Dataset/Factor semantics. It defines no `ModelVersion` or `PredictionArtifact`. Until a future owner exposes a typed canonical receipt/resolver on `main`, a generic model-owned artifact may cross only the unresolved exact-ID/hash research boundary and remains capped at PRE_ALPHA.

## Definition identity

`StrategyDefinitionVersion` is computed from:

- canonical Strategy IR with component defaults expanded;
- exact component registry version;
- compiler version;
- deterministic runtime profile;
- custom dependency references, when present.

The identity excludes concrete Dataset, Snapshot, Universe, calendar, date range, knowledge cutoff, wall clock and run IDs. Node tuple order, visual coordinates, viewport, display metadata and formatting do not enter canonical IR.

Compiler validation rejects duplicate nodes/bindings, dangling references, incompatible typed ports, cycles, unknown component versions, unknown parameters and output/artifact type mismatches. A `PortfolioIntent` output additionally requires an explicitly published `SelectionArtifact` output.

## Component descriptors

Every registered component declares a stable type/version, role, typed input/output ports, closed parameters with executable defaults, missing semantics, lookback, lag, deterministic behavior, truth/PIT requirements, named conflict semantics and its bounded capability set.

V0 includes:

- exact bound score input/reference;
- minimum condition/gate;
- named primary/fallback score combine;
- deterministic score ranking;
- stable top-N selection;
- SignalArtifact output;
- SelectionArtifact output;
- PortfolioIntent output.

Ranking is total and stable: score order first, then canonical `instrument_id`. Missing values are explicit and excluded only under the declared policy.

## Evaluation binding identity

`StrategyEvaluationBindingVersion` binds:

- exact `StrategyDefinitionVersion`;
- typed Track C `DatasetVersion`, every member `FactorEvaluation`, and matching `FeatureMaterialization`;
- exact Snapshot ID/content research reference;
- exact Universe definition, membership artifact/hash and deterministic member IDs;
- evaluation period and knowledge cutoff;
- exact calendar hash and IANA timezone;
- compiler, runtime and environment fingerprints;
- each required input artifact ID/hash/truth state;
- optional generic unresolved artifact references reserved for another domain owner.

`latest`, `current`, `unresolved`, missing slots and content mismatches fail closed. Changing Dataset/Snapshot/Universe/time changes binding identity, never definition identity.

### External authority resolution boundary

`ExactSnapshotReference`, `ExactUniverseReference`, `ExactCalendarReference` and `GenericAdmittedArtifactReference` are exact evaluation bindings, not canonical owner receipts. Their public constructors always emit `resolution=UNRESOLVED_CALLER_ASSERTED`, never an `*_OWNER_REFERENCE` claim, and meet any caller-proposed truth state with `PRE_ALPHA_CEILING`.

Consequently, reusing a source/version ID cannot establish owner resolution. Snapshot content hash, Universe definition and membership hashes/member IDs, Calendar hash/timezone, and generic artifact ID/hash all remain in binding identity, so any evidence change changes `StrategyEvaluationBindingVersion`. No formal owner-receipt path is exposed until the corresponding canonical resolver is available on `main`.

## Pure deterministic evaluator

The evaluator accepts only a definition, its exact binding and in-memory exact input artifacts. It has no repository, database, filesystem, network, live account, Backtest, broker, order or fill handle. All runtime inputs must match bound artifact IDs/hashes, share one injected decision time, lie within the evaluation period/cutoff, and contain no instrument outside the bound universe.

The only financial outputs are:

- `SignalArtifact`: exact definition/binding/input linkage, decision-time semantics, per-instrument value/direction, missing diagnostics, source node path, compiler/runtime, truth ceiling and provenance hash.
- `SelectionArtifact`: exact Universe membership boundary, stable ranks/tie-breaks, selected/excluded instruments, source reasons/paths, truth ceiling and provenance hash.
- `PortfolioIntent`: desired exposure proposal, scores, constraints and rebalance intent. It cannot carry `TargetWeightVector`, orders, fills or execution fields.

Every canonical output factory independently closes provenance:

- Signal and Selection input evidence keys, artifact IDs and content hashes must exactly equal `binding.input_references`; missing, extra, duplicate or mismatched evidence fails closed.
- Selection also requires an exact definition/binding match and covers the exact bound Universe through disjoint selected/excluded members.
- PortfolioIntent accepts actual `SelectionArtifact` and optional `SignalArtifact` objects, never caller-provided source ID strings. It verifies their definition, evaluation binding, Universe membership, input evidence, truth, provenance hash and content-addressed artifact identity before deriving source IDs internally.
- PortfolioIntent items must exactly match its source SelectionArtifact, and source artifact truth states participate in its output ceiling.

`PortfolioService` remains the sole formal publisher of `TargetWeightVector`. Track F performs no trade or Backtest invocation.

## Truth and admission

Compilation yields `PASSED_NOT_ADMITTED` and a `PRE_ALPHA` ceiling; validation success is never treated as Formal admission. Binding and all output factories use the existing A0 meet/propagation functions. Therefore every output ceiling is less than or equal to the meet of the definition, Dataset/Factor/materialization, Snapshot, Universe, calendar and optional admitted-artifact upstreams. A PRE_ALPHA input cannot produce FORMAL output.
