import React from "react";
import type { ReviewerFindingView } from "./model";

export function FindingList({ findings, selectedFindingId, onSelect }: { findings: readonly ReviewerFindingView[]; selectedFindingId: string | null; onSelect: (findingId: string) => void }) {
  return <section className="finding-list" aria-label="不可变评审发现">
    <header><small>A 层 · 不可变发现</small><span>已载入 {findings.length} 项</span></header>
    {findings.length ? findings.map((finding) => <button key={finding.findingId} className={finding.findingId === selectedFindingId ? "active" : ""} onClick={() => onSelect(finding.findingId)} data-finding-outcome={finding.outcome}>
      <span>{finding.severity}</span><b>{finding.title}</b><code>{finding.ruleId}</code>
    </button>) : <p>已载入投影中没有确定性的 FINDING / BLOCKED 结果。</p>}
  </section>;
}
