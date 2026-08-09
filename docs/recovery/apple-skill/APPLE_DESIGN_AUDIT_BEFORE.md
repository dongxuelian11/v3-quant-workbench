# FR-1 Apple Skill-Assisted Design Audit — Before

```yaml
task_id: V3-OSS-REBUILD-FR1-APPLE-SKILL-ASSISTED-UI-UX-UE-REFINEMENT-SOL-HIGH-03
audit_completed_at: 2026-08-09T19:33:15.3475080+08:00
ui_mutation_started: false
candidate_head: 97ce15b7548df56312b785a5ce10b0fadb87d81a
candidate_hash_match: 14_of_14
skill_status: VERIFIED_AND_LOADED
authority_order: USER_UAU > V3_CHART_FIRST_CONTRACT > APPLE_HIG > APPLE_UI_DESIGN_SKILL
```

## Evidence reviewed

- All 17 embedded real-Electron screenshots were reviewed at 1280×720, 1536×864 and 1920×1080, including the five Labs, Research drawers, Strategy modes, Model phases, Dockview multi-panel and restart-restored layout.
- The embedded repository delta was compared with the current worktree; every one of the 14 expected after hashes matches.
- The live React composition, Dockview orchestration, ECharts, React Flow, Monaco, store/persistence and current CSS were inspected without changing renderer code.
- The pinned `apple-ui-design` skill was verified and read from `.agents/skills/apple-ui-design/SKILL.md`.
- Apple official HIG pages for design principles, layout, typography, toolbars, sidebars, split views, segmented controls, lists/tables and color were fetched from `developer.apple.com` on 2026-08-09. Their transferable guidance is used only below V3 authority.

## Executive diagnosis

The candidate already restores the correct V3 identity: one coherent, dark, chart-first quantitative desktop workbench with five Labs, compact truth labels, contextual drawers and persistent Dockview layouts. The refinement should be evolutionary, not a redesign.

The most material remaining issues are hierarchy and contextual action competition:

- Global chrome uses many adjacent one-pixel borders and repeated status/action rows, so the app frame competes more than necessary with analytical content.
- Research is strongly chart-first, but the context header can group facts and actions more calmly; run feedback is only a label flip and drawers do not announce open state.
- Strategy modes read as ordinary text tabs; validation and Handoff are both permanently prominent even when Handoff is not ready. Diff is present as a permanent peer despite being a review-only flow.
- Model phases are clear but visually oversized. Study exposes Resume and Pause simultaneously, plus Checkpoint and Cancel, regardless of current state. Version/Signal has a large empty center and four equal metric blocks that approach a completion-card layout.
- Backtest duplicates queue state/actions between the header and right evidence rail; Pause, Cancel and Resume compete simultaneously.
- Result has a strong performance chart, but top context/actions and four metric cells retain more border weight than needed.
- Focus outlines exist and core shortcuts exist, but tab semantics, pressed/selected state, Escape exits, live feedback, reduced motion and disabled/non-applicable operations are incomplete.
- Only the hydration loading state is explicit; empty/error/unavailable patterns are not consistently represented in the five analytical workflows.

## Apple/V3 interpretation

Apple HIG is useful here for clarity, adaptive layout, content-deferential chrome, contextual toolbars, leading navigation, adjacent split panes, mutually exclusive segmented choices, typographic hierarchy, restrained color and state feedback. These principles reinforce V3.

Literal Apple imitation conflicts with the product contract. The following skill suggestions are rejected: SF Pro dependency, 44px minimum for every dense desktop control, 680px analytical width, 18px rounded glass cards, pill buttons, decorative fade-up entrances and a universal 300ms transition. V3 keeps Segoe UI/Microsoft YaHei, 28–34px dense controls, full-width charts/tables, low-radius surfaces and 100–240ms state-linked motion.

## Global workbench audit

### Hierarchy and deference

- Keep the 54px top Lab strip, asset tree, Dockview workspace and contextual Inspector architecture.
- Reduce border accumulation by relying on spacing and tonal surfaces for headers, toolbars and metric strips.
- Preserve cyan for current Lab, selection, focus and the contextual primary action; avoid using it as decoration.
- Consolidate local feedback near the action that caused it and expose it through an ARIA live region.

### Typography and spacing

