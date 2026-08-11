import React from "react";
import type { ReviewerFindingView } from "./model";

export function FindingDetail({ finding, loadedEvidenceIds, onSelectEvidence }: { finding: ReviewerFindingView | null; loadedEvidenceIds: ReadonlySet<string>; onSelectEvidence: (objectId: string) => void }) {
  if (!finding) return <section className="finding-detail empty"><small>FINDING DETAIL</small><p>Select a deterministic finding to inspect its exact evidence links.</p></section>;
  return <section className="finding-detail" data-finding-id={finding.findingId}>
    <header><small>FINDING DETAIL · {finding.outcome}</small><b>{finding.title}</b></header>
    <p>{finding.explanation}</p>
    <dl><dt>Rule</dt><dd>{finding.ruleId}</dd><dt>Report binding</dt><dd>{finding.reviewReportId ?? "BACKEND_REPORT_NOT_LOADED"}</dd><dt>Remediation</dt><dd>{finding.remediationSuggestion}</dd></dl>
    <div className="finding-evidence-links"><small>EXACT EVIDENCE LINKS</small>{finding.evidenceObjectIds.map((objectId) => <button key={objectId} disabled={!loadedEvidenceIds.has(objectId)} onClick={() => onSelectEvidence(objectId)} title={objectId}>{objectId}</button>)}</div>
    <div className="finding-lifecycle"><small>RE-REVIEW HISTORY</small>{finding.lifecycleLinks.length ? finding.lifecycleLinks.map((link) => <code key={`${link.reportId}:${link.findingId}`}>{link.relation} · {link.reportId} · {link.findingId}</code>) : <span>No RESOLVES / SUPERSEDES link loaded.</span>}</div>
  </section>;
}
