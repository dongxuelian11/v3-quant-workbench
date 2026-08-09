# WS-E Runtime Boundary and Later WS-K Binding

Status: `READY_FOR_LATER_WS_K_BINDING`

WS-E is based on committed WS-A seed `1f598ace73bbd1fe2c43e7253a7b9fcbe1f1658a`.
The verified WS-A Contract Seed V1 digest is
`99476cfd4d6768397c5ee2df2f2cdadaee4b499244a31213d179a9755f009f80`.

## Boundary

- `v3_backend.runtime` owns authenticated framing, handshake, frozen-operation
  dispatch, capability delivery, durable-event delivery/replay, operational
  health, and graceful shutdown coordination only.
- Business calls exist only as injected callables keyed by frozen WS-A
  operation IDs. An unbound callable is explicitly `CAPABILITY_UNAVAILABLE`.
- Electron Main owns the single Python process, token handle, correlation,
  timeouts, reconnect/replay, crash-loop ceiling, typed Task cancellation,
  stream-ticket mediation, and shutdown lifecycle.
- Preload exposes only named runtime/capability methods and event subscriptions.
  It exposes no raw transport, spawn, path, database, or filesystem API.
- No legacy launcher, runtime installation, `sys.path` mutation, business
  owner, renderer storage access, or fallback route exists.

## Later WS-K one-time binding

After FR-1 stabilizes, WS-K may make one bounded integration in the current
Main/Preload entrypoints:

1. In Electron Main, instantiate `BackendSupervisor` with the packaged Python
   executable, fixed backend module working directory, desktop version, and
   trusted ProjectContext.
2. Register `registerBackendRuntimeIpc` with the existing trusted-sender guard.
3. Attach `BackendRuntimeEventRelay` to the active window webContents and bind
   `BackendRuntimeLifecycle` to tray/window-close and explicit-quit hooks.
4. In Preload, call `installBackendRuntimeBridge()` once. Do not expose the
   internal supervisor `request` method or any process/path handle.
5. Bind renderer providers only to the named `v3BackendRuntime` methods. Keep
   capability truth visible and never convert disconnect/unavailable to Demo.

WS-K must preserve the existing FR-1 UI behavior and must not move business
logic into Electron Main or Preload.

## Verification commands

```text
PYTHONPATH=apps/backend/src python -B -m unittest discover -s apps/backend/tests/ws_e_runtime -v
npm run typecheck
npm run lint
npm test
npm run build
node --test tests/ws_e_electron_runtime/*.test.mjs
```
