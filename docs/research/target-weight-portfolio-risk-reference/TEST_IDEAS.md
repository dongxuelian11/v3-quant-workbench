# Test ideas

## Testing strategy

Use small golden vectors, property tests, metamorphic tests, contract tests and adapter conformance tests. Every test asserts both numerical behavior and provenance/identity behavior. Third-party tests inspired these cases, but V3 should implement them independently.

## Canonical contract tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| TW-001 | Permute row input order | identical canonical bytes/hash | **ADOPT** |
| TW-002 | Change one weight by one canonical unit | different hash | **ADOPT** |
| TW-003 | `0`, `0.0`, `-0`, exponent forms | only canonical representation admitted; semantic zero hashes consistently | **ADOPT** |
| TW-004 | Duplicate instrument/sleeve key | rejection with both source locations | **ADOPT** |
| TW-005 | NaN/Infinity/null weight | schema rejection | **ADOPT** |
| TW-006 | Same rows, different universe hash | different vector identity | **ADOPT** |
| TW-007 | Same rows, different signal/policy/as-of | different vector identity | **ADOPT** |
| TW-008 | Change nonsemantic display annotation | content hash unchanged; annotation revision audited separately | **ADAPT** |
| TW-009 | Rehydrate serialized artifact | byte-for-byte canonical equivalence | **ADOPT** |
| TW-010 | Unsupported major schema | deterministic incompatibility failure | **ADOPT** |

## Exposure and cash property tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| PF-001 | Random long-only weights plus explicit residual cash | profile equation holds within declared tolerance | **ADOPT** |
| PF-002 | Negative weight under long-only | rejected | **ADOPT** |
| PF-003 | Long/short vectors with equal net but different gross | independently measured and constrained | **ADOPT** |
| PF-004 | Cash missing or inferred from omissions | rejected | **ADOPT** |
| PF-005 | Sparse vector under complete contract | absent members resolve to zero only under the single declared policy | **ADOPT** |
| PF-006 | Outside-universe instrument | rejected before optimization/execution | **ADOPT** |
| PF-007 | Boundary values exactly at min/max and tolerance | consistent inclusive/exclusive behavior | **ADOPT** |
| PF-008 | Decimal accumulation across thousands of rows | deterministic sum independent of platform/thread order | **ADOPT** |

## Rebalance and turnover tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| RB-001 | Target equals current state | explicit no-op plan and zero predicted turnover | **ADOPT** |
| RB-002 | Same target, different current holdings | same target ID, different execution plan/delta ID | **ADOPT** |
| RB-003 | One complete switch in two-asset long-only portfolio | declared one-way/two-sided turnover formula matches golden value | **ADOPT** |
| RB-004 | Stale `valid_until` | plan admission rejected, no orders | **ADOPT** |
| RB-005 | Holiday/DST/calendar boundary | rebalance resolution follows pinned calendar/timezone | **ADOPT** |
| RB-006 | Two targets for same rebalance event | deterministic supersession or explicit conflict | **ADOPT** |
| RB-007 | Changed portfolio snapshot in turnover-aware optimization | new construction run/vector identity | **ADOPT** |

## Optimizer tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| OP-001 | Known feasible constraints | solution independently validates all bounds/budgets | **ADOPT** |
| OP-002 | Contradictory sector/name constraints | typed infeasible; no target published | **ADOPT** |
| OP-003 | Solver unavailable or timeout | typed failure; no silent equal-weight/previous-weight fallback | **ADOPT** |
| OP-004 | `optimal_inaccurate` with violated tolerance | formal admission rejected | **ADOPT** |
| OP-005 | Same inputs/seed/version | canonical result and provenance repeat | **ADOPT** |
| OP-006 | Change solver/tolerance/postprocessor | new result identity even if rows happen to match | **ADOPT** |
| OP-007 | Explicit approved fallback | separate candidate/run identity and visible degraded truth state | **ADAPT** |

## Risk composition tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| RK-001 | Validate-only policy passes | original unchanged; distinct decision evidence | **ADOPT** |
| RK-002 | Single-name clip sends residual to cash | source target unchanged; adjusted equation valid | **ADOPT** |
| RK-003 | Reverse two noncommuting policies | different policy-set/result identity and expected different rows | **ADOPT** |
| RK-004 | Two conflicting policies | infeasible report, not last-writer-wins | **ADOPT** |
| RK-005 | All policies no-op | deterministic `UNCHANGED` result referencing same weights | **ADOPT** |
| RK-006 | Risk worker crashes halfway | no partially published adjusted vector; retry is new attempt | **ADOPT** |
| RK-007 | Stale/missing risk model | reject or explicit degraded policy; no implicit bypass | **ADOPT** |
| RK-008 | Risk-adjusted target all cash | source StrategyVersion and original target identities remain unchanged | **ADOPT** |

## Execution adapter golden tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| EX-001 | Weight to quantity with known NAV/price/lot | exact target quantity, rounding and residual cash | **ADOPT** |
| EX-002 | Zero/missing price | blocked/rejected item; no invented price | **ADOPT** |
| EX-003 | Suspended desired buy | target preserved; blocked residual produced | **ADOPT** |
| EX-004 | T+1/frozen desired sale | executable partial quantity and residual are correct | **ADOPT** |
| EX-005 | Price-limit blocks order/fill | explicit rule evidence, no target rewrite | **ADOPT** |
| EX-006 | Insufficient buying power | exact configured resize/block behavior | **ADAPT** |
| EX-007 | Duplicate plan delivery | no duplicate order/ledger effect | **ADOPT** |
| EX-008 | Partial fill then retry | new attempt reconciles actual holdings/open orders without erasing history | **ADOPT** |
| EX-009 | Same vector in simulated/live-compatible fixture | same desired semantics; adapter-specific plans remain separately identified | **ADAPT** |
| EX-010 | Unknown/fuzzy ticker mapping | hard failure | **ADOPT** |

## Provenance and boundary tests

| ID | Test | Expected result | Disposition |
|---|---|---|---|
| PV-001 | Traverse result back to source | fills -> plan -> adjusted vector -> target -> intent -> signal/strategy/model -> dataset/snapshot/universe is complete | **ADOPT** |
| PV-002 | Attempt Strategy direct DB/account/engine capability | denied by contract/worker boundary | **ADOPT** |
| PV-003 | Attempt Risk mutation of source target | immutable-store/registry rejection | **ADOPT** |
| PV-004 | Change input after run submission | new run required; old run remains immutable | **ADOPT** |
| PV-005 | Worker returns unknown identity | main service rejects worker-owned truth | **ADOPT** |
| PV-006 | DEMO artifact passed to FORMAL pipeline | explicit truth-state rejection | **ADOPT** |

## Reference-derived coverage

- **ADAPT:** LEAN portfolio-construction rebalance tests: new insight, insight expiry, security change and time-based rebalance should inspire V3 schedule/supersession tests.
- **ADAPT:** LEAN target-collection tests: no-data and margin-impact ordering should inspire execution planning tests, without adopting its concrete quantity contract.
- **ADAPT:** WonderTrader backtest mocker checks: no-short, target=current no-op and T+1 frozen position should become V3 rule-profile goldens.
- **ADAPT:** skfolio failure modes and bounds/budget tests should inspire independent optimizer-admission tests.
- **REJECT:** copying third-party test code or treating upstream green tests as V3 conformance.
- **FUTURE:** differential conformance against multiple admitted backtest/live adapters once formal adapters exist.
