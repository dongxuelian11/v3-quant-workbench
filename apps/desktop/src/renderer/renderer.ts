import {
  type BackendStatus,
  type LabId,
  type WorkspaceState
} from "../../../../packages/contracts/src/index";

declare global {
  interface Window {
    v3Desktop: import("../../../../packages/contracts/src/index").DesktopBridge;
  }
}

interface LabDefinition {
  id: LabId;
  number: string;
  label: string;
  kicker: string;
  title: string;
  summary: string;
  state: "recovered" | "reimplemented" | "unavailable";
}

const labs: LabDefinition[] = [
  {
    id: "research",
    number: "01",
    label: "Research",
    kicker: "Explore",
    title: "Research Lab",
    summary: "Chart-led research, universe construction, and contextual evidence in one workspace.",
    state: "recovered"
  },
  {
    id: "strategy",
    number: "02",
    label: "Strategy",
    kicker: "Define",
    title: "Strategy Lab",
    summary: "Move from visual intent to typed strategy drafts, diffs, and handoff-ready versions.",
    state: "recovered"
  },
  {
    id: "model",
    number: "03",
    label: "Model",
    kicker: "Learn",
    title: "Model Lab",
    summary: "Organize datasets, model families, studies, trials, HPO, and prediction-signal versions.",
    state: "reimplemented"
  },
  {
    id: "backtest",
    number: "04",
    label: "Backtest",
    kicker: "Evaluate",
    title: "Backtest Lab",
    summary: "Configure formal evaluation intent while the canonical backend is still being rebuilt.",
    state: "unavailable"
  },
  {
    id: "result",
    number: "05",
    label: "Result",
    kicker: "Inspect",
    title: "Result Lab",
    summary: "Review the result, ledger, performance, risk, attribution, and comparison information architecture.",
    state: "unavailable"
  }
];

// Renderer runtime stays self-contained: type-only imports preserve the typed
// boundary without asking a context-isolated browser document to call require().
const LAB_ORDER: readonly LabId[] = ["research", "strategy", "model", "backtest", "result"];
const INITIAL_WORKSPACE_STATE: WorkspaceState = {
  activeLab: "research",
  inspectorOpen: true,
  layout: { leftRail: true, inspector: true, bottomPanel: true },
  activeProject: "Momentum Research / 2026 Q2",
  selectedAsset: "Universe / CN Large Cap"
};

const rootElement = document.querySelector<HTMLDivElement>("#app");
if (!rootElement) throw new Error("V3 renderer root was not found");
const root: HTMLDivElement = rootElement;

let state: WorkspaceState = structuredClone(INITIAL_WORKSPACE_STATE);
let backendStatus: BackendStatus = {
  availability: "unavailable",
  provider: "UnavailableBackendProvider",
  message: "Canonical backend reconstruction is not part of FR-0 / FR-1.",
  formalOutputAllowed: false
};

function activeLab(): LabDefinition {
  return labs.find((lab) => lab.id === state.activeLab) ?? labs[0];
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "'": "&#39;",
      '"': "&quot;"
    };
    return entities[character] ?? character;
  });
}

function iconFor(id: LabId): string {
  const icons: Record<LabId, string> = {
    research: "⌁",
    strategy: "◈",
    model: "✦",
    backtest: "◫",
    result: "◒"
  };
  return icons[id];
}

function renderNav(): string {
  return labs
    .map(
      (lab) => `
        <button class="nav-item ${lab.id === state.activeLab ? "active" : ""}" data-lab="${lab.id}" title="Open ${lab.title}">
          <span class="nav-index">${lab.number}</span>
          <span class="nav-icon">${iconFor(lab.id)}</span>
          <span class="nav-label">${lab.label}</span>
        </button>`
    )
    .join("");
}

function availabilityBadge(label = "UNAVAILABLE"): string {
  return `<span class="availability-badge"><span class="status-dot"></span>${label}</span>`;
}

