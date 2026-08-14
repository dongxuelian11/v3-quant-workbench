# Formal Backtest Canonical Payload Contract

Task: `V3-SYSTEMIC-A3-BACKTEST-MARKET-PAYLOAD-CLOSURE-01`

Status: A3 `INTEGRATION_ACCEPTED` candidate within the formal Backtest/market payload scope only, conditional on exact-head tests, PR CI, and review. This does not claim `PRODUCT_CONNECTED`, `USER_VISUAL_ACCEPTED`, `PRODUCTION_AVAILABLE`, or Agent execution availability.

## Formal entry

`FormalBacktestService.execute(FormalBacktestRunRequest)` is the only A3 entry that returns `FormalBacktestRunResult`.

The request deliberately contains no `MarketSession`, `DailyMarketState`, instrument/board rows, corporate-action values, or numeric weight rows. It contains exact owner references, session range, explicit initial state, canonical Backtest profiles, runtime identity, and engine identity.

```text
FormalBacktestRunRequest
  -> BacktestCanonicalPayloadBindingResolver
  -> P1 CanonicalPayloadResolver
  -> existing verified Artifact Store reader
  -> VerifiedPayload + PayloadResolutionReceipt
  -> A3 strict canonical-JSON decoder and cross-binding checks
  -> BacktestRunSpec
  -> DeterministicAshareBacktestEngine
  -> BacktestRunResult
  -> FormalBacktestRunResult with all receipt IDs
```

The pure engine remains public and deterministic for internal/research/unit use. It returns only `BacktestRunResult`; direct engine use cannot produce the A3 formal provenance wrapper.

## Closed owner/role map

| Payload role | Required owner namespace | Schema fingerprint |
|---|---|---|
| `SNAPSHOT_CONTEXT` | `DATA_TRUTH` | `v3.backtest_snapshot_context/1.0.0` |
| `MARKET_STATE` | `DATA_TRUTH` | `v3.backtest_market_state/1.0.0` |
| `TRADING_CALENDAR` | `DATA_TRUTH` | `v3.backtest_trading_calendar/1.0.0` |
| `CORPORATE_ACTIONS` | `DATA_TRUTH` | `v3.backtest_corporate_actions/1.0.0` |
| `HISTORICAL_UNIVERSE` | `UNIVERSE` | `v3.backtest_historical_universe/1.0.0` |
| `RISK_ADJUSTED_WEIGHT_VECTOR` | `RISK` | accepted W0 `RiskAdjustedWeightVector.schema_version` |

Unknown roles and owner/role substitutions fail closed. Owner versions, IDs, exact context, byte bounds, artifact IDs, SHA-256, byte sizes, and schema fingerprints are all verified before decoding.

## Deterministic schemas

All payloads are strict UTF-8 canonical JSON. Duplicate keys, floats, non-finite values, non-canonical key encoding, wrong versions, extra/missing fields, and non-canonical record ordering are rejected. No pickle or executable deserialization exists.

### Snapshot context

Binds the exact Snapshot ID, knowledge cutoff, market-data owner ID, calendar owner ID, corporate-action owner ID, Universe owner ID, and shared context identity.

### Trading calendar

Binds the exact calendar version and Snapshot plus ordered unique `(session_date, is_open)` facts. The requested start/end dates must exist in the verified calendar, and every selected session must have exact market coverage.

### Historical Universe

Binds the exact Universe version and Snapshot plus ordered unique instrument identity, board, and membership effective interval. The current pure engine has a fixed-Universe contract, so every member must be active on every selected session. W0 source Universe membership must equal the verified set exactly.

### Market state

Binds the exact market-data version, Snapshot, calendar, Universe, and ordered per-session/per-instrument records. Each record carries board, raw OHLC, volume, amount, canonical open-execution trading status, session availability, restricted-security fact, buy restriction, and no-price-limit-session fact.

A3 derives `DailyMarketState` rather than accepting caller booleans:

- `suspended` derives from canonical `SUSPENDED` status;
- `tradable` derives from canonical open-session availability and `TRADING / LIMIT_UP / LIMIT_DOWN` status;
- limit-up/down flags derive from canonical status;
- board must equal verified Universe board;
- active verified Universe membership cannot coexist with `DELISTED` status;
- session availability must equal the verified calendar.

OHLC envelope and exact decimal/integer constraints are validated even where a field is not consumed by the current engine. Changing any verified-but-not-currently-consumed field still changes the P1 receipt and formal result identity.

### Corporate actions

Binds the exact action-set owner and Snapshot plus ordered exact events. Supported and unsupported action types are preserved for the existing engine's fail-closed financial semantics. No absent owner binding is converted into an empty event set. A canonically verified empty event set can exist only when the owner actually publishes and binds those exact empty bytes.

### Risk-adjusted weights

A3 does not define a shadow weight wire or change W0/R semantics. For each scheduled vector:

1. resolve exact Risk artifact bytes through P1;
2. obtain the canonical `RiskAdjustedWeightVector` through the injected Risk owner port;
3. run the existing `assert_canonical()` checks;
4. require exact vector ID/content identity;
5. require `canonical_json_bytes(vector.to_wire())` to equal the verified artifact bytes;
6. require scheduled `effective_at` to equal the canonical source target rebalance time;
7. require exact W0 Universe equality with the verified historical Universe.

An exact vector ID plus detached altered numeric weights therefore cannot enter the formal engine.

## Formal result provenance

`FormalBacktestRunResult` is content-addressed over:

- exact formal request ID/hash;
- resolved `BacktestRunSpec` ID/hash;
- pure Backtest result ID/hash;
- every P1 resolution receipt ID and actual artifact hash/size;
- owner namespace/ID/version/role/context;
- engine/runtime identity;
- exact rule, cost, and timing profile IDs plus content hashes.

The internal `BacktestRunSpec` also receives exact references generated from verified P1 results, plus the existing cost/timing profile references. Caller-provided exact-looking refs are not accepted by the formal request.

## Preserved boundaries

- P0 and P1 source files are unchanged.
- Portfolio/Risk/weights semantic-owner source is unchanged.
- Existing A-share suspension, limit, T+1, lot, cash, fee, corporate-action, schedule-selection, and valuation behavior remains in the pure engine.
- Production R Agent execution remains `NOT_AVAILABLE / NOT_RUN`.
- No runtime handler, Electron bridge, UI, or product availability is claimed by A3.
