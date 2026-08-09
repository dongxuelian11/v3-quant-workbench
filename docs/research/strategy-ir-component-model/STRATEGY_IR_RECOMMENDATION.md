# Canonical Strategy IR recommendation

## Decision

V3 should establish a versioned, canonical, declarative Strategy IR as the only semantic strategy definition. StrategyDraft remains editable; publishing compiles and validates its canonical IR into an immutable `StrategyDefinitionVersion`. Evaluation separately binds exact immutable inputs and emits SignalArtifact and/or PortfolioIntent. It never reads a database, mutates an account or invokes Backtest/Execution. The existing V3 Catalog term `StrategyVersion` should mean this definition identity. **Disposition: ADOPT**.

The IR is a component graph, not a workflow engine and not a serialized Python object. It captures financial intent and evaluation semantics; task scheduling, worker leases, storage ports, fills and backtest scenarios remain outside it. **Disposition: ADOPT**.

## Recommended authority model

```text
StrategyDraft
  ├─ semantic Strategy IR  <── sole authority
  ├─ VisualProjection      <── layout/selection only
  └─ CodeProjection        <── generated/parsed view + source map
             │ validate + canonicalize + hash
             ▼
Immutable StrategyDefinitionVersion
             │ bind StrategyEvaluationBindingVersion
             ▼
SignalArtifact / SelectionArtifact / PortfolioIntent
             │ separate Portfolio/Risk/Backtest/Execution pipeline
             ▼
Targets, orders, fills, results
```

| Decision | Rationale | Disposition |
|---|---|---|
| Semantic IR is authoritative | Avoids graph/code split-brain and makes identity/hash independent of UI formatting | ADOPT |
| Visual projection is non-semantic | Coordinates, zoom, groups, comments and collapsed panels should not create a new StrategyDefinitionVersion | ADOPT |
| Code is a constrained projection | A parseable DSL can round-trip; unsupported code becomes an explicit typed CustomCode node | ADAPT |
| Editable draft and immutable version are different objects | Autosave/review can remain flexible without weakening published identity | ADOPT |
| Evaluation outputs artifacts, not side effects | Enables replay, provenance and multiple downstream engines | ADOPT |

## Proposed IR envelope

The following is illustrative implementation input, not a frozen wire contract.

```json
{
  "ir_schema": "v3.strategy-ir/1.0",
  "semantic_api": "v3.strategy-components/1.0",
  "required_bindings": {
    "dataset": {"type": "DatasetVersion", "required_fields": ["factor.momentum_12m"]},
    "snapshot": {"type": "DataSnapshotVersion"},
    "universe": {"type": "UniverseVersion"},
    "calendar": {"type": "CalendarVersion"},
    "knowledge_context": {"type": "PitKnowledgeContext"},
    "evaluation_clock": {"type": "EvaluationClock"},
    "environment": {"type": "EnvironmentProfile"}
  },
  "semantics": {
    "numeric_profile": "decimal128-v1",
    "missing_policy": "EXPLICIT",
    "stable_order": ["instrument_id"],
    "random": null
  },
  "nodes": [
    {
      "id": "signal.momentum",
      "type": "v3.signal.rank/1.0",
      "params": {"field_id": "factor.momentum_12m", "ascending": false},
      "inputs": {"universe": {"binding": "universe"}, "dataset": {"binding": "dataset"}}
    },
    {
      "id": "selection.top50",
      "type": "v3.selector.top_n/1.0",
      "params": {"count": 50, "tie_break": ["instrument_id"]},
      "inputs": {"score": {"node": "signal.momentum", "port": "score"}}
    },
    {
      "id": "allocation.equal",
      "type": "v3.allocation.equal_weight/1.0",
      "params": {"cash_policy": "RESIDUAL"},
      "inputs": {"selection": {"node": "selection.top50", "port": "selection"}}
    }
  ],
  "outputs": {
    "signal": {"node": "signal.momentum", "port": "signal_artifact"},
    "portfolio_intent": {"node": "allocation.equal", "port": "portfolio_intent"}
  },
  "custom_code": []
}
```

## Envelope rules

