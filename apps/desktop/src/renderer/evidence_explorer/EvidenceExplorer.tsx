import React, { memo, useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node
} from "@xyflow/react";
import type { LabId } from "../../../../../packages/contracts/src/index";
import type { RuntimeConnectionState } from "../../preload/backendRuntime/types";
import { ROUND3_MAIN_CONTRACT_SLOTS, type ArtifactView, type EvidenceView, type ResearchSessionView } from "../agentWorkspace";
import type { ExactLineageRelationInput } from "./contracts";
import {
  boundedEvidenceNeighborhood,
  buildEvidenceGraphView,
  exactBreadcrumb,
  exactRelationsForNode,
  filterEvidenceGraph,
  type DiscoveryScopeMode,
  type DiscoverySource,
  type EvidenceGraphFilter,
  type EvidenceGraphView,
  type EvidenceNodeView,
  type LineageDirection
} from "./model";
import "./styles.css";

const DEFAULT_FILTER: EvidenceGraphFilter = {
  search: "",
  nodeType: "ALL",
  truth: "ALL",
  admission: "ALL",
  validation: "ALL",
  finding: "ALL"
};

export function EvidenceExplorer({
  sessions,
  activeSessionId,
  evidence,
  artifacts,
  exactRelations,
  discoverySource,
  selectedEvidenceId,
  connectionState,
  onSelectEvidence,
  onOpenLab
}: {
  sessions: readonly ResearchSessionView[];
  activeSessionId: string;
  evidence: readonly EvidenceView[];
  artifacts: readonly ArtifactView[];
  exactRelations: readonly ExactLineageRelationInput[];
  discoverySource: DiscoverySource;
  selectedEvidenceId: string | null;
  connectionState: RuntimeConnectionState;
  onSelectEvidence: (exactId: string) => void;
  onOpenLab: (lab: LabId) => void;
}) {
  const [viewMode, setViewMode] = useState<"GRAPH" | "LIST">("GRAPH");
  const [scopeMode, setScopeMode] = useState<DiscoveryScopeMode>("ACTIVE_SESSION");
  const [focusExactId, setFocusExactId] = useState<string | null>(selectedEvidenceId);
  const [direction, setDirection] = useState<LineageDirection>("BOTH");
  const [maxHops, setMaxHops] = useState(1);
  const [filter, setFilter] = useState<EvidenceGraphFilter>(DEFAULT_FILTER);

  const graph = useMemo(() => buildEvidenceGraphView({
    sessions,
    activeSessionId,
    evidence,
    artifacts,
    exactRelations,
    discoverySource,
    scopeMode,
    explicitWorkspaceScope: scopeMode === "VISIBLE_WORKSPACE"
  }), [activeSessionId, artifacts, discoverySource, evidence, exactRelations, scopeMode, sessions]);
  const filtered = useMemo(() => filterEvidenceGraph(graph, filter), [filter, graph]);
  const bounded = useMemo(
    () => boundedEvidenceNeighborhood(filtered, focusExactId, direction, maxHops, 60),
    [direction, filtered, focusExactId, maxHops]
  );
  const focusedNode = graph.nodes.find((node) => node.exactId === focusExactId)
    ?? graph.nodes.find((node) => node.exactId === selectedEvidenceId)
    ?? graph.nodes[0]
    ?? null;

  useEffect(() => {
    setScopeMode("ACTIVE_SESSION");
    setFocusExactId(selectedEvidenceId);
    setFilter(DEFAULT_FILTER);
    setDirection("BOTH");
    setMaxHops(1);
  }, [activeSessionId]);

  useEffect(() => {
    if (selectedEvidenceId && graph.nodes.some((node) => node.exactId === selectedEvidenceId)) setFocusExactId(selectedEvidenceId);
  }, [graph.nodes, selectedEvidenceId]);

  const focusNode = useCallback((node: EvidenceNodeView) => {
    setFocusExactId(node.exactId);
    if (node.nodeType !== "Artifact") onSelectEvidence(node.exactId);
  }, [onSelectEvidence]);

  const nodeTypes = useMemo(() => ["ALL", ...new Set(graph.nodes.map((node) => node.nodeType))], [graph.nodes]);
  const breadcrumb = focusedNode ? exactBreadcrumb(graph, focusedNode.exactId) : [];
  const activeSession = sessions.find((session) => session.sessionViewId === activeSessionId);
  const activeSessionNodes = (activeSession?.evidenceIds ?? []).map((exactId) => graph.nodes.find((node) => node.exactId === exactId)).filter((node): node is EvidenceNodeView => node !== undefined);

  return <div className="evidence-explorer" data-testid="evidence-lineage-explorer" data-scope={scopeMode} data-discovery={graph.discoveryScope.completeness} data-discovery-source={graph.discoveryScope.source}>
    <header className="evidence-explorer-head">
      <div><small>证据与来源链检查器</small><b>精确关系 · 只读视图</b></div>
      <div className="explorer-statuses"><span>{graph.discoveryScope.completeness}</span><em>{graph.nodes.length} 个节点 · {graph.edges.length} 条精确边</em></div>
      <code className="explorer-source-authority">{graph.discoveryScope.source}</code>
    </header>

    <div className="evidence-index explorer-evidence-index" role="list" aria-label="会话证据对象">
      {activeSessionNodes.map((node) => <button key={node.exactId} role="listitem" data-evidence-object-id={node.exactId} data-truth-state={node.canonicalTruthState} data-admission-state={node.canonicalAdmissionState} className={node.exactId === focusedNode?.exactId ? "active" : ""} onClick={() => focusNode(node)}><span>{node.nodeType}</span><code>{compactId(node.exactId)}</code><small>{node.canonicalTruthState} / {node.canonicalAdmissionState}</small></button>)}
    </div>

    <div className="evidence-explorer-toolbar" aria-label="证据检查器控件">
      <label className="explorer-search"><span>搜索当前可见范围</span><input value={filter.search} onChange={(event) => setFilter((current) => ({ ...current, search: event.target.value }))} placeholder="精确或前缀 ID、产物、类型、标签"/></label>
      <div className="segmented" aria-label="检查器视图">
        <button aria-pressed={viewMode === "GRAPH"} onClick={() => setViewMode("GRAPH")}>关系图</button>
        <button aria-pressed={viewMode === "LIST"} onClick={() => setViewMode("LIST")}>列表</button>
      </div>
      <div className="segmented scope-switch" aria-label="发现范围">
        <button aria-pressed={scopeMode === "ACTIVE_SESSION"} onClick={() => setScopeMode("ACTIVE_SESSION")}>当前会话</button>
        <button aria-pressed={scopeMode === "VISIBLE_WORKSPACE"} onClick={() => setScopeMode("VISIBLE_WORKSPACE")}>已载入工作区</button>
      </div>
    </div>

    <div className="evidence-explorer-filters" aria-label="证据筛选器">
      <FilterSelect label="类型" value={filter.nodeType} values={nodeTypes} onChange={(value) => setFilter((current) => ({ ...current, nodeType: value as EvidenceGraphFilter["nodeType"] }))}/>
      <FilterSelect label="真值" value={filter.truth} values={["ALL", "UNKNOWN", "NOT_FORMAL", "FORMAL"]} onChange={(value) => setFilter((current) => ({ ...current, truth: value as EvidenceGraphFilter["truth"] }))}/>
      <FilterSelect label="准入" value={filter.admission} values={["ALL", "UNKNOWN", "PRE_ALPHA", "FORMAL_ADMITTED"]} onChange={(value) => setFilter((current) => ({ ...current, admission: value as EvidenceGraphFilter["admission"] }))}/>
      <FilterSelect label="验证" value={filter.validation} values={["ALL", "NOT_RUN", "FAILED", "PASSED"]} onChange={(value) => setFilter((current) => ({ ...current, validation: value as EvidenceGraphFilter["validation"] }))}/>
      <FilterSelect label="发现" value={filter.finding} values={["ALL", "HAS_FINDING", "NO_FINDING"]} onChange={(value) => setFilter((current) => ({ ...current, finding: value as EvidenceGraphFilter["finding"] }))}/>
    </div>

    <div className="lineage-focus-bar">
      <div className="segmented" aria-label="来源链展开方向">
        {(["UPSTREAM", "BOTH", "DOWNSTREAM"] as const).map((value) => <button key={value} aria-pressed={direction === value} onClick={() => setDirection(value)}>{value === "BOTH" ? "上下游" : value === "UPSTREAM" ? "上游" : "下游"}</button>)}
      </div>
      <label>跳数 <select value={maxHops} onChange={(event) => setMaxHops(Number(event.target.value))}><option value={1}>1</option><option value={2}>2</option><option value={3}>3</option></select></label>
      <span>{bounded.truncated ? "有界视图 · 还有已知节点未显示" : bounded.relationAvailability}</span>
    </div>

    <nav className="lineage-breadcrumb" aria-label="精确来源链面包屑">
      {breadcrumb.length > 0 ? breadcrumb.map((exactId, index) => <React.Fragment key={exactId}>{index > 0 && <i aria-hidden="true">›</i>}<button title={exactId} onClick={() => setFocusExactId(exactId)}>{compactId(exactId)}</button></React.Fragment>) : <span>NO_KNOWN_RELATION</span>}
    </nav>

    {graph.nodes.length === 0 ? <div className="evidence-explorer-empty" data-testid="session-evidence-empty"><b>{connectionState === "READY" ? "没有可用 canonical 证据" : "后端证据不可用"}</b><p>未替换为 fixture 或全局回退；发现范围保持 {graph.discoveryScope.completeness}。</p></div> : <div className="evidence-explorer-body">
      <section className="lineage-surface" aria-label={`精确证据关系${viewMode === "GRAPH" ? "图" : "列表"}`}>
        {viewMode === "GRAPH"
          ? <EvidenceGraphCanvas view={bounded} focusExactId={focusedNode?.exactId ?? null} onFocus={focusNode}/>
          : <EvidenceNodeList view={bounded} focusExactId={focusedNode?.exactId ?? null} onFocus={focusNode}/>}
      </section>
      <EvidenceNodeInspector node={focusedNode} graph={graph} onFocusId={(exactId) => setFocusExactId(exactId)} onOpenLab={onOpenLab}/>
    </div>}
  </div>;
}

