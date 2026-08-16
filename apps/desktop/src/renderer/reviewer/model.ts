import type { AgentStatementView, EvidenceView, ResearchSessionView } from "../agentWorkspace";

export type ReviewOutcome = "PASS" | "FINDING" | "NOT_APPLICABLE" | "NOT_RUN" | "BLOCKED";
export type OverallReviewStatus = "CLEAR_WITHIN_CHECKED_SCOPE" | "FINDINGS_PRESENT" | "INCOMPLETE_REVIEW" | "BLOCKED";

export const REVIEWER_RULE_SET = Object.freeze({
  version: "v3.reviewer-integration/1",
  id: "rrs_sha256_e4a3dfcf23fd173b8b0c68c9a897a4f16ebb4a74951eb21e7f8bc3b50f2b2860",
  source: "TRACK_O_BACKEND_DETERMINISTIC_RULESET" as const
});

export const REVIEWER_AGENT_CAPABILITIES = Object.freeze([
  { permission: "L0_READ", label: "读取 A 层结果与精确证据" },
  { permission: "L1_DRAFT", label: "起草摘要、风险排序与研究建议" }
] as const);

export const REVIEWER_FORBIDDEN_ACTIONS = Object.freeze([
  "FORMAL_ADMISSION",
  "PUBLISH",
  "WAIVE_FINDING",
  "MUTATE_CANONICAL_EVIDENCE",
  "PROMOTE_NOT_RUN",
  "PROMOTE_FINDING"
] as const);

export interface ReviewCheckView {
  ruleId: string;
  layer: "LAYER_A_DETERMINISTIC";
  required: boolean;
  outcome: ReviewOutcome;
  title: string;
  detail: string;
  evidenceObjectIds: readonly string[];
}

export interface ReviewerFindingView {
  findingId: string;
  reviewReportId: string | null;
  ruleId: string;
  severity: "WARNING" | "BLOCKING";
  outcome: "FINDING" | "BLOCKED";
  title: string;
  explanation: string;
  remediationSuggestion: string;
  evidenceObjectIds: readonly string[];
  lifecycleLinks: readonly { relation: "RESOLVES" | "SUPERSEDES"; findingId: string; reportId: string }[];
}

export interface ReviewCoverageView {
  checkedRules: number;
  PASS: number;
  FINDING: number;
  NOT_RUN: number;
  NOT_APPLICABLE: number;
  BLOCKED: number;
}

export interface ReviewerAgentDraftView {
  statementId: string;
  layer: "LAYER_B_REVIEWER_AGENT";
  permission: "L1_DRAFT";
  authorityStatus: "NON_CANONICAL";
  title: string;
  body: string;
  evidenceObjectIds: readonly string[];
}

export interface ReviewerReportView {
  reportId: string | null;
  authority: "DERIVED_READ_ONLY_UI_PROJECTION";
  ruleSetId: string;
  ruleSetVersion: string;
  overallStatus: OverallReviewStatus;
  coverage: ReviewCoverageView;
  checks: readonly ReviewCheckView[];
  findings: readonly ReviewerFindingView[];
  agentDrafts: readonly ReviewerAgentDraftView[];
}

const RULES = Object.freeze([
  ["O-001", true, "研究会话范围"],
  ["O-002", true, "精确 ID / hash 与来源链"],
  ["O-003", true, "Canonical 验证状态"],
  ["O-004", true, "真值 / 准入上限"],
  ["O-010", true, "切分、purge 与 embargo"],
  ["O-011", true, "数据集成员关系"],
  ["O-012", true, "实验运行 / 尝试"],
  ["O-020", true, "模型训练链"],
  ["O-021", true, "预测链"],
  ["O-030", true, "策略周期 / 截止时间"],
  ["O-031", true, "组合策略 / 目标时点"],
  ["O-032", true, "风险目标绑定"],
  ["O-040", true, "回测 RunSpec / Result"],
  ["O-050", true, "PIT / 泄漏证据"],
  ["O-060", false, "过拟合 / 稳健性边界"]
] as const);

