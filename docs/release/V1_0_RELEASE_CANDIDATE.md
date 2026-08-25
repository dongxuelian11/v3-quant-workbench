# V3 V1.0 Product Release Candidate

Status: `RELEASED AS PUBLIC PRERELEASE / PRE-ALPHA / RESEARCH-ONLY`

Version: `1.0.0`

This document is the historical record for the single V1.0 candidate produced
by task `V3-V1-INTEGRATED-PRODUCT-RELEASE-CLOSURE-20260822-01`. PR #49 was
merged into `main` on 2026-08-23 as exact commit
`02c5b8748170569ffc436f3bf5d2f682c21d2811`; the `v1.0.0` tag points to that
commit and the public GitHub release is a prerelease. This closure does not
promote any path to `PRODUCTION_AVAILABLE`.

## Final exact-main closure

| Evidence | Final state |
|---|---|
| PR | [#49](https://github.com/dongxuelian11/v3-quant-workbench/pull/49) `MERGED`; head `41f769aca426aa4c82ff9d9b5d31c0c015c2bb1d`; merge/main `02c5b8748170569ffc436f3bf5d2f682c21d2811` |
| exact-main CI | [run 32626717592](https://github.com/dongxuelian11/v3-quant-workbench/actions/runs/32626717592) `SUCCESS` on `02c5b8748170569ffc436f3bf5d2f682c21d2811` |
| packaging / clean-machine workflow | [run 32626717564](https://github.com/dongxuelian11/v3-quant-workbench/actions/runs/32626717564) `SUCCESS` on the same exact main |
| tag / release | [`v1.0.0`](https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/v1.0.0) points to exact main and was published as a public prerelease on 2026-08-23 |

These are historical V1.0 facts. They are not evidence for the unpushed V1.1
candidate or its redesigned Jobs A-F.

## Frozen product scope

```text
LOCAL-FIRST
A-SHARE-FIRST
RESEARCH-ONLY
PRE-ALPHA
AI-READY (L0 READ / L1 DRAFT only)
REPRODUCIBLE / AUDITABLE
NO BROKER
NO LIVE TRADING
```

The Windows product candidate includes project create/open, Product Research,
canonical Task/Run/Result/Artifact persistence, full Electron/backend exit, and
cold history rediscovery from `TaskService.v1.listTasks`. The restart gate uses
a new Electron process, renderer, and Zustand store; it begins from the real
`getInitialState()` and does not inject known IDs or use a shadow history store.

## Product wiring versus source availability

The required packaged wiring gate uses an explicit
`TEST_EXTERNAL_PROVIDER_BOUNDARY`. Successful deterministic rows are marked
with that source kind in the admitted raw payload and source metadata. They are
never described as Eastmoney observations and remain
`DEMO / PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`.

The separate unavailable gate deterministically proves:

```text
CAPABILITY_UNAVAILABLE
PROVIDER_ACQUISITION_UNAVAILABLE
fallback_used = false
Task = 0
Run = 0
Result = 0
RawCapture = 0
```

The admission owner may persist its real `DATA_TRUTH_CAPABILITY_POLICY`
Artifact. That policy evidence is not market data or a research/result
Artifact. No synthetic market bytes, successful task, result, or raw capture
is minted when acquisition fails, and the bound project remains usable for a
later retry.

Real AKShare/Eastmoney success is desirable but not a release blocker. The
bounded prior probe ended in external upstream/IP availability failure and did
not prove a V3 differential defect. V1.0 performs no silent fallback and does
not change provider to manufacture a PASS.

## Release identity and artifacts

The final candidate is required to bind one exact Git SHA/tree to:

- product/UI/package version `1.0.0`;
- backend `BuildManifest` and package lock;
- Windows x64 unpacked package and NSIS installer;
- `app.asar` and packaged runtime manifest hashes;
- embedded CPython 3.14.5 executable/license hashes;
- exact AKShare 1.18.84 import and wheel integrity;
- SPDX 2.3 SBOM, npm lock inventory, Python inventory, and license matrix.

`artifacts/package/V3_RELEASE_MANIFEST.json` is generated evidence and is not
committed. GitHub release CI uploads the tested installer/package plus this
manifest and their transfer hashes. A second fresh Windows runner begins with
no checkout, downloads only that artifact, installs it, exercises success,
cold restart, provider-unavailable, clean exit, and uninstall, and uploads its
bounded evidence.

## Known limitations

- Free-source PIT/available-time/revision and complete A-share trading-status,
  price-limit, listing, ST, suspension, and corporate-action truth remain
  incomplete. Results cannot become `FORMAL`.
- Live free-provider availability depends on external service/network state.
- Fully offline Python wheelhouse/`--require-hashes`, provider redundancy,
  high-scale Task pagination, architecture cleanup, UI polish, performance,
  advanced auto-update, and production signing remain V1.1/Post-V1 work.
- Agent execution/publish authority remains `NOT_AVAILABLE / NOT_RUN`.

The current deferred entries remain in `docs/status/V3_DEFERRED_GAPS.md`.
V1.1 evidence and remaining gates are tracked separately in
`V1_1_RELEASE_CANDIDATE.md` and the V1.1 State Ledger.