| Field/area | Recommendation | Disposition |
|---|---|---|
| `ir_schema` | Version syntax and canonicalization rules independently from component semantics | ADOPT |
| `semantic_api` | Pin the component catalog/runtime API used to interpret node types | ADOPT |
| `required_bindings` | Declare typed input slots and required fields, but exclude concrete Dataset/Snapshot/Universe/calendar/time values from definition identity | ADOPT |
| Evaluation binding | Put exact input IDs/hashes, calendar, decision/PIT context, evaluation clock and environment in a separate immutable `StrategyEvaluationBindingVersion` | ADOPT |
| `semantics` | Pin numeric, null, ordering and RNG profiles | ADOPT |
| `nodes` | Store a stable-ID typed DAG; sort canonically by node ID; reject duplicate/dangling nodes | ADOPT |
| `params` | Closed typed schema with defaults expanded and decimals represented canonically | ADOPT |
| `inputs` | Reference only bindings, upstream node ports or canonical constants | ADOPT |
| `outputs` | Declare all publishable outputs explicitly; unreachable calculations do not silently become outputs | ADOPT |
| UI layout | Store in a separate draft projection artifact keyed by semantic node ID | ADOPT |
| Execution/slippage/broker config | Keep outside Strategy IR and bind in Backtest/Execution request | REJECT |

## Component type model

Each registered component descriptor should contain:

| Descriptor field | Purpose | Disposition |
|---|---|---|
| Stable `namespace/name@semver` | Prevent meaning from changing behind a friendly label | ADOPT |
| Input/output port schemas | Enable graph validation, Monaco types and visual connection rules from one source | ADOPT |
| Closed parameter schema | Validate type/range/unit and generate both forms | ADOPT |
| Determinism declaration | State whether randomness/state exists and what must be pinned | ADOPT |
| Capability declaration | Built-ins should need only named artifact reads; custom code is deny-by-default | ADOPT |
| Canonical lowering hook | Convert DSL and Visual nodes into the same normalized representation | ADOPT |
| Diagnostic/source-map metadata | Map errors back to node, port and code span | ADOPT |
| Migration function | Explicitly create a new IR/version; never reinterpret old bytes in place | ADOPT |

Recommended v1 semantic roles are `input`, `transform`, `environment`, `condition`, `signal`, `exit_policy`, `selector`, `allocation`, `merge`, `schedule`, `custom_code` and `output`. These are roles, not necessarily one concrete node type each. **Disposition: ADAPT**.

Slippage, commissions, fills, broker restrictions and order algorithms are execution scenario components. They may be displayed beside a strategy, but cannot be semantic Strategy IR nodes. **Disposition: REJECT**.

## Canonicalization and identity

Recommended publish calculation:

```text
ir_sha256 = SHA256(canonical_json(expand_defaults(normalize(validated_ir))))

strategy_definition_version_content_sha256 = SHA256(canonical_json({
  ir_sha256,
  ir_schema,
  semantic_api,
  compiler_profile_id,
  compiler_binary_sha256,
  custom_code_artifact_hashes,
  dependency_lock_hashes,
  deterministic_runtime_profile_id
}))
```

| Identity rule | Rationale | Disposition |
|---|---|---|
| Use a specified canonical JSON profile (for example RFC 8785 plus V3 restrictions) | Same meaning must yield the same bytes across clients | ADOPT |
| Reject ambiguous floats; use integers or normalized decimal strings for identity-sensitive values | Avoid cross-language formatting drift | ADOPT |
| Sort node and edge representations by semantic IDs/ports | UI insertion order must not affect identity | ADOPT |
| Expand component defaults before hashing | A future catalog default cannot alter an old version | ADOPT |
| Exclude layout, cursor, comments, display labels and timestamps from semantic hash | Non-semantic edits should not create a version | ADOPT |
| Include code/dependency/runtime/compiler hashes | Custom code and lowering semantics are part of executable identity | ADOPT |
| Exclude concrete Dataset/Snapshot/Universe/calendar/decision-time/PIT values | The same strategy definition remains the same definition when evaluated on different admitted inputs | ADOPT |
| Never hash generated StrategyDefinitionVersion ID into its own content identity | Prevent circular identity | ADOPT |

