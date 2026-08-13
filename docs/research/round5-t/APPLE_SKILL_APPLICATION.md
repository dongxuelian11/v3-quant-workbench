# Apple Design Skill Application Evidence

## Gate identity

- Skill: `apple-design`
- Path: `D:\V3OpenSource\.agents\skills\apple-design\SKILL.md`
- Full read: 282 lines
- SHA-256: `DA9581408C2B37A49565A9C7E32F26763F78B581C7E802DFA2357738E43BA7D5`
- Target: a professional Windows workbench informed by the skill, not a macOS clone.

## Applied principles

| Skill principle | Concrete T application | Evidence |
| --- | --- | --- |
| Purpose | Agent context remains the default; five Labs remain deep-work destinations. | `App.tsx`, `Workbench.tsx` |
| Agency and responsibility | AI content is visibly `L1_DRAFT`, requires confirmation, and leaves L2/L3 disabled. | `FactorWorkbench.tsx` |
| Familiarity | Windows controls stay at the top-right; no traffic lights or macOS chrome imitation. | `WindowControls.tsx`, `main.ts` |
| Simplicity, not minimalism | Research Lab exposes one clear switch between its canvas and Factor workspace; detailed truth is one level deeper. | `Workbench.tsx`, `FactorWorkbench.tsx` |
| Craft | System typography, size-specific heading tracking, compact data density, long-ID wrapping, and deliberate focus states. | `styles.css` |
| Response | Press feedback is immediate; controls remain usable during visual transitions. | `styles.css` |
| Materials and depth | The title layer uses one restrained translucent material; content panes remain solid for legibility. | `styles.css` |
| Wayfinding | Chinese-first direct labels state the current Lab, factor surface, connection boundary, lifecycle, and evaluation state. | `App.tsx`, `FactorWorkbench.tsx` |
| Accessibility and flexibility | Keyboard focus plus reduced motion, reduced transparency, and increased contrast media queries are explicit. | `styles.css` |

## Non-applicable motion features

No drag, sheet, carousel, or momentum interaction was introduced. Velocity projection, rubber-banding, and gesture spring handoff were therefore intentionally not added. Adding decorative springs without a physical gesture would violate the skill's restraint and purpose principles.

## Truth and production boundary

Monaco edits source only. The renderer does not implement TDX math, parsing, translation, or evaluation. Exact W0 output metadata is shown only when the existing runtime reports `DEVELOPMENT_INTEGRATION_FIXTURE`; default production mode shows `尚未接入 / NOT_CONNECTED`, `未评估`, and `Reviewer: NOT_RUN` rather than fixture success.
