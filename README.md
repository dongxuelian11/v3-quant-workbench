# V3 Open Source Rebuild

V3 is a desktop quantitative research workbench organized around five connected product Labs: Research, Strategy, Model, Backtest, and Result.

This repository is the same-lineage FR-0 / FR-1 recovery candidate created after the former local worktree was lost. FR-1 now uses a componentized React 19 + Vite renderer inside Electron 39, with Dockview workspaces, linked ECharts research, React Flow, Monaco Editor/Diff, and durable restart persistence. The canonical backend has not been rebuilt. Deterministic Demo providers keep all five product Labs operable and are visibly marked as non-formal output.

## Run the recovered frontend

```text
npm install
npm run build
npm run validate
npm run smoke:electron
```

The application is launched from the compiled Electron main process. Context isolation is enabled, Node integration is disabled in the renderer, and the preload bridge is the only desktop boundary.

## Scope and status

- FR-0 repository bootstrap: implemented locally; no remote, tag, release, or license has been created.
- FR-1 frontend capability restoration: candidate ready for user UAU; no user result is claimed.
- Backtest / Result: `RECOVERED_FROM_PRODUCT_DESIGN_NOT_PRIOR_WAVE3_ACCEPTANCE`, with explicit Demo provenance.
- Backend reconstruction: intentionally out of scope. See `apps/backend/README.md`.
- License: pending explicit user decision; see `LICENSE_PENDING.md`.

Recovery and provenance details live in `docs/recovery/`.