const EvidenceGraphCanvas = memo(function EvidenceGraphCanvas({ view, focusExactId, onFocus }: { view: EvidenceGraphView; focusExactId: string | null; onFocus: (node: EvidenceNodeView) => void }) {
  const graphNodes = useMemo<Node[]>(() => view.nodes.map((node, index) => ({
    id: node.exactId,
    position: { x: (index % 3) * 218, y: Math.floor(index / 3) * 116 },
    data: { label: <div className="lineage-node-label"><small>{node.nodeType}</small><b>{node.displayLabel}</b><code>{compactId(node.exactId)}</code><span>{node.canonicalTruthState} · {node.canonicalAdmissionState}</span></div> },
    className: node.exactId === focusExactId ? "lineage-node focused" : "lineage-node",
    selectable: true,
    draggable: true,
    ariaLabel: `${node.nodeType}：${node.displayLabel}；${node.exactId}`
  })), [focusExactId, view.nodes]);
  const graphEdges = useMemo<Edge[]>(() => view.edges.map((edge) => ({
    id: edge.edgeId,
    source: edge.sourceExactId,
    target: edge.targetExactId,
    label: edge.relationType,
    type: "smoothstep",
    selectable: true,
    focusable: true,
    ariaLabel: `${edge.relationType}：${edge.sourceExactId} 到 ${edge.targetExactId}`
  })), [view.edges]);
  const byId = useMemo(() => new Map(view.nodes.map((node) => [node.exactId, node])), [view.nodes]);
  return <div className="lineage-flow" data-testid="evidence-graph" data-node-count={view.nodes.length} data-edge-count={view.edges.length}>
    <ReactFlow
      nodes={graphNodes}
      edges={graphEdges}
      onNodeClick={(_, node) => { const source = byId.get(node.id); if (source) onFocus(source); }}
      nodesConnectable={false}
      edgesReconnectable={false}
      deleteKeyCode={null}
      onlyRenderVisibleElements
      fitView
      fitViewOptions={{ padding: .18, maxZoom: 1.05 }}
      minZoom={.35}
      maxZoom={1.6}
      proOptions={{ hideAttribution: false }}
    >
      <Background gap={22} size={1} color="#263345"/>
      <MiniMap pannable zoomable nodeColor={(node) => node.id === focusExactId ? "#47BFEF" : "#34465D"}/>
      <Controls showInteractive={false}/>
    </ReactFlow>
  </div>;
});

