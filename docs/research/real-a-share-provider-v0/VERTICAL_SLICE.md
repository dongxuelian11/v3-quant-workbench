# Track B Real A-Share Provider V0 — Vertical Slice

```text
AKShare 1.18.84 / stock_zh_a_hist / Eastmoney
  -> exact-version lazy adapter
  -> canonical provider response bytes
  -> content-addressed RawCapture + acquisition record
  -> v3-cn-a-share-eod-normalization-v0.1.0
  -> acquisition-bound deterministic research Snapshot
  -> explicit unknown available-time and revision evidence
  -> observed-symbol Research Universe input
  -> A0 ceiling propagation (NOT_FORMAL / PRE_ALPHA at most)
```

The capture identity is based on canonical response content and exact provider
identity, not the acquisition clock. The acquisition record separately preserves
request fingerprint and acquisition time in an `acquisition_id`. Row order is
normalized before capture hashing, so semantically identical responses have the
same RawCapture identity even when acquired by different events. Each normalized
observation carries its acquisition ID and time, and Snapshot identity binds the
deterministically ordered acquisition IDs. The same content and acquisition
provenance therefore reproduce the same Snapshot identity, while a different
acquisition event produces a different Snapshot identity.

Normalization preserves provider nulls and absent trading-status semantics rather
than filling, dropping, or inferring them. It records the session event time at
15:00 Asia/Shanghai, but does not invent a provider available-time or data revision.
Because those two evidence dimensions are unknown, `require_strict_pit()` fails
closed. Even a caller-proposed `FORMAL_ADMITTED` state is met with the provider
upstream ceiling and becomes `NOT_FORMAL / PRE_ALPHA`.

V0 intentionally rejects adjusted prices because corporate-action source and
revision evidence are not part of this bounded slice. It also has no automatic
provider fallback and does not perform all-market history backfill.
