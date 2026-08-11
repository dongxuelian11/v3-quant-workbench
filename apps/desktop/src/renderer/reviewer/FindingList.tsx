import React from "react";
import type { ReviewerFindingView } from "./model";

export function FindingList({ findings, selectedFindingId, onSelect }: { findings: readonly ReviewerFindingView[]; selectedFindingId: string | null; onSelect: (findingId: string) => void }) {
  return <section className="finding-list" aria-label="Immutable Reviewer findings">
    <header><small>LAYER A · IMMUTABLE FINDINGS</small><span>{findings.length} loaded</span></header>
    {findings.length ? findings.map((finding) => <button key={finding.findingId} className={finding.findingId === selectedFindingId ? "active" : ""} onClick={() => onSelect(finding.findingId)} data-finding-outcome={finding.outcome}>
      <span>{finding.severity}</span><b>{finding.title}</b><code>{finding.ruleId}</code>
    </button>) : <p>No deterministic FINDING/BLOCKED result in the loaded projection.</p>}
  </section>;
}