function renderResearch(): string {
  return `
    <section class="lab-grid research-grid">
      <article class="panel chart-panel span-2">
        <div class="panel-heading"><div><span class="eyebrow">PRICE + FACTOR EVIDENCE</span><h2>CN Large Cap · Momentum composite</h2></div><span class="panel-action">1D · 3Y⌄</span></div>
        <div class="chart-meta"><span class="price">4,218.36</span><span class="positive">+1.84%</span><span class="muted">As of 2026-06-30 · adjusted close</span></div>
        <svg class="research-chart" viewBox="0 0 760 250" role="img" aria-label="Illustrative research chart">
          <defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#42d9d0" stop-opacity=".28"/><stop offset="1" stop-color="#42d9d0" stop-opacity="0"/></linearGradient></defs>
          <path class="chart-grid" d="M0 45H760 M0 95H760 M0 145H760 M0 195H760 M90 0V250 M210 0V250 M330 0V250 M450 0V250 M570 0V250 M690 0V250"/>
          <path class="chart-area" d="M0 198 L34 184 L67 190 L101 164 L134 178 L168 145 L201 159 L235 133 L268 140 L302 112 L335 128 L369 106 L402 120 L436 82 L469 101 L503 69 L536 87 L570 57 L603 70 L637 43 L670 60 L704 28 L760 20 L760 250 L0 250 Z"/>
          <path class="chart-line" d="M0 198 L34 184 L67 190 L101 164 L134 178 L168 145 L201 159 L235 133 L268 140 L302 112 L335 128 L369 106 L402 120 L436 82 L469 101 L503 69 L536 87 L570 57 L603 70 L637 43 L670 60 L704 28 L760 20"/>
          <circle class="chart-point" cx="704" cy="28" r="5"/>
          <text x="705" y="18" class="chart-label">4,218</text>
        </svg>
        <div class="chart-footer"><span>2023</span><span>2024</span><span>2025</span><span>2026</span></div>
      </article>
      <article class="panel insight-panel">
        <div class="panel-heading"><div><span class="eyebrow">INSPECTOR · FACTOR</span><h2>Signal snapshot</h2></div><span class="spark">↗</span></div>
        <div class="metric-row"><span>Momentum 12M</span><strong>+0.71</strong></div>
        <div class="metric-row"><span>Quality blend</span><strong>+0.44</strong></div>
        <div class="metric-row"><span>Coverage</span><strong>1,842 names</strong></div>
        <div class="mini-note"><span class="teal-bar"></span>Research evidence only · no trade instruction</div>
      </article>
      <article class="panel universe-panel">
        <div class="panel-heading"><div><span class="eyebrow">UNIVERSE BUILDER</span><h2>Workspace assets</h2></div><button class="ghost-button" data-action="select-universe">Open</button></div>
        <div class="asset-item selected"><span class="asset-icon">◎</span><div><strong>CN Large Cap</strong><small>Universe · 1,842 constituents</small></div><span class="asset-check">✓</span></div>
        <div class="asset-item"><span class="asset-icon">◌</span><div><strong>Momentum composite</strong><small>Factor document · 12 signals</small></div><span class="muted">›</span></div>
        <div class="asset-item"><span class="asset-icon">□</span><div><strong>2026 Q2 research memo</strong><small>Document · last edited today</small></div><span class="muted">›</span></div>
      </article>
      <article class="panel timeline-panel span-2">
        <div class="panel-heading"><div><span class="eyebrow">RESEARCH WORKSPACE</span><h2>Evidence trail</h2></div><span class="muted">3 linked assets</span></div>
        <div class="trail"><span class="trail-node done">✓</span><div><strong>Universe selected</strong><small>CN Large Cap · point-in-time membership intent</small></div><span class="trail-line"></span><span class="trail-node done">✓</span><div><strong>Factor inspected</strong><small>Momentum composite · rank normalized</small></div><span class="trail-line"></span><span class="trail-node current">3</span><div><strong>Strategy handoff</strong><small>Ready for Strategy Lab review</small></div></div>
      </article>
    </section>`;
}

