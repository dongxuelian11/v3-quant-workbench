# Systemic A3 Backtest Payload Gap Audit

Task: `V3-SYSTEMIC-A3-BACKTEST-MARKET-PAYLOAD-CLOSURE-01`

Audited base: GitHub CURRENT protected `main` at `9dda07c254e1e3108d9ce3fec7624b4c7d0710f1`, the exact merge commit for P1 PR #32 (P1 head `b721544b0b53e4073b2eed001d200d2513085155`).

Status: mandatory pre-edit audit. This document records current-main gaps; it is not an acceptance claim.

## Authority and scope

The required formal path is:

```text
canonical owner ref
-> P1 CanonicalPayloadResolver
-> verified exact bytes + PayloadResolutionReceipt
-> strict versioned deterministic decoder
-> BacktestRunSpec / DailyMarketState / scheduled weights
-> pure DeterministicAshareBacktestEngine
-> content-addressed result + exact resolution provenance
```

P0 Authority is read-only. P1 is the only shared payload-authority foundation and is also read-only for A3. Portfolio, Risk, and weights semantic-owner code is protected. A1/A2/A4/Q/S/T/UI are outside this task.

## Current execution path

Current main has no formal Backtest service or owner-specific P1 binding adapter. All executable Backtest paths call `DeterministicAshareBacktestEngine.run(BacktestRunSpec)` directly. The engine correctly remains pure and deterministic, but `BacktestRunSpec.create(...)` accepts caller-created execution values and only checks that separate exact-looking references are present.

The development evidence runtime under `adapters/round3_evidence/development_runtime.py` also constructs caller-owned `MarketSession` / `DailyMarketState` values and invokes the pure engine directly. It is explicitly development evidence and must not be promoted into A3 formal authority.

The Round 5 R Agent application seam is `NOT_AVAILABLE / NOT_RUN` for production execution and fails closed before Backtest invocation. A3 does not change R Agent authority.

## Execution-changing payload inventory

