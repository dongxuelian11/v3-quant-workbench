# V3 Open Source Rebuild

V3 is a desktop quantitative research workbench organized around five connected product Labs: Research, Strategy, Model, Backtest, and Result.

This repository is the FR-0 / FR-1 frontend recovery candidate created after the former local worktree was lost. It restores the accepted Wave 1 / Wave 2 product surface as a clean local Electron application. The canonical backend has not been rebuilt in this task. Backtest and Result actions therefore expose an explicit unavailable state and do not present formal financial or model output.

## Run the recovered frontend

```text
npm install
npm run validate
npm run build
npm run smoke:electron
```

The application is launched from the compiled Electron main process. Context isolation is enabled, Node integration is disabled in the renderer, and the preload bridge is the only desktop boundary.

## Scope and status

- FR-0 repository bootstrap: implemented locally; no remote, tag, release, or license has been created.
- FR-1 accepted frontend reconstruction: implemented as a review candidate.
- Backend reconstruction: intentionally out of scope. See `apps/backend/README.md`.
- License: pending explicit user decision; see `LICENSE_PENDING.md`.

Recovery and provenance details live in `docs/recovery/`.

