import React, { useMemo, useState } from "react";
import type { AgentStatementView, EvidenceView, ResearchSessionView } from "../agentWorkspace";
import { FindingDetail } from "./FindingDetail";
import { FindingList } from "./FindingList";
import { ReviewSummary } from "./ReviewSummary";
import { REVIEWER_AGENT_CAPABILITIES, REVIEWER_FORBIDDEN_ACTIONS, deriveReviewerReportView } from "./model";

export function ReviewerPanel({ session, evidence, statements, onSelectEvidence }: { session: ResearchSessionView; evidence: readonly EvidenceView[]; statements: readonly AgentStatementView[]; onSelectEvidence: (objectId: string) => void }) {
  const report = useMemo(() => deriveReviewerReportView(session, evidence, statements), [evidence, session, statements]);
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(report.findings[0]?.findingId ?? null);
  const selectedFinding = report.findings.find((item) => item.findingId === selectedFindingId) ?? report.findings[0] ?? null;
  const loadedEvidenceIds = useMemo(() => new Set(evidence.map((item) => item.objectId)), [evidence]);
  return <section className="reviewer-panel" data-testid="reviewer-panel" data-review-authority={report.authority}>
    <header className="reviewer-panel-head"><div><small>REVIEWER INTEGRATION · TWO LAYERS</small><b>Contract checks first; Agent interpretation second</b></div><div><code>{report.ruleSetVersion}</code><code>{report.ruleSetId}</code></div></header>
    <ReviewSummary report={report}/>
    <div className="reviewer-layer-grid">
      <section className="deterministic-layer" data-review-layer="LAYER_A_DETERMINISTIC"><header><small>LAYER A</small><b>Deterministic contract checks</b><span>closed outcomes only</span></header><div className="review-check-grid">{report.checks.map((item) => <article key={item.ruleId} data-review-outcome={item.outcome}><code>{item.ruleId}</code><b>{item.outcome}</b><span>{item.title}</span><small>{item.required ? "REQUIRED" : "OPTIONAL"}</small></article>)}</div></section>
      <section className="reviewer-agent-layer" data-review-layer="LAYER_B_REVIEWER_AGENT"><header><small>LAYER B</small><b>Reviewer Agent interpretation</b><span>NON_CANONICAL · L1_DRAFT</span></header><div className="reviewer-agent-boundary">{REVIEWER_AGENT_CAPABILITIES.map((item) => <div key={item.permission}><b>{item.permission}</b><span>{item.label}</span></div>)}<small>DENIED · {REVIEWER_FORBIDDEN_ACTIONS.join(" · ")}</small></div>{report.agentDrafts.map((draft) => <article key={draft.statementId}><small>{draft.permission} · {draft.authorityStatus}</small><b>{draft.title}</b><p>{draft.body}</p><div>{draft.evidenceObjectIds.map((objectId) => <button key={objectId} onClick={() => onSelectEvidence(objectId)}>{objectId}</button>)}</div></article>)}</section>
    </div>
    <div className="reviewer-finding-grid"><FindingList findings={report.findings} selectedFindingId={selectedFinding?.findingId ?? null} onSelect={setSelectedFindingId}/><FindingDetail finding={selectedFinding} loadedEvidenceIds={loadedEvidenceIds} onSelectEvidence={onSelectEvidence}/></div>
  </section>;
}
