import React from "react";

export type IconName =
  | "research" | "strategy" | "model" | "backtest" | "result"
  | "project" | "command" | "inspector" | "operations" | "close"
  | "add" | "more" | "chevron" | "pulse" | "focus";

const paths: Record<IconName, React.ReactNode> = {
  research: <><circle cx="11" cy="11" r="5.5"/><path d="m15 15 4 4M11 8v6M8 11h6"/></>,
  strategy: <><circle cx="5" cy="12" r="2"/><circle cx="12" cy="6" r="2"/><circle cx="19" cy="12" r="2"/><path d="m7 11 3.5-3.5M13.5 7.5 17 11M7 13l10 0"/></>,
  model: <><path d="M4 7.5 12 3l8 4.5-8 4.5-8-4.5Z"/><path d="m4 12 8 4.5 8-4.5M4 16.5 12 21l8-4.5"/></>,
  backtest: <><path d="M4 18V6M4 18h16"/><path d="m7 15 4-5 3 2 5-7"/></>,
  result: <><path d="M4 19h16M6.5 16V9h3v7M11 16V5h3v11M15.5 16v-4h3v4"/></>,
  project: <><path d="M3.5 7.5h7l2-2h8v13h-17v-11Z"/><path d="M3.5 9.5h17"/></>,
  command: <><path d="M9 6.5A2.5 2.5 0 1 0 6.5 9H9V6.5ZM15 6.5A2.5 2.5 0 1 1 17.5 9H15V6.5ZM9 15.5A2.5 2.5 0 1 1 6.5 13H9v2.5ZM15 15.5a2.5 2.5 0 1 0 2.5-2.5H15v2.5ZM9 9h6v4H9z"/></>,
  inspector: <><path d="M4 4h16v16H4zM14 4v16"/><path d="M7 8h4M7 12h4M7 16h3"/></>,
  operations: <><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="1.5"/><circle cx="16" cy="12" r="1.5"/><circle cx="10" cy="18" r="1.5"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  add: <path d="M12 5v14M5 12h14"/>,
  more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
  chevron: <path d="m9 6 6 6-6 6"/>,
  pulse: <path d="M3 12h4l2.3-6 4.2 12 2.2-6H21"/>,
  focus: <><path d="M8 4H4v4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><circle cx="12" cy="12" r="3"/></>
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg className="v3-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function TruthMark({ detail = "非正式金融输出", compact = false }: { detail?: string; compact?: boolean }) {
  return <span className={`truth-mark ${compact ? "compact" : ""}`} data-truth-label-mode="compact-status-line"><i/><b>{compact ? "DEMO" : `DEMO · ${detail}`}</b></span>;
}

export function SegmentedControl<T extends string>({
  value, options, onChange, label, testAttribute
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
  testAttribute?: string;
}) {
  return <div className="segmented-control" role="tablist" aria-label={label}>{options.map((option) => <button
    key={option.value}
    role="tab"
    aria-selected={value === option.value}
    className={value === option.value ? "active" : ""}
    data-strategy-mode={testAttribute === "strategy" ? option.value : undefined}
    onClick={() => onChange(option.value)}
  >{option.label}</button>)}</div>;
}

export function PaneHeading({ eyebrow, title, detail, actions }: { eyebrow: string; title: string; detail?: React.ReactNode; actions?: React.ReactNode }) {
  return <header className="pane-heading drawer-head"><div className="pane-title"><small>{eyebrow}</small><h2>{title}</h2>{detail && <span>{detail}</span>}</div>{actions && <div className="pane-actions">{actions}</div>}</header>;
}

export function MetricRail({ items, className = "" }: { items: readonly { label: string; value: string; tone?: "positive" | "negative" | "neutral" }[]; className?: string }) {
  return <div className={`metric-rail ${className}`}>{items.map((item) => <div key={item.label}><small>{item.label}</small><strong className={item.tone ?? "neutral"}>{item.value}</strong></div>)}</div>;
}

export function StatusSurface({ state, title, detail }: { state: "loading" | "empty" | "error" | "unavailable"; title: string; detail: string }) {
  return <div className="status-surface" data-state={state} role={state === "error" ? "alert" : "status"}><span>{state === "loading" ? "···" : state === "error" ? "!" : "—"}</span><b>{title}</b><p>{detail}</p></div>;
}
