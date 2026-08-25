# Product surface

V3 remains one continuous desktop workbench. The current V1.1 `ProductEntryService` path is a focused Home → Data → Research → Backtest → Result journey over shared canonical Project/ProjectContext state. It does not claim that every historical Lab contract or broad ASL service is product-connected.

## Current V1.1 Product actions

| Surface/action | Current product state | Exact boundary |
| --- | --- | --- |
| Home: create/open/switch project | `PRODUCT_CONNECTED` | Main owns Project/Session binding and refreshes the backend-owned `ProductProjectHomeView`; project identity is canonical, but it grants no financial truth. |
| Home: staged next action and progress | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Data/Factor/Strategy/Backtest stages derive from Project Home. Missing prerequisites remain explicit and the corresponding navigation item stays disabled. |
| Data: choose and import CSV/Parquet | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Native chooser and one-use main-process transfer; canonical Data owners validate actual bytes. Source is `LOCAL_USER_SUPPLIED`, PIT is `PIT_UNPROVABLE`, and invalid input creates no successful chain. |
| Data: live AKShare acquisition | `NOT_RUN` for the V1.1 exact package | Product acquisition is fail-closed with no fixture/provider fallback. Only exact `PROVIDER_ACQUISITION_UNAVAILABLE` may be classified as an external block. |
| Research: Factor source/evaluation | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Product Entry submits a durable Task; backend resolves Snapshot/Universe/partition bytes and uses the sole canonical Factor evaluator. The renderer performs no Factor math. |
| Research: Factor Analysis | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Daily cross-sectional metrics precede aggregate metrics. One-symbol cases report `INSUFFICIENT_SAMPLE`; numeric values are not fabricated. |
| Backtest: publish research Strategy | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Exact current Factor/Profile refs are resolved from fresh Project Home. The resulting decision chain is research-only; broad Formal Strategy/Portfolio/Risk facades are not implied. |
| Backtest: preflight and run | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Product Entry owns the Task and isolated worker path. Explicit A-share research assumptions remain visible. Legacy Formal `BacktestService` stays `UNAVAILABLE / FORMAL_EXECUTION_CONTRACT_NOT_CLOSED`. |
| Backtest: retry failed run | `PRODUCT_CONNECTED` for eligible failed V1.1 research Tasks | Retry uses the same canonical input identities and a new durable attempt; terminal/invalid states fail closed. Generic resume is `NOT_AVAILABLE`. |
| Result: latest VALID publication | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Project Home must point to the exact VALID Result. VALID denotes completed publication, not Formal data or `PRODUCTION_AVAILABLE`. |
| Result: charts, metrics, orders/fills/holdings/diagnostics, exports and lineage | `PRODUCT_CONNECTED / PRE_ALPHA / NOT_FORMAL` | Main resolves and verifies exact Result, Analytics, Lineage, and table Artifact bytes; renderer presentation cannot mint or alter canonical numbers. Missing/corrupt readback remains unavailable. |
| Agent execution/publish | `NOT_AVAILABLE / NOT_RUN` | L0 READ and L1 DRAFT are the ceiling until shared canonical user-action authority exists. |
| Model Product flow | `NOT_AVAILABLE` in this V1.1 Product entry | Model modules do not imply a V1.1 page, bridge, or Product Entry operation set. |

## Presentation and release evidence

The current packaged same-machine matrix covers Home, Data, Research, Backtest, and Result at four viewports and Electron zoom 100/125/150. Machine layout/accessibility checks pass, while physical Windows scaling, keyboard completion through the native file chooser, and `USER_VISUAL_ACCEPTED` remain `NOT_RUN` / `PENDING`.

The package still reports version `1.0.0`, has a DIRTY BuildManifest, and is not a clean V1.1 release. Hosted exact-head Jobs A-F, distinct clean-machine execution, live-provider acceptance, PR checks, and independent review remain separate evidence gates.

Risk is not a sixth Lab. It belongs to the Backtest/Result and wider research workflow, and its broad Formal product facade is not promoted by the bounded V1.1 research decision chain.