There is no combined definition-plus-data identity named `StrategyVersion`. `StrategyDefinitionVersion` is determined only by canonical IR, component/operator semantic versions, compiler/runtime interpretation profile, custom-code hashes and dependency hashes. `StrategyEvaluationBindingVersion` separately binds exact DatasetVersion, DataSnapshotVersion, UniverseVersion, calendar, knowledge/PIT context, evaluation clock and environment. Evaluation/run identity is derived from both identities plus the explicit evaluation request. Changing data creates a new binding and run, not a new strategy definition. **Disposition: ADOPT**.

This matches the current V3 Catalog boundary: `strategy_version` stores the Strategy IR artifact, validation artifact, content hash and compiler profile, while `backtest_run_spec` separately references `strategy_version_id`, dataset, universe, snapshot and environment/run inputs. In next-phase naming, current `strategy_version` is the persisted `StrategyDefinitionVersion`; `backtest_run_spec` may reference a reusable `StrategyEvaluationBindingVersion` or carry semantically equivalent exact bindings. **Disposition: ADOPT**.

## Evaluation contract

Conceptually:

```text
evaluate(
  strategy_definition_version,
  strategy_evaluation_binding_version,
  read_only_artifact_handles,
  optional_portfolio_state_snapshot
) -> {
  signal_artifact?,
  selection_artifact?,
  portfolio_intent?,
  diagnostics_artifact,
  provenance_manifest
}
```

| Runtime boundary | Recommendation | Disposition |
|---|---|---|
| Data access | Orchestrator resolves IDs and provides bounded read tickets/artifact handles; strategy has no repository API | ADOPT |
| Account access | Optional immutable PortfolioStateSnapshot only; no live TradeManager | ADOPT |
| Engine access | No Backtest/Execution handle is supplied | ADOPT |
| Time | Evaluation clock and observation cutoff are injected; wall clock is unavailable | ADOPT |
| Output | Worker stages schema-valid artifacts; supervisor publishes after hash/provenance checks | ADOPT |
| Failure | No partial successful artifact; deterministic error taxonomy and node path | ADOPT |

## Upstream truth and admission ceiling

Strategy evaluation can preserve or lower upstream truth, never raise it. The maximum truth state of SignalArtifact, SelectionArtifact and PortfolioIntent is bounded by the least-admitted required upstream input and by Strategy validation/provenance gates. **Disposition: ADOPT**.

```text
downstream_truth_ceiling = min(
  DatasetVersion/DataSnapshotVersion truth and admission,
  UniverseVersion truth and admission,
  calendar and knowledge/PIT context admission,
  evaluation environment admission,
  StrategyDefinitionVersion validation/provenance admission
)
```

`PRE_ALPHA` is `NOT_FORMAL`; any required PRE_ALPHA/NOT_FORMAL input makes every evaluation output NOT_FORMAL. Only when all required upstream inputs satisfy their corresponding FORMAL admission and Strategy validation/provenance gates pass may the supervisor publish a FORMAL downstream artifact. `PUBLISHED`, `STRICT_PIT` and Strategy validation `PASS` are each necessary only where their gate requires them; none alone, nor any incomplete subset, upgrades truth to FORMAL. **Disposition: ADOPT**.

The worker cannot choose or raise truth state. It returns staged candidates with inherited evidence; the V3 control plane computes the ceiling and performs admission. **Disposition: ADOPT**.

## SignalArtifact recommendation

Minimum inherited or per-row fields should include `instrument_id`, `event_time`, `as_of`, `signal_kind`, `value`, optional `direction`, optional `confidence`, `source_node_id`, `strategy_definition_version_id`, `strategy_evaluation_binding_version_id`, `universe_version_id`, `evaluation_run_id`, inherited truth/admission evidence and quality/missing flags. **Disposition: ADOPT**.

Signals are observations/preferences, not quantities, weights or orders. A strategy may also emit PortfolioIntent when allocation is part of its hypothesis; downstream code must still treat that as desired state rather than executable instruction. **Disposition: ADOPT**.

## PortfolioIntent recommendation

PortfolioIntent expresses “what the strategy wants to hold” at a rebalance decision. It should state target scope, absolute/relative semantics, selected instruments, desired exposures/weights or allocation instructions, cash policy, rebalance time, source signals/version, universe, constraints context and provenance. Prompt D should determine whether the normalized TargetWeightVector becomes the stable cross-domain wire contract. **Disposition: ADAPT**.

## Custom-code Worker boundary

