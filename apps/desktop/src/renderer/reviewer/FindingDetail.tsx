import React from "react";
import type { ReviewerFindingView } from "./model";

export function FindingDetail({ finding, loadedEvidenceIds, onSelectEvidence }: { finding: ReviewerFindingView | null; loadedEvidenceIds: ReadonlySet<string>; onSelectEvidence: (objectId: string) => void }) {
  if (!finding) return <section className="finding-detail empty"><small>发现详情</small><p>选择一项确定性发现以检查其精确证据链接。</p></section>;
  return <section className="finding-detail" data-finding-id={finding.findingId}>
    <header><small>发现详情 · {finding.outcome}</small><b>{finding.title}</b></header>
    <p>{finding.explanation}</p>
    <dl><dt>规则</dt><dd>{finding.ruleId}</dd><dt>报告绑定</dt><dd>{finding.reviewReportId ?? "BACKEND_REPORT_NOT_LOADED"}</dd><dt>整改建议</dt><dd>{finding.remediationSuggestion}</dd></dl>
    <div className="finding-evidence-links"><small>精确证据链接</small>{finding.evidenceObjectIds.map((objectId) => <button key={objectId} disabled={!loadedEvidenceIds.has(objectId)} onClick={() => onSelectEvidence(objectId)} title={objectId}>{objectId}</button>)}</div>
    <div className="finding-lifecycle"><small>重新评审历史</small>{finding.lifecycleLinks.length ? finding.lifecycleLinks.map((link) => <code key={`${link.reportId}:${link.findingId}`}>{link.relation} · {link.reportId} · {link.findingId}</code>) : <span>未载入 RESOLVES / SUPERSEDES 链接。</span>}</div>
  </section>;
}
