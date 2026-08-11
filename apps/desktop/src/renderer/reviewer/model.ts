import type { AgentStatementView, EvidenceView, ResearchSessionView } from "../agentWorkspace";

export type ReviewOutcome = "PASS" | "FINDING" | "NOT_APPLICABLE" | "NOT_RUN" | "BLOCKED";
export type OverallReviewStatus = "CLEAR_WITHIN_CHECKED_SCOPE" | "FINDINGS_PRESENT" | "INCOMPLETE_REVIEW" | "BLOCKED";

export const REVIEWER_RULE_SET = Object.freeze({
  version: "v3.reviewer-integration/1",
  id: "rrs_sha256_e4a3dfcf23fd173b8b0c68c9a897a4f16ebb4a74951eb21e7f8bc3b50f2b2860",
  source: "TRACK_O_BACKEND_DETERMINISTIC_RULESET" as const
});

export const REVIEWER_AGENT_CAPABILITIES = Object.freeze([
  { permission: "L0_READ", label: "Read Layer A and exact evidence" },
  { permission: "L1_DRAFT", label: "Draft summary, risk ordering, and research suggestions" }
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
  ["O-001", true, "Research Session scope"],
  ["O-002", true, "Exact ID/hash and lineage"],
  ["O-003", true, "Canonical validation state"],
  ["O-004", true, "Truth / Admission ceiling"],
  ["O-010", true, "Split, purge, and embargo"],
  ["O-011", true, "Dataset membership"],
  ["O-012", true, "Experiment Run / Attempt"],
  ["O-020", true, "Model training chain"],
  ["O-021", true, "Prediction chain"],
  ["O-030", true, "Strategy period / cutoff"],
  ["O-031", true, "Portfolio policy / target timing"],
  ["O-032", true, "Risk target binding"],
  ["O-040", true, "Backtest RunSpec / Result"],
  ["O-050", true, "PIT / leakage evidence"],
  ["O-060", false, "Overfitting / robustness boundary"]
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
    detail: "The exact backend ReviewReport for this rule is not loaded in the current read-only workspace projection.",
    evidenceObjectIds: []
  }));
  const replaceCheck = (ruleId: string, value: Omit<ReviewCheckView, "ruleId" | "layer" | "required" | "title">) => {
    const index = checks.findIndex((item) => item.ruleId === ruleId);
    checks[index] = { ...checks[index], ...value };
  };

  replaceCheck("O-001", missingIds.length
    ? { outcome: "BLOCKED", detail: `The session declares ${missingIds.length} evidence object(s) that are not loaded.`, evidenceObjectIds: exactIds.map((item) => item.objectId) }
    : { outcome: "PASS", detail: "Every loaded evidence object is explicitly linked by this Research Session.", evidenceObjectIds: scoped.map((item) => item.objectId) });

  replaceCheck("O-002", exactIds.length !== scoped.length
    ? { outcome: "FINDING", detail: "At least one loaded object lacks a content-addressed ID.", evidenceObjectIds: scoped.filter((item) => !exactIds.includes(item)).map((item) => item.objectId) }
    : { outcome: "NOT_RUN", detail: "Object IDs are content-addressed, but separate source content hashes and complete lineage edges are not loaded in this UI projection.", evidenceObjectIds: exactIds.map((item) => item.objectId) });

  const failed = scoped.filter((item) => item.validationState === "FAILED");
  const notRun = scoped.filter((item) => item.validationState === "NOT_RUN");
  replaceCheck("O-003", failed.length
    ? { outcome: "FINDING", detail: "Canonical validation failures are present.", evidenceObjectIds: failed.map((item) => item.objectId) }
    : notRun.length
      ? { outcome: "NOT_RUN", detail: "Canonical validation remains NOT_RUN; the Reviewer does not promote it to PASS.", evidenceObjectIds: notRun.map((item) => item.objectId) }
      : scoped.length
        ? { outcome: "PASS", detail: "All loaded evidence has canonical validation_state=PASSED.", evidenceObjectIds: scoped.map((item) => item.objectId) }
        : { outcome: "NOT_RUN", detail: "No validation-bearing evidence is loaded.", evidenceObjectIds: [] });

  const insufficient = scoped.filter((item) => item.canonicalTruthState !== "FORMAL" || item.canonicalAdmissionState !== "FORMAL_ADMITTED");
  replaceCheck("O-004", !scoped.length
    ? { outcome: "NOT_RUN", detail: "No canonical Truth / Admission state is loaded.", evidenceObjectIds: [] }
    : insufficient.length
      ? { outcome: "FINDING", detail: "Source evidence is below FORMAL / FORMAL_ADMITTED. Reviewer output cannot elevate it.", evidenceObjectIds: insufficient.map((item) => item.objectId) }
      : { outcome: "PASS", detail: "Loaded sources are FORMAL / FORMAL_ADMITTED; Reviewer still grants no admission.", evidenceObjectIds: scoped.map((item) => item.objectId) });

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
      remediationSuggestion: "Produce new canonical evidence and load the immutable backend ReviewReport; do not mutate or waive history.",
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
