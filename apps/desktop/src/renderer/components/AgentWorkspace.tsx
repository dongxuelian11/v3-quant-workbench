import React, { useEffect, useMemo, useState } from "react";
import type { LabId } from "../../../../../packages/contracts/src/index";
import type { RuntimeConnectionState } from "../../preload/backendRuntime/types";
import {
  PERMISSION_SURFACE,
  deriveAgentWorkspaceSessionScope,
  resolveSessionArtifact,
  resolveSessionEvidenceSelection,
  statusTone,
  type AgentWorkspaceBoundary,
  type AgentWorkspaceData,
  type ResearchSessionView
} from "../agentWorkspace";
import { EvidenceExplorer } from "../evidence_explorer/EvidenceExplorer";
import { discoverySourceFromAgentWorkspaceBoundary } from "../evidence_explorer/model";
import { GenerativeResearchView } from "../generative_ui/GenerativeResearchView";
import { createGenerativeResearchViewFixture } from "../generative_ui/integrationFixture";
import { ArtifactViewer } from "./ArtifactViewer";
import { ReviewerPanel } from "../reviewer";

export function AgentWorkspace({ session, data, boundary, connectionState, onOpenLab }: {
  session: ResearchSessionView;
  data: AgentWorkspaceData;
  boundary: AgentWorkspaceBoundary;
  connectionState: RuntimeConnectionState;
  onOpenLab: (lab: LabId) => void;
}) {
  const sessionScope = useMemo(
    () => deriveAgentWorkspaceSessionScope(session, data.statements, data.timeline, data.evidence),
    [data.evidence, data.statements, data.timeline, session]
  );
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(session.evidenceIds[0] ?? null);
  const [draftInput, setDraftInput] = useState("");
  const [localDrafts, setLocalDrafts] = useState<Record<string, string>>({});
  const selectedEvidence = resolveSessionEvidenceSelection(sessionScope.evidence, selectedEvidenceId);
  const selectedArtifact = resolveSessionArtifact(selectedEvidence, data.artifacts);
  const generativeResearchViewSpec = useMemo(
    () => createGenerativeResearchViewFixture(session.sessionViewId, sessionScope.evidence),
    [session.sessionViewId, sessionScope.evidence]
  );

  useEffect(() => {
    setSelectedEvidenceId((currentObjectId) => resolveSessionEvidenceSelection(sessionScope.evidence, currentObjectId)?.objectId ?? null);
    setDraftInput("");
  }, [session.sessionViewId, sessionScope.evidence]);

  const selectEvidence = (objectId: string | null) => {
    if (!objectId) return;
    setSelectedEvidenceId((currentObjectId) => resolveSessionEvidenceSelection(sessionScope.evidence, currentObjectId, objectId)?.objectId ?? null);
  };

  const saveDraft = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draftInput.trim();
    if (!text) return;
    setLocalDrafts((current) => ({ ...current, [session.sessionViewId]: text }));
    setDraftInput("");
  };

  return <section className="agent-workspace" data-testid="agent-workspace" data-session-id={session.sessionViewId} data-boundary={boundary.mode} data-connection-state={connectionState}>
    <header className="agent-workspace-head">
      <div className="agent-session-title"><small>当前研究会话 · 派生只读视图</small><h1>{session.title}</h1><p>{session.goal}</p></div>
      <div className="agent-boundary-stack"><span className="boundary-chip">{boundary.label}</span><code>{boundary.transport}</code><small>{boundary.source}</small></div>
    </header>

    <div className="agent-workspace-body">
      <main className="agent-active-surface">
        <section className="research-composer" aria-labelledby="research-input-title">
          <div><small id="research-input-title">研究输入 · L1_DRAFT</small><span>仅创建本地非 canonical 草案；不开放执行或发布操作。</span></div>
          <form onSubmit={saveDraft}>
            <textarea value={draftInput} onChange={(event) => setDraftInput(event.target.value)} placeholder="输入有边界的研究问题，并注明希望智能体检查的证据…" aria-label="研究问题"/>
            <button type="submit" disabled={!draftInput.trim()}>保存 L1 草案</button>
          </form>
        </section>

        <section className="permission-strip" aria-label="智能体权限边界">
          {PERMISSION_SURFACE.map((permission) => <div key={permission.level} data-allowed={permission.allowed}><span>{permission.level}</span><b>{permission.allowed ? "允许 · AVAILABLE" : "拒绝 · DENIED"}</b><small>{permission.label}</small></div>)}
        </section>

        <ReviewerPanel session={session} evidence={sessionScope.evidence} statements={sessionScope.statements} onSelectEvidence={selectEvidence}/>

        <section className="agent-stream" aria-label="智能体草案与发现">
          <header><div><small>智能体工作区</small><b>研究 · 数据 · 评审者</b></div><span>AI 陈述 ≠ 证据事实</span></header>
          {localDrafts[session.sessionViewId] && <article className="agent-statement local-draft" data-testid="local-agent-draft" data-session-id={session.sessionViewId}><div className="agent-role"><span>用户</span><b>L1_DRAFT</b></div><div><small>非 canonical · NON_CANONICAL · DRAFT</small><h2>本地研究意图</h2><p>{localDrafts[session.sessionViewId]}</p></div></article>}
          {sessionScope.statements.map((statement) => <article className="agent-statement" key={statement.id} data-statement-id={statement.id} data-session-id={statement.sessionViewId} data-agent-role={statement.role}>
            <div className="agent-role"><span>{statement.role}</span><b>{statement.permission}</b></div>
            <div className="statement-content"><small>{statement.authorityStatus} · {statement.lifecycleState} · {statement.type}</small><h2>{statement.title}</h2><p>{statement.body}</p><div className="statement-evidence">{statement.evidenceIds.map((objectId) => <button key={objectId} onClick={() => selectEvidence(objectId)} title={objectId}>证据 · {compactId(objectId)}</button>)}</div></div>
          </article>)}
        </section>

        <GenerativeResearchView spec={generativeResearchViewSpec} sessionViewId={session.sessionViewId} evidence={sessionScope.evidence} onSelectEvidence={selectEvidence} onOpenLab={onOpenLab}/>

        <ArtifactViewer artifact={selectedArtifact} evidence={selectedEvidence} exactRelations={data.exactRelations ?? []} onOpenLab={onOpenLab}/>
      </main>

      <aside className="evidence-inspector" aria-label="证据检查器" data-testid="evidence-inspector" data-open-in-lab-route="Open in canonical Lab">
        <EvidenceExplorer sessions={data.sessions} activeSessionId={session.sessionViewId} evidence={data.evidence} artifacts={data.artifacts} exactRelations={data.exactRelations ?? []} discoverySource={discoverySourceFromAgentWorkspaceBoundary(boundary)} selectedEvidenceId={selectedEvidence?.objectId ?? null} connectionState={connectionState} onSelectEvidence={selectEvidence} onOpenLab={onOpenLab}/>
      </aside>
    </div>

    <section className="execution-timeline" aria-label="计划、任务、工具、实验、证据与评审时间线" data-testid="agent-timeline">
      <header><div><small>执行流</small><b>计划 · 任务 · 工具 · 实验 · 证据 · 评审者</b></div><span>使用真实状态词汇</span></header>
      <div className="timeline-track">{sessionScope.timeline.map((entry) => <button key={entry.id} data-timeline-id={entry.id} data-session-id={entry.sessionViewId} data-timeline-state={entry.state} className={`timeline-entry ${statusTone(entry.state)}`} onClick={() => selectEvidence(entry.objectId)} disabled={!entry.objectId} title={entry.objectId ?? entry.detail}>
        <time>{entry.at}</time><span>{entry.authority}</span><b>{entry.state}</b><strong>{entry.title}</strong><small>{entry.detail}</small>
      </button>)}</div>
    </section>
  </section>;
}

function compactId(value: string) {
  return value.length > 28 ? `${value.slice(0, 17)}…${value.slice(-8)}` : value;
}
