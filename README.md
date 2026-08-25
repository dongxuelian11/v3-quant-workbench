# V3 Quantitative Research IDE / Workbench

V3 is a local-first, A-share-first, AI-native, reproducible and auditable professional Quant Research IDE / Workbench. It is organized around an Agent-first flow and five professional Labs: Research, Strategy, Model, Backtest, and Result.

> **Current line: V3 V1.1 Usable Research Product local candidate**
>
> **Package version: `1.0.0` until the complete C4 release gate passes**
>
> The current candidate connects a real packaged Product Home to local user-supplied data import, canonical Factor study, research Strategy publication, research Backtest, and VALID Result/Analytics readback. Its ceiling is `PRODUCT_CONNECTED / PRE_ALPHA / RESEARCH_ONLY / NOT_FORMAL`. The exact local package journey passes on the same machine, but the candidate is still unpushed and has a DIRTY BuildManifest. Hosted Jobs A-F, a distinct clean-machine run, live-provider acceptance, physical Windows scaling, user visual acceptance, independent review, and the `1.1.0` version bump remain `NOT_RUN` or `PENDING`.

The intended market scope is China A-share daily/end-of-day research. Live trading, broker connectivity, and paper trading are not included. Research results remain `PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE`; the current free-source path does not prove complete PIT, available-time, revision, suspension, ST, price-limit, or corporate-action truth.

Project doctrine and mandatory maturity language are defined by:

- [`V3_PROJECT_CONSTITUTION.md`](V3_PROJECT_CONSTITUTION.md) — product identity and non-negotiable authority invariants.
- [`docs/architecture/V3_CANONICAL_ARCHITECTURE.md`](docs/architecture/V3_CANONICAL_ARCHITECTURE.md) — target owner/resolver/runtime/product architecture, not a claim of full current wiring.
- [`docs/status/V3_CAPABILITY_LEVELS.md`](docs/status/V3_CAPABILITY_LEVELS.md) — evidence-based capability vocabulary.
- [`docs/status/V3_SYSTEMIC_REAUDIT_BASELINE.md`](docs/status/V3_SYSTEMIC_REAUDIT_BASELINE.md) — conservative unresolved finding register.

## What exists today

- Electron 39 desktop shell with a React 19/Vite presentation system, Dockview workspaces, ECharts, React Flow, Monaco, and persisted local layout/state.
- A typed Canonical Backend Foundation: contracts, Control Catalog/repositories, artifact plane, task/worker control plane, resource governor, and supervised local transport.
- Domain modules and bounded accepted slices across Data Truth, Factor/Dataset/Experiment, Model, Strategy/Signal, Portfolio/Risk, Backtest, Result Analytics, Reviewer, and L0/L1 Agent support. Exact maturity varies by owner and remains intentionally conservative pending systemic re-audit.
- A supervised Electron `backendRuntime` bridge and closed Product bridge. Product Home, local Data, Factor Research, research Strategy/Backtest, and Result pages become available only when their exact backend-owned prerequisites and bridge operations are present.
- A packaged Product Entry path over canonical Project, ProjectContext, Task, Run, Snapshot, Universe, Factor, Strategy, Backtest publication, Result/Analytics, Artifact, and provenance owners. Restart recovery rediscovers the same canonical chain without known-ID injection.
- CSV and Parquet local import through a native chooser and one-use main-process transfer. The renderer supplies neither authoritative paths/bytes nor canonical owner IDs. Imported observations remain `LOCAL_USER_SUPPLIED / PIT_UNPROVABLE / NOT_FORMAL`.
- Factor evaluation through the sole canonical evaluator, including honest single-symbol `INSUFFICIENT_SAMPLE` states and a 20-symbol cross-sectional acceptance case with independently checked IC, Rank IC, quantiles, and spread.
- A research-only Strategy → Portfolio/Risk decision chain → Backtest → VALID Result/Analytics path. The legacy Formal `BacktestService` remains fail-closed as `UNAVAILABLE / FORMAL_EXECUTION_CONTRACT_NOT_CLOSED`; VALID publication does not mean Formal market truth.
- Provider acquisition failure is explicit and fail-closed: it cannot mint market bytes or a successful canonical chain and performs no silent provider/fixture fallback.
- A Windows x64 NSIS installer and unpacked delivery with embedded CPython 3.14.5 and exact AKShare 1.18.84. First launch performs no Python dependency installation.
- Foundation and domain tests covering catalog/contracts, artifact/task boundaries, runtime framing, deterministic owner behavior, and selected integration paths.
- Clearly marked Demo/development providers for non-formal workflows; they cannot mint formal financial truth or silently stand in for unavailable production handlers.

