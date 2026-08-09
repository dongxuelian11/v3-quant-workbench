# Architecture

V3 currently has two deliberately separate planes.

## Desktop presentation plane

Electron owns the desktop process boundary. The renderer is a React/Vite application composed around five Labs and local Demo providers. Context isolation is enabled, Node integration is disabled in the renderer, and preload is the only desktop bridge.

The current presentation system is a development baseline, not a final UI or final user-acceptance freeze.

## Canonical Backend Foundation

The Python Foundation provides contracts, provenance primitives, the Control Catalog/repository layer, artifact boundaries, task/worker supervision, resource governance, and framed local transport. It deliberately stops before financial-domain implementation.

```text
Desktop development baseline
  └─ typed availability boundaries

Canonical Backend Foundation
  ├─ contracts and provenance
  ├─ 56-table Control Catalog / repositories
  ├─ artifact plane
  ├─ task / worker / resource control plane
  └─ supervised local transport (not yet wired to the desktop entrypoints)

Future isolated capability profiles
  ├─ Data Truth
  ├─ Research and Model
  ├─ Portfolio and Risk
  └─ Backtest and Result
```

Formal market truth must arrive through a later, independently admitted Data Truth implementation. Demo providers and contract shapes are not substitutes for that implementation.

See `PRODUCT_SURFACE.md`, `BACKEND_FUTURE_CONTRACT.md`, `docs/status/CURRENT_STATUS.md`, and `docs/runtime/OPTIONAL_ENVIRONMENT_PROFILE_BOUNDARIES.md`.
