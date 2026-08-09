# Strategy IR failure modes

Severity assumes a published/reproducible research workflow. “Fail closed” means no successful financial artifact or invalid StrategyDefinitionVersion/StrategyEvaluationBindingVersion is published.

## Definition and projection failures

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-001 | Visual graph and code represent different semantics | Ambiguous strategy identity and misleading review | Sole canonical IR; revision/hash on both projections; round-trip gate | ADOPT |
| FM-002 | Code parser partially applies a file before hitting an unsupported construct | Graph silently becomes a different strategy | Transactional full-file lowering; no semantic mutation on error | ADOPT |
| FM-003 | Node coordinates, insertion order or formatting enter the semantic hash | False versions and cache misses | Separate projection artifacts; canonical sort | ADOPT |
| FM-004 | Default value changes in component registry | Old StrategyDefinitionVersion replays differently | Expand defaults and pin component/compiler versions at definition publish | ADOPT |
| FM-005 | Duplicate node IDs, dangling edges, cycle or incompatible port | Nondeterministic/invalid evaluation | Typed DAG compiler with closed schemas | ADOPT |
| FM-006 | Traversal order decides conflict/exit precedence | Visual layout or container order changes trades/intents | Explicit merge/priority policy in IR | ADOPT |
| FM-007 | Stale Split-pane edit overwrites a newer revision | Lost semantic change | Compare-and-swap revision and semantic rebase/diff | ADOPT |
| FM-008 | Unsupported component version is silently upgraded | Historical meaning changes | Read with pinned descriptor or fail; explicit migration creates version | ADOPT |
| FM-009 | Display label is used as a semantic reference | Rename breaks or changes graph | Stable semantic node IDs and field IDs | ADOPT |
| FM-010 | Custom code hides an entire uninspectable strategy | Visual equivalence and provenance collapse | Typed custom-code node with declared ports and source artifact | ADAPT |

## Input, time and universe failures

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-011 | `latest` Dataset/Snapshot/Universe resolves at evaluation time | Same evaluation binding yields different results | Resolve aliases before StrategyEvaluationBindingVersion publish; exact IDs and hashes only | ADOPT |
| FM-012 | Universe definition is pinned but membership artifact is not | Constituent drift or survivorship bias | Pin definition and chronological member artifact hashes | ADOPT |
| FM-013 | Strategy performs ad hoc DB/symbol lookup | Untracked inputs, permission bypass and PIT failure | No repository/DB/network capability in worker | ADOPT |
| FM-014 | Adjusted and raw price basis are mixed | Incorrect exits, returns and thresholds | Typed price-basis metadata on ports; compiler compatibility checks | ADOPT |
| FM-015 | Wall clock/timezone/calendar is ambient | Boundary bars and schedules differ across machines | Inject pinned evaluation clock, timezone and calendar | ADOPT |
| FM-016 | Missing data silently forward-fills or becomes zero | False signal/selection | Explicit missing policy and per-row diagnostic flags | ADOPT |
| FM-017 | Future availability is ignored | Look-ahead leakage | Observation cutoff and availability-time checks in data binding | ADOPT |
| FM-018 | Selector expands beyond bound universe | Hidden data scope and provenance loss | Membership validation on all selected/output instruments | ADOPT |
| FM-019 | Equal-score ties depend on hash/thread order | Non-reproducible selection | Stable total order by score and `instrument_id` | ADOPT |
| FM-020 | Instrument is renamed/remapped by display symbol | Identity collision or wrong asset | Stable instrument ID plus versioned symbology mapping | ADOPT |

## Lifecycle and state failures learned from Hikyuu

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-021 | Required component is missing | Runtime null/error or implicit behavior | Compile-time required-port validation, mirroring Hikyuu required TM/MM/SG tests | ADOPT |
| FM-022 | Cached `calculated` result survives a semantic/input mutation | Stale output | Content-addressed cache key covers IR, all inputs and runtime; immutable entries | ADAPT |
| FM-023 | Shared mutable component leaks state across instruments/runs | Cross-run contamination | Fresh isolated evaluation state; sharing only immutable values | ADOPT |
| FM-024 | Reset order changes initial Environment/Condition state | Different first-bar behavior | Explicit initial state and deterministic lifecycle; pure batch baseline | ADOPT |
| FM-025 | Same-bar versus next-bar delay is implicit | Look-ahead or timestamp shift | Strategy emits decision/rebalance time; execution delay belongs to engine profile | ADAPT |
| FM-026 | Malformed OHLC is silently skipped | Missing trades without explainability | Data-quality failure/diagnostic policy is explicit and counted | ADAPT |
| FM-027 | Environment/Condition invalidation silently liquidates | Gate unexpectedly acts as execution | Gate emits eligibility/exit intent; downstream policy decides target | ADAPT |
| FM-028 | Money manager depends on hidden fill callbacks | Replay depends on execution history | Explicit PortfolioStateSnapshot or move stateful sizing downstream | ADAPT |
| FM-029 | Takeprofit/stoploss/profit-goal conflict uses hidden early return | Different exit reason/target | Versioned conflict/priority node and provenance reason | ADOPT |
| FM-030 | Stochastic slippage is treated as strategy behavior without seed | Execution assumptions contaminate StrategyDefinitionVersion | Keep slippage downstream; pin seed/RNG in scenario | REJECT |

