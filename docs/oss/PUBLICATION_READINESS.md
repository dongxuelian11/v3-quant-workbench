# Publication readiness

This document describes the technical public-source baseline. It is not a release authorization or a legal license decision.

## Public positioning

- Status: pre-alpha / active reconstruction.
- Origin: personal/private-origin quantitative research workbench rebuilt from accepted source authority after catastrophic local workspace loss.
- Intended formal market scope: China A-share daily/end-of-day research.
- Live trading: not included.
- Paper trading: not included.
- Production-ready: false.
- Trading-ready: false.
- Frontend: current development baseline, not final UI.
- Backend: Canonical Foundation present; formal Data Truth and financial-domain capabilities not rebuilt.
- Demo data: non-formal illustrative output only.

## Technical controls

- Reproducible JavaScript install through the committed npm lockfile.
- CPython Core authority pinned in `.python-version` and documented under `docs/runtime/`.
- CI runs frontend checks, Foundation tests/compile, cross-language runtime checks, tracked-source secret/history checks, forbidden-file/size audit, and SBOM validation.
- SPDX 2.3 inventory and an exact dependency-license matrix are generated from committed manifests/lock data.
- Task packages, local agent state, runtime databases, market datasets, model weights, credentials, dependencies, and build output are ignored and forbidden from the public tree.

## Deliberate blockers before publication

1. The owner must select and add the project license.
2. The owner must explicitly authorize creation of a public remote and push.
3. The first hosted CI run must be observed after remote creation.

PB0 does not create a remote, authenticate to GitHub, push, tag, publish a release, or claim legal open-source availability.