function renderStrategy(): string {
  return `
    <section class="lab-grid strategy-grid">
      <article class="panel span-2 strategy-editor">
        <div class="panel-heading"><div><span class="eyebrow">STRATEGY DRAFT · V0.8</span><h2>Momentum / Quality Blend</h2></div><span class="draft-state"><span class="status-dot teal"></span>Draft saved</span></div>
        <div class="mode-tabs"><button class="mode-tab active">Visual</button><button class="mode-tab">Code</button><button class="mode-tab">Split</button><span class="mode-hint">⌘ ↵ Validate</span></div>
        <div class="flow-canvas">
          <div class="flow-node source"><span class="node-kicker">UNIVERSE</span><strong>CN Large Cap</strong><small>1,842 names</small></div><span class="flow-arrow">→</span>
          <div class="flow-node factor"><span class="node-kicker">FACTOR</span><strong>Momentum 12M</strong><small>rank · winsorize</small></div><span class="flow-arrow">→</span>
          <div class="flow-node factor"><span class="node-kicker">FILTER</span><strong>Quality &gt; 0.35</strong><small>top 40%</small></div><span class="flow-arrow">→</span>
          <div class="flow-node output"><span class="node-kicker">ALLOCATION</span><strong>Equal Weight</strong><small>rebalance · monthly</small></div>
        </div>
        <div class="editor-footer"><span><span class="status-dot teal"></span>3 nodes valid</span><span class="muted">Last handoff: none</span><button class="primary-button" data-action="handoff">Create handoff</button></div>
      </article>
      <article class="panel diff-panel">
        <div class="panel-heading"><div><span class="eyebrow">VERSION HISTORY</span><h2>Draft diff</h2></div><button class="ghost-button">Compare</button></div>
        <div class="version-row current"><span class="version-tag">V0.8</span><div><strong>Quality threshold</strong><small>Changed from 0.30 to 0.35</small></div><span class="positive">now</span></div>
        <div class="version-row"><span class="version-tag">V0.7</span><div><strong>Monthly rebalance</strong><small>Added allocation cadence</small></div><span class="muted">yesterday</span></div>
        <div class="version-row"><span class="version-tag">V0.6</span><div><strong>Initial draft</strong><small>Universe + momentum factor</small></div><span class="muted">Jun 24</span></div>
      </article>
      <article class="panel inspector-card">
        <div class="panel-heading"><div><span class="eyebrow">CONTEXTUAL INSPECTOR</span><h2>Quality filter</h2></div><span class="selected-mark">●</span></div>
        <label class="field-label">Threshold <output>0.35</output><input type="range" min="0" max="1" value="35" /></label>
        <div class="chip-row"><span class="chip active">Quality</span><span class="chip">Stability</span><span class="chip">Value</span></div>
        <div class="mini-note">Typed StrategyDraft state · ready for a future backend handoff.</div>
      </article>
    </section>`;
}

function renderModel(): string {
  const modelFamilies = ["Linear", "Tree Ensemble", "Boosting", "Neural Net", "Sequence", "Graph", "Hybrid"];
  return `
    <section class="lab-grid model-grid">
      <article class="panel model-overview span-2">
        <div class="panel-heading"><div><span class="eyebrow">MODEL WORKFLOW · STUDY S-014</span><h2>Momentum prediction study</h2></div><span class="study-state"><span class="status-dot teal"></span>Resumable</span></div>
        <div class="model-summary"><div><small>DATASET</small><strong>factor_panel_v3</strong><span>1,842 × 64 features</span></div><div><small>OBJECTIVE</small><strong>Rank IC</strong><span>validation · walk-forward</span></div><div><small>STUDY / HPO</small><strong>18 / 24 trials</strong><span>ModelVersion boost-v0.4 · best: 0.084</span></div></div>
        <div class="progress-track"><span style="width: 76%"></span></div>
        <div class="model-actions"><button class="primary-button" data-action="resume-study">Resume study</button><button class="ghost-button" data-action="compare-models">Compare models</button><span class="muted">Last checkpoint · 14 min ago</span></div>
      </article>
      <article class="panel families-panel">
        <div class="panel-heading"><div><span class="eyebrow">MODEL FAMILIES</span><h2>Product choices</h2></div><span class="muted">7 available</span></div>
        <div class="family-list">${modelFamilies.map((family, index) => `<div class="family-row ${index === 2 ? "selected" : ""}"><span class="family-number">0${index + 1}</span><strong>${family}</strong><span class="family-state">${index === 2 ? "selected" : "available"}</span></div>`).join("")}</div>
      </article>
      <article class="panel trial-panel span-2">
        <div class="panel-heading"><div><span class="eyebrow">TRIAL TABLE</span><h2>Run / model comparison</h2></div><span class="muted">Showing 4 of 18</span></div>
        <div class="data-table"><div class="table-row table-header"><span>TRIAL</span><span>MODEL VERSION</span><span>RANK IC</span><span>STATUS</span></div><div class="table-row"><span>T-018</span><strong>boost-v0.4</strong><span class="positive">0.084</span><span class="table-status best">Best</span></div><div class="table-row"><span>T-017</span><strong>boost-v0.3</strong><span>0.079</span><span class="table-status">Complete</span></div><div class="table-row"><span>T-016</span><strong>tree-v0.8</strong><span>0.071</span><span class="table-status">Complete</span></div><div class="table-row"><span>T-015</span><strong>linear-v1.2</strong><span>0.052</span><span class="table-status">Complete</span></div></div>
      </article>
    </section>`;
}

