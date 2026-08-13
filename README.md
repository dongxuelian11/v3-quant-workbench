# V3 Quantitative Research IDE / Workbench

V3 is a local-first, A-share-first, AI-native, reproducible and auditable professional Quant Research IDE / Workbench. It is organized around an Agent-first flow and five professional Labs: Research, Strategy, Model, Backtest, and Result.

> **Status: PRE-ALPHA / ACTIVE RECONSTRUCTION**
>
> Multiple canonical domain modules and historically accepted owner/integration slices exist, but their presence does not by itself prove `PRODUCT_CONNECTED` or `PRODUCTION_AVAILABLE`. The systemic payload, integration, runtime, product, and capability-level re-audit is pending; it is not complete. Demo and development-fixture data is never formal financial output.

The intended formal market scope is China A-share daily/end-of-day research. Live trading, broker connectivity, and paper trading are not included. This repository makes no feature-complete, production-ready, or trading-ready claim.

Project doctrine and mandatory maturity language are defined by:

- [`V3_PROJECT_CONSTITUTION.md`](V3_PROJECT_CONSTITUTION.md) — product identity and non-negotiable authority invariants.
- [`docs/architecture/V3_CANONICAL_ARCHITECTURE.md`](docs/architecture/V3_CANONICAL_ARCHITECTURE.md) — target owner/resolver/runtime/product architecture, not a claim of full current wiring.
- [`docs/status/V3_CAPABILITY_LEVELS.md`](docs/status/V3_CAPABILITY_LEVELS.md) — evidence-based capability vocabulary.
- [`docs/status/V3_SYSTEMIC_REAUDIT_BASELINE.md`](docs/status/V3_SYSTEMIC_REAUDIT_BASELINE.md) — conservative unresolved finding register.

## What exists today

- Electron 39 desktop shell with a React 19/Vite presentation system, Dockview workspaces, ECharts, React Flow, Monaco, and persisted local layout/state.
- A typed Canonical Backend Foundation: contracts, Control Catalog/repositories, artifact plane, task/worker control plane, resource governor, and supervised local transport.
- Domain modules and bounded accepted slices across Data Truth, Factor/Dataset/Experiment, Model, Strategy/Signal, Portfolio/Risk, Backtest, Result Analytics, Reviewer, and L0/L1 Agent support. Exact maturity varies by owner and remains intentionally conservative pending systemic re-audit.
- A supervised Electron `backendRuntime` bridge for a bounded read-only canonical evidence path, including explicit disconnected/no-evidence states and an explicitly named development-fixture mode.
- Foundation and domain tests covering catalog/contracts, artifact/task boundaries, runtime framing, deterministic owner behavior, and selected integration paths.
- Clearly marked Demo/development providers for non-formal workflows; they cannot mint formal financial truth or silently stand in for unavailable production handlers.

Not every domain module has a production runtime handler, desktop bridge, or product surface. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN` until shared canonical user-action authority exists. See the authority documents above instead of inferring availability from file or PR presence.

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
- `docs/architecture/` — canonical target ownership plus implemented/future boundary documentation.
- `docs/status/` — mandatory capability vocabulary, authority manifest, systemic baseline, and status records.
- `docs/runtime/` — Core Python authority and optional-environment policy.
- `docs/oss/` and `sbom/` — publication readiness, license inventory, and SBOM.

## License and publication status

V3 is licensed under the **Apache License 2.0** (`Apache-2.0`). See the root `LICENSE` file. Dependency licenses remain separately recorded in `docs/oss/THIRD_PARTY_LICENSE_MATRIX.csv`.

The authorized PB1 public repository target is `https://github.com/dongxuelian11/v3-quant-workbench`. Publication does not create a tag or GitHub release. Recovery provenance is documented in `docs/recovery/PROVENANCE_AND_DISASTER_REBUILD.md`.
