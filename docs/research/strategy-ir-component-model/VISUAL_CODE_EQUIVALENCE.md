# Visual / Code equivalence

## Equivalence definition

Visual and Code are equivalent when both lower to byte-identical canonical Strategy IR after normalization and default expansion. Textual equality, node coordinates and pretty-printing are irrelevant. **Disposition: ADOPT**.

```text
VisualProjection ──lower──┐
                         ├── Canonical Strategy IR ──hash── semantic revision
CodeProjection ───parse──┘
```

There must never be a “current visual strategy” and a separate “current code strategy.” Both views edit one draft semantic revision. **Disposition: ADOPT**.

## Three-layer draft model

| Layer | Contents | Identity effect | Disposition |
|---|---|---|---|
| `DraftSemanticIR` | Nodes, typed ports, parameters, exact bindings, outputs and semantics | Creates new draft semantic revision; publishable | ADOPT |
| `VisualProjection` | Position, size, group, collapsed state, viewport, selection, comments | No StrategyVersion effect | ADOPT |
| `CodeProjection` | Generated text, formatting preferences, source map, parse diagnostics, pending text buffer | No effect until successfully lowered to semantic IR | ADOPT |

The current `StrategyDraft.mode` remains a presentation preference. It must not enter the canonical hash. **Disposition: ADAPT**.

## Editing transaction rules

### Visual edit

1. User performs a semantic graph operation (add/connect/delete/change parameter). **Disposition: ADOPT**.
2. Client validates local graph shape and sends an IR patch against `expected_draft_revision`. **Disposition: ADOPT**.
3. Service applies patch atomically, validates/canonicalizes, increments semantic revision and regenerates CodeProjection/source map. **Disposition: ADOPT**.
4. If validation fails, no semantic revision is created; the visual operation remains a local rejected proposal with diagnostics. **Disposition: ADOPT**.

Layout-only changes update VisualProjection independently and do not regenerate code. **Disposition: ADOPT**.

### Code edit

1. Monaco owns a pending text buffer and incremental diagnostics. **Disposition: ADOPT**.
2. Parser/lowerer must produce a complete supported AST and proposed IR against `expected_draft_revision`. **Disposition: ADOPT**.
3. On success, service canonicalizes and atomically commits a semantic revision, then regenerates VisualProjection for new nodes while preserving layout by stable node ID. **Disposition: ADOPT**.
4. On syntax/type/unsupported-feature failure, keep the pending buffer and diagnostics but do not partially mutate the semantic graph. **Disposition: ADOPT**.

### Split edit and concurrency

Both panes display the same `draft_semantic_revision`. Concurrent edits use compare-and-swap. A stale edit is rebased as an explicit proposal/diff; last-writer-wins is forbidden for semantics. **Disposition: ADOPT**.

## Code surface recommendation

A deliberately constrained, Python-shaped DSL is preferable to arbitrary Python as the canonical code view. It should support component construction, constants, named parameters, typed references and explicit outputs. **Disposition: ADAPT**.

Example projection:

```python
strategy(
    universe=ref.universe("unv_..."),
    signal=rank(field("factor.momentum_12m"), ascending=False),
    selection=top_n(ref("signal"), count=50, tie_break=["instrument_id"]),
    portfolio=equal_weight(ref("selection"), cash_policy="RESIDUAL"),
    rebalance=schedule("monthly", at="close"),
)
```

| Language feature | Policy | Disposition |
|---|---|---|
| Named component calls and literal parameters | Directly lower to registered node types | ADOPT |
| Local symbolic names | Preserve as display aliases; semantic node IDs are stable and explicit in source map | ADAPT |
| Pure helper expressions supported by the catalog | Inline or lower to explicit expression nodes | ADAPT |
| Loops/comprehensions for graph generation | Reject in baseline because identity and source mapping become less transparent | REJECT |
| Arbitrary imports, I/O, network, DB and engine calls | Reject | REJECT |
| User algorithm not expressible in DSL | Wrap as a typed `custom_code` node with explicit ports and Worker runtime | ADAPT |
| Formatting/comments | Preserve in pending/projection artifact; exclude from StrategyVersion identity | ADOPT |

