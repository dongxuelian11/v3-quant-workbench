# Track B Real A-Share Provider V0 — Reuse Adoption Report

As of 2026-08-11, the bounded Reuse-First Gate selected one real provider and
kept all V3 authority, identity, PIT, and admission semantics inside V3.

## Provider Adoption Matrix

| Candidate | Current evidence | Coverage and operation | License / terms | Python 3.14 and dependency risk | PIT, revision, and provenance | Adoption |
| --- | --- | --- | --- | --- | --- | --- |
| AKShare | `release-v1.18.84`; repository revision `1a0c07ca4017f26f8dc817829b074d857227f562`; active 2026-08-10 | `stock_zh_a_hist` provides unadjusted daily history for SSE, SZSE, and BSE symbols through Eastmoney; provider network remains outside offline tests | MIT code; upstream data-source terms still apply | Documentation says Python 3.9+ and recommends 3.11; no authoritative Python 3.14 guarantee. Large transitive dependency surface is not admitted into core CI | Exact package/repository identity can be recorded, but response revision and record-level available-time are not supplied | `ADAPTER`: optional, lazy-loaded, exact-version thin adapter; no mandatory dependency |
| free-stockdb | repository revision `c430ac9408ea7b685c9018f5ca6d245910fa4972`; active 2026-08-09 | Strong local-first A-share EOD/minute engine, incremental sync, SHA-256 verification, Windows binaries, Python/HTTP interfaces | MIT code; project explicitly leaves data rights and redistribution terms to each source | Separate C++ service, release binary, local dataset, and operational lifecycle increase isolation and supply-chain work | Local snapshots help reproducibility, but V3 cannot prove the supplied data's record-level available-time/revision lineage; adopting the engine would risk a second authority | `REFERENCE`: reuse local-first/checksummed-sync ideas only |
| efinance | package `0.5.8`; repository revision `c8fd370a3109b2d14a121e3a32a86e9c8354b01b`; active 2026-07-17 | A-share history through Eastmoney, overlapping the selected AKShare source | PyPI/GitHub say MIT, while the README also says learning use only and not commercial use | PyPI classifiers stop at Python 3.12; no Python 3.14 evidence | No provider revision or record-level available-time proof; documentation discusses network/rate-limit alternatives | `REJECT`: duplicated source path, ambiguous use constraint, and no stronger truth evidence |

## Why V3-Native Remains Required

No candidate provides V3's canonical RawCapture identity, normalization version,
Snapshot identity, explicit unknown/missing semantics, record-level PIT proof,
Research Universe input, or A0 truth/admission ceiling. Those parts therefore use
small V3-native value objects and canonical hashing. Third-party IDs, caches,
local database keys, and provider responses remain evidence only and never become
V3 canonical authority.

## Selected Boundary

- Provider: AKShare `1.18.84`, repository revision
  `1a0c07ca4017f26f8dc817829b074d857227f562`.
- Endpoint/source: `stock_zh_a_hist`, Eastmoney A-share daily history.
- Input: one explicit six-digit symbol, daily period, bounded date range,
  unadjusted prices only.
- Failure: explicit exception; there is no fallback chain.
- Runtime: optional and lazy-loaded. Offline fixtures inject a provider-shaped
  object and never import AKShare or use the network.
- Truth: unknown response revision and unknown available-time are preserved;
  Strict PIT fails closed and the canonical ceiling cannot exceed
  `NOT_FORMAL / PRE_ALPHA`.

## Primary Sources

- AKShare repository and release metadata: <https://github.com/akfamily/akshare>
- AKShare A-share history documentation: <https://akshare.akfamily.xyz/data/stock/stock.html>
- free-stockdb repository: <https://github.com/hello245m/free-stockdb>
- efinance repository: <https://github.com/Micro-sheep/efinance>
- efinance package metadata: <https://pypi.org/project/efinance/0.5.8/>
