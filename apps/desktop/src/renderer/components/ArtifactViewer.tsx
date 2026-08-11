import React from "react";
import { ARTIFACT_RENDERER_REGISTRY, assertSafeArtifactOutput, type ArtifactView } from "../agentWorkspace";

export function ArtifactViewer({ artifact }: { artifact: ArtifactView }) {
  assertSafeArtifactOutput(artifact.payload);
  const renderer = ARTIFACT_RENDERER_REGISTRY[artifact.payload.renderer];
  return <section className="artifact-viewer" data-testid="artifact-viewer" data-renderer={artifact.payload.renderer}>
    <header>
      <div><small>ARTIFACT VIEWER · {renderer.label.toUpperCase()}</small><b>{artifact.title}</b></div>
      <span className={renderer.availability === "AVAILABLE" ? "status-badge success" : "status-badge neutral"}>{renderer.availability}</span>
    </header>
    <div className="artifact-meta"><code>{artifact.artifactId}</code><span>{artifact.mediaType}</span></div>
    <ArtifactBody artifact={artifact}/>
    <footer><small>PROVENANCE</small><code>{artifact.provenanceRef}</code></footer>
  </section>;
}

function ArtifactBody({ artifact }: { artifact: ArtifactView }) {
  const payload = artifact.payload;
  if (payload.renderer === "metric") return <div className="artifact-metrics">{payload.metrics.map((metric) => <div key={metric.label}><small>{metric.label}</small><strong>{metric.value}</strong></div>)}</div>;
  if (payload.renderer === "table") return <div className="artifact-table-wrap"><table><thead><tr>{payload.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{payload.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>;
  if (payload.renderer === "details") return <dl className="artifact-details">{payload.entries.map((entry) => <React.Fragment key={entry.label}><dt>{entry.label}</dt><dd>{entry.value}</dd></React.Fragment>)}</dl>;
  if (payload.renderer === "text") return <p className="artifact-text">{payload.text}</p>;
  return <div className="future-renderer-slot"><b>{payload.renderer === "chart" ? "Chart" : "Backtest / Result"} renderer slot</b><p>{payload.reason}</p><span>NOT_CONNECTED · no formal support claim</span></div>;
}
