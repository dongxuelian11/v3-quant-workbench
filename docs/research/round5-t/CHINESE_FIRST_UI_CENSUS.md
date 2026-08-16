# A4 Chinese-first visible-string census

Task: `V3-SYSTEMIC-A4-T-CHINESE-LOW-CHROME-PRODUCT-REMEDIATION-01`

Pre-edit head: `7e404b5d9d8164f38a5cd80ce4980b23a3030248`

Scope: the Electron title/chrome, Agent Workspace, Research, Strategy, Model, Backtest, Result, Factor Library/detail, TDX, Evidence Explorer, Reviewer, artifact/generative views, dialogs, popovers, context actions, empty/loading/error/unsupported states, ARIA labels, titles, placeholders, chart legends, fixture-projected copy, and exact technical metadata under `apps/desktop/src/**`.

This is a closed classification ledger. Every user-visible string in scope is classified by the rules and exhaustive source-family rows below; dynamic values inherit the class of the field that renders them. Tests and developer-only exception messages that never enter a product surface are outside the visible-string census.

## Classification rules

### Class A — Chinese required

Ordinary product language: navigation, headings, buttons, tabs, tooltips, field labels, help, filters, categories, state explanations, commands, chart legends, empty/loading/error copy, accessibility labels, and fixture narrative shown to a user. Class A must be Chinese-primary after A4.

### Class B — Chinese plus canonical token

Traceability concepts whose exact token matters. The Chinese label/explanation is primary and the canonical token remains adjacent or is rendered as the value. Examples:

- `运行状态 · NOT_RUN / 尚未运行`
- `因子定义版本 · FactorDefinitionVersion`
- `输出类型 · BOOLEAN_SERIES`
- `评审者 · Reviewer`
- `权限 · L1_DRAFT`
- `产品连接 · NOT_CONNECTED`
- `真值 / 准入 / 验证 · NOT_FORMAL / PRE_ALPHA / NOT_RUN`

### Class C — exact technical text preserved

SHA-256 values, canonical object IDs, formulas, operator names, code, media types, source/transport IDs, immutable enum values in data cells, contract names, version IDs, market symbols, dates, numeric values, filenames, relation types, and parser/contract diagnostics that require exact traceability. Class C is not used as an excuse for an ordinary English label: its surrounding label/help remains Class A or B.

## Exhaustive pre-edit source-family register

| Product surface | Source family | Class A pre-edit findings | Class B/C retained |
| --- | --- | --- | --- |
| Shell and title bar | `App.tsx`, `WindowControls.tsx`, `main.ts` | `Agent Workspace`, `ACTIVE PROJECT`, `Momentum Research`, `Operations`, `Workspace ready`, `Agent-first`, `Research sessions`, `Context Inspector`, layout command help, English product ARIA name | `Ctrl K`, `Ctrl 0..5`, runtime/fixture tokens, project/version IDs |
| Global navigation and assets | `App.tsx`, `demo.ts` | `Universe`, `CN Daily Adjusted`, `Factor Panel`, `Imported Watchlist`, `IC Decay Analysis`, `Coverage Diagnostics`, `Deterministic provider`, availability label | symbols, version IDs, `Demo`, `LOCAL`, `UniverseVersion` |
| Agent Workspace shell | `AgentWorkspace.tsx`, `ResearchSessionNavigator.tsx` | active-session heading, research input/help, save action, permission explanations, stream headings, local draft label, evidence/action labels, timeline heading, empty-session explanation | `L0_READ`, `L1_DRAFT`, `L2_EXECUTE`, `L3_PUBLISH`, `NON_CANONICAL`, exact evidence IDs and state enums |
| Agent projected data | `agentWorkspaceFixture.ts`, `round3Evidence.ts`, `agentWorkspace.ts` | session titles/goals, statement titles/bodies, evidence titles/summaries/facts, artifact labels, timeline titles/details, boundary display labels, renderer display names | object types, exact IDs/hashes, state/admission/validation enums, transport/source IDs |
| Reviewer | `reviewer/*.tsx`, `reviewer/model.ts` | two-layer headings, rule titles/details, coverage explanations, required/optional labels, finding empty/detail/remediation/history copy, Agent capability explanations | rule IDs, `Reviewer`, outcome enums, report/rule-set IDs, forbidden-action tokens |
| Evidence Explorer | `evidence_explorer/EvidenceExplorer.tsx` plus projected model labels | explorer heading, search/help, graph/list/scope/filter/direction labels, empty/disconnected copy, detail headings, copy/open actions, relation/reference headings | exact IDs/hashes, node/artifact types, relation types, discovery/truth/admission/validation/integrity enums |
| Artifact Viewer | `ArtifactViewer.tsx` and renderer registry | empty/unsupported copy, identity/status headings, copy/open actions, artifact/result labels, future-slot explanation | IDs/hashes/media types, renderer tokens, availability/truth/admission/validation/integrity enums |
| Generative research | `generative_ui/GenerativeResearchView.tsx`, fixture/spec projections | generative heading, invalid/unsupported explanations, select/open/copy actions, evidence-binding summaries | `L1_DRAFT`, data-authority enums, block types, exact IDs, closed parser diagnostics |
| Research Lab | `Workbench.tsx`, `ResearchPanels.tsx`, `demo.ts` | Dockview titles, chart legend (`Price`, `Momentum MA`, `Benchmark`, `Volume`), context/metadata labels, Universe/analysis actions, event/ledger labels, analytics headings, constructor/config/form labels | security symbols, dates/values, `OHLC`, `UniverseVersion`, `As-of`, correlation/source IDs |
| Factor Library/detail | `FactorWorkbench.tsx` | `FACTOR WORKSPACE`, category taxonomy, lifecycle/help labels, `lookback`, detail field labels, `Operators`, `Source language`, `Canonical IR`, ID-block labels, connection explanations | `FactorDefinitionVersion`, `FactorAssetVersion`, `BOOLEAN_SERIES`, `CANDIDATE`, operators, IDs, formulas |
| TDX editor | `FactorWorkbench.tsx`, `monacoPresentation.tsx` | editor/analysis headings, fixture-loading actions, deterministic preview headings, validation/static-analysis/data-semantic labels, AI draft/review actions | TDX source, canonical operators, `PASSED`, `UNSUPPORTED`, `NOT_CONNECTED`, `L1_DRAFT`, formula and profile IDs |
| Strategy Lab | `Workbench.tsx`, `StrategyPanels.tsx`, `store.ts`, `demo.ts` | Dockview/editor titles, node labels/details, `Visual/Code/Split/Diff`, validation/handoff/status/autosave copy, review/hunk/contract headings | `StrategyDraft`, `BacktestHandoffDraft`, `Proposal`, state enums, node-kind tokens, Python code |
| Model Lab | `Workbench.tsx`, `ModelPanels.tsx`, `demo.ts` | phase titles/subtitles, dataset/config/run/study/compare/version headings and help, form labels, split labels, guard copy, run table headers, actions, study tabs/actions, metrics and version review labels | `DatasetVersion`, `SplitPlan`, `Study`, `Trial`, `ModelVersion`, `PredictionSignalVersion`, state tokens, run IDs, parameter names |
| Backtest Lab | `Workbench.tsx`, `BacktestResultPanels.tsx` | tab labels, experiment/context headings, queue/scenario/cost/constraint labels, actions, run matrix labels, metrics, evidence fields, execution-table headers | `BacktestHandoffDraft`, run/order IDs, state enums, bps, symbols, numeric values |
| Result Lab | `Workbench.tsx`, `ResultAnalyticsPanel.tsx`, `resultAnalyticsViewModel.ts` | all five tabs, hero title/metric labels, chart legend, KPI labels, drawdown/benchmark/period/trading/cost/policy headings and fields, empty/unavailable explanations | result/policy/benchmark/analytics IDs and hashes, `NAV`, state/reason tokens, exact policy values |
| Dialogs/popovers/context actions | `App.tsx`, Workbench menu, drawers, scenario/form controls | command palette groups/help, layout menu, inspector/operations drawers, research/universe/backtest drawers, placeholders and tooltip labels | keyboard shortcuts, canonical object names and IDs |
| Accessibility and responsive text | all JSX `aria-*`, `title`, placeholders; CSS pseudo-content if present | English ARIA names and titles mirror the ordinary labels above and require Chinese-primary replacements | canonical tokens remain included where needed for exact technical context |
| Loading/empty/error/unsupported | `StatusSurface`, Agent/Evidence/Artifact/Generative/Factor/Result surfaces | English ordinary explanations and action labels require Chinese-primary copy | exact state/reason tokens and closed technical diagnostics remain adjacent as Class B/C |

