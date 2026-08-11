# Track J A-share Backtest Core — Reuse Adoption Matrix

Research cut-off: 2026-08-11 (Asia/Shanghai). This scan precedes implementation. The V0 core remains V3-native and adds no third-party runtime dependency.

| Candidate | Pin / license observed | Useful semantics | Decision | Why no direct reuse |
|---|---|---|---|---|
| [RQAlpha](https://github.com/ricequant/rqalpha) | 6.1.5 (2026-05-21); non-commercial restricted license | A-share suspension, ST, corporate-action and order-event concepts | `REFERENCE` | License is unsuitable for an Apache-2.0 core; complete data semantics depend on RQData; no V3 canonical identity or W0 seam. |
| [LEAN](https://github.com/QuantConnect/Lean) | repository/release page inspected 2026-08-11; Apache-2.0 | Event ordering, order/fill and corporate-action separation | `REFERENCE` | C# engine plus Python bridge, broad live brokerage authority, and global-market defaults do not provide exact A-share daily rules or V3 provenance. |
| [vn.py](https://github.com/vnpy/vnpy) | 4.4.0 (2026-05-14); MIT | Backtest/order lifecycle and Chinese-market vocabulary | `REFERENCE` | Gateway-oriented live authority and optional ecosystem are outside scope; no exact immutable V3 run/result contract. |
| [Hikyuu](https://github.com/fasiondog/hikyuu) | 2.8.1 (2026-07-09); Apache-2.0 | A-share adjustment, limit, minimum-volume and T+1 concepts | `REFERENCE` | C++/plugin/data stack increases Windows and Python 3.14 supply-chain risk; includes trading extensions and cannot own V3 truth/provenance. |
| [WonderTrader](https://github.com/wondertrader/wondertrader) | repository inspected 2026-08-11; MIT; no GitHub release tags | Backtest/live event separation | `REFERENCE` | Native C++ full-lifecycle trader includes brokers/live execution, conflicts with the research-only authority boundary, and lacks V3 identities. |
| [free-stockdb](https://github.com/hello245m/free-stockdb) | repository inspected 2026-08-11; MIT | Local A-share raw/adjusted price, factor and ST data concepts | `REFERENCE` | Data utility, not a point-in-time eligibility/rule/cost/order/ledger authority; raw input identity still must be supplied by V3. |
| [backtrader](https://github.com/mementum/backtrader) | repository inspected 2026-08-11; GPL-3.0+ | Generic event-driven order lifecycle | `REFERENCE` | Copyleft and maintenance posture are unsuitable; generic rules cannot establish A-share regulatory semantics. |
| [backtesting.py](https://github.com/kernc/backtesting.py) | repository inspected 2026-08-11; AGPL-3.0 | Small candle-backtest API concepts | `REFERENCE` | Copyleft, bar-centric abstractions, and no exact T+1/ST/limit/corporate-action ledger semantics. |
| [vectorbt](https://github.com/polakowo/vectorbt) | 1.0.0 (2026-04-22); Apache-2.0 plus Commons Clause | Deterministic vectorized comparison/oracle ideas | `REFERENCE` | Vectorized portfolio simulation is not the required event/ledger authority; optional accelerated paths risk silent runtime divergence. |
| SSE/SZSE/BSE/ChinaClear/tax authorities | exact sources in `OFFICIAL_RULE_SOURCES.md` | Regulatory source of truth | `ADOPT_AS_PINNED_INPUT_EVIDENCE` | Rules are encoded as explicit versioned profiles and session-state inputs, not scraped or fetched during a run. |

## V3-native seams required

- Exact consumption of the existing W0 `RiskAdjustedWeightVector`; no copied weight DTO.
- Content-addressed `AshareTradingRuleProfileVersion`, `CostPolicyVersion`, market-data/calendar/corporate-action references, and `BacktestRunSpec`.
- Deterministic target quantity, order, fill, cash/position ledger, holding snapshot and NAV artifacts.
- Explicit T+1, lot, suspension, restriction/ST, price-limit, cost, corporate-action and missing-price outcomes.
- A PRE_ALPHA truth ceiling bound by the weakest upstream input.
- A research-only engine with no network, broker, live or paper-trading capability.

Context7 was required by repository instructions for library documentation, but no Context7 MCP capability was available in this session. Official project repositories/release pages and primary regulatory sources were used instead; this does not authorize runtime reuse.