Custom code should be a typed node, not a loophole around the IR.

| Control | Recommendation | Disposition |
|---|---|---|
| Packaging | Content-addressed source artifact, explicit entrypoint, language/runtime, dependency lock and license/SBOM metadata | ADOPT |
| Inputs | Arrow/Parquet or equivalent bounded read-only artifacts plus a small canonical request; no raw DB connection | ADOPT |
| Capabilities | No network, secrets, repository ports, account, broker, Backtest engine or arbitrary filesystem | ADOPT |
| Isolation | Separate OS process/container/sandbox Worker with read-only root/input mounts and isolated scratch | ADOPT |
| Resources | CPU/wall/memory/process/thread/output/log limits enforced by supervisor | ADOPT |
| Determinism | Fixed locale/timezone/hash seed/thread policy/RNG; wall clock and ambient environment removed | ADOPT |
| Validation | Validate output schema, instrument/time/universe membership, finiteness, row limits and canonical ordering | ADOPT |
| Publication | Worker proposes staged outputs; V3 control plane owns IDs, hashes, provenance and publication | ADOPT |
| Native extensions | Deny in the baseline profile; allow only in separately pinned/reviewed profiles | ADAPT |

The existing V3 worker protocol already states that workers own no identities or truth. Strategy evaluation should reuse that control-plane invariant instead of creating a special in-process executor. **Disposition: ADOPT**.

## Compatibility with current V3

| Current V3 seam | Recommendation | Disposition |
|---|---|---|
| `StrategyDraft` holds `mode`, `code`, validation and review state | Split semantic IR, VisualProjection and CodeProjection while preserving a draft facade for UI | ADAPT |
| React Flow graph currently uses hard-coded demo nodes | Bind it to registry descriptors and semantic node IDs | ADAPT |
| Monaco edits a Python-like demo string on blur | Move to incremental parse/diagnostics; commit semantic changes transactionally only after successful lowering | ADAPT |
| Split shows graph and code simultaneously | Both subscribe to the same draft IR revision and source map | ADOPT |
| `compileStrategyIr` accepts draft artifact/hash and compiler profile | Preserve the seam; strengthen the artifact shape and canonical validation | ADOPT |
| `publishStrategyVersion` requires matching IR/validation artifacts | Preserve it as definition publication; compiler/runtime/code provenance belongs to definition identity, not evaluation data | ADOPT |
| Catalog `strategy_version` and `backtest_run_spec` are separate | Treat `strategy_version` as definition identity and keep exact evaluation/run bindings in the run-spec/binding boundary | ADOPT |
| `BacktestHandoffDraft` exists in the UI | Handoff must reference published StrategyDefinitionVersion, exact evaluation binding and immutable outputs, not editable code | ADAPT |
| Renderer has no direct filesystem access | Preserve; custom code never executes in renderer/main process | ADOPT |

## Rejected alternatives

| Alternative | Why rejected | Disposition |
|---|---|---|
| Code is canonical and Visual reverse-engineers arbitrary Python | General code cannot be losslessly reconstructed as a stable component graph | REJECT |
| Visual JSON and code are independent peer definitions | Creates unavoidable drift and ambiguous StrategyDefinitionVersion identity | REJECT |
| Persist live component instances like Hikyuu serialization | Captures hidden caches/shared state and runtime objects | REJECT |
| Strategy calls Backtest for previews during evaluation | Couples definition to a specific engine and creates recursive provenance | REJECT |
| Strategy mutates a paper account to derive signals | Mixes signal, sizing, execution and state ownership | REJECT |

## Phased implementation input

| Phase | Input to next implementation plan | Disposition |
|---|---|---|
| 1 | Freeze IR envelope, canonicalization, component descriptor and diagnostics schemas; implement pure built-ins only | ADOPT |
| 2 | Make Visual and constrained Code projections round-trip through IR with conformance tests | ADOPT |
| 3 | Publish immutable StrategyDefinitionVersion; separately publish exact StrategyEvaluationBindingVersion and evaluate to truth-ceiling-limited artifacts | ADOPT |
| 4 | Add typed custom-code Worker node after capability/resource/determinism tests pass | ADAPT |
| 5 | Add stateful intraday/checkpoint semantics only after pure batch semantics are stable | FUTURE |
