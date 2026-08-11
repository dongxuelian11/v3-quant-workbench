import React, { useState } from "react";
import type { LabId } from "../../../../../packages/contracts/src/index";
import { ARTIFACT_RENDERER_REGISTRY, assertSafeArtifactOutput, type ArtifactView, type EvidenceView } from "../agentWorkspace";
import type { ExactLineageRelationInput } from "../evidence_explorer/contracts";
import { exactSha256FromId } from "../evidence_explorer/model";

export function ArtifactViewer({ artifact, evidence = null, exactRelations = [], onOpenLab }: {
  artifact: ArtifactView | null;
  evidence?: EvidenceView | null;
  exactRelations?: readonly ExactLineageRelationInput[];
  onOpenLab?: (lab: LabId) => void;
}) {
  if (!artifact) return <section className="artifact-viewer artifact-empty" data-testid="artifact-viewer" data-renderer="none" data-empty="true"><header><div><small>ARTIFACT VIEWER</small><b>No session artifact selected</b></div><span className="status-badge neutral">EMPTY</span></header><p>Only an Artifact explicitly linked by the selected evidence in this Research Session can render here.</p></section>;
  let renderer: (typeof ARTIFACT_RENDERER_REGISTRY)[keyof typeof ARTIFACT_RENDERER_REGISTRY] | null = null;
  let rendererError: string | null = null;
  try {
    assertSafeArtifactOutput(artifact.payload);
    renderer = ARTIFACT_RENDERER_REGISTRY[artifact.payload.renderer];
  } catch (error) {
    rendererError = error instanceof Error ? error.message : "unsupported artifact renderer";
  }
  const contentSha256 = artifact.contentSha256 ?? exactSha256FromId(artifact.artifactId) ?? "UNKNOWN";
  const sourceObjectId = artifact.sourceObjectId ?? evidence?.objectId ?? "UNKNOWN";
  const integrityStatus = artifact.integrityStatus ?? evidence?.integrityStatus ?? "NOT_RUN";
  const validationState = artifact.validationState ?? evidence?.validationState ?? "NOT_RUN";
  const lineage = exactRelations.filter((edge) => edge.sourceExactId === sourceObjectId || edge.targetExactId === sourceObjectId);
  const openInLab = artifact.openInLab ?? evidence?.openInLab;
  return <section className="artifact-viewer" data-testid="artifact-viewer" data-artifact-id={artifact.artifactId} data-renderer={renderer ? artifact.payload.renderer : "unsupported-safe"} data-integrity={integrityStatus}>
    <header>
      <div><small>ARTIFACT VIEWER · {(renderer?.label ?? "UNSUPPORTED SAFE").toUpperCase()}</small><b>{artifact.title}</b></div>
      <span className={renderer?.availability === "AVAILABLE" ? "status-badge success" : renderer ? "status-badge neutral" : "status-badge warning"}>{renderer?.availability ?? "UNSUPPORTED_SAFE"}</span>
    </header>
    <div className="artifact-meta"><code>{artifact.artifactId}</code><span>{artifact.mediaType}</span></div>
    <div className="artifact-integrity-grid">
      <div><small>CONTENT SHA-256</small><code>{contentSha256}</code></div>
      <div><small>INTEGRITY</small><b>{integrityStatus}</b></div>
      <div><small>VALIDATION</small><b>{validationState}</b></div>
      <div><small>RENDERER</small><b>{renderer?.availability ?? "UNSUPPORTED_SAFE"}</b></div>
    </div>
    <div className="artifact-copy-actions"><CopyButton label="Copy artifact ID" value={artifact.artifactId}/><CopyButton label="Copy hash" value={contentSha256}/>{openInLab && onOpenLab && <button type="button" className="open-in-lab" onClick={() => onOpenLab(openInLab)}>Open in {labLabel(openInLab)} Lab</button>}</div>
    {renderer ? <ArtifactBody artifact={artifact}/> : <div className="artifact-unsupported-safe" data-testid="artifact-unsupported-safe"><b>Unsupported renderer · passive safe state</b><p>{rendererError}. No HTML, script, embedded active content, or filesystem target was executed.</p></div>}
    <div className="artifact-lineage-meta"><small>SOURCE OBJECT</small><code>{sourceObjectId}</code><small>EXACT LINEAGE</small>{lineage.length === 0 ? <code>NO_KNOWN_RELATION · DISCOVERY_SCOPE_LIMITED</code> : lineage.map((edge) => <code key={`${edge.sourceExactId}-${edge.relationType}-${edge.targetExactId}`}>{edge.sourceExactId} — {edge.relationType} → {edge.targetExactId}{edge.bindingRef ? ` · binding ${edge.bindingRef}` : ""}</code>)}</div>
    <footer><small>PROVENANCE</small>{(artifact.provenanceRefs ?? [artifact.provenanceRef]).map((reference) => <code key={reference}>{reference}</code>)}</footer>
  </section>;
}

function ArtifactBody({ artifact }: { artifact: ArtifactView }) {
  const payload = artifact.payload;
  if (payload.renderer === "metric") return <div className="artifact-metrics">{payload.metrics.map((metric) => <div key={metric.label}><small>{metric.label}</small><strong>{metric.value}</strong></div>)}</div>;
  if (payload.renderer === "table") return <div className="artifact-table-wrap"><table><thead><tr>{payload.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{payload.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>;
  if (payload.renderer === "details") return <dl className="artifact-details">{payload.entries.map((entry) => <React.Fragment key={entry.label}><dt>{entry.label}</dt><dd>{entry.value}</dd></React.Fragment>)}</dl>;
  if (payload.renderer === "text") return <p className="artifact-text">{payload.text}</p>;
  if (payload.renderer === "backtest-result" && !("availability" in payload)) return <div className="backtest-result-artifact" data-testid="canonical-backtest-result">
    <div className="artifact-metrics">
      <div><small>FILLS</small><strong>{payload.fillCount}</strong></div>
      <div><small>DIAGNOSTICS</small><strong>{payload.diagnosticCount}</strong></div>
      <div><small>CASH LEDGER</small><strong>{payload.cashLedgerSummary}</strong></div>
      <div><small>FEE LEDGER</small><strong>{payload.feeLedgerSummary}</strong></div>
    </div>
    <dl className="artifact-details"><dt>Result ID</dt><dd>{payload.resultId}</dd><dt>Run spec ID</dt><dd>{payload.runSpecId}</dd></dl>
    <div className="artifact-table-wrap"><table><thead><tr>{payload.nav.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{payload.nav.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>
  </div>;
  return <div className="future-renderer-slot"><b>{payload.renderer === "chart" ? "Chart" : "Backtest / Result"} renderer slot</b><p>{payload.reason}</p><span>NOT_CONNECTED · no formal support claim</span></div>;
}

function CopyButton({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!navigator.clipboard || value === "UNKNOWN") return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return <button type="button" onClick={() => { void copy(); }} disabled={value === "UNKNOWN"}>{copied ? "Copied" : label}</button>;
}

function labLabel(lab: LabId) {
  return lab[0].toUpperCase() + lab.slice(1);
}