function renderUnavailableLab(lab: LabDefinition): string {
  const isBacktest = lab.id === "backtest";
  return `
    <section class="lab-grid unavailable-grid">
      <article class="panel unavailable-hero span-2">
        <div class="unavailable-mark">—</div>
        <div><span class="eyebrow">${isBacktest ? "FORMAL EXECUTION SURFACE" : "RESULT WORKSPACE"}</span><h2>${isBacktest ? "Backtest configuration is ready" : "Result workspace is ready"}</h2><p>${isBacktest ? "The accepted portfolio, risk, cost, and execution structure is present for review." : "The accepted ledger, performance, risk, attribution, and comparison structure is present for review."}</p></div>
        ${availabilityBadge()}
      </article>
      <article class="panel unavailable-detail">
        <div class="panel-heading"><div><span class="eyebrow">PROVIDER STATE</span><h2>Canonical backend</h2></div><span class="status-ring">!</span></div>
        <div class="provider-line"><span>Availability</span><strong>Not rebuilt</strong></div>
        <div class="provider-line"><span>Formal output</span><strong>Blocked</strong></div>
        <div class="provider-line"><span>Fallback</span><strong>None</strong></div>
        <div class="mini-note">${escapeHtml(backendStatus.message)}</div>
      </article>
      <article class="panel form-surface span-2">
        <div class="panel-heading"><div><span class="eyebrow">${isBacktest ? "BACKTEST SPECIFICATION" : "RESULT VIEWS"}</span><h2>${isBacktest ? "Evaluation intent" : "Analysis views"}</h2></div><span class="muted">Frontend surface only</span></div>
        <div class="surface-grid">${(isBacktest ? ["Portfolio & risk", "Time range", "Costs & adjustments", "Execution policy"] : ["Performance ledger", "Risk attribution", "Factor attribution", "Run comparison"]).map((item) => `<div class="surface-tile"><span class="tile-icon">${isBacktest ? "□" : "◒"}</span><strong>${item}</strong><small>Available when the canonical backend is rebuilt</small></div>`).join("")}</div>
        <div class="unavailable-callout">${availabilityBadge("UNAVAILABLE · NO FORMAL OUTPUT")}<span>Actions are intentionally disabled until a canonical backend is independently reconstructed.</span></div>
      </article>
    </section>`;
}

function renderLabContent(): string {
  switch (state.activeLab) {
    case "research":
      return renderResearch();
    case "strategy":
      return renderStrategy();
    case "model":
      return renderModel();
    case "backtest":
    case "result":
      return renderUnavailableLab(activeLab());
  }
}

function renderInspector(): string {
  if (!state.inspectorOpen) return "";
  const details: Record<LabId, { title: string; subtitle: string; fields: string[] }> = {
    research: { title: "CN Large Cap", subtitle: "Selected universe", fields: ["1,842 constituents", "Point-in-time intent", "Adjusted close"] },
    strategy: { title: "Quality filter", subtitle: "Selected node", fields: ["Threshold · 0.35", "Top 40%", "Draft V0.8"] },
    model: { title: "boost-v0.4", subtitle: "Selected model version", fields: ["Rank IC · 0.084", "Trial T-018", "Prediction signal pending"] },
    backtest: { title: "Evaluation intent", subtitle: "No provider attached", fields: ["Portfolio + risk", "Costs required", "Execution policy"] },
    result: { title: "Result views", subtitle: "No provider attached", fields: ["Ledger", "Attribution", "Comparison"] }
  };
  const detail = details[state.activeLab];
  return `<aside class="inspector"><div class="inspector-title"><div><span class="eyebrow">INSPECTOR</span><h3>${detail.title}</h3><p>${detail.subtitle}</p></div><button class="icon-button" data-action="toggle-inspector" aria-label="Close inspector">×</button></div><div class="inspector-section"><span class="eyebrow">CONTEXT</span>${detail.fields.map((field) => `<div class="inspector-field"><span class="field-bullet">•</span>${field}</div>`).join("")}</div><div class="inspector-section"><span class="eyebrow">WORKSPACE</span><div class="workspace-card"><span class="workspace-glyph">◈</span><div><strong>${escapeHtml(state.activeProject)}</strong><small>Saved locally · layout synced</small></div></div></div><div class="inspector-footer">${availabilityBadge(backendStatus.availability === "unavailable" ? "BACKEND UNAVAILABLE" : backendStatus.availability.toUpperCase())}</div></aside>`;
}