## Source-map requirements

| Requirement | Purpose | Disposition |
|---|---|---|
| Node ID ↔ code span | Selecting a React Flow node highlights the correct Monaco span and vice versa | ADOPT |
| Port/parameter ↔ token span | Type/range diagnostics point to the exact argument and visual inspector field | ADOPT |
| Generated/provenance marker | Distinguish generated DSL text from user-authored custom-code artifacts | ADOPT |
| Stable diagnostic code and semantic path | The same error appears consistently in Visual, Code and Split | ADOPT |
| Revision/hash on map | Prevent using a stale source map after either view changes | ADOPT |

## Round-trip laws

Let `C` be canonicalization, `L_v` visual lowering, `P_c` code parsing/lowering, `G_v` visual generation and `G_c` code generation.

| Law | Expected result | Disposition |
|---|---|---|
| `C(L_v(G_v(IR))) = C(IR)` | Visual generation/lowering is semantics-preserving | ADOPT |
| `C(P_c(G_c(IR))) = C(IR)` | Code generation/parsing is semantics-preserving | ADOPT |
| `G_c(C(P_c(code)))` parses to same IR | Formatting normalization may change text, never semantics | ADOPT |
| Layout edit leaves `C(IR)` unchanged | Moving/grouping nodes does not create a StrategyVersion | ADOPT |
| Rename display label leaves `C(IR)` unchanged unless referenced semantically | Friendly labels are not identity | ADOPT |
| Unknown code construct produces no IR mutation | No partial or guessed translation | ADOPT |
| Registry/compiler upgrade does not reinterpret old IR | Old semantic API/compiler remains pinned; migration creates a new version | ADOPT |

## Semantic diff

Monaco text diff is useful for review but cannot be the only authority. V3 should produce a semantic IR diff with stable operations such as `AddNode`, `RemoveNode`, `SetParam`, `ConnectPort`, `ChangeBinding`, `ChangeOutput` and `ChangeSemanticProfile`. **Disposition: ADOPT**.

| Diff behavior | Recommendation | Disposition |
|---|---|---|
| Accept/reject hunk | Apply semantic operations to expected draft revision, then regenerate both projections | ADAPT |
| Formatting-only text change | Mark non-semantic and do not require a new StrategyVersion | ADOPT |
| Binding change | Always semantic and prominently disclose provenance impact | ADOPT |
| Component version/default change | Show expanded old/new values, not only friendly type names | ADOPT |
| Custom code change | Diff source artifact and dependency lock hashes; semantic identity changes | ADOPT |

## Drift prevention and recovery

| Failure | Required behavior | Disposition |
|---|---|---|
| Code buffer is invalid | Show pending/invalid state; Visual remains on last committed semantic revision | ADOPT |
| Visual edit arrives while code buffer is dirty | Do not overwrite buffer; show base/ours/theirs semantic reconciliation | ADOPT |
| Projection hash mismatches IR revision | Regenerate projection from IR and record a diagnostic; never trust stale projection | ADOPT |
| Unsupported old node type | Open read-only with pinned descriptor when available; require explicit migration to edit/publish | ADAPT |
| Node deleted but layout remains | Garbage-collect projection entry only after semantic commit | ADOPT |
| Generated node lacks a layout | Apply deterministic layout seed/order, then let UI changes remain projection-only | ADOPT |

## Compatibility with React Flow and Monaco

React Flow node/edge objects should be adapters over registry descriptors and DraftSemanticIR; their `position` and selection state stay in VisualProjection. Monaco models should hold the CodeProjection plus source map and diagnostics. Neither library object graph is persisted as Strategy IR. **Disposition: ADAPT**.

The current Split implementation renders both editors but does not synchronize graph semantics from code. Retain its presentation behavior while replacing hard-coded `baseNodes/baseEdges` and blur-only string persistence with the shared revision protocol above. **Disposition: ADAPT**.

## Acceptance gate

Visual/Code equivalence is ready for production implementation only when the property and golden tests in `TEST_IDEAS.md` prove round-trip equivalence, stale-revision handling, unsupported-code atomicity, stable hashes across formatting/layout and matching diagnostics across both views. **Disposition: ADOPT**.
