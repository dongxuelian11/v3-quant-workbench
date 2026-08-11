import type { ResearchViewSpecV1 } from "../../../../../packages/contracts/src/generativeResearchView";
import type { ResearchEvidenceProjection } from "./schemaParser";

type ResearchViewBlock = ResearchViewSpecV1["blocks"][number];

export function createGenerativeResearchViewFixture(
  sessionViewId: string,
  evidence: readonly ResearchEvidenceProjection[]
): ResearchViewSpecV1 | null {
  const scopedEvidence = evidence.slice(0, 32);
  if (scopedEvidence.length === 0) return null;
  const evidenceIds = scopedEvidence.map((item) => item.objectId);
  const primaryId = evidenceIds[0];
  const blocks: ResearchViewBlock[] = [
    {
      type: "Narrative",
      block_id: "track-m-fixture-narrative",
      title: "Evidence-bound research view",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [primaryId],
      text: "This deterministic integration fixture demonstrates a typed L1 proposal. Interpretations remain NON_CANONICAL / DRAFT and do not change evidence authority."
    },
    {
      type: "MetricGroup",
      block_id: "track-m-fixture-metrics",
      title: "Current-session authority states",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [primaryId],
      metrics: [
        { label: "Admission", evidence_id: primaryId, selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } },
        { label: "Validation", evidence_id: primaryId, selector: { kind: "EVIDENCE_FIELD", field: "validationState", normalization: "NONE" } }
      ]
    },
    {
      type: "DataTable",
      block_id: "track-m-fixture-table",
      title: "Bound evidence projection",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: evidenceIds,
      columns: [
        { key: "kind", header: "Kind", selector: { kind: "EVIDENCE_FIELD", field: "kind", normalization: "NONE" } },
        { key: "title", header: "Evidence", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "admission", header: "Admission", selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } },
        { key: "validation", header: "Validation", selector: { kind: "EVIDENCE_FIELD", field: "validationState", normalization: "NONE" } }
      ],
      rows: evidenceIds.map((evidence_id) => ({ evidence_id })),
      sort: null,
      top_n: 20
    },
    {
      type: "EvidenceList",
      block_id: "track-m-fixture-evidence",
      title: "Exact source evidence",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: evidenceIds.slice(0, 6),
      fields: [
        { key: "title", label: "Evidence", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "truth", label: "Truth", selector: { kind: "EVIDENCE_FIELD", field: "canonicalTruthState", normalization: "NONE" } },
        { key: "admission", label: "Admission", selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } }
      ]
    },
    {
      type: "Callout",
      block_id: "track-m-fixture-boundary",
      title: "Fixture boundary",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [primaryId],
      tone: "WARNING",
      text: "No live production Agent structured-output connection is claimed. Execute, rerun, mutate, approve, and publish actions are absent."
    }
  ];
  const numericEvidence = scopedEvidence.find((item) => item.facts.some((fact) => finiteNumber(fact.value) !== null));
  const numericFact = numericEvidence?.facts.find((fact) => finiteNumber(fact.value) !== null);
  if (numericEvidence && numericFact) {
    blocks.splice(3, 0, {
      type: "BarChart",
      block_id: "track-m-fixture-chart",
      title: `${numericFact.label} from bound evidence`,
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [numericEvidence.objectId],
      category_label: "Evidence",
      value_label: numericFact.label,
      bars: [{
        evidence_id: numericEvidence.objectId,
        category_selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" },
        value_selector: { kind: "FACT", label: numericFact.label, normalization: "NUMBER" }
      }],
      sort: "INPUT",
      top_n: null
    });
  }
  return {
    schema_version: "v3.generative_research_view/1.0.0",
    spec_id: `track-m-fixture-${sessionViewId}`.slice(0, 256),
    session_view_id: sessionViewId,
    permission: "L1_DRAFT",
    authority: "AGENT_DRAFT_PROPOSAL",
    title: "Generative Research UI",
    blocks
  };
}

function finiteNumber(value: string): number | null {
  const normalized = value.replaceAll(",", "");
  if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}
