# Strategy component invariants

These are proposed next-phase invariants, not a formal ASL change. Every rule is classified for implementation planning.

## Global definition and evaluation invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-001 | One canonical Strategy IR is the sole semantic authority. Visual layout and code formatting are projections and cannot add hidden semantics. | ADOPT |
| SCI-002 | A published `StrategyDefinitionVersion` is immutable. Any semantic edit, dependency change, parameter-default change or custom-code change creates a new definition version. Existing V3 `StrategyVersion` maps to this definition identity. | ADOPT |
| SCI-003 | `StrategyDefinitionVersion` identity is derived only from canonical IR bytes, component/operator semantic versions, compiler/runtime interpretation profile and referenced custom-code/dependency hashes; concrete data/time/environment bindings and mutable display metadata are excluded. | ADOPT |
| SCI-004 | Evaluation is a pure function of `StrategyDefinitionVersion`, exact `StrategyEvaluationBindingVersion` and explicit evaluation request. | ADOPT |
| SCI-005 | Strategy reads only capability-scoped, read-only input artifacts supplied by the orchestrator. It cannot discover or query a database, filesystem, network or secret store. | ADOPT |
| SCI-006 | Strategy cannot write cash, holdings, orders, fills or broker state and cannot call a Backtest/Execution engine. | ADOPT |
| SCI-007 | Strategy emits only schema-valid SignalArtifact, SelectionArtifact and/or PortfolioIntent plus diagnostics and provenance. | ADOPT |
| SCI-008 | Node evaluation order is determined by typed data dependencies and explicit priority/merge operators, never UI position, JSON object order or hash-map iteration. | ADOPT |
| SCI-009 | All numeric outputs reject NaN and infinities; decimal/weight precision, rounding and comparison tolerances are part of the runtime profile. | ADOPT |
| SCI-010 | A failed, timed-out or cancelled evaluation publishes no partial financial output as successful truth. Staged artifacts remain non-authoritative. | ADOPT |

## Input and time invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-011 | Each evaluation binds exact DatasetVersion, DataSnapshotVersion and UniverseVersion IDs plus content hashes/member artifact hash. Aliases such as `latest` are rejected after draft resolution. | ADOPT |
| SCI-012 | `as_of`, decision time, observation cutoff, market calendar, timezone, bar frequency, adjustment basis and availability-time policy are explicit. | ADOPT |
| SCI-013 | A component cannot expand the universe through ad hoc symbol lookup. Cross-sectional selection consumes only the bound candidate universe. | ADOPT |
| SCI-014 | Missing, stale, unavailable and not-yet-known values are distinct states; no silent forward fill or fallback is allowed. | ADOPT |
| SCI-015 | Dataset column references are stable field IDs plus schema/version, not display names. | ADOPT |
| SCI-016 | Historical replay may use a PortfolioStateSnapshot only when its timestamp and source run are explicit; it is not a live account handle. | ADAPT |
| SCI-017 | `StrategyEvaluationBindingVersion` immutably binds exact DatasetVersion, DataSnapshotVersion, UniverseVersion, calendar, knowledge/PIT context, evaluation clock and environment. Changing any binding never changes `StrategyDefinitionVersion`. | ADOPT |
| SCI-018 | Evaluation/run identity includes both `StrategyDefinitionVersion` and `StrategyEvaluationBindingVersion`; the same definition over different bindings creates different evaluation/run identities. | ADOPT |

## Component port invariants

| Component role | Required contract | Forbidden behavior | Disposition |
|---|---|---|---|
| Universe binding | Resolve one pinned candidate universe and membership chronology | Dynamic DB query, hidden watchlist, `latest` at evaluation | ADOPT |
| Environment/regime | Time-indexed gate or score independent of a specific instrument unless the type says otherwise | Reading account or orders | ADAPT |
| Condition/eligibility | Typed boolean/score mask over explicit input ports | Backreference to mutable Signal/TradeManager objects | ADAPT |
| Signal | Rows keyed by instrument/time with value, direction/meaning, confidence/quality and source node | Quantity/order/fill mutation | ADOPT |
| Stoploss/takeprofit/goal | Exit constraint or exit-intent attributes with explicit price basis and precedence | Executing liquidation or reading hidden position state | ADAPT |
| Sizing/money management | Pure transform of signals, constraints and optional PortfolioStateSnapshot into desired exposure | Mutating an account or consuming fills by callback | ADAPT |
| Selector | Deterministic selection/ranking from the bound candidate universe, including stable tie-break | Expanding universe or running child strategies with shared mutable state | ADAPT |
| Allocation | Desired instrument/exposure weights or allocation instructions, cash policy and constraint context | Owning shadow cash accounts | ADAPT |
| Slippage | Not a Strategy IR semantic component; referenced only by downstream execution/backtest profile | Affecting StrategyDefinitionVersion identity | REJECT |

