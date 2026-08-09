# Publication readiness

This document describes the technical public-source baseline and its PB1 publication controls. It is not a versioned release authorization.

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
- Public GitHub CI runs `npm run validate:public`. Its frontend smoke is deterministic and repository-contained: it checks build outputs, renderer assets, five-Lab contracts, Electron security invariants, and Demo truth boundaries without starting Electron or reading generated evidence.
- Local desktop evidence remains a separate, stronger route: `npm run smoke:electron` captures the real Electron states, then `npm run smoke:visual-evidence` validates screenshots, geometry, restart persistence, interaction evidence, and security preferences. `deliverables/` remains ignored and is never a Public CI input. If local evidence is absent, that local-only gate is not run; it is not a PASS.
- SPDX 2.3 inventory and an exact dependency-license matrix are generated from committed manifests/lock data.
- Task packages, local agent state, runtime databases, market datasets, model weights, credentials, dependencies, and build output are ignored and forbidden from the public tree.

## PB1 publication controls

1. Project license: Apache-2.0, with the canonical text committed as root `LICENSE`.
2. Authorized public target: `https://github.com/dongxuelian11/v3-quant-workbench`.
3. The published `main` SHA, hosted CI conclusion for that exact SHA, and branch-protection state must be independently verified through GitHub.

PB1 creates no tag or GitHub release. Publication does not change the PRE-ALPHA / ACTIVE RECONSTRUCTION status or claim production/trading readiness.
