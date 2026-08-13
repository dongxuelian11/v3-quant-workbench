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
      <div><small>研究会话</small><b>工作区索引</b></div>
      <span className="boundary-chip">{boundary.label}</span>
    </header>
    <div className="session-nav-summary"><span>{sessions.length} 个派生视图</span><span>只读索引</span></div>
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
          <code>{session.linkedExperimentRunId ? "已绑定实验 · Experiment" : "未绑定实验"}</code>
          <time>{session.lastEvidenceUpdate.replace("2026-08-11 ", "")}</time>
        </span>
      </button>)}
    </div>
    <section className="session-boundary-note">
      <small>派生导航视图</small>
      <p>此处不会创建 canonical 研究会话权威；链接仅解析到 current-main 对象词汇或显式 fixture ID。</p>
    </section>
  </div>;
}
