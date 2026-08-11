# `v3.generative_research_view/1.0.0`

## Authority and lifecycle

A ResearchViewSpec is an `AGENT_DRAFT_PROPOSAL` requiring `L1_DRAFT`. It is never a canonical artifact, Truth/Admission/Validation decision, execution request, approval or publication. L0 remains read-only; L2 Execute and L3 Publish remain denied.

The Python PydanticAI seam and TypeScript wire contract both use strict extra-field rejection. The frontend parser validates the envelope, then validates and resolves each block independently. An invalid envelope produces an explicit invalid view. An invalid or unsupported block is isolated and cannot prevent valid sibling blocks from rendering. The existing text draft may remain visible.

## Closed block vocabulary

| Block | Data authority | Value source |
|---|---|---|
| `Narrative` | `AGENT_DRAFT_DERIVED` | Bounded escaped text, source evidence required, always `NON_CANONICAL / DRAFT` |
| `MetricGroup` | `CANONICAL_EVIDENCE` | Approved selectors over active-session evidence |
| `DataTable` | `CANONICAL_EVIDENCE` | Evidence rows plus approved column selectors; closed sort/topN only |
| `TimeSeriesChart` | `CANONICAL_EVIDENCE` | Evidence-bound ISO date and finite numeric selectors; maximum 200 points |
| `BarChart` | `CANONICAL_EVIDENCE` | Evidence-bound category/numeric selectors; closed sort/topN; maximum 100 inputs |
| `EvidenceList` | `CANONICAL_EVIDENCE` | Exact evidence IDs, approved fields and canonical Lab link |
| `Callout` | `AGENT_DRAFT_DERIVED` | Bounded escaped text with closed `INFO/WARNING/BLOCKED` tone and source evidence |

## Frozen structural limits

Python/Pydantic and the TypeScript runtime parser accept the same V0 structural set:

| Contract item | Limit |
|---|---:|
| `ShortText` | 1..256 Unicode code points |
| `BoundedText` | 1..4096 Unicode code points |
| blocks per spec | 1..64 |
| evidence IDs per block | 1..128, unique |
| metrics per `MetricGroup` | 1..32 |
| table columns / rows | 1..20 / 1..500 |
| time-series points | 1..200 |
| bar points | 1..100 |
| evidence-list fields | 1..10 |

Every evidence ID must match `^[a-z][a-z0-9_]*_sha256_[0-9a-f]{64}$`, even if a malformed key is present in the renderer context map. Every `block_id` must be unique within one spec. `block_id` is deterministic Draft-view identity, not canonical artifact identity.

The V0 text-length unit is Unicode code points—not UTF-16 code units and not grapheme clusters. Agent-authored safe text also has one exact cross-language rejection rule: reject when its lowercase form contains `<script`, `<iframe` or `javascript:`, or when the source contains both `<` and `>`. Spaced forms such as `javascript :` are not the exact forbidden marker and are accepted unless another rejection condition applies.

## Approved selectors and display transforms

Selectors are exactly:

- `EVIDENCE_FIELD`: one approved field from `objectId`, `kind`, `title`, `summary`, `canonicalTruthState`, `canonicalAdmissionState`, `validationState`, `reviewerFinding`, `openInLab`, `artifactId`.
- `FACT`: exact case-sensitive fact label from the selected evidence projection.

Display normalization is exactly `NONE`, `NUMBER` or `ISO_DATE`. V0 intentionally has no `PERCENT` transform: active-session evidence does not carry unit proof that distinguishes a ratio from an exact percent literal, and Track M must not guess or apply ratio-to-percent scaling.

`NUMBER` accepts only a finite numeric literal and produces a display coordinate/value; it does not create canonical financial numeric authority. `ISO_DATE` accepts only:

- a valid date-only value `YYYY-MM-DD`, preserved exactly; or
- a valid timestamp `YYYY-MM-DDTHH:mm:ss(.fraction)?Z` / `YYYY-MM-DDTHH:mm:ss(.fraction)?±HH:mm`, where the optional fraction is exactly 1..3 decimal digits, deterministically normalized to UTC.

Timezone-naive timestamps, fractions longer than three digits, locale date strings and invalid calendar/clock/offset values fail closed. `TimeSeriesChart.date_window` uses the same millisecond-precision grammar and ordering, so no microsecond/millisecond comparison drift is admitted. `DataTable` permits a declared column sort and bounded `top_n`; `BarChart` permits `INPUT`, `VALUE_ASC`, `VALUE_DESC` and bounded `top_n`. These are display transforms only; no formula or financial calculation engine exists.

## Exact evidence binding

The renderer receives only the active session's already-derived `EvidenceView[]`. The spec's `session_view_id` must match the active session. Every referenced `evidence_id` must occur in the block declaration and active-session evidence map. A session switch regenerates the deterministic fixture for the new session; a prior session spec fails closed.

For `CANONICAL_EVIDENCE`, Agent output contains labels, evidence IDs, selectors and display choices—not canonical values. The resolver reads the value from the current evidence projection. For `AGENT_DRAFT_DERIVED`, text remains visibly `NON_CANONICAL / DRAFT` and cannot set Truth, Admission or Validation.

Resolved display values retain `sourceEvidenceId`, and UI evidence bindings return to the original canonical evidence. Normalization never mutates the evidence projection. Chart numbers and normalized temporal coordinates are renderer-only display values, not new Artifacts, Truth, Admission or Validation state.

## Renderer safety

The closed registry contains only the seven block names above. React renders text normally; no `dangerouslySetInnerHTML` is used. Charts use a fixed option builder with deterministic axes/series, disabled animation, bounded points, no formatter functions and no raw option merge. Unknown block/selector/normalization and every extra field fail closed.

The only UI actions are select evidence, open its existing Lab, copy an exact evidence ID, and expand/collapse evidence bindings. There is no execute, backtest rerun, mutation, approval or publish action.

## Integration status

- PydanticAI: exact existing `pydantic-ai-slim==2.27.0`, Track M typed output seam verified with deterministic `FunctionModel` tests.
- Production model connection: `NOT_OBSERVED`.
- UI source: explicitly labeled `DETERMINISTIC INTEGRATION FIXTURE`; selectors resolve current active-session evidence.
- Canonical promotion: forbidden; no `fixture→production` or `Draft→canonical` claim.