- Replace the non-guaranteed leading `Inter` reference with the V3 Windows-native stack: `Segoe UI`, `Microsoft YaHei UI`, `Microsoft YaHei`, sans-serif; keep monospace only for identifiers and numeric/code contexts.
- Retain financial text at 11–14px and avoid negative tracking.
- Normalize a compact 4/6/8/12/16/24 spacing rhythm derived from the skill’s consistency principle but adapted to workstation density.
- Use stronger title/eyebrow/body distinctions instead of larger decorative headings.

### Keyboard, focus and state

- Retain Ctrl/Cmd+K and Ctrl/Cmd+1…5.
- Add Escape exits for command palette, Inspector, operations and contextual Research drawers where context permits.
- Add correct `role=tab`, `aria-selected`, `aria-controls`, `aria-pressed`, disabled and live-status semantics.
- Preserve the 2px cyan focus ring and ensure focus is visible on buttons, tabs, summaries, inputs, React Flow and Dockview surfaces.
- Add reduced-motion handling that disables nonessential transitions.

## Five-Lab audit

### Research

Primary surface: price/volume/momentum/benchmark chart. This is already the strongest object and meets the 720×400 minimum in the baseline geometry.

Refine:

- Make the instrument identity and current research window the header’s first reading path; subordinate Universe/as-of metadata.
- Group Universe and secondary analytics as contextual tools; keep Run Research as the single context primary action.
- Preserve the metric strip but reduce cell border weight and strengthen numeric alignment.
- Add `aria-pressed` to drawers, local running feedback and selected event state.
- Keep Inspector at 280–420px and drawers on demand; never permanently reduce the chart below authority minimum.
- Preserve crosshair, brush and event-ledger provenance behavior.

### Strategy

Primary surface: React Flow in Visual, Monaco in Code, both in Split, Monaco Diff in review.

Refine:

- Present Visual/Code/Split as a compact mutually exclusive work-mode segmented group.
- Move Diff to a distinct contextual review action while retaining the existing review implementation.
- Keep validation available; only make Handoff primary after validation succeeds, otherwise render it disabled/subordinate with an explanation.
- Add local validation/Handoff feedback and selected-node context without adding another permanent panel.
- Preserve React Flow and Monaco shortcuts and their dominant canvas geometry.

### Model

Primary surface changes by phase: Dataset/Run → Study/Trial → Version/Signal.

Refine:

- Compress the three-step phase switcher into a quiet workflow rail; active phase remains obvious without a large filled slab.
- Keep configuration on the left and run comparison as the dominant Dataset/Run canvas.
- In Study, show only the operation applicable to the current state as primary (Resume when paused/checkpointed, Pause when running); keep Checkpoint secondary and Cancel destructive.
- Add immediate CommandRegistry receipt feedback and disabled state for non-applicable operations.
- Recompose Version/Signal into a denser evidence-led review surface with identity, quality metrics, lineage and handoff grouped by meaning rather than equal card blocks.

### Backtest

Primary surface: execution/equity/drawdown review chart.

Refine:

- Preserve the chart plus a narrow evidence rail.
- Treat scenario setup and queue controls as workflow tools, not competing cards.
- Show one applicable queue operation as primary and keep Cancel destructive; avoid simultaneous Pause and Resume.
- Keep Demo/available-time truth visible in a compact provenance line.
- Add local queue feedback and clear selected-run evidence semantics.

### Result

Primary surface: performance/equity/benchmark/drawdown chart.

Refine:

- Keep Performance as the default and secondary analytical layers as tabs/on-demand drawers.
- Reduce header/metric border weight so result identity and the performance canvas dominate.
- Keep compare/lineage actions contextual; expose pressed/open state.
- Preserve Demo truth, benchmark identity, as-of time and result lineage.

## State design audit

- `loading`: hydration exists; retain it and add calm progress/status semantics.
- `empty`: add reusable analytical empty-state treatment for no selection/no results without inventing backend behavior.
- `error`: use explicit text/icon and bounded retry/context action; never color alone.
- `unavailable`: use V3 `BACKEND_UNWIRED`/Demo wording and neutral hatch treatment; never imply production data.
- `success/action feedback`: provide short local receipts; avoid toast noise for every selection.

## Pre-code gate

This audit and `APPLE_V3_RECONCILIATION_MATRIX.json` were completed before the first renderer/CSS mutation for this refinement. Implementation is permitted only for rows classified `ADOPT` or `ADAPT_TO_V3`.