export function deriveReviewerReportView(
  session: ResearchSessionView,
  evidence: readonly EvidenceView[],
  statements: readonly AgentStatementView[]
): ReviewerReportView {
  const byId = new Map(evidence.map((item) => [item.objectId, item]));
  const scoped = session.evidenceIds.map((objectId) => byId.get(objectId)).filter((item): item is EvidenceView => item !== undefined);
  const missingIds = session.evidenceIds.filter((objectId) => !byId.has(objectId));
  const exactIds = scoped.filter((item) => /_sha256_[0-9a-f]{64}$/.test(item.objectId));
  const checks: ReviewCheckView[] = RULES.map(([ruleId, required, title]) => ({
    ruleId,
    layer: "LAYER_A_DETERMINISTIC",
    required,
    outcome: "NOT_RUN",
    title,
    detail: "当前只读工作区投影尚未载入此规则对应的精确后端 ReviewReport。",
    evidenceObjectIds: []
  }));
  const replaceCheck = (ruleId: string, value: Omit<ReviewCheckView, "ruleId" | "layer" | "required" | "title">) => {
    const index = checks.findIndex((item) => item.ruleId === ruleId);
    checks[index] = { ...checks[index], ...value };
  };

  replaceCheck("O-001", missingIds.length
    ? { outcome: "BLOCKED", detail: `会话声明的 ${missingIds.length} 个证据对象尚未载入。`, evidenceObjectIds: exactIds.map((item) => item.objectId) }
    : { outcome: "PASS", detail: "每个已载入证据对象都由当前研究会话显式链接。", evidenceObjectIds: scoped.map((item) => item.objectId) });

  replaceCheck("O-002", exactIds.length !== scoped.length
    ? { outcome: "FINDING", detail: "至少一个已载入对象缺少内容寻址 ID。", evidenceObjectIds: scoped.filter((item) => !exactIds.includes(item)).map((item) => item.objectId) }
    : { outcome: "NOT_RUN", detail: "对象 ID 已内容寻址，但此 UI 投影尚未载入独立来源内容 hash 与完整来源链边。", evidenceObjectIds: exactIds.map((item) => item.objectId) });

  const failed = scoped.filter((item) => item.validationState === "FAILED");
  const notRun = scoped.filter((item) => item.validationState === "NOT_RUN");
  replaceCheck("O-003", failed.length
    ? { outcome: "FINDING", detail: "存在 canonical 验证失败。", evidenceObjectIds: failed.map((item) => item.objectId) }
    : notRun.length
      ? { outcome: "NOT_RUN", detail: "Canonical 验证保持 NOT_RUN；Reviewer 不会将其提升为 PASS。", evidenceObjectIds: notRun.map((item) => item.objectId) }
      : scoped.length
        ? { outcome: "PASS", detail: "全部已载入证据均为 canonical validation_state=PASSED。", evidenceObjectIds: scoped.map((item) => item.objectId) }
        : { outcome: "NOT_RUN", detail: "尚未载入带有验证状态的证据。", evidenceObjectIds: [] });

  const insufficient = scoped.filter((item) => item.canonicalTruthState !== "FORMAL" || item.canonicalAdmissionState !== "FORMAL_ADMITTED");
  replaceCheck("O-004", !scoped.length
    ? { outcome: "NOT_RUN", detail: "尚未载入 canonical 真值 / 准入状态。", evidenceObjectIds: [] }
    : insufficient.length
      ? { outcome: "FINDING", detail: "来源证据低于 FORMAL / FORMAL_ADMITTED；Reviewer 输出不能提升它。", evidenceObjectIds: insufficient.map((item) => item.objectId) }
      : { outcome: "PASS", detail: "已载入来源为 FORMAL / FORMAL_ADMITTED；Reviewer 仍不授予准入。", evidenceObjectIds: scoped.map((item) => item.objectId) });

  const findings: ReviewerFindingView[] = checks
    .filter((item): item is ReviewCheckView & { outcome: "FINDING" | "BLOCKED" } => item.outcome === "FINDING" || item.outcome === "BLOCKED")
    .map((item) => ({
      findingId: `ui-review-finding:${session.sessionViewId}:${item.ruleId}`,
      reviewReportId: null,
      ruleId: item.ruleId,
      severity: item.outcome === "BLOCKED" ? "BLOCKING" : "WARNING",
      outcome: item.outcome,
      title: item.title,
      explanation: item.detail,
      remediationSuggestion: "生成新的 canonical 证据并载入不可变后端 ReviewReport；不得篡改或豁免历史。",
      evidenceObjectIds: item.evidenceObjectIds,
      lifecycleLinks: []
    }));
  const coverage = summarizeReviewCoverage(checks);
  const overallStatus: OverallReviewStatus = coverage.BLOCKED
    ? "BLOCKED"
    : coverage.FINDING
      ? "FINDINGS_PRESENT"
      : checks.some((item) => item.required && item.outcome === "NOT_RUN")
        ? "INCOMPLETE_REVIEW"
        : "CLEAR_WITHIN_CHECKED_SCOPE";
  const agentDrafts = statements
    .filter((item) => item.role === "REVIEWER")
    .map((item): ReviewerAgentDraftView => ({
      statementId: item.id,
      layer: "LAYER_B_REVIEWER_AGENT",
      permission: "L1_DRAFT",
      authorityStatus: "NON_CANONICAL",
      title: item.title,
      body: item.body,
      evidenceObjectIds: item.evidenceIds
    }));
  return {
    reportId: null,
    authority: "DERIVED_READ_ONLY_UI_PROJECTION",
    ruleSetId: REVIEWER_RULE_SET.id,
    ruleSetVersion: REVIEWER_RULE_SET.version,
    overallStatus,
    coverage,
    checks,
    findings,
    agentDrafts
  };
}

export function summarizeReviewCoverage(checks: readonly ReviewCheckView[]): ReviewCoverageView {
  const coverage: ReviewCoverageView = { checkedRules: checks.length, PASS: 0, FINDING: 0, NOT_RUN: 0, NOT_APPLICABLE: 0, BLOCKED: 0 };
  for (const item of checks) coverage[item.outcome] += 1;
  return coverage;
}