| Payload / record | Canonical ref on current main | Actual values supplied today | Current constructor / authority gap | Recomputed or verified today | A3 P1 integration required |
|---|---|---|---|---|---|
| `BacktestRunSpec.exact_references` | Requires `SNAPSHOT`, `MARKET_DATA`, `TRADING_CALENDAR`, `UNIVERSE`, `CORPORATE_ACTIONS`, `OFFICIAL_TRADING_HOURS`, `OFFICIAL_COST_RULES` refs | IDs, hashes, and truth fields only | Any caller can create refs independently of the execution payload | Ref syntax and inclusion only; no bytes are resolved | Formal request must resolve all execution payload refs through P1 and create refs from verified results, never accept caller refs as proof |
| `BacktestRunSpec.sessions` | Decorated by market/calendar/corporate-action refs | Complete `MarketSession` tuple | Caller supplies every date, open/closed bit, state, and action | Sorted and unique only | Construct only from verified calendar, market, and action payloads in the formal path |
| `MarketSession.is_open` | `TRADING_CALENDAR` ref exists separately | Caller boolean | Caller can mark a closed date open or an open date closed while retaining the ref | Not cross-checked | Resolve canonical calendar bytes and derive sessions exactly; missing/empty/unbound calendar fails closed |
| `DailyMarketState.raw_open` | `MARKET_DATA` ref exists separately | Caller decimal string | Caller can alter execution prices under the correct-looking ref | Positivity only | Decode verified market bytes; formal request has no raw price field |
| `DailyMarketState.raw_close` | `MARKET_DATA` ref exists separately | Caller decimal string or `None` | Caller can alter valuation or cause missing-close failure under the same ref | Positivity if present | Decode verified market bytes; verify OHLC envelope and fail closed for open-session missing close |
| `DailyMarketState.suspended` | Market ref only | Caller boolean | Alters order eligibility | Not derived or verified | Derive from verified canonical trading status |
| `DailyMarketState.tradable` | Market/Universe refs only | Caller boolean | Alters order eligibility | Not derived or verified | Derive from verified market status plus verified historical Universe membership |
| `DailyMarketState.buy_restricted` | Market ref only | Caller boolean | Alters buy eligibility | Not derived or verified | Decode verified restriction fact/metadata under the market schema |
| `DailyMarketState.restricted_security` | Market ref only | Caller boolean | Board/rule-relevant metadata is detached | Stored but not currently used by engine execution | Decode verified security metadata and retain it in state/spec identity |
| `DailyMarketState.at_limit_up_open` / `at_limit_down_open` | Market ref only | Caller booleans | Alters fill blocking | Not derived or verified | Derive from verified canonical trading status/raw facts; caller flags are absent from formal request |
| `DailyMarketState.no_price_limit_session` | Market ref only | Caller boolean | Can bypass limit blocking | Not derived or verified | Decode verified rule-relevant session fact |
| `InstrumentDefinition.board` | Universe/market refs exist separately | Caller enum | Selects lot sizes, price-limit profile, and fee schedule | Enum type only | Resolve exact board/security metadata from verified Universe and market payloads and require cross-payload equality |
| `MarketSession.corporate_actions` | `CORPORATE_ACTIONS` ref exists separately | Caller action tuples | Caller can omit, add, or alter dividends/splits under a valid ref | Date equality and basic numeric validation only | Resolve verified canonical action bytes, validate snapshot/context/instrument/date, reject unsupported actions through existing engine semantics |
| `ScheduledWeights.vector` | Vector carries canonical W0/R IDs and hashes | Caller supplies the full `RiskAdjustedWeightVector` object and numeric rows | `assert_canonical()` detects internal mutation, but formal Backtest does not resolve it from the Risk owner or verified Artifact Store | Recomputed against its own nested object graph only | Resolve each exact RiskAdjusted vector artifact via P1, resolve the canonical Risk owner object through an injected owner port, and require canonical JSON bytes to match `vector.to_wire()` exactly before engine use |
| `ScheduledWeights.effective_at` | W0 source target rebalance time | Caller datetime | Alters schedule selection | Checked equal to the supplied vector's source target | Keep equality check, but vector must first be owner-resolved and byte-verified |
| Initial cash / holdings | No external owner required by A3 | Caller execution request | Legitimate experimental starting state | Included in RunSpec identity | Keep explicit; any change creates a different formal request, RunSpec, and result identity |
| Rule / timing / cost profiles | Exact content-addressed profile IDs/hashes in RunSpec | Caller supplies canonical profile objects | Objects already self-recompute and define current Backtest semantics | `assert_canonical()` and effective-range checks | Preserve; A3 must not simplify financial rules. Formal request binds exact profiles and output provenance |
| `BacktestRunResult` | `run_spec_id` only | Pure engine outputs ledgers/results | No P1 receipt IDs or formal-request identity | Result is content-addressed over engine output | Formal wrapper must bind request, RunSpec, canonical input refs, all P1 receipt IDs, engine/runtime/profile identities, and pure result ID/hash |

## P1 foundation audit

P1 already provides the only shared trust boundary:

- `PayloadResolutionRequest` contains intent/ref/context/read bound and cannot carry raw values;
- an injected canonical-owner binding resolver supplies the binding;
- the existing verified Artifact Store byte reader returns actual bytes;
- P1 independently verifies artifact ID, SHA-256, byte size, role, owner, and exact context;
- P1 emits deterministic `VerifiedPayload` and `PayloadResolutionReceipt`;
- caller-created binding/result/receipt objects are not accepted as authorization.

A3 therefore needs only Backtest-specific request construction, owner-role policy, strict schema decoders, cross-payload semantic validation, a Risk owner object resolver for W0 values, formal execution orchestration, and result provenance. It must not add a second resolver, artifact namespace, store, canonical JSON implementation, or generic receipt type.

## Data Truth / calendar / corporate-action audit