## Boundary and side-effect failures

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-031 | Strategy obtains live account handle | Can mutate holdings/cash and entangle identity | Only immutable PortfolioStateSnapshot may cross boundary | ADOPT |
| FM-032 | Strategy calls Backtest engine for a preview/decision | Recursive dependency and engine-specific semantics | Orchestrator owns evaluation and backtest; strategy has no engine capability | ADOPT |
| FM-033 | Strategy emits orders/fills | Execution choice becomes strategy identity and bypasses risk | Output schema limited to Signal/Selection/PortfolioIntent | ADOPT |
| FM-034 | Slippage/commission/broker config is embedded in IR | Same hypothesis cannot be tested across scenarios cleanly | Bind separate execution/backtest profile | ADOPT |
| FM-035 | Downstream consumes editable StrategyDraft | Result cannot be reproduced after edit | Handoff references immutable StrategyDefinitionVersion, exact StrategyEvaluationBindingVersion and artifacts only | ADOPT |
| FM-036 | Risk mutates StrategyDefinitionVersion or source signals | Audit chain loses original intent | Risk emits separate RiskAdjusted output referencing original identity | ADOPT |

## Custom-code and Worker failures

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-041 | Custom code opens DB/network/files | Exfiltration, hidden inputs and unreproducible output | OS sandbox, deny network, read-only mounts, no credentials | ADOPT |
| FM-042 | Custom code spawns subprocess/native extension | Sandbox escape/resource bypass | Deny syscalls/process creation and native modules in baseline | ADOPT |
| FM-043 | Infinite loop, memory bomb or output bomb | Worker/host denial of service | CPU/wall/memory/process/output/log limits; supervisor termination | ADOPT |
| FM-044 | Worker publishes IDs/truth directly | Control-plane integrity violation | Worker only stages proposals; supervisor owns identity/publication | ADOPT |
| FM-045 | Output has NaN/Inf, duplicate keys or out-of-universe rows | Corrupt downstream calculations | Strict schema, finiteness, uniqueness, membership and size validation | ADOPT |
| FM-046 | Ambient locale/hash seed/thread count changes result | Cross-machine drift | Deterministic runtime profile and replay conformance | ADOPT |
| FM-047 | Dependency resolution floats | Same source executes different library code | Content-addressed lockfile/image/SBOM | ADOPT |
| FM-048 | Logs are interpreted as financial outputs | Unvalidated result channel | Separate bounded logs from structured artifact output | ADOPT |
| FM-049 | Timeout publishes partial rows as success | Biased/incomplete portfolio | Atomic staged output; terminal success required | ADOPT |
| FM-050 | Exception leaks secrets/paths or non-deterministic details | Security/provenance inconsistency | Sanitized stable error taxonomy plus private diagnostic artifact | ADOPT |

## Provenance and identity failures

| ID | Failure mode | Impact | Required control | Disposition |
|---|---|---|---|---|
| FM-051 | StrategyDefinitionVersion hash omits component/operator/compiler/runtime/custom dependency semantics | Identical ID can mean different strategy behavior | Definition identity covers all executable interpretation inputs, but never concrete evaluation data/time/environment | ADOPT |
| FM-052 | Output omits source node path or input hashes | Cannot explain or reproduce signal | Complete ProvenanceManifest and row/artifact lineage | ADOPT |
| FM-053 | Retry reuses mutable output location | Previous evidence overwritten | New immutable attempt; same run/input identity where applicable | ADOPT |
| FM-054 | Cache hit is accepted without verifying input hashes/runtime | Stale or poisoned artifact | Verify manifest and bytes before reuse | ADOPT |
| FM-055 | Failed validation artifact is paired with a different IR | Invalid publish | Bind validation artifact to exact IR and compiler hashes | ADOPT |
| FM-056 | Truth state silently falls back from FORMAL to DEMO | Misrepresented financial result | Preserve explicit V3 truth-state rule; no silent fallback | ADOPT |
| FM-057 | Evaluation promotes PRE_ALPHA/NOT_FORMAL input to FORMAL output | Non-formal evidence is misrepresented as formal truth | Compute downstream ceiling from every required upstream admission; reject attempted promotion | ADOPT |
| FM-058 | `PUBLISHED`, `STRICT_PIT` or Strategy validation PASS is treated as sufficient FORMAL admission | One partial gate masks missing upstream truth/provenance | Require the full conjunctive admission set; no single flag upgrades truth | ADOPT |
| FM-059 | Concrete Dataset/Snapshot/Universe/time enters StrategyDefinitionVersion hash | Same strategy is falsely redefined for each evaluation binding | Keep exact bindings in StrategyEvaluationBindingVersion and run identity | ADOPT |

## Deferred high-complexity failures

| ID | Failure mode | Why deferred | Disposition |
|---|---|---|---|
| FM-061 | Stateful intraday checkpoint replay diverges | Needs a formal event clock, checkpoint and recovery contract | FUTURE |
| FM-062 | Distributed evaluation changes reduction order | Pure local deterministic semantics should land first | FUTURE |
| FM-063 | Live feature-service response changes after evaluation | Requires snapshot/attestation protocol | FUTURE |
