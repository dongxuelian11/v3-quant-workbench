# V3 Quantitative Research Workbench

V3 is a personal/private-origin quantitative research workbench being rebuilt as a public source project. It is organized around five connected Labs: Research, Strategy, Model, Backtest, and Result.

> **Status: PRE-ALPHA / ACTIVE RECONSTRUCTION**
>
> The current frontend is an accepted development baseline, not a final UI. The Canonical Backend Foundation is present, but formal Data Truth, Research, Model, Portfolio/Risk, Backtest, and Result capabilities have not been rebuilt. Demo data is illustrative UI input, not formal financial output.

The intended formal market scope is China A-share daily/end-of-day research. Live trading and paper trading are not included. This repository is not production-ready or trading-ready.

## What exists today

- Electron 39 desktop shell with a React 19/Vite presentation system, Dockview workspaces, ECharts, React Flow, Monaco, and persisted local layout/state.
- A typed Canonical Backend Foundation: contracts, Control Catalog/repositories, artifact plane, task/worker control plane, resource governor, and supervised local transport.
- Foundation tests covering the 56-table Control Catalog, contract digest, artifact and task boundaries, runtime framing, and ownership invariants.
- Clearly marked deterministic Demo providers that keep the five Labs explorable while formal domain backends remain unavailable.

The WS-E transport modules are not wired into the current frontend main/preload entrypoints. That integration remains future work.

## Prerequisites

- Node.js 24 (the current baseline was verified with 24.16.0) and npm 11.
- CPython 3.14.7 for the Canonical Core authority. The Foundation is currently standard-library-only; no optional Qlib/RQData/RQAlpha/GPU environment is required.

## Build and verify

```text
npm ci
npm run validate:public
```

For the full local Electron smoke route, run `npm run validate` from a desktop session. Build output is generated under `dist/` and is not committed.

## Repository map

- `apps/desktop/` — Electron main/preload and React renderer.
- `apps/backend/src/v3_backend/` — Canonical Backend Foundation source.
- `apps/backend/tests/` — Foundation conformance and integration tests.
- `packages/contracts/` — current typed frontend boundary contracts.
- `docs/architecture/` — implemented boundaries and future capability separation.
- `docs/status/` — current truthful capability status.
- `docs/runtime/` — Core Python authority and optional-environment policy.
- `docs/oss/` and `sbom/` — publication readiness, license inventory, and SBOM.

## License and publication status

V3 is licensed under the **Apache License 2.0** (`Apache-2.0`). See the root `LICENSE` file. Dependency licenses remain separately recorded in `docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv`.

The authorized PB1 public repository target is `https://github.com/dongxuelian11/v3-quant-workbench`. Publication does not create a tag or GitHub release. Recovery provenance is documented in `docs/recovery/PROVENANCE_AND_DISASTER_REBUILD.md`.
