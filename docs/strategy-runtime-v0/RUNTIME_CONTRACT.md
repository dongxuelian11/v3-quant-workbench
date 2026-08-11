# Deterministic Strategy runtime V0

## Ownership

Track F is the canonical owner of:

- `StrategyDefinitionVersion`
- `StrategyEvaluationBindingVersion`
- the closed Strategy component registry/compiler/evaluator
- `SignalArtifact`
- `SelectionArtifact`
- `PortfolioIntent`

It consumes, but does not redefine, A0 truth/admission and Track C Dataset/Factor semantics. It defines no `ModelVersion` or `PredictionArtifact`. A future model-owned artifact may cross only the generic exact admitted-artifact reference boundary.

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
- exact Snapshot content reference;
- exact Universe definition, membership artifact/hash and canonical member IDs;
- evaluation period and knowledge cutoff;
- exact calendar hash and IANA timezone;
- compiler, runtime and environment fingerprints;
- each required input artifact ID/hash/truth state;
- optional generic admitted-artifact references owned by another domain.

`latest`, `current`, `unresolved`, missing slots and content mismatches fail closed. Changing Dataset/Snapshot/Universe/time changes binding identity, never definition identity.

## Pure deterministic evaluator

The evaluator accepts only a definition, its exact binding and in-memory exact input artifacts. It has no repository, database, filesystem, network, live account, Backtest, broker, order or fill handle. All runtime inputs must match bound artifact IDs/hashes, share one injected decision time, lie within the evaluation period/cutoff, and contain no instrument outside the bound universe.

The only financial outputs are:

- `SignalArtifact`: exact definition/binding/input linkage, decision-time semantics, per-instrument value/direction, missing diagnostics, source node path, compiler/runtime, truth ceiling and provenance hash.
- `SelectionArtifact`: exact Universe membership boundary, stable ranks/tie-breaks, selected/excluded instruments, source reasons/paths, truth ceiling and provenance hash.
- `PortfolioIntent`: desired exposure proposal, scores, constraints and rebalance intent. It cannot carry `TargetWeightVector`, orders, fills or execution fields.

`PortfolioService` remains the sole formal publisher of `TargetWeightVector`. Track F performs no trade or Backtest invocation.

## Truth and admission

Compilation yields `PASSED_NOT_ADMITTED` and a `PRE_ALPHA` ceiling; validation success is never treated as Formal admission. Binding and all output factories use the existing A0 meet/propagation functions. Therefore every output ceiling is less than or equal to the meet of the definition, Dataset/Factor/materialization, Snapshot, Universe, calendar and optional admitted-artifact upstreams. A PRE_ALPHA input cannot produce FORMAL output.
