# V3 Quantitative Research IDE / Workbench

V3 is a local-first, A-share-first, AI-native, reproducible and auditable professional Quant Research IDE / Workbench. It is organized around an Agent-first flow and five professional Labs: Research, Strategy, Model, Backtest, and Result.

> **Version: 1.0.0 Product Release Candidate / PRE-ALPHA / RESEARCH-ONLY**
>
> V1.0 is a Windows local-first product candidate. The packaged flow can create/open a project, run explicitly test-safe Product Research, persist canonical Task/Run/Result/Artifact evidence, and rediscover the same identities after a full process restart. This is not a `PRODUCTION_AVAILABLE`, formal-data, or trading claim. Deterministic acceptance data is visibly classified `TEST_EXTERNAL_PROVIDER_BOUNDARY` and is never represented as live Eastmoney data.

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
- A supervised Electron `backendRuntime` bridge for a bounded read-only canonical evidence path, including explicit disconnected/no-evidence states and an explicitly named development-fixture mode.
- A packaged Product Entry/Product Research path over the canonical Project, Task, Run, Result, Artifact, and raw-capture owners. Provider acquisition failure is explicit and fail-closed: it creates no Task/Run/Result/RawCapture and performs no silent fallback.
- A Windows x64 NSIS installer and unpacked delivery with embedded CPython 3.14.5 and exact AKShare 1.18.84. First launch performs no Python dependency installation.
- Foundation and domain tests covering catalog/contracts, artifact/task boundaries, runtime framing, deterministic owner behavior, and selected integration paths.
- Clearly marked Demo/development providers for non-formal workflows; they cannot mint formal financial truth or silently stand in for unavailable production handlers.

Not every domain module has a production runtime handler, desktop bridge, or product surface. Production Agent execution remains `NOT_AVAILABLE / NOT_RUN` until shared canonical user-action authority exists. Real free-provider availability is external and may be unavailable; V1.0 reports `PROVIDER_ACQUISITION_UNAVAILABLE`, keeps the application usable, and allows a later retry without inventing market bytes or a successful research chain.

## Prerequisites

- Node.js 24 (the current baseline was verified with 24.16.0) and npm 11.
- CPython 3.14.7 for repository validation where configured. The shipped Windows V1.0 package contains exact CPython 3.14.5 win_amd64, whose executable and license hashes are bound in the runtime/release manifests. No optional Qlib/RQData/RQAlpha/GPU environment is required for the V1 Product Research flow.

## Build and verify

```text
npm ci
npm run validate:public
```

For the full local Electron smoke route, run `npm run validate` from a desktop session. Build output is generated under `dist/` and is not committed.

The Windows release gates require an exact CPython 3.14.5 build input through `V3_PACKAGED_PYTHON_ROOT`:

```text
npm run sbom:check
npm run package:win:release
npm run verify:package
npm run verify:release
npm run smoke:product-release
```

`smoke:product-release` is product-wiring acceptance, not a live-provider availability test. It proves deterministic canonical persistence/cold rediscovery and deterministic provider-unavailable fail-closed behavior. The optional `smoke:product-closure` command remains the bounded real AKShare/Eastmoney probe and may truthfully fail when the upstream service or current IP path is unavailable.

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

V1.0 candidate scope and limitations are recorded in [`docs/release/V1_0_RELEASE_CANDIDATE.md`](docs/release/V1_0_RELEASE_CANDIDATE.md). Unfinished scale, hermeticity, provider-redundancy, architecture, and polish work remains literal in [`docs/status/V3_DEFERRED_GAPS.md`](docs/status/V3_DEFERRED_GAPS.md).

The authorized PB1 public repository target is `https://github.com/dongxuelian11/v3-quant-workbench`. Publication does not create a tag or GitHub release. Recovery provenance is documented in `docs/recovery/PROVENANCE_AND_DISASTER_REBUILD.md`.
