# Track K Agent-First Frontend V0 — Reuse / Adoption Report

Date: 2026-08-11
V3 base: `f88b0ebe5af4733e46a00ab373ff61c159e82ff2`
Decision rule: reuse only when license, current maintenance, React/Electron compatibility, dependency weight, authority fit, and long-term ownership are all acceptable.

## Executive decision

Track K adds **no new runtime dependency and copies no third-party component source**. The reviewed products are valuable design and interaction references, but their agent authority, transport, data models, and application shells do not match V3's current-main contracts. The safe reusable unit is the interaction pattern: session-first navigation, observable plans and tool calls, evidence beside conclusions, and a closed renderer registry. V3 implements those patterns natively on top of its existing React 19, Dockview, ECharts, Zustand, and Electron presentation system.

## Adoption matrix

| Candidate | Reviewed revision/version | License and maintenance evidence | Decision | Adopt in V0 | Reject in V0 |
| --- | --- | --- | --- | --- | --- |
| [TideTrading](https://github.com/skloxo/TideTrading) | `29b3b425163c98b49de48eb36dbdc37a77542559`; frontend `1.7.9`; pushed 2026-08-02 | MIT; active; React 19/Vite 6/ECharts 6/Zustand 5 is technically close to V3 | `DESIGN_REFERENCE` | Agent-first entry, research goal/session framing, visible tool/run/swarm progress, compact provenance tables, dense research-terminal rhythm | Its API/message authority, live-trading surfaces, multi-tenant/runtime model, Tailwind/router/grid stack, and source components. Existing components are coupled to Tide `AgentMessage` and domain payloads, so direct adoption would import a second authority model. |
| [OpenBB Workspace](https://docs.openbb.co/workspace) | Docs reviewed 2026-08-11; product docs updated 2026-07-21 | Workspace UI is a product, not a reusable V3 React package | `DESIGN_REFERENCE` | Agent-to-workspace context, artifact return loop, widgets as professional work objects, citations beside claims, context-aware prompts | Product shell, service governance claims, proprietary UI implementation, and any assumption that an AI response is admitted evidence. |
| [agents-for-openbb](https://github.com/OpenBB-finance/agents-for-openbb) / [openbb-ai](https://github.com/OpenBB-finance/openbb-ai) | `aa1073d2b098ae6cf597dabf0635822aa808dd81` / `2e54bc2fc3caef83fb592b11cc73399c7eee0c48`; pushed 2026-07-01 / 2026-08-02 | MIT; active Python SDK/examples; `/agents.json`, `/query`, SSE, reasoning/citation/chart/table examples | `DESIGN_REFERENCE` | Typed agent feature discovery and the distinction between text, reasoning, citations, charts, tables, and dashboard context | `DIRECT_DEPENDENCY` and `ADAPTER` now. V3 current main does not wire WS-E into main/preload, and importing OpenBB's Python/SSE contract would create a parallel transport/authority boundary. |
| [Alpha Terminal](https://thealphaterminal.com/) | Public product surface reviewed 2026-08-11; no public source revision | Commercial/proprietary; no reusable code license found | `DESIGN_REFERENCE` | Professional three-pane information architecture, configurable multi-panel workspace, command palette, keyboard navigation, signal-to-driver drill-down | Code/assets, proprietary models, trading/execution authority, and dashboard metric claims. |
| [financial-agent-ui](https://github.com/virattt/financial-agent-ui) | `4125810b601dbd3f9720a465fba7f75c785ae9fb`; pushed 2024-09-29; frontend `0.1.0` | README claims MIT through a placeholder link, but GitHub reports no SPDX license and no valid root license file; inactive implementation baseline; Next 14/React 18 | `DESIGN_REFERENCE` + `REJECT` code reuse | The closed `tool type -> approved loading/final component` mapping concept | Source copying, packages, Next/RSC/RemoteRunnable transport, `any`-typed tool props, and arbitrary markdown as evidence. V3 requires validated renderer schemas and its own truth/admission semantics. |
| [Dexter](https://github.com/virattt/dexter) | `ecaed3011f24ea24ef687ab536aa7f22f7294038`; pushed 2026-08-04 | README declares MIT, while GitHub SPDX metadata is absent; active TypeScript/Bun/Ink CLI | `DESIGN_REFERENCE` | Question-to-plan decomposition, visible tool execution, self-validation step, bounded-loop presentation | CLI/runtime integration, agent completion as canonical completion, market-data/tool authority, LangChain dependency graph, and autonomous execution permissions. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | `a33fd4c0f134485a43553a2c23a63cb14adbd88f`; v0.2.5 noted in current README; pushed 2026-07-18 | Apache-2.0; active Python/LangGraph project | `DESIGN_REFERENCE` | Clear specialist-role presentation and explicit debate/review stages | Trading verdict authority, portfolio manager/risk authority, LangGraph runtime, simulated-firm ontology, and any UI implication that a role opinion is evidence. |
| [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund) | `eff8a7320fcf0b473b135690fa1a5b0d9b022a83`; pushed 2026-08-07 | MIT; active Python project | `DESIGN_REFERENCE` | Compact agent-role roster and synthesis sequencing | Investor-persona authority, buy/sell decisions, portfolio execution, backend orchestration, and dependency adoption. |
| V3 Evidence Inspector + Artifact Registry | current main contracts only | V3 Apache-2.0; owned by this repository | `V3_NATIVE_REQUIRED` | Exact source object IDs, truth/admission, provenance, reviewer findings, known renderers, H/I/J future slots, Open-in-Lab | Shadow canonical types, dynamic JSX/HTML, `eval`, `dangerouslySetInnerHTML`, or any unapproved renderer. |

## Evidence by product dimension

### Agent-first navigation and research sessions

TideTrading demonstrates a strong agent-first research entry and visible conversation/run progress. Alpha Terminal demonstrates the stronger desktop information hierarchy: navigation on the left, active professional surface in the center, contextual evidence on the right. V3 combines those ideas without importing either product shell: Research Sessions become the primary navigator, while the five existing Labs remain keyboard-accessible professional expansion surfaces.

### Plan, task, tool, run, and reviewer trace

Dexter's plan/tool/self-validation loop and TideTrading's thinking/tool progress make intermediate work inspectable. TradingAgents makes specialist roles legible. V3 adopts the visibility but not their authority. Timeline entries retain the current-main vocabulary and semantic class: an Agent Draft remains `NON_CANONICAL / DRAFT`; `PENDING`, `NOT_RUN`, and `BLOCKED` never receive success styling; tool reads and reviewer findings remain distinct from Task, Run, and Experiment states.

### Evidence and citations

OpenBB Workspace closes the loop by returning text, tables, charts, and citations into a workspace. V3 adopts that relationship while making the boundary stricter: every conclusion exposes exact object IDs, canonical truth state, canonical admission state, validation/reviewer status, and provenance references. The AI statement and canonical evidence use different semantic containers and labels.

### Generative UI

`financial-agent-ui` uses a closed `TOOL_COMPONENT_MAP` rather than executing model-authored JSX. That is the right directional pattern. Its implementation is not adopted because the React/Next stack is mismatched, props are not closed, maintenance is stale, and the repository's license file is not validly discoverable. V3 implements a local registry that accepts only known artifact renderer keys and rejects unknown, HTML, script, and executable payloads.

## Dependency and component conclusion

- `DIRECT_DEPENDENCY`: none.
- `COMPONENT_ADOPTION`: none; no reviewed component is authority-neutral enough to import unchanged.
- `ADAPTER`: none to external projects. The only adapter is a V3-owned frontend transport boundary for current-main data when it becomes wired.
- `SELECTIVE_MODULE_REUSE`: none at source level.
- `DESIGN_REFERENCE`: TideTrading, OpenBB Workspace/agents-for-openbb, Alpha Terminal, financial-agent-ui, Dexter, TradingAgents, AI Hedge Fund.
- `REJECT`: external agent runtimes, trading authority, service contracts, dynamic model UI/code, and additional dependency graphs.
- `V3_NATIVE_REQUIRED`: Research Session view model, Evidence Inspector, Artifact Renderer Registry, unified Timeline, permission surface, future H/I/J slots, and Open-in-Lab routing.

## Sources inspected

- TideTrading repository, frontend package, `ConversationTimeline`, and `DataProvenancePanel`: <https://github.com/skloxo/TideTrading>
- OpenBB Workspace overview and agent integration: <https://docs.openbb.co/workspace>, <https://docs.openbb.co/workspace/developers/agents-integration>
- agents-for-openbb and openbb-ai: <https://github.com/OpenBB-finance/agents-for-openbb>, <https://github.com/OpenBB-finance/openbb-ai>
- Alpha Terminal public product surface: <https://thealphaterminal.com/>
- financial-agent-ui README, package, and closed tool-component map: <https://github.com/virattt/financial-agent-ui>
- Dexter: <https://github.com/virattt/dexter>
- TradingAgents: <https://github.com/TauricResearch/TradingAgents>
- AI Hedge Fund: <https://github.com/virattt/ai-hedge-fund>

No reviewed source or contract from an unmerged Track H, I, or J branch was read or used.
