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
      <div className="agent-session-title"><small>ACTIVE RESEARCH SESSION · DERIVED VIEW</small><h1>{session.title}</h1><p>{session.goal}</p></div>
      <div className="agent-boundary-stack"><span className="boundary-chip">{boundary.label}</span><code>{boundary.transport}</code><small>{boundary.source}</small></div>
    </header>

    <div className="agent-workspace-body">
      <main className="agent-active-surface">
        <section className="research-composer" aria-labelledby="research-input-title">
          <div><small id="research-input-title">RESEARCH INPUT · L1_DRAFT</small><span>Creates a local non-canonical draft only. No Execute or Publish action is exposed.</span></div>
          <form onSubmit={saveDraft}>
            <textarea value={draftInput} onChange={(event) => setDraftInput(event.target.value)} placeholder="Ask a bounded research question; cite the evidence you expect the Agent to inspect…" aria-label="Research question"/>
            <button type="submit" disabled={!draftInput.trim()}>Save L1 draft</button>
          </form>
        </section>

        <section className="permission-strip" aria-label="Agent permission surface">
          {PERMISSION_SURFACE.map((permission) => <div key={permission.level} data-allowed={permission.allowed}><span>{permission.level}</span><b>{permission.allowed ? "AVAILABLE" : "DENIED"}</b><small>{permission.label}</small></div>)}
        </section>

        <ReviewerPanel session={session} evidence={sessionScope.evidence} statements={sessionScope.statements} onSelectEvidence={selectEvidence}/>

        <section className="agent-stream" aria-label="Agent drafts and findings">
          <header><div><small>AGENT WORKSPACE</small><b>Research / Data / Reviewer</b></div><span>AI statement ≠ Evidence fact</span></header>
          {localDrafts[session.sessionViewId] && <article className="agent-statement local-draft" data-testid="local-agent-draft" data-session-id={session.sessionViewId}><div className="agent-role"><span>USER</span><b>L1_DRAFT</b></div><div><small>NON_CANONICAL · DRAFT</small><h2>Local research intent</h2><p>{localDrafts[session.sessionViewId]}</p></div></article>}
          {sessionScope.statements.map((statement) => <article className="agent-statement" key={statement.id} data-statement-id={statement.id} data-session-id={statement.sessionViewId} data-agent-role={statement.role}>
            <div className="agent-role"><span>{statement.role}</span><b>{statement.permission}</b></div>
            <div className="statement-content"><small>{statement.authorityStatus} · {statement.lifecycleState} · {statement.type}</small><h2>{statement.title}</h2><p>{statement.body}</p><div className="statement-evidence">{statement.evidenceIds.map((objectId) => <button key={objectId} onClick={() => selectEvidence(objectId)} title={objectId}>Evidence · {compactId(objectId)}</button>)}</div></div>
          </article>)}
        </section>

        <GenerativeResearchView spec={generativeResearchViewSpec} sessionViewId={session.sessionViewId} evidence={sessionScope.evidence} onSelectEvidence={selectEvidence} onOpenLab={onOpenLab}/>

        <ArtifactViewer artifact={selectedArtifact} evidence={selectedEvidence} exactRelations={data.exactRelations ?? []} onOpenLab={onOpenLab}/>
      </main>

      <aside className="evidence-inspector" aria-label="Evidence Inspector" data-testid="evidence-inspector" data-open-in-lab-route="Open in canonical Lab">
        <EvidenceExplorer sessions={data.sessions} activeSessionId={session.sessionViewId} evidence={data.evidence} artifacts={data.artifacts} exactRelations={data.exactRelations ?? []} discoverySource={discoverySourceFromAgentWorkspaceBoundary(boundary)} selectedEvidenceId={selectedEvidence?.objectId ?? null} connectionState={connectionState} onSelectEvidence={selectEvidence} onOpenLab={onOpenLab}/>
      </aside>
    </div>

    <section className="execution-timeline" aria-label="Execution Task Tool Experiment Timeline" data-testid="agent-timeline">
      <header><div><small>EXECUTION STREAM</small><b>Plan / Task / Tool / Experiment / Evidence / Reviewer</b></div><span>truthful state vocabulary</span></header>
      <div className="timeline-track">{sessionScope.timeline.map((entry) => <button key={entry.id} data-timeline-id={entry.id} data-session-id={entry.sessionViewId} data-timeline-state={entry.state} className={`timeline-entry ${statusTone(entry.state)}`} onClick={() => selectEvidence(entry.objectId)} disabled={!entry.objectId} title={entry.objectId ?? entry.detail}>
        <time>{entry.at}</time><span>{entry.authority}</span><b>{entry.state}</b><strong>{entry.title}</strong><small>{entry.detail}</small>
      </button>)}</div>
    </section>
  </section>;
}

function compactId(value: string) {
  return value.length > 28 ? `${value.slice(0, 17)}…${value.slice(-8)}` : value;
}
