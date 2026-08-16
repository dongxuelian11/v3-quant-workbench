# Round 5 T Reuse Adoption Matrix

This matrix records the reuse-first gate against accepted main `eda009b601b681c8a26d2a98a1093b3e6f33245e`. Unmerged P/Q/S code is not consumed.

| Need | Current-main owner / dependency | Decision | T boundary |
| --- | --- | --- | --- |
| Application shell | React 19 renderer and existing `App.tsx` | `DIRECT_REUSE` | Extend the existing shell; no second frontend. |
| Five professional Labs | Existing `LabId`, navigation, and Dockview workbench | `DIRECT_REUSE` | Factor Library is a Research Lab surface, not a sixth Lab. |
| Agent-first surface | Existing `AgentWorkspace`, session navigator, evidence timeline | `DIRECT_REUSE` | Preserve the canonical read-only projection and session scope. |
| Desktop transport | Existing context-isolated preload and trusted main-process IPC | `THIN_EXTENSION` | Add only bounded window state/control messages; no second IPC or remote bridge. |
| Desktop chrome | Electron 39 `BrowserWindow` and `Menu` | `THIN_EXTENSION` | Frameless Windows chrome, suppressed native menu, native minimize/maximize/restore/close. |
| Command/search | Existing `cmdk` palette | `DIRECT_REUSE` | Keep Ctrl+K and Chinese-first labels. |
| Research layouts | Existing Dockview 7 | `DIRECT_REUSE` | Keep persisted professional panels and add an adjacent Factor workspace switch. |
| Charts | Existing ECharts 6 | `DIRECT_REUSE` | No chart dependency added. |
| Formula editing | Existing Monaco 0.56 | `DIRECT_REUSE` | Editor only; no browser formula parser, translator, or evaluator. |
| Factor truth | Accepted W0 `FactorAssetVersion` / `FactorDefinitionVersion` / TDX contracts | `READ_ONLY_FIXTURE_PROJECTION` | Exact IDs are present only under the existing development integration mode. Production is `NOT_CONNECTED`. |
| Evaluation truth | Existing canonical evaluation owner | `NO_SHADOW_MODEL` | No context means `未评估`; never show intrinsic IC/ICIR. |
| AI factor creation | Current-main L1 permission contract | `BOUNDARY_UI_ONLY` | P is unmerged; production says `NOT_CONNECTED`. Fixture demonstrates proposal/review only. |
| Animation | Existing CSS presentation system | `BOUNDED_POLISH` | Instant feedback, restrained material, no new motion dependency. |
| Localization | Existing Chinese-first product copy | `MAINTAINABLE_COLOCATED_COPY` | Primary navigation, Factor, TDX, truth states, errors, and actions are Chinese-first while canonical IDs remain exact. |

No dependency, framework, package manifest, or lockfile change is required.
