import React, { useMemo } from "react";
import type { LabId } from "../../../../../packages/contracts/src/index";
import { ClosedChart } from "./ClosedChart";
import { getClosedResearchRenderer } from "./rendererRegistry";
import {
  parseResearchViewSpec,
  type ResearchEvidenceProjection,
  type ResolvedResearchViewBlock
} from "./schemaParser";
import "./generativeResearchView.css";

export function GenerativeResearchView({ spec, sessionViewId, evidence, onSelectEvidence, onOpenLab }: {
  spec: unknown;
  sessionViewId: string;
  evidence: readonly ResearchEvidenceProjection[];
  onSelectEvidence: (evidenceId: string) => void;
  onOpenLab: (lab: LabId) => void;
}) {
  const parsed = useMemo(
    () => parseResearchViewSpec(spec, { sessionViewId, evidence }),
    [evidence, sessionViewId, spec]
  );
  const evidenceById = useMemo(() => new Map(evidence.map((item) => [item.objectId, item])), [evidence]);

  return <section className="generative-research-view" aria-labelledby="generative-research-title" data-testid="generative-research-view" data-status={parsed.status} data-session-id={sessionViewId}>
    <header className="generative-research-head">
      <div>
        <small>GENERATIVE RESEARCH UI · L1_DRAFT</small>
        <b id="generative-research-title">{parsed.title}</b>
      </div>
      <div className="generative-boundary">
        <span>DETERMINISTIC INTEGRATION FIXTURE</span>
        <code>NO LIVE AGENT STRUCTURED OUTPUT CLAIM</code>
      </div>
    </header>
    {parsed.error && <div className="generative-invalid-view" role="status" data-testid="invalid-research-view">
      <strong>INVALID STRUCTURED VIEW</strong>
      <span>{parsed.error}</span>
      <small>Text draft remains available; no renderer payload executed.</small>
    </div>}
    <div className="generative-block-grid">
      {parsed.blocks.map((block) => <ResearchBlock key={block.blockId} block={block} evidenceById={evidenceById} onSelectEvidence={onSelectEvidence} onOpenLab={onOpenLab}/>)}
      {parsed.invalidBlocks.map((block) => <article className="generative-block invalid" key={block.blockId} role="status" data-testid="unsupported-research-renderer">
        <header><small>UNSUPPORTED / INVALID BLOCK</small><b>{block.blockId}</b></header>
        <p>{block.reason}</p>
        <span>Fail-closed; remaining valid blocks stay available.</span>
      </article>)}
    </div>
  </section>;
}

function ResearchBlock({ block, evidenceById, onSelectEvidence, onOpenLab }: {
  block: ResolvedResearchViewBlock;
  evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>;
  onSelectEvidence: (evidenceId: string) => void;
  onOpenLab: (lab: LabId) => void;
}) {
  const renderer = getClosedResearchRenderer(block.type);
  return <article className={`generative-block type-${block.type.toLowerCase()}`} data-block-type={block.type} data-authority={block.dataAuthority}>
    <header>
      <div><small>{renderer.label.toUpperCase()} · {block.dataAuthority}</small><b>{block.title}</b></div>
      <span className={block.dataAuthority === "CANONICAL_EVIDENCE" ? "canonical" : "draft"}>{block.dataAuthority === "CANONICAL_EVIDENCE" ? "CANONICAL SOURCE" : "NON_CANONICAL / DRAFT"}</span>
    </header>
    <div className="generative-block-body">{renderBlockBody(block, onSelectEvidence, onOpenLab)}</div>
    <EvidenceBindings evidenceIds={block.evidenceIds} evidenceById={evidenceById} onSelectEvidence={onSelectEvidence} onOpenLab={onOpenLab}/>
  </article>;
}

function renderBlockBody(block: ResolvedResearchViewBlock, onSelectEvidence: (evidenceId: string) => void, onOpenLab: (lab: LabId) => void) {
  if (block.type === "Narrative") return <p className="generative-narrative">{block.text}</p>;
  if (block.type === "Callout") return <div className="generative-callout" data-tone={block.tone}><strong>{block.tone}</strong><p>{block.text}</p></div>;
  if (block.type === "MetricGroup") return <div className="generative-metrics">{block.metrics.map((metric) => <div key={`${metric.sourceEvidenceId}:${metric.label}`}><small>{metric.label}</small><b>{metric.value}</b><code title={metric.sourceEvidenceId}>{compactId(metric.sourceEvidenceId)}</code></div>)}</div>;
  if (block.type === "DataTable") return <div className="generative-table-wrap"><table><thead><tr>{block.columns.map((column) => <th key={column.key} scope="col">{column.header}</th>)}</tr></thead><tbody>{block.rows.map((row) => <tr key={row.evidenceId}>{row.cells.map((cell, index) => <td key={block.columns[index].key}>{index === 0 ? <button type="button" className="generative-table-select" onClick={() => onSelectEvidence(row.evidenceId)}>{cell}</button> : cell}</td>)}</tr>)}</tbody></table></div>;
  if (block.type === "TimeSeriesChart" || block.type === "BarChart") return <ClosedChart block={block}/>;
  return <div className="generative-evidence-list">{block.items.map((item) => <section key={item.evidenceId}>
    <div>{item.values.map((entry) => <span key={entry.key}><small>{entry.label}</small><b>{entry.value}</b></span>)}</div>
    <div className="generative-inline-actions"><button type="button" onClick={() => onSelectEvidence(item.evidenceId)}>Select evidence</button><button type="button" onClick={() => onOpenLab(item.openInLab)}>Open {item.openInLab} Lab</button><CopyIdButton evidenceId={item.evidenceId}/></div>
  </section>)}</div>;
}

function EvidenceBindings({ evidenceIds, evidenceById, onSelectEvidence, onOpenLab }: {
  evidenceIds: readonly string[];
  evidenceById: ReadonlyMap<string, ResearchEvidenceProjection>;
  onSelectEvidence: (evidenceId: string) => void;
  onOpenLab: (lab: LabId) => void;
}) {
  return <details className="generative-bindings">
    <summary>{evidenceIds.length} bound evidence source{evidenceIds.length === 1 ? "" : "s"}</summary>
    <div>{evidenceIds.map((evidenceId) => {
      const source = evidenceById.get(evidenceId);
      return <section key={evidenceId}><code title={evidenceId}>{compactId(evidenceId)}</code><span>{source?.title ?? "Unavailable source"}</span><div><button type="button" onClick={() => onSelectEvidence(evidenceId)}>Select</button>{source && <button type="button" onClick={() => onOpenLab(source.openInLab)}>Open Lab</button>}<CopyIdButton evidenceId={evidenceId}/></div></section>;
    })}</div>
  </details>;
}

function CopyIdButton({ evidenceId }: { evidenceId: string }) {
  const copy = () => { void navigator.clipboard?.writeText(evidenceId).catch(() => undefined); };
  return <button type="button" onClick={copy} aria-label={`Copy evidence ID ${evidenceId}`}>Copy ID</button>;
}

function compactId(value: string): string {
  return value.length <= 30 ? value : `${value.slice(0, 18)}…${value.slice(-8)}`;
}
