# V3 recommendations

## Overall conclusion

Build canonical Strategy IR now, but treat this research as architecture and implementation input rather than a contract edit. The existing V3 ASL already exposes the right seams—validate draft, compile IR, publish immutable StrategyVersion, worker isolation and handoff. `StrategyVersion` should remain definition identity, consistent with Catalog `strategy_version`; exact evaluation inputs belong to a separate binding/run boundary. **Disposition: ADOPT**.

## Priority recommendations

| Priority | Recommendation | Concrete V3 fit | Disposition |
|---|---|---|---|
| P0 | Make canonical Strategy IR the single semantic authority | Replace `StrategyDraft.code` as de facto authority with semantic IR plus projections | ADOPT |
| P0 | Freeze immutable StrategyDefinitionVersion over canonical IR, component/operator semantics, compiler/runtime interpretation and code dependency hashes | Current Catalog `strategy_version` and `publishStrategyVersion` remain the definition seam | ADOPT |
| P0 | Enforce pure evaluation to SignalArtifact/SelectionArtifact/PortfolioIntent | No DB, account or Backtest engine capability in Strategy worker | ADOPT |
| P0 | Publish a separate immutable StrategyEvaluationBindingVersion with exact DatasetVersion/DataSnapshotVersion/UniverseVersion, calendar, PIT/knowledge context, evaluation clock and environment | Aligns with ProjectContextRevision and current `backtest_run_spec` ownership of bound run inputs | ADOPT |
| P0 | Enforce upstream truth/admission ceiling on Signal/Selection/PortfolioIntent | PRE_ALPHA/NOT_FORMAL inputs cannot yield FORMAL outputs; no individual gate upgrades truth | ADOPT |
| P0 | Reuse V3 Worker/control-plane ownership | Worker stages outputs; supervisor owns IDs, persistence and truth | ADOPT |
| P1 | Introduce a component registry with typed ports, closed parameters and pinned semantic versions | One descriptor drives backend validation, React Flow palette and Monaco types | ADOPT |
| P1 | Implement Visual/Code revision protocol and semantic source maps | Split panes edit one revision; semantic CAS prevents drift | ADOPT |
| P1 | Add semantic diff alongside Monaco text diff | Existing accept/reject hunks become IR operations | ADAPT |
| P1 | Separate selector, signal and allocation outputs | Makes multi-instrument boundary and provenance explicit | ADAPT |
| P1 | Keep slippage/fills/order algorithms out of Strategy IR | Bind them in Backtest/Execution scenario | ADOPT |
| P2 | Add typed custom-code nodes only after sandbox/determinism gates | Reuse worker resource limits, deny capabilities and staged outputs | ADAPT |
| P3 | Design stateful intraday/checkpoint nodes | Requires separate event-clock/recovery work | FUTURE |

## Hikyuu decisions for V3

| Reference lesson | V3 action | Disposition |
|---|---|---|
| Explicit Environment/Condition/Signal/Exit/MM/Selector/AF slots | Use as component vocabulary and typed-role catalog | ADAPT |
| Logical/arithmetic component composition | Support explicit typed graph operators | ADOPT |
| Required-part validation and broad component tests | Port test categories and fail early | ADOPT |
| Clone/reset awareness | Guarantee evaluation isolation, but do not expose share flags in persisted semantics | ADAPT |
| Signal separate from MoneyManager | Preserve separation; use explicit state snapshot for sizing | ADAPT |
| Selector separate from AllocateFunds | Preserve selection artifact before portfolio intent | ADAPT |
| System directly owns TradeManager and calls buy/sell | Do not adopt | REJECT |
| Slippage inside System | Move to Backtest/Execution profile | REJECT |
| Mutable parameter objects and cached component instances | Replace with immutable canonical nodes and content-addressed caches | REJECT |

## Current V3 gap-to-target

| Current state | Gap | Next implementation input | Disposition |
|---|---|---|---|
| `StrategyDraft` stores mode/code/review/validation/handoff | No semantic IR/projection split or separate evaluation-binding draft | Define DraftSemanticIR, DraftEvaluationBinding, VisualProjection, CodeProjection and independent revisions | ADAPT |
| React Flow uses hard-coded demo nodes/edges | Visual graph is presentation, not canonical semantics | Render registry-backed IR nodes and persist layout separately | ADAPT |
| Monaco stores a Python-like string on blur | No parser, type system, source map or atomic lowering | Add constrained DSL parser/lowerer and pending-buffer state | ADAPT |
| Split renders both editors | No shared semantic revision | Subscribe both to IR revision and source map | ADAPT |
| Validation checks only whether code contains `Universe.ref` in demo store | Not semantic, typed or authoritative | Route to backend IR validation diagnostics | REJECT |
| Handoff ID derives from editable draft version | Not enough immutability/provenance | Require published StrategyDefinitionVersion plus exact StrategyEvaluationBindingVersion/output references | ADAPT |
| ASL compile request pins draft hash/artifact/compiler | Good seam; IR payload not defined | Adopt canonical envelope/hash rules from this study | ADOPT |
| ASL publish requires matching IR/validation and immutable StrategyVersion | Good definition invariant | Add component/runtime/code provenance to definition identity; keep evaluation data out | ADOPT |
| Catalog `strategy_version` and `backtest_run_spec` are separate | Already the correct ownership boundary | Map the former to definition identity and the latter to exact binding/run identity | ADOPT |
| Worker protocol denies identity/truth ownership and has resource controls | Strong base | Add strategy-specific capability and output validators | ADOPT |