## Pre-edit ordinary-English removal set

The bounded automated guard will reject these known ordinary labels when they occur as product copy after A4:

`Agent Workspace`, `Workspace index`, `Research sessions`, `Active research session`, `Research input`, `Save L1 draft`, `Evidence Inspector`, `Execution stream`, `Workspace ready`, `Active project`, `Selected context`, `Operations`, `Layout actions`, `Research · Price / Evidence`, `StrategyDraft · Editor`, `Model · Workflow`, `Backtest · Execution`, `Result · Performance`, `Visual`, `Code`, `Split`, `Validation`, `Selected node`, `Autosaved locally`, `Dataset`, `Configure`, `Run`, `Compare`, `Version`, `Trial History`, `Importance`, `Relationships`, `Parallel Coordinates`, `Overview`, `Period Returns`, `Trading & Cost`, `Policy & Identity`, `Review`, `Run Matrix`, `Holdings`, `Orders / Fills`, `Attribution`, `Graph`, `List`, `Active session`, `Loaded workspace`, `Copy ID`, `Copy hash`, `Open in`, `No canonical evidence available`, `Backend evidence unavailable`, `No session artifact selected`, `Deterministic Result Lab`.

## Post-edit acceptance accounting

- Class A remaining ordinary English from the bounded removal set: `0` in the edited source. The focused A4 census test and final real Electron capture passed.
- Class B presentation: source and Electron review `PASS`. Canonical concepts are Chinese-primary with adjacent exact tokens, including `FactorDefinitionVersion`, `BOOLEAN_SERIES`, `Reviewer`, `NOT_CONNECTED`, `L1_DRAFT`, `L2 EXECUTE`, and `L3 PUBLISH`.
- Class C preservation: focused source/test gate and final full validation `PASS`. Exact formulas, operators, object IDs, hashes, internal tab/state identifiers, and test selectors remain intact.
- Low-chrome source gate: metadata grids and provenance IDs default to borderless label/value rows; borders remain for inputs, warnings, selected objects, graph nodes, and semantically bounded artifacts. Eleven A4 evidence PNGs were manually inspected after the final full validation; the only first-pass layout finding was corrected and recaptured.
- `USER_VISUAL_ACCEPTANCE`: `PENDING`; screenshots cannot self-award it.

Focused command: `node --test --experimental-strip-types tests/unit/round5-t-desktop-productization.test.mjs` → `8/8 PASS`.

Final command: `npm run validate` → `PASS` (complete public chain, Electron capture/restart/production-boundary, and visual evidence inventory).
