import React from "react";
import { statusTone, type AgentWorkspaceBoundary, type ResearchSessionView } from "../agentWorkspace";

export function ResearchSessionNavigator({ sessions, boundary, activeSessionId, onSelect }: {
  sessions: readonly ResearchSessionView[];
  boundary: AgentWorkspaceBoundary;
  activeSessionId: string;
  onSelect: (sessionId: string) => void;
}) {
  return <div className="session-navigator" data-testid="research-session-navigator">
    <header className="session-nav-head">
      <div><small>RESEARCH SESSIONS</small><b>Workspace index</b></div>
      <span className="boundary-chip">{boundary.label}</span>
    </header>
    <div className="session-nav-summary"><span>{sessions.length} derived views</span><span>read-only index</span></div>
    <div className="session-list">
      {sessions.map((session) => <button
        key={session.sessionViewId}
        data-session-id={session.sessionViewId}
        data-session-status={session.status}
        className={activeSessionId === session.sessionViewId ? "active" : ""}
        aria-current={activeSessionId === session.sessionViewId ? "page" : undefined}
        onClick={() => onSelect(session.sessionViewId)}
      >
        <span className={`state-dot ${statusTone(session.status)}`}/>
        <span className="session-copy"><b>{session.title}</b><small>{session.goal}</small></span>
        <span className={`status-badge ${statusTone(session.status)}`}>{session.status}</span>
        <span className="session-links">
          <code>{session.linkedExperimentRunId ? "Experiment linked" : "No Experiment"}</code>
          <time>{session.lastEvidenceUpdate.replace("2026-08-11 ", "")}</time>
        </span>
      </button>)}
    </div>
    <section className="session-boundary-note">
      <small>DERIVED NAVIGATION VIEW</small>
      <p>No canonical Research Session authority is created here. Links resolve only to current-main object vocabulary or explicit fixture IDs.</p>
    </section>
  </div>;
}
