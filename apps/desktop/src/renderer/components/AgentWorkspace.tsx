import React, { useEffect, useMemo, useState } from "react";
import type { LabId } from "../../../../../packages/contracts/src/index";
import {
  AGENT_WORKSPACE_BOUNDARY,
  FUTURE_EXTENSION_SLOTS,
  PERMISSION_SURFACE,
  deriveAgentWorkspaceSessionScope,
  resolveSessionArtifact,
  resolveSessionEvidenceSelection,
  statusTone,
  type EvidenceView,
  type ResearchSessionView
} from "../agentWorkspace";
import { agentStatements, artifactViews, evidenceViews, timelineEntries } from "../agentWorkspaceFixture";
import { ArtifactViewer } from "./ArtifactViewer";

export function AgentWorkspace({ session, onOpenLab }: { session: ResearchSessionView; onOpenLab: (lab: LabId) => void }) {
  const sessionScope = useMemo(() => deriveAgentWorkspaceSessionScope(session, agentStatements, timelineEntries, evidenceViews), [session.sessionViewId]);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(session.evidenceIds[0] ?? null);
  const [draftInput, setDraftInput] = useState("");
  const [localDrafts, setLocalDrafts] = useState<Record<string, string>>({});
  const selectedEvidence = resolveSessionEvidenceSelection(sessionScope.evidence, selectedEvidenceId);
  const selectedArtifact = resolveSessionArtifact(selectedEvidence, artifactViews);

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

  return <section className="agent-workspace" data-testid="agent-workspace" data-session-id={session.sessionViewId} data-boundary={AGENT_WORKSPACE_BOUNDARY.mode}>
    <header className="agent-workspace-head">
      <div className="agent-session-title"><small>ACTIVE RESEARCH SESSION · DERIVED VIEW</small><h1>{session.title}</h1><p>{session.goal}</p></div>
      <div className="agent-boundary-stack"><span className="boundary-chip">{AGENT_WORKSPACE_BOUNDARY.label}</span><code>{AGENT_WORKSPACE_BOUNDARY.transport}</code></div>
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

        <section className="agent-stream" aria-label="Agent drafts and findings">
          <header><div><small>AGENT WORKSPACE</small><b>Research / Data / Reviewer</b></div><span>AI statement ≠ Evidence fact</span></header>
          {localDrafts[session.sessionViewId] && <article className="agent-statement local-draft" data-testid="local-agent-draft" data-session-id={session.sessionViewId}><div className="agent-role"><span>USER</span><b>L1_DRAFT</b></div><div><small>NON_CANONICAL · DRAFT</small><h2>Local research intent</h2><p>{localDrafts[session.sessionViewId]}</p></div></article>}
          {sessionScope.statements.map((statement) => <article className="agent-statement" key={statement.id} data-statement-id={statement.id} data-session-id={statement.sessionViewId} data-agent-role={statement.role}>
            <div className="agent-role"><span>{statement.role}</span><b>{statement.permission}</b></div>
            <div className="statement-content"><small>{statement.authorityStatus} · {statement.lifecycleState} · {statement.type}</small><h2>{statement.title}</h2><p>{statement.body}</p><div className="statement-evidence">{statement.evidenceIds.map((objectId) => <button key={objectId} onClick={() => selectEvidence(objectId)} title={objectId}>Evidence · {compactId(objectId)}</button>)}</div></div>
          </article>)}
        </section>

        <ArtifactViewer artifact={selectedArtifact}/>
      </main>

      <aside className="evidence-inspector" aria-label="Evidence Inspector" data-testid="evidence-inspector">
        <header><div><small>EVIDENCE INSPECTOR</small><b>Exact authority view</b></div><span>{sessionScope.evidence.length} linked</span></header>
        <div className="evidence-index" role="list" aria-label="Session evidence objects">
          {sessionScope.evidence.map((item) => <button key={item.objectId} data-evidence-object-id={item.objectId} data-truth-state={item.canonicalTruthState} data-admission-state={item.canonicalAdmissionState} className={item.objectId === selectedEvidence?.objectId ? "active" : ""} onClick={() => selectEvidence(item.objectId)} role="listitem"><span>{item.kind}</span><code>{compactId(item.objectId)}</code><small>{item.canonicalTruthState} / {item.canonicalAdmissionState}</small></button>)}
        </div>
        {selectedEvidence ? <EvidenceDetails evidence={selectedEvidence} onOpenLab={onOpenLab}/> : <div className="evidence-empty" data-testid="session-evidence-empty"><small>SESSION EVIDENCE</small><b>No evidence linked</b><p>This Research Session has no explicit evidence links. Nothing from another session is displayed.</p></div>}
        <section className="future-slots"><h3>Future main-contract slots</h3>{FUTURE_EXTENSION_SLOTS.map((slot) => <div key={slot.object}><b>{slot.object}</b><span>{slot.status}</span><small>{slot.owner}</small></div>)}</section>
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

function EvidenceDetails({ evidence, onOpenLab }: { evidence: EvidenceView; onOpenLab: (lab: LabId) => void }) {
  return <div className="evidence-details">
    <div className="evidence-kind"><small>{evidence.kind.toUpperCase()}</small><h2>{evidence.title}</h2><p>{evidence.summary}</p></div>
    <div className="exact-object-id"><small>EXACT OBJECT ID</small><code>{evidence.objectId}</code></div>
    <div className="truth-admission-grid">
      <div><small>CANONICAL TRUTH</small><b>{evidence.canonicalTruthState}</b></div>
      <div><small>ADMISSION</small><b>{evidence.canonicalAdmissionState}</b></div>
      <div><small>VALIDATION</small><b className={evidence.validationState === "PASSED" ? "ok" : evidence.validationState === "FAILED" ? "error" : "muted"}>{evidence.validationState}</b></div>
    </div>
    <dl>{evidence.facts.map((fact) => <React.Fragment key={fact.label}><dt>{fact.label}</dt><dd>{fact.value}</dd></React.Fragment>)}</dl>
    <section><h3>Provenance refs</h3>{evidence.provenanceRefs.map((reference) => <code key={reference}>{reference}</code>)}</section>
    <section><h3>Reviewer finding</h3><p>{evidence.reviewerFinding ?? "No linked blocking finding in this view."}</p></section>
    <button className="open-in-lab" onClick={() => onOpenLab(evidence.openInLab)}>Open in {labLabel(evidence.openInLab)} Lab</button>
  </div>;
}

function compactId(value: string) {
  return value.length > 28 ? `${value.slice(0, 17)}…${value.slice(-8)}` : value;
}

function labLabel(lab: LabId) {
  return lab[0].toUpperCase() + lab.slice(1);
}