## Proposed next-phase deliverables

| Deliverable | Acceptance focus | Disposition |
|---|---|---|
| Strategy IR v1 schema and canonicalization spec | Cross-language canonical fixtures and hash stability | ADOPT |
| Component descriptor/catalog v1 | Typed ports, closed params, defaults, versions and diagnostics | ADOPT |
| Draft revision/projection contract | Atomic Visual/Code lowering and stale-edit behavior | ADOPT |
| SignalArtifact and PortfolioIntent candidate schemas | Clear separation from orders/accounts and full provenance | ADAPT |
| Strategy evaluator Worker profile | No DB/network/account/engine; bounded deterministic execution | ADOPT |
| StrategyDefinitionVersion identity profile | IR, component/operator semantics, compiler/runtime interpretation and custom dependency hashes only | ADOPT |
| StrategyEvaluationBindingVersion | Exact Dataset/Snapshot/Universe, calendar, PIT/knowledge context, evaluation clock and environment | ADOPT |
| Truth/admission propagation gate | Compute downstream ceiling from all required upstream admission plus Strategy validation/provenance | ADOPT |
| BacktestHandoffDraft refinement proposal | References published version/artifacts without changing Backtest research scope | ADAPT |
| Conformance test corpus | Round trip, PIT, security, reproducibility and failure atomicity | ADOPT |

## Ten core conclusions

1. Canonical Strategy IR, not React Flow JSON or Python text, should define strategy semantics. **Disposition: ADOPT**.
2. Visual and Code must be lossless, revisioned projections of the same IR; unsupported code must fail atomically. **Disposition: ADOPT**.
3. StrategyDefinitionVersion (the meaning of existing V3 `StrategyVersion`) is immutable and excludes concrete Dataset/Snapshot/Universe/time/environment bindings. **Disposition: ADOPT**.
4. Strategy evaluation must be pure and side-effect free: no database, account or Backtest engine access. **Disposition: ADOPT**.
5. Strategy outputs SignalArtifact and/or PortfolioIntent; orders, fills and account mutations are downstream responsibilities. **Disposition: ADOPT**.
6. Hikyuu's component vocabulary and tests are mature inputs, but its TradeManager-owning System runtime is not V3's boundary. **Disposition: ADAPT**.
7. Selector must operate only on a pinned candidate universe and emit an explicit selection artifact before allocation. **Disposition: ADAPT**.
8. Signal generation and sizing/allocation remain separate; state enters only as an immutable, timestamped PortfolioStateSnapshot. **Disposition: ADAPT**.
9. Evaluation/run identity combines StrategyDefinitionVersion with exact StrategyEvaluationBindingVersion, and downstream truth cannot exceed the least-admitted required upstream input. **Disposition: ADOPT**.
10. Custom code is acceptable only as a typed, content-addressed Worker node with deny-by-default capabilities, hard resource bounds and supervisor-validated outputs. **Disposition: ADOPT**.

## Tradeoffs accepted

| Tradeoff | Decision | Disposition |
|---|---|---|
| Constrained DSL reduces arbitrary expressiveness | Use explicit CustomCode nodes for escape hatches; equivalence and safety are worth the constraint | ADAPT |
| Exact data binding creates more evaluation/run identities, not more strategy definitions | One StrategyDefinitionVersion can be evaluated against multiple immutable StrategyEvaluationBindingVersions | ADOPT |
| Full provenance and canonicalization add publish latency | Cache by verified content hash; do not weaken identity | ADOPT |
| Pure strategy cannot observe live mutable account | Supply versioned PortfolioStateSnapshot when the hypothesis genuinely needs holdings; never a handle | ADAPT |
| Separate execution scenarios can yield multiple results per strategy | This is desirable: hypothesis identity remains stable while execution assumptions vary | ADOPT |

## Explicit non-recommendations

| Non-recommendation | Disposition |
|---|---|
| Do not modify current Portfolio/Risk ASL contracts in this study | REJECT |
| Do not broaden this work into a Backtest engine comparison | REJECT |
| Do not copy Hikyuu, LEAN or WonderTrader component code | REJECT |
| Do not run custom strategy code in Electron renderer/main or backend API process | REJECT |
| Do not permit silent Demo/Formal or data-source fallback | REJECT |