## Composition invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-020 | The semantic graph is a typed directed acyclic graph. Stateful nodes must declare bounded state and transition semantics; undeclared cycles are invalid. | ADOPT |
| SCI-021 | Each port declares cardinality (`scalar`, `timeseries`, `cross_section`, `artifact`), value type, time basis, universe basis and null policy. | ADOPT |
| SCI-022 | Logical combination of gates defines three-valued/missing semantics and short-circuit behavior. | ADOPT |
| SCI-023 | Signal merge defines conflict behavior for simultaneous long/short/exit intents and a stable precedence rule. | ADOPT |
| SCI-024 | Environment/Condition/Signal/Exit precedence is represented by explicit operators or a versioned policy node, not hard-coded runtime order. | ADAPT |
| SCI-025 | Selector output is materialized before allocation; allocation cannot silently re-rank or add members. | ADOPT |
| SCI-026 | An allocation result states whether absent instruments mean zero target, unchanged target or out-of-scope. | ADOPT |
| SCI-027 | Component defaults are expanded into canonical IR; compiler upgrades cannot retroactively change an existing StrategyDefinitionVersion. | ADOPT |
| SCI-028 | Duplicate node IDs, dangling edges, incompatible ports and unreachable declared outputs are compile errors. | ADOPT |
| SCI-029 | Semantic node IDs survive formatting/layout changes and are used in diagnostics and provenance paths. | ADOPT |

## Parameter invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-030 | Each component type is identified by a stable namespace, type name and semantic version. | ADOPT |
| SCI-031 | Parameters use a closed schema; unknown fields, ambiguous units and out-of-range values fail validation. | ADOPT |
| SCI-032 | Canonical values distinguish integer, decimal string, boolean, enum, timestamp, duration and artifact reference. Binary floating-point serialization is not an identity boundary. | ADOPT |
| SCI-033 | Parameter expressions may reference only declared constants or upstream typed ports. Environment variables and wall-clock calls are forbidden. | ADOPT |
| SCI-034 | Randomness requires an explicit seed, RNG algorithm/version and deterministic partitioning rule; otherwise the component is not publishable as reproducible. | ADOPT |
| SCI-035 | Secret values are never Strategy IR parameters. External services are unavailable during deterministic evaluation. | ADOPT |

## Output and provenance invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-040 | Every output row carries or inherits `strategy_definition_version_id`, `strategy_evaluation_binding_version_id`, output schema version, evaluation run ID, `as_of`, bound universe, truth state and source node path. | ADOPT |
| SCI-041 | Provenance includes canonical IR hash, compiler profile/hash, custom-code artifact hash, dependency lock hash, worker image/runtime hash and exact input IDs/hashes. | ADOPT |
| SCI-042 | Selection and signal artifacts preserve exclusion/missing diagnostics so “not selected” is distinguishable from “not evaluated.” | ADOPT |
| SCI-043 | PortfolioIntent records whether it is absolute or relative, target scope, cash semantics, rebalance semantics and constraint context. | ADOPT |
| SCI-044 | StrategyDefinitionVersion identity is not changed by Risk. Risk emits a separately identified transformation from PortfolioIntent/TargetWeightVector to RiskAdjustedWeightVector. | ADOPT |
| SCI-045 | Downstream Backtest/Execution references published intent artifacts; it cannot reach into an editable StrategyDraft. | ADOPT |
| SCI-046 | Strategy evaluation cannot raise truth. SignalArtifact, SelectionArtifact and PortfolioIntent truth is capped by the least-admitted required upstream Dataset/Snapshot/Universe/calendar/PIT/environment input and by Strategy validation/provenance admission. | ADOPT |
| SCI-047 | Any required PRE_ALPHA or NOT_FORMAL upstream input caps all evaluation outputs at NOT_FORMAL. | ADOPT |
| SCI-048 | FORMAL output is eligible only when every required upstream input is FORMAL-admitted and Strategy validation/provenance gates pass. | ADOPT |
| SCI-049 | `PUBLISHED`, `STRICT_PIT` or Strategy validation `PASS` alone, and any incomplete combination of them, cannot upgrade an artifact to FORMAL. | ADOPT |

## Custom-code invariants

| ID | Invariant | Disposition |
|---|---|---|
| SCI-050 | Custom code is a typed node with declared inputs/outputs, entrypoint, language/runtime, source artifact and dependency lock. It is not an unrestricted whole-strategy process. | ADOPT |
| SCI-051 | Custom code runs in a dedicated Worker with no network, no database credentials, read-only mounted inputs, isolated scratch space and deny-by-default capabilities. | ADOPT |
| SCI-052 | CPU, wall time, memory, process/thread count, output bytes and log bytes are bounded and recorded. | ADOPT |
| SCI-053 | Worker responses are schema-validated; stdout/logging is not a financial result channel. | ADOPT |
| SCI-054 | Dynamic imports, native extensions, subprocesses and nondeterministic system APIs are denied unless a separately reviewed runtime profile explicitly permits them. | ADOPT |
| SCI-055 | A custom-code node cannot receive repository/identity/persistence ports and cannot publish V3 truth. The supervisor stages and validates outputs. | ADOPT |
| SCI-056 | Byte-identical inputs on the same runtime profile must produce byte-identical canonical outputs; divergence is a reproducibility failure. | ADOPT |

## Deferred areas

| Area | Boundary for this study | Disposition |
|---|---|---|
| Formal Portfolio/Risk ASL wire shape | Prompt D provides reference input; no contract is changed here | FUTURE |
| Stateful intraday strategy checkpoint format | Requires execution-clock and recovery design beyond this reference study | FUTURE |
| Distributed graph scheduling | Canonical IR must not depend on it; choose after local evaluator semantics stabilize | FUTURE |
| Live external feature services | Incompatible with deterministic baseline until snapshots and attestations exist | FUTURE |