function EvidenceNodeList({ view, focusExactId, onFocus }: { view: EvidenceGraphView; focusExactId: string | null; onFocus: (node: EvidenceNodeView) => void }) {
  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!(["ArrowDown", "ArrowUp", "Home", "End"] as string[]).includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? view.nodes.length - 1 : Math.max(0, Math.min(view.nodes.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
    const next = view.nodes[nextIndex];
    if (next) {
      onFocus(next);
      document.querySelector<HTMLButtonElement>(`[data-lineage-list-index="${nextIndex}"]`)?.focus();
    }
  };
  return <div className="lineage-list" role="list" data-testid="evidence-list" data-node-count={view.nodes.length}>
    {view.nodes.map((node, index) => <button key={node.exactId} role="listitem" data-lineage-list-index={index} className={node.exactId === focusExactId ? "active" : ""} onClick={() => onFocus(node)} onKeyDown={(event) => moveFocus(event, index)}>
      <span><small>{node.nodeType}</small><b>{node.displayLabel}</b><code>{node.exactId}</code></span>
      <em>{node.canonicalTruthState}<br/>{node.canonicalAdmissionState}<br/>{node.validationState}</em>
    </button>)}
  </div>;
}

function EvidenceNodeInspector({ node, graph, onFocusId, onOpenLab }: { node: EvidenceNodeView | null; graph: EvidenceGraphView; onFocusId: (exactId: string) => void; onOpenLab: (lab: LabId) => void }) {
  if (!node) return <aside className="lineage-detail"><p>没有已知关系 · NO_KNOWN_RELATION</p></aside>;
  const relations = exactRelationsForNode(graph, node.exactId);
  return <aside className="lineage-detail" aria-label="精确证据详情检查器" data-testid="lineage-detail-inspector">
    <header><small>{node.nodeType.toUpperCase()}</small><b>{node.displayLabel}</b><span>{relations.availability}</span></header>
    <section className="lineage-exact-identity exact-object-id"><label>精确 ID</label><code>{node.exactId}</code><CopyExactButton label="复制 ID" value={node.exactId}/><label>内容 SHA-256</label><code>{node.contentSha256}</code><CopyExactButton label="复制 hash" value={node.contentSha256}/></section>
    {node.nodeType === "Artifact" ? <>
      <section className="lineage-authority-section artifact-owned-status"><h3>产物自有状态</h3><div className="truth-admission-grid"><StateCell label="产物真值" value={node.canonicalTruthState}/><StateCell label="产物准入" value={node.canonicalAdmissionState}/><StateCell label="产物验证" value={node.validationState}/><StateCell label="完整性" value={node.integrityStatus}/></div></section>
      <section className="lineage-authority-section source-evidence-authority"><h3>来源证据权威</h3>{node.sourceEvidenceAuthorities.length === 0 ? <p>未知 / 未链接 · UNKNOWN / UNLINKED</p> : node.sourceEvidenceAuthorities.map((source) => <div key={source.sourceObjectId} className="source-evidence-status"><small>来源对象</small><code>{source.sourceObjectId}</code><StateCell label="来源真值" value={source.canonicalTruthState}/><StateCell label="来源准入" value={source.canonicalAdmissionState}/><StateCell label="来源验证" value={source.validationState}/></div>)}</section>
    </> : <div className="lineage-state-grid"><div className="truth-admission-grid"><StateCell label="真值" value={node.canonicalTruthState}/><StateCell label="准入" value={node.canonicalAdmissionState}/><StateCell label="验证" value={node.validationState}/></div><StateCell label="完整性" value={node.integrityStatus}/></div>}
    <RelationList title="派生自" edges={relations.derivedFrom} endpoint="source" onFocusId={onFocusId}/>
    <RelationList title="被使用于" edges={relations.usedBy} endpoint="target" onFocusId={onFocusId}/>
    <ReferenceList title="来源引用" values={node.provenanceRefs}/>
    <ReferenceList title="产物引用" values={node.artifactRefs}/>
    <ReferenceList title="显式会话链接" values={node.sessionLinks}/>
    <button className="open-in-lab" onClick={() => onOpenLab(node.openInLab)}>在{labLabel(node.openInLab)}实验室中打开</button>
    <section className="future-slots"><h3>Round 3 主合同连接</h3>{ROUND3_MAIN_CONTRACT_SLOTS.map((slot) => <div key={slot.object}><b>{slot.object}</b><span>{slot.status}</span><small>{slot.owner}</small></div>)}</section>
  </aside>;
}

function RelationList({ title, edges, endpoint, onFocusId }: { title: string; edges: EvidenceGraphView["edges"]; endpoint: "source" | "target"; onFocusId: (exactId: string) => void }) {
  return <section className="lineage-relation-list"><h3>{title}</h3>{edges.length === 0 ? <p>NO_KNOWN_RELATION · {"DISCOVERY_SCOPE_LIMITED"}</p> : edges.map((edge) => {
    const exactId = endpoint === "source" ? edge.sourceExactId : edge.targetExactId;
    return <button key={edge.edgeId} onClick={() => onFocusId(exactId)} title={exactId}><b>{edge.relationType}</b><code>{exactId}</code>{edge.bindingRef && <small>binding · {edge.bindingRef}</small>}</button>;
  })}</section>;
}

function ReferenceList({ title, values }: { title: string; values: readonly string[] }) {
  return <section className="lineage-reference-list"><h3>{title}</h3>{values.length === 0 ? <p>没有显式链接</p> : values.map((value) => <code key={value}>{value}</code>)}</section>;
}

function FilterSelect({ label, value, values, onChange }: { label: string; value: string; values: readonly string[]; onChange: (value: string) => void }) {
  return <label><span>{label}</span><select aria-label={`${label}筛选`} value={value} onChange={(event) => onChange(event.target.value)}>{values.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>;
}

function StateCell({ label, value }: { label: string; value: string }) {
  return <div><small>{label}</small><b>{value}</b></div>;
}

function CopyExactButton({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!navigator.clipboard || value === "UNKNOWN") return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return <button type="button" onClick={() => { void copy(); }} disabled={value === "UNKNOWN"}>{copied ? "已复制" : label}</button>;
}

function compactId(value: string) {
  return value.length > 28 ? `${value.slice(0, 14)}…${value.slice(-8)}` : value;
}

function labLabel(lab: LabId) {
  return lab === "research" ? "研究" : lab === "strategy" ? "策略" : lab === "model" ? "模型" : lab === "backtest" ? "回测" : "结果";
}
