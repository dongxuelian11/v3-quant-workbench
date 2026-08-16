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
      title: "证据绑定研究视图",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [primaryId],
      text: "此确定性集成 fixture 演示类型化 L1 提案；解释保持 NON_CANONICAL / DRAFT，不改变证据权威。"
    },
    {
      type: "MetricGroup",
      block_id: "track-m-fixture-metrics",
      title: "当前会话权威状态",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [primaryId],
      metrics: [
        { label: "准入", evidence_id: primaryId, selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } },
        { label: "验证", evidence_id: primaryId, selector: { kind: "EVIDENCE_FIELD", field: "validationState", normalization: "NONE" } }
      ]
    },
    {
      type: "DataTable",
      block_id: "track-m-fixture-table",
      title: "已绑定证据投影",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: evidenceIds,
      columns: [
        { key: "kind", header: "类型", selector: { kind: "EVIDENCE_FIELD", field: "kind", normalization: "NONE" } },
        { key: "title", header: "证据", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "admission", header: "准入", selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } },
        { key: "validation", header: "验证", selector: { kind: "EVIDENCE_FIELD", field: "validationState", normalization: "NONE" } }
      ],
      rows: evidenceIds.map((evidence_id) => ({ evidence_id })),
      sort: null,
      top_n: 20
    },
    {
      type: "EvidenceList",
      block_id: "track-m-fixture-evidence",
      title: "精确来源证据",
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: evidenceIds.slice(0, 6),
      fields: [
        { key: "title", label: "证据", selector: { kind: "EVIDENCE_FIELD", field: "title", normalization: "NONE" } },
        { key: "truth", label: "真值", selector: { kind: "EVIDENCE_FIELD", field: "canonicalTruthState", normalization: "NONE" } },
        { key: "admission", label: "准入", selector: { kind: "EVIDENCE_FIELD", field: "canonicalAdmissionState", normalization: "NONE" } }
      ]
    },
    {
      type: "Callout",
      block_id: "track-m-fixture-boundary",
      title: "Fixture 边界",
      data_authority: "AGENT_DRAFT_DERIVED",
      evidence_ids: [primaryId],
      tone: "WARNING",
      text: "不声明已连接生产智能体结构化输出；执行、重跑、修改、批准与发布操作均不存在。"
    }
  ];
  const numericEvidence = scopedEvidence.find((item) => item.facts.some((fact) => finiteNumber(fact.value) !== null));
  const numericFact = numericEvidence?.facts.find((fact) => finiteNumber(fact.value) !== null);
  if (numericEvidence && numericFact) {
    blocks.splice(3, 0, {
      type: "BarChart",
      block_id: "track-m-fixture-chart",
      title: `${numericFact.label} · 来自已绑定证据`,
      data_authority: "CANONICAL_EVIDENCE",
      evidence_ids: [numericEvidence.objectId],
      category_label: "证据",
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
    title: "生成式研究界面",
    blocks
  };
}

function finiteNumber(value: string): number | null {
  const normalized = value.replaceAll(",", "");
  if (!/^-?(?:\d+\.?\d*|\.\d+)$/.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}
