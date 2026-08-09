# Strategy IR test ideas

These tests are implementation input. Upstream Hikyuu tests are used as category references, especially required-part checks, reset/clone, exact event timestamps, delay semantics, component parameter tests, selector/allocation behavior and deterministic ties.

## Canonicalization and identity

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TIR-001 | Permute JSON object keys, node list and edge list | Canonical bytes/hash remain identical | ADOPT |
| TIR-002 | Move/resize/group React Flow nodes and change viewport | Strategy semantic hash remains identical | ADOPT |
| TIR-003 | Reformat code, alter whitespace/comments | Parsed canonical IR/hash remain identical | ADOPT |
| TIR-004 | Change one expanded parameter, component version or binding hash | StrategyVersion content hash changes | ADOPT |
| TIR-005 | Upgrade registry default while replaying old IR | Old expanded IR output/hash remains unchanged | ADOPT |
| TIR-006 | Serialize identity decimals through JS, Python and backend implementation | Canonical bytes are identical | ADOPT |
| TIR-007 | Duplicate IDs, cycle, dangling edge, incompatible port, unreachable declared output | Compile fails with stable node/port diagnostic | ADOPT |
| TIR-008 | Validation artifact from IR A supplied to publish IR B | Publish fails closed | ADOPT |

## Visual/Code equivalence properties

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TVC-001 | Property-generate valid component DAGs; Visual → IR → Code → IR | Canonical IR is byte-identical | ADOPT |
| TVC-002 | Property-generate valid DSL; Code → IR → Visual → IR | Canonical IR is byte-identical | ADOPT |
| TVC-003 | Select graph node/port/parameter | Monaco highlights exact source-map span | ADOPT |
| TVC-004 | Place syntax error after valid statements | No partial semantic revision is committed | ADOPT |
| TVC-005 | Use unsupported import/loop/I/O call | Stable diagnostic; last committed Visual graph remains unchanged | ADOPT |
| TVC-006 | Dirty code buffer plus concurrent Visual semantic edit | Compare-and-swap conflict; no last-writer-wins loss | ADOPT |
| TVC-007 | Accept/reject semantic diff hunk | Both projections regenerate from the resulting IR revision | ADOPT |
| TVC-008 | Rename labels and variables without changing stable IDs | Semantic hash is stable and selection mapping remains correct | ADAPT |
| TVC-009 | Open old pinned component descriptor | Read/replay works or fails explicitly; no silent migration | ADOPT |
| TVC-010 | New node has no saved layout | Deterministic initial layout; layout does not affect IR | ADOPT |

## Component contract tests

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TCO-001 | Omit required Signal/Selector/Allocation input port | Compile-time required-port failure, analogous to Hikyuu required-part tests | ADOPT |
| TCO-002 | Pass unknown parameter/wrong unit/out-of-range value | Closed-schema validation fails | ADOPT |
| TCO-003 | Environment is independent of instrument input | Same bound regime series is reused without mutable cross-talk | ADAPT |
| TCO-004 | Condition receives explicit signal port and state snapshot | No hidden object backreference is possible | ADOPT |
| TCO-005 | Same timestamp has long, short, stop and takeprofit intents | Versioned merge/priority policy yields one explained result | ADOPT |
| TCO-006 | Selector scores are all tied | Stable `instrument_id` tie-break across runs/thread counts | ADOPT |
| TCO-007 | Selector tries to emit non-member instrument | Output validation fails with membership diagnostic | ADOPT |
| TCO-008 | Allocation receives empty selection | Explicit cash/empty intent according to declared policy | ADOPT |
| TCO-009 | Absent target member under ZERO/UNCHANGED/OUT_OF_SCOPE policy | Each policy has distinct deterministic result | ADOPT |
| TCO-010 | Stoploss uses adjusted price while port requires raw price | Type/basis mismatch fails before evaluation | ADOPT |
| TCO-011 | Signal contains NaN/Inf or duplicate instrument/time key | Artifact publication fails | ADOPT |
| TCO-012 | Stateful component is undeclared | Compiler rejects stateful behavior in pure profile | ADOPT |

## Exact-input and PIT tests

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TIN-001 | Published binding contains `latest` alias | Publish/evaluate rejects it | ADOPT |
| TIN-002 | Dataset ID matches but content hash differs | Fail closed before worker dispatch | ADOPT |
| TIN-003 | Universe definition hash matches but member artifact differs | Fail closed | ADOPT |
| TIN-004 | Feature availability time is after `as_of` | PIT violation diagnostic and no output | ADOPT |
| TIN-005 | Same local timestamp under different timezone/calendar | Only pinned timezone/calendar result is accepted | ADOPT |
| TIN-006 | Missing row under ERROR/DROP/PROPAGATE policies | Distinct expected diagnostics and artifacts | ADOPT |
| TIN-007 | Adjusted/raw series share display name | Stable field ID and price-basis metadata prevent substitution | ADOPT |
| TIN-008 | Input membership order is randomized | Canonical output ordering/hash remains stable | ADOPT |