function render(): void {
  const lab = activeLab();
  root.innerHTML = `
    <div class="app-shell">
      <aside class="rail">
        <div class="brand"><div class="brand-mark">V3</div><div class="brand-copy"><strong>Workbench</strong><span>RECOVERY CANDIDATE</span></div></div>
        <div class="rail-section"><span class="rail-label">PRODUCT LABS</span><nav>${renderNav()}</nav></div>
        <div class="rail-spacer"></div>
        <div class="rail-foot"><div class="project-pill"><span class="project-dot"></span><div><strong>Momentum Research</strong><small>Local workspace</small></div></div><button class="rail-command" data-action="toggle-inspector"><span>⌘</span> Commands <kbd>⌘ K</kbd></button><div class="build-label">FR-0 / FR-1 · LOCAL ONLY</div></div>
      </aside>
      <main class="main-column">
        <header class="topbar"><div class="crumb"><span>V3</span><span class="crumb-separator">/</span><strong>${lab.label}</strong><span class="crumb-separator">/</span><span class="muted">${lab.kicker}</span></div><div class="top-actions"><span class="sync-state"><span class="status-dot teal"></span>Workspace saved</span><button class="icon-button" data-action="save-workspace" title="Save workspace">↥</button><button class="avatar">LM</button></div></header>
        <div class="content-scroll"><div class="lab-heading"><div><div class="heading-line"><span class="lab-number">${lab.number}</span><span class="eyebrow">${lab.kicker.toUpperCase()} · ${lab.state === "unavailable" ? "TRUTHFUL UNAVAILABLE" : "ACCEPTED SURFACE"}</span></div><h1>${lab.title}</h1><p>${lab.summary}</p></div><div class="heading-actions"><button class="ghost-button" data-action="reset-workspace">Reset layout</button><button class="primary-button" data-action="save-workspace">Save workspace</button></div></div>${renderLabContent()}</div>
      </main>
      ${renderInspector()}
    </div>`;
  bindEvents();
}

function setLab(id: LabId): void {
  state = { ...state, activeLab: id, selectedAsset: id === "research" ? "Universe / CN Large Cap" : null };
  render();
}

function bindEvents(): void {
  root.querySelectorAll<HTMLButtonElement>("[data-lab]").forEach((button) => {
    button.addEventListener("click", () => {
      const lab = button.dataset.lab;
      if (lab && (LAB_ORDER as readonly string[]).includes(lab)) setLab(lab as LabId);
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      void handleAction(button.dataset.action ?? "");
    });
  });
}

async function handleAction(action: string): Promise<void> {
  switch (action) {
    case "toggle-inspector":
      state = { ...state, inspectorOpen: !state.inspectorOpen, layout: { ...state.layout, inspector: !state.inspectorOpen } };
      render();
      return;
    case "save-workspace":
      state = await window.v3Desktop.saveWorkspaceState({ state });
      render();
      return;
    case "reset-workspace":
      state = await window.v3Desktop.resetWorkspaceState();
      render();
      return;
    case "resume-study":
      showToast("Study resume is staged; canonical backend is unavailable.");
      return;
    case "compare-models":
      showToast("Model comparison surface is ready; no formal run is executed.");
      return;
    case "handoff":
      showToast("Strategy handoff draft created locally.");
      return;
    case "select-universe":
      showToast("Universe selected in the local workspace.");
      return;
  }
}

function showToast(message: string): void {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.append(toast);
  window.setTimeout(() => toast.remove(), 2600);
}

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey) {
    if (event.key >= "1" && event.key <= "5") {
      event.preventDefault();
      setLab(LAB_ORDER[Number(event.key) - 1]);
    }
    if (event.key.toLowerCase() === "i") {
      event.preventDefault();
      void handleAction("toggle-inspector");
    }
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      void handleAction("save-workspace");
    }
  }
});

async function bootstrap(): Promise<void> {
  if (window.v3Desktop) {
    state = await window.v3Desktop.getWorkspaceState();
    backendStatus = await window.v3Desktop.getBackendStatus();
  }
  render();
}

void bootstrap();
