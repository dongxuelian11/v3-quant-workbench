# V3 Windows packaged runtime candidate

This document records the bounded `PACKAGING_CLEAN_MACHINE_RUNTIME` implementation on the task branch. It is a packaging/runtime candidate, not a V1 release or a claim that the whole product is production available.

## Selected delivery

Exactly two backend delivery strategies were compared on the execution-time `main`:

| Strategy | Decision | Reason |
| --- | --- | --- |
| Bundled CPython plus shipped Python dependencies and backend resources | Selected | Preserves the existing `BackendSupervisor` framed stdio transport, module bootstrap, handshake, backpressure, generation/tombstone behavior, and graceful shutdown with the least semantic change. |
| One standalone backend executable | Rejected | The current repository has no standalone build chain; native/dynamic import collection and a direct-executable Supervisor branch would add packaging and validation surface that is not required for this wave. |

The only Electron packaging tool is `electron-builder` `26.15.3`. The selected Windows target is its unpacked `dir` output, which is a portable/fresh-extractable candidate and does not require Node.js or npm at runtime.

The shipped backend contains exact CPython `3.14.5` `win_amd64` files, a generated site-packages closure from the exact backend requirements, the backend package, the transport contract, dependency inventory, licenses, and a resource manifest with SHA-256 entries. The build fails closed on a missing or mismatched critical resource. Packaged mode selects `resources/backend-runtime` through Electron's `process.resourcesPath`; it never uses `process.cwd()`, `V3_BACKEND_PYTHON`, `V3_PYTHON`, or a system Python fallback.

The packaging command requires `V3_PACKAGED_PYTHON_ROOT` to point to the pre-supplied exact CPython `3.14.5` `win_amd64` build input. The preparation script verifies `python.exe`, `python314.dll`, the version/architecture, and the recorded runtime/license hashes before installing the pinned dependency closure. This build-time input is not a runtime prerequisite.

## Resource and storage boundaries

```text
<install>/
  resources/
    app.asar
    backend-runtime/
      python/python.exe
      python/python314.dll
      python/Lib/
      python/Lib/site-packages/
      backend-package/
      python-dependency-inventory.json
      runtime-manifest.json
```

Installation resources are treated as read-only. Product state remains under Electron `app.getPath("userData")` and the existing product storage resolver under `%LOCALAPPDATA%`. The smoke evidence verifies the catalog, artifact root, workspace state, and product binding paths are outside the extracted install root. No database migration was added.

In packaged mode, development backend overrides and `V3_PRODUCT_STORAGE_ROOT` are stripped from the backend environment; storage is derived from `%LOCALAPPDATA%` so an inherited override cannot redirect writes into the install tree. If a critical packaged resource is missing or corrupt, startup logs `PACKAGED_RUNTIME_UNAVAILABLE` and the Product Runtime reports a typed `DISCONNECTED`/`UNAVAILABLE` state without a fallback or fake `READY`.

The packaged core source capability remains `NOT_AVAILABLE` (`DataSourceService`, `ASL_FACADE_NOT_BOUND`) because real free-source/AkShare authority is outside this wave and is not silently installed or substituted at first launch.

## Verification commands

From the repository checkout, set the exact verified CPython input and build/verify the candidate with:

```powershell
$env:V3_PACKAGED_PYTHON_ROOT = Read-Host "Exact verified CPython 3.14.5 win_amd64 root"
npm.cmd run package:win:unpacked
npm.cmd run verify:package
npm.cmd run smoke:packaged-win
```

The smoke driver copies the final unpacked artifact to a fresh path containing spaces, scrubs developer Python/Node/npm overrides, creates fresh userData/storage roots, runs create/bind and relaunch/reopen, verifies the packaged backend handshake and Product Runtime state, checks truthful source capability, verifies graceful shutdown and no orphan backend, and checks that the installation tree is unchanged.

The observed same-machine candidate evidence is:

```text
PACKAGING_ISOLATED_RUNTIME_CANDIDATE = PASS
CLEAN_ENVIRONMENT_CLASS = ISOLATED_SAME_MACHINE
CLEAN_MACHINE_LAUNCH = NOT_PROVEN
SOURCE_CAPABILITY = NOT_AVAILABLE
```

The current local machine run is not Windows Sandbox, a clean VM, or a dedicated clean machine. The package build, verifier, and isolated create/bind/relaunch smoke pass on the task worktree, but this evidence cannot produce the task's success token. A clean exact-final-head guard, clean-machine evidence, push/PR/CI, and independent review remain separate gates.

## Level-2 clean-machine evidence workflow

`.github/workflows/packaging-clean-machine-evidence.yml` is a bounded PR #47 evidence workflow, not release CI. It has two independent `windows-latest` jobs:

1. `build-package` checks out the exact PR head, installs the build-only Node/CPython prerequisites, builds/verifies the unpacked Windows x64 package, reconciles the CPython build pin against `runtime-manifest.json` and the actual shipped `python.exe`, then uploads only a delivery ZIP, manifests, and `packaged-clean-machine-evidence.ps1`.
2. `verify-clean-machine` has no checkout/setup/install step. It proves the fresh Job B workspace has no repository markers, downloads only Job A's delivery artifact and driver, verifies the ZIP SHA-256, extracts to a fresh path containing spaces, scrubs runtime overrides/PATH, and runs the packaged Electron smoke twice.

The standalone driver emits `V3_PACKAGING_LEVEL2_CLEAN_MACHINE_EVIDENCE.json`. It fails closed unless the runner is distinct from Job A, the shipped CPython three-way SHA reconciliation is exact, framed `backend.hello`/`backend.ready` and Product Runtime `READY` are observed, empty storage creates and binds a canonical Project, `DataSourceService` remains `UNAVAILABLE`, both full app exits are graceful with zero orphan backend processes, the exact Project/ProjectContextRevision reopens, and the install tree digest is unchanged. Before a fresh GitHub-hosted Job B succeeds, the Level-2 claim remains `CLEAN_MACHINE_LAUNCH = NOT_PROVEN` and the result token is not permitted.

## Explicitly deferred

This candidate does not close real free-source authority, First Source Authority, full-app historical research rediscovery, release CI, V1 acceptance, code signing, auto-update, Model/Agent productization, async workers, or checkpoint/resume.
