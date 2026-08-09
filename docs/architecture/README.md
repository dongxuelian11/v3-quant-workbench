# Architecture

V3 currently has two deliberately separate planes.

## Desktop presentation plane

Electron owns the desktop process boundary. The renderer is a React/Vite application composed around five Labs and local Demo providers. Context isolation is enabled, Node integration is disabled in the renderer, and preload is the only desktop bridge.

The current presentation system is a development baseline, not a final UI or final user-acceptance freeze.

## Canonical Backend Foundation

The Python Foundation provides contracts, provenance primitives, the Control Catalog/repository layer, artifact boundaries, task/worker supervision, resource governance, framed local transport, and the WS-F provider-independent Data Truth layer. It stops before external provider admission and downstream research/execution domains.

```text
Desktop development baseline
  └─ typed availability boundaries

Canonical Backend Foundation
  ├─ contracts and provenance
  ├─ 67-table Control Catalog / repositories
  ├─ artifact plane
  ├─ task / worker / resource control plane
  └─ supervised local transport (not yet wired to the desktop entrypoints)

Future isolated capability profiles
  ├─ external Data providers
  ├─ Research and Model
  ├─ Portfolio and Risk
  └─ Backtest and Result
```

WS-F now supplies the provider-independent Data Truth objects and fail-closed Snapshot/PIT/Universe policies. No external market-data provider is admitted, so Demo providers and contract shapes remain non-Formal. See `DATA_TRUTH_V1.md`.

See `PRODUCT_SURFACE.md`, `BACKEND_FUTURE_CONTRACT.md`, `docs/status/CURRENT_STATUS.md`, and `docs/runtime/OPTIONAL_ENVIRONMENT_PROFILE_BOUNDARIES.md`.
