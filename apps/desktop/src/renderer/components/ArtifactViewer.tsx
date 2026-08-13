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
  if (!artifact) return <section className="artifact-viewer artifact-empty" data-testid="artifact-viewer" data-renderer="none" data-empty="true"><header><div><small>产物查看器</small><b>尚未选择会话产物</b></div><span className="status-badge neutral">空 · EMPTY</span></header><p>这里只能呈现由当前研究会话所选证据显式链接的 Artifact。</p></section>;
  let renderer: (typeof ARTIFACT_RENDERER_REGISTRY)[keyof typeof ARTIFACT_RENDERER_REGISTRY] | null = null;
  let rendererError: string | null = null;
  try {
    assertSafeArtifactOutput(artifact.payload);
    renderer = ARTIFACT_RENDERER_REGISTRY[artifact.payload.renderer];
  } catch (error) {
    rendererError = error instanceof Error ? `技术诊断：${error.message}` : "产物渲染器不受支持";
  }
  const contentSha256 = artifact.contentSha256 ?? exactSha256FromId(artifact.artifactId) ?? "UNKNOWN";
  const sourceObjectId = artifact.sourceObjectId ?? evidence?.objectId ?? "UNKNOWN";
  const sourceEvidence = evidence?.objectId === sourceObjectId ? evidence : null;
  const integrityStatus = artifact.integrityStatus ?? "NOT_RUN";
  const validationState = artifact.validationState ?? "NOT_RUN";
  const lineage = exactRelations.filter((edge) => edge.sourceExactId === sourceObjectId || edge.targetExactId === sourceObjectId);
  const openInLab = artifact.openInLab ?? evidence?.openInLab;
  return <section className="artifact-viewer" data-testid="artifact-viewer" data-artifact-id={artifact.artifactId} data-renderer={renderer ? artifact.payload.renderer : "unsupported-safe"} data-integrity={integrityStatus}>
    <header>
      <div><small>产物查看器 · {renderer?.label ?? "不支持 · 安全状态"}</small><b>{artifact.title}</b></div>
      <span className={renderer?.availability === "AVAILABLE" ? "status-badge success" : renderer ? "status-badge neutral" : "status-badge warning"}>{renderer?.availability ?? "UNSUPPORTED_SAFE"}</span>
    </header>
    <section className="artifact-authority-section artifact-identity"><h3>产物身份</h3><div className="artifact-meta"><small>产物 ID · ARTIFACT ID</small><code>{artifact.artifactId}</code><span>{artifact.mediaType}</span></div><div><small>内容 SHA-256</small><code>{contentSha256}</code></div></section>
    <section className="artifact-authority-section artifact-owned-status"><h3>产物自有状态</h3><div className="artifact-integrity-grid">
      <div><small>产物真值</small><b>UNKNOWN</b></div>
      <div><small>产物准入</small><b>UNKNOWN</b></div>
      <div><small>完整性</small><b>{integrityStatus}</b></div>
      <div><small>产物验证</small><b>{validationState}</b></div>
    </div></section>
    <section className="artifact-authority-section source-evidence-authority"><h3>来源证据权威</h3><div className="artifact-source-status"><div><small>来源对象</small><code>{sourceEvidence?.objectId ?? "UNKNOWN / UNLINKED"}</code></div><div><small>来源真值</small><b>{sourceEvidence?.canonicalTruthState ?? "UNKNOWN"}</b></div><div><small>来源准入</small><b>{sourceEvidence?.canonicalAdmissionState ?? "UNKNOWN"}</b></div><div><small>来源证据验证</small><b>{sourceEvidence?.validationState ?? "NOT_RUN"}</b></div></div></section>
    <div className="artifact-renderer-state"><small>渲染器</small><b>{renderer?.availability ?? "UNSUPPORTED_SAFE"}</b></div>
    <div className="artifact-copy-actions"><CopyButton label="复制产物 ID" value={artifact.artifactId}/><CopyButton label="复制 hash" value={contentSha256}/>{openInLab && onOpenLab && <button type="button" className="open-in-lab" onClick={() => onOpenLab(openInLab)}>在{labLabel(openInLab)}实验室中打开</button>}</div>
    {renderer ? <ArtifactBody artifact={artifact}/> : <div className="artifact-unsupported-safe" data-testid="artifact-unsupported-safe"><b>渲染器不受支持 · 被动安全状态</b><p>{rendererError}。未执行 HTML、脚本、嵌入式活动内容或文件系统目标。</p></div>}
    <div className="artifact-lineage-meta"><small>来源对象</small><code>{sourceObjectId}</code><small>精确来源链</small>{lineage.length === 0 ? <code>NO_KNOWN_RELATION · DISCOVERY_SCOPE_LIMITED</code> : lineage.map((edge) => <code key={`${edge.sourceExactId}-${edge.relationType}-${edge.targetExactId}`}>{edge.sourceExactId} — {edge.relationType} → {edge.targetExactId}{edge.bindingRef ? ` · 绑定 ${edge.bindingRef}` : ""}</code>)}</div>
    <footer><small>来源 · PROVENANCE</small>{(artifact.provenanceRefs ?? [artifact.provenanceRef]).map((reference) => <code key={reference}>{reference}</code>)}</footer>
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
      <div><small>成交</small><strong>{payload.fillCount}</strong></div>
      <div><small>诊断</small><strong>{payload.diagnosticCount}</strong></div>
      <div><small>现金账本</small><strong>{payload.cashLedgerSummary}</strong></div>
      <div><small>费用账本</small><strong>{payload.feeLedgerSummary}</strong></div>
    </div>
    <dl className="artifact-details"><dt>结果 ID</dt><dd>{payload.resultId}</dd><dt>运行规范 ID</dt><dd>{payload.runSpecId}</dd></dl>
    <div className="artifact-table-wrap"><table><thead><tr>{payload.nav.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{payload.nav.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>
  </div>;
  return <div className="future-renderer-slot"><b>{payload.renderer === "chart" ? "图表" : "回测 / 结果"}渲染器槽位</b><p>{payload.reason}</p><span>尚未连接 · NOT_CONNECTED · 不声明正式支持</span></div>;
}

function CopyButton({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!navigator.clipboard || value === "UNKNOWN") return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return <button type="button" onClick={() => { void copy(); }} disabled={value === "UNKNOWN"}>{copied ? "已复制" : label}</button>;
}

function labLabel(lab: LabId) {
  return lab === "research" ? "研究" : lab === "strategy" ? "策略" : lab === "model" ? "模型" : lab === "backtest" ? "回测" : "结果";
}
