# Round 5 P Factor Pack Coverage

Observed against frozen W0 `f2cd80ee377d213a1bc1e78fb9812d2192b10cf9`. Network-current revision refresh remains `PENDING_NETWORK_RECHECK`.

| Pack / record | Coverage basis | Total known | SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED_OPERATOR | UNSUPPORTED_DATA | PIT_UNRESOLVED | LICENSE_BLOCKED | REFERENCE_ONLY | Canonical imports |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qlib Alpha158 | Documented total only; formulas/membership not copied | 158 | 0 | 0 | 0 | 0 | 0 | 0 | 158 | 0 |
| Qlib Alpha360 | Exact 6 fields × 60 lags manifest | 360 | 4 | 0 | 354 | 1 | 1 | 0 | 0 | 4 |
| WorldQuant Alpha101 | Exact numbered publication membership; unlicensed implementation formula code not copied | 101 | 0 | 0 | 0 | 0 | 0 | 101 | 0 | 0 |
| GTJA Alpha191 | Exact numbered publication-family membership; implementation/license/semantics unresolved | 191 | 0 | 0 | 0 | 0 | 0 | 0 | 191 | 0 |
| TA-Lib current V3 adapter record | Existing W0 SMA adapter capability record, **not the full TA-Lib catalog total** | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pandas-ta-classic adoption record | Library/reference record, **not a claim about the full current indicator count** | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| A-share extended data families | Seven explicit semantic families, not invented factor formulas | 7 | 0 | 0 | 0 | 3 | 4 | 0 | 0 | 0 |

Alpha360 exact status detail:

- `CLOSE0`, `OPEN0`, `HIGH0`, and `LOW0` use the exact lag-0 Alpha360 price-field-to-current-close ratios and current registered daily OHLC semantics. They are admitted through the W0 TDX translator, pack receipt, and canonical definition path. `CLOSE0` deliberately remains `CLOSE/CLOSE`; it is not silently simplified into a different definition.
- The remaining 59 lags for each of six fields require `REF`, which is unsupported by the frozen W0 TDX compatibility profile: 354 `UNSUPPORTED_OPERATOR`.
- `VWAP0` is `UNSUPPORTED_DATA`; current V3 data semantics do not prove exact Qlib VWAP source/adjustment parity.
- `VOLUME0` is `PIT_UNRESOLVED`; current V3 volume unit evidence does not prove exact Qlib volume normalization parity.

A-share extended family detail:

- `UNSUPPORTED_DATA`: northbound, large-order/main-force, chip distribution.
- `PIT_UNRESOLVED`: shareholder facts, financial facts, sentiment, historical industry/index membership.

TA-Lib unavailable at runtime may remain honest SKIP. No third-party dependency is added, and neither the TA-Lib nor pandas-ta row inflates a library-wide factor count.