Current Data Truth models define `TradingSession`, `CanonicalEodRecord`, `TradingStatus`, `CorporateAction`, `InstrumentLifecycle`, and PIT-aware timestamps. SQLite migrations/repositories persist calendar, snapshot-calendar, Universe membership, and corporate-action relationships. However, current main has no A3 owner binding resolver or admitted Backtest payload schema that projects these owner records into P1 bindings and strict deterministic Backtest inputs.

A3 will define a bounded canonical JSON wire for Backtest consumption. It will preserve exact owner IDs/context/snapshot links and facts actually used by the engine. It will not alter Data Truth owner code. If the Data Truth owner cannot issue a binding/artifact for a requested payload, P1 fails closed; A3 will not create empty calendar, empty action, all-tradable, or demo defaults.

## Universe audit

Current `BacktestRunSpec` checks only that each supplied W0 source Universe set equals caller-supplied `InstrumentDefinition` IDs. This does not prove historical membership or the bytes behind the Universe ref. Data Truth has PIT-aware membership interval models/repository queries, but Backtest does not resolve a membership artifact.

A3 must resolve a versioned historical Universe payload, require exact snapshot/context equality, validate ordered unique instruments and board metadata, require membership across the formal run sessions under the current fixed-universe engine contract, and require exact equality with W0 source Universe membership. A caller-created symbol list cannot enter the formal path.

## Weight owner audit

W0 `RiskAdjustedWeightVector` is immutable and content-addressed, preserves `TargetWeightVector` and `RiskApplicationReceipt` bindings, and exposes `assert_canonical()`. This is reused without modification. The gap is ownership/reachability: Backtest accepts a Python object rather than resolving actual owner bytes.

A3 must not decode a shadow weight type or reimplement Portfolio/Risk. It will resolve the exact Risk artifact through P1, obtain the canonical W0 object from the injected Risk owner port, run `assert_canonical()`, and require its canonical `to_wire()` bytes to equal the verified artifact bytes exactly. Exact ID plus detached altered numeric rows is rejected.

## Formal entry and bypass audit

There is no formal Backtest entry on current main. A3 must add one bounded service. Its request will contain only canonical payload references, initial state, profiles, runtime identity, and engine identity; it will not accept `DailyMarketState`, `MarketSession`, `CorporateAction`, `InstrumentDefinition`, or numeric weight rows.

The pure engine remains public for deterministic internal/unit/research use and returns only `BacktestRunResult`. It cannot mint the new formal provenance wrapper. Only the formal service performs P1 resolution and returns the content-addressed formal result.

## Required negative evidence mapping

1. Correct market ref + altered stored/returned price bytes: P1 content mismatch.
2. Correct ref + detached caller open/close: impossible in formal request; legacy pure spec cannot mint formal output.
3. Altered suspension: P1 content mismatch or verified decoded status wins.
4. Altered limit/tradable: P1 content mismatch or deterministic derivation wins.
5. Wrong calendar/session: owner/context/schema/cross-payload rejection.
6. Wrong corporate actions: owner/context/schema/cross-payload rejection.
7. Wrong Universe membership/context: owner/context/membership/W0 equality rejection.
8. Valid IDs + empty substitute bytes: P1 hash/size mismatch; no default fallback.
9. Wrong RiskAdjusted payload: owner/role/context/content rejection.
10. Exact weight ID + detached altered numeric weights: canonical object bytes mismatch verified Risk artifact.
11. Market context mismatch: exact P1 context and decoded cross-context rejection.
12. Initial state/context mismatch: formal request and RunSpec identity changes.
13. Pure engine determinism remains evidenced.
14. Pure engine returns no formal result/provenance wrapper.
15. Exact canonical happy path resolves all inputs, runs, and emits receipt-bound formal output.

## Planned bounded write shape

```text
apps/backend/src/v3_backend/domain/backtest_runtime/**
apps/backend/src/v3_backend/adapters/backtest_payloads/**
apps/backend/tests/systemic_a3_backtest_payload/**
docs/research/systemic-a3/**
scripts/backend-foundation-test.mjs   # only if focused suite registration is required
```

No protected owner or P0/P1 foundation file is required for the planned closure.