## Reproducibility and isolation tests

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TRP-001 | Run identical request twice in fresh workers | Byte-identical output artifacts and provenance except attempt metadata | ADOPT |
| TRP-002 | Vary process hash seed, locale and host timezone | Deterministic runtime profile neutralizes variation | ADOPT |
| TRP-003 | Vary permitted thread count/reduction partition | Output stays identical or profile rejects parallel mode | ADOPT |
| TRP-004 | Change explicit RNG seed/algorithm | Identity and output change; replay with same seed is identical | ADOPT |
| TRP-005 | Reuse cache with one omitted/changed input hash | Cache miss/fail; stale artifact not accepted | ADOPT |
| TRP-006 | Run two instruments/strategies concurrently | No shared mutable component contamination | ADOPT |
| TRP-007 | Retry after worker failure | New attempt, immutable old evidence, same run identity only when inputs unchanged | ADOPT |

## Worker security/resource tests

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TSW-001 | Attempt socket/DNS/HTTP access | Denied and recorded without network egress | ADOPT |
| TSW-002 | Attempt DB connector/repository API/secret environment read | Capability absent/denied | ADOPT |
| TSW-003 | Attempt filesystem traversal outside mounts | Denied | ADOPT |
| TSW-004 | Attempt subprocess, shell or native extension load | Denied in baseline profile | ADOPT |
| TSW-005 | Infinite loop and excessive CPU | Worker terminated with stable resource error | ADOPT |
| TSW-006 | Allocate beyond memory limit | Worker fails `WORKER_OOM`; no partial artifact published | ADOPT |
| TSW-007 | Emit excessive rows/log bytes/output bytes | Bounded failure; host remains healthy | ADOPT |
| TSW-008 | Emit malformed schema, NaN/Inf, duplicate rows or wrong universe | Supervisor rejects staged output | ADOPT |
| TSW-009 | Worker invents V3 ID or tries direct publication | Protocol rejects; only supervisor publishes | ADOPT |
| TSW-010 | Timeout after staging partial output | Staging is quarantined/non-authoritative | ADOPT |

## Strategy/execution separation tests

| Test ID | Test | Expected invariant | Disposition |
|---|---|---|---|
| TSE-001 | Inspect WorkerRequest capabilities | No account, broker, Backtest engine, DB or repository port | ADOPT |
| TSE-002 | Strategy returns order/fill shape | Output schema rejects it | ADOPT |
| TSE-003 | Same StrategyVersion evaluated under two slippage/execution profiles downstream | Signal/PortfolioIntent identity stays same; results differ only downstream | ADOPT |
| TSE-004 | Risk adjusts target | Original StrategyVersion and PortfolioIntent remain immutable and referenced | ADOPT |
| TSE-005 | Backtest handoff references editable draft | Handoff validation fails | ADOPT |
| TSE-006 | PortfolioStateSnapshot timestamp is later than decision time | PIT validation fails | ADOPT |

## Golden reference scenarios

| Scenario | Assertions | Disposition |
|---|---|---|
| Momentum top-50 equal weight | Exact selection order, residual cash policy, monthly rebalance time and complete provenance | ADOPT |
| Regime gate transitions | Explicit invalid→valid/valid→invalid intent reason without direct liquidation side effect | ADAPT |
| Stoploss/takeprofit/profit-goal collision | Policy version selects documented reason/intent deterministically | ADAPT |
| Long/short eligibility | Gross/net semantics and missing/blocked members are explicit | FUTURE |
| Custom-code rank node | Same output as built-in fixture within exact canonical bytes; sandbox attempts denied | ADAPT |

## CI gates suggested for the implementation phase

| Gate | Requirement | Disposition |
|---|---|---|
| IR conformance | Canonicalization, schema and cross-language fixtures pass | ADOPT |
| Projection conformance | Property round trips and source-map tests pass | ADOPT |
| Reproducibility | Repeated fresh-worker runs are byte-identical | ADOPT |
| Security | Worker deny-capability/resource suite passes | ADOPT |
| Provenance | Every output fixture validates a complete manifest | ADOPT |
| Scope | No Strategy evaluator dependency on DB/account/backtest/execution packages | ADOPT |