Not every domain module has a production runtime handler, desktop bridge, or product surface. In particular, the broad ASL service catalog is not implied by the additive V1.1 Product Entry path. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN` until shared canonical user-action authority exists. Real free-provider availability is external and the V1.1 exact-package provider acceptance has not run; an exact `PROVIDER_ACQUISITION_UNAVAILABLE` result may be recorded as blocked, never converted into PASS.

## Prerequisites

- Node.js 24 (the current baseline was verified with 24.16.0) and npm 11.
- CPython 3.14.7 for repository validation where configured. The current Windows package contains exact CPython 3.14.5 win_amd64, whose executable and license hashes are bound in the runtime/package manifests. No optional Qlib/RQData/RQAlpha/GPU environment is required for the V1.1 local-data Golden Journeys.

## Build and verify

```text
npm ci
npm run validate:public
```

For the full local Electron smoke route, run `npm run validate` from a desktop session. Build output is generated under `dist/` and is not committed.

The Windows packaging gates require an exact CPython 3.14.5 build input through `V3_PACKAGED_PYTHON_ROOT`:

```text
npm run sbom:check
npm run package:win:release
npm run verify:package
npm run verify:release
npm run smoke:product-release
```

`smoke:product-release` is the V1.1 packaged local-data Journey A/B driver, not a live-provider or distinct-clean-machine test. `verify:release` is expected to reject a DIRTY BuildManifest; only a clean exact head may pass it. The hosted packaging workflow owns Jobs D-F: exact-package production, a no-checkout transferred-artifact clean-machine journey, and real AKShare acceptance with no deterministic/fallback provider inheritance.

For source-shaped product verification without claiming package or hosted evidence:

```text
npm run smoke:product-data
npm run smoke:product-factor
npm run smoke:product-backtest
npm run smoke:product-result
```

## Repository map

- `apps/desktop/` — Electron main/preload and React renderer.
- `apps/backend/src/v3_backend/` — Canonical Backend Foundation source.
- `apps/backend/tests/` — Foundation conformance and integration tests.
- `packages/contracts/` — current typed frontend boundary contracts.
- `docs/architecture/` — canonical target ownership plus implemented/future boundary documentation.
- `docs/status/` — mandatory capability vocabulary, authority manifest, systemic baseline, and status records.
- `docs/runtime/` — Core Python authority and optional-environment policy.
- `docs/oss/` and `sbom/` — publication readiness, license inventory, and SBOM.
- `docs/release/` — V1 scope, release identity, acceptance semantics, and known limitations.

## License and publication status

V3 is licensed under the **Apache License 2.0** (`Apache-2.0`). See the root `LICENSE` file. Dependency licenses remain separately recorded in `docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv`.

The released V1.0 history is recorded in [`docs/release/V1_0_RELEASE_CANDIDATE.md`](docs/release/V1_0_RELEASE_CANDIDATE.md). The current V1.1 candidate evidence and non-promoted gates are recorded in [`docs/release/V1_1_RELEASE_CANDIDATE.md`](docs/release/V1_1_RELEASE_CANDIDATE.md) and the task [`State Ledger`](docs/release/V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md). Unfinished scale, hermeticity, provider, physical-visual, clean-machine, and release work remains literal in [`docs/status/V3_DEFERRED_GAPS.md`](docs/status/V3_DEFERRED_GAPS.md).

The public repository is `https://github.com/dongxuelian11/v3-quant-workbench`. V1.0 has the historical public prerelease linked above; no V1.1 tag or release exists. Recovery provenance is documented in `docs/recovery/PROVENANCE_AND_DISASTER_REBUILD.md`.
