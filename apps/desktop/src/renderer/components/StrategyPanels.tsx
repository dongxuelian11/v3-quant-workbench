import React, { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, Handle, Position, ReactFlow, useEdgesState, useNodesState, type NodeProps } from "@xyflow/react";
import * as monaco from "monaco-editor";
import { strategyProposal } from "../demo";
import { ensureV3MonacoTheme, V3_MONACO_SCROLLBAR_OPTIONS } from "../monacoPresentation";
import { useWorkbench } from "../store";
import { Icon, TruthMark } from "./PresentationSystem";

if (!monaco.languages.getLanguages().some((language) => language.id === "python")) {
  monaco.languages.register({ id: "python" });
  monaco.languages.setMonarchTokensProvider("python", { keywords: ["from", "import", "def", "return", "if", "else", "for", "in"], tokenizer: { root: [[/[a-zA-Z_]\w*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }], [/#.*$/, "comment"], [/\d+(\.\d+)?/, "number"], [/"[^\"]*"|'[^']*'/, "string"]] } });
}

ensureV3MonacoTheme();

const baseNodes = [
  { id: "universe", type: "strategy", position: { x: 30, y: 92 }, data: { kind: "UNIVERSE", label: "CN Large Cap @v12", detail: "1,842 symbols" } },
  { id: "factor-momentum", type: "strategy", position: { x: 270, y: 28 }, data: { kind: "FACTOR", label: "Momentum 12M", detail: "rank · winsorize" } },
  { id: "factor-quality", type: "strategy", position: { x: 270, y: 168 }, data: { kind: "FACTOR", label: "Quality Blend", detail: "threshold 0.35" } },
  { id: "combine", type: "strategy", position: { x: 520, y: 92 }, data: { kind: "COMBINE", label: "Weighted Signal", detail: "0.65 / 0.35" } },
  { id: "allocation", type: "strategy", position: { x: 770, y: 92 }, data: { kind: "ALLOCATION", label: "Equal Weight", detail: "Top 50 · Monthly" } }
];
const baseEdges = [{ id: "e1", source: "universe", target: "factor-momentum" }, { id: "e2", source: "universe", target: "factor-quality" }, { id: "e3", source: "factor-momentum", target: "combine" }, { id: "e4", source: "factor-quality", target: "combine" }, { id: "e5", source: "combine", target: "allocation" }];

function StrategyNode({ data, selected }: NodeProps) {
  const node = data as { kind: string; label: string; detail: string };
  return <div className={`strategy-node ${selected ? "selected" : ""}`}><Handle type="target" position={Position.Left}/><small>{node.kind}</small><b>{node.label}</b><span>{node.detail}</span><Handle type="source" position={Position.Right}/></div>;
}

function VisualEditor() {
  const [nodes, , onNodesChange] = useNodesState(baseNodes);
  const [edges, , onEdgesChange] = useEdgesState(baseEdges);
  const selectNode = useWorkbench((state) => state.selectNode);
  const nodeTypes = useMemo(() => ({ strategy: StrategyNode }), []);
  return <div className="flow-editor primary-canvas" data-testid="react-flow" data-primary-canvas><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={(_, node) => selectNode(node.id, `策略节点 · ${String((node.data as { label: string }).label)}`)} fitView fitViewOptions={{ padding: .12 }} snapToGrid snapGrid={[12, 12]} minZoom={.45} maxZoom={1.6}><Background gap={24} size={1} color="#202634"/><Controls/></ReactFlow></div>;
}

function MonacoCode({ diff = false }: { diff?: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const code = useWorkbench((state) => state.strategy.code);
  const setCode = useWorkbench((state) => state.setStrategyCode);
  useEffect(() => {
    if (!host.current) return;
    if (diff) {
      const editor = monaco.editor.createDiffEditor(host.current, { theme: "v3-quant", automaticLayout: true, readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12, lineHeight: 20, scrollbar: V3_MONACO_SCROLLBAR_OPTIONS });
      const original = monaco.editor.createModel(code, "python");
      const modified = monaco.editor.createModel(code.replace("0.65 + rank(quality) * 0.35", "0.55 + rank(quality) * 0.45").replace("top_n(signal, 50).equal_weight()", "top_n(signal, 40).risk_parity(max_weight=0.04)"), "python");
      editor.setModel({ original, modified });
      return () => { editor.dispose(); original.dispose(); modified.dispose(); };
    }
    const editor = monaco.editor.create(host.current, { value: code, language: "python", theme: "v3-quant", automaticLayout: true, minimap: { enabled: false }, fontSize: 13, lineHeight: 22, lineNumbersMinChars: 3, padding: { top: 16, bottom: 16 }, smoothScrolling: false, scrollbar: V3_MONACO_SCROLLBAR_OPTIONS });
    const disposable = editor.onDidBlurEditorText(() => setCode(editor.getValue()));
    return () => { disposable.dispose(); editor.dispose(); };
  }, [diff, code, setCode]);
  return <div ref={host} className={`${diff ? "monaco-diff" : "monaco-code"} primary-canvas`} data-testid={diff ? "monaco-diff" : "monaco-editor"} data-primary-canvas />;
}

export function StrategyDraftPanel() {
  const mode = useWorkbench((state) => state.strategy.mode);
  const setMode = useWorkbench((state) => state.setStrategyMode);
  const strategy = useWorkbench((state) => state.strategy);
  const validate = useWorkbench((state) => state.validateStrategy);
  const handoff = useWorkbench((state) => state.createHandoff);
  const [reviewMode, setReviewMode] = useState(false);

  const chooseMode = (next: typeof mode) => { setReviewMode(false); setMode(next); };
  return <section className="panel-page strategy-workspace" data-primary-panel="strategy-editor" data-major-panel>
    <header className="editor-context">
      <div className="editor-identity"><small>STRATEGYDRAFT / DEMO-V{strategy.version}</small><h1>{reviewMode ? "提案差异审阅" : mode === "visual" ? "可视化策略图" : mode === "code" ? "策略代码" : "图与代码联动"}</h1><span>Momentum 12M · CN Large Cap @v12</span></div>
      <div className="mode-tabs" role="tablist" aria-label="策略编辑工作模式">{(["visual", "code", "split"] as const).map((item) => <button role="tab" aria-selected={!reviewMode && mode === item} aria-controls="strategy-active-canvas" data-strategy-mode={item} className={!reviewMode && mode === item ? "active" : ""} onClick={() => chooseMode(item)} key={item}>{item === "visual" ? "Visual" : item === "code" ? "Code" : "Split"}</button>)}</div>
      <div className="editor-actions"><button className="review-trigger" data-strategy-mode="diff" aria-pressed={reviewMode} onClick={() => setReviewMode(true)}><Icon name="focus" size={14}/>Diff</button><button onClick={validate}>验证</button><button className={strategy.validation === "valid" ? "primary" : ""} onClick={handoff} disabled={strategy.validation !== "valid"} title={strategy.validation === "valid" ? "生成 BacktestHandoffDraft" : "请先验证草案"}>生成 Handoff</button></div>
    </header>
    <div className="editor-subline"><TruthMark detail="Proposal guarded"/><span role="status" aria-live="polite">Validation <b className={strategy.validation === "valid" ? "ok" : strategy.validation === "invalid" ? "error" : "muted"}>{strategy.validation}</b></span><span>Draft v{strategy.version}</span><span>{strategy.handoffId ?? (strategy.validation === "valid" ? "可生成 BacktestHandoffDraft" : "验证后可生成 Handoff")}</span></div>
    {reviewMode ? <StrategyReviewPanel /> : <div id="strategy-active-canvas" role="tabpanel" className={`strategy-canvas ${mode}`}>{mode !== "code" && <VisualEditor/>}{mode !== "visual" && <MonacoCode/>}</div>}
    {!reviewMode && <footer className="strategy-status"><span><i/>Selected node <b>{strategy.selectedNodeId ?? "none"}</b></span><span>Draft v{strategy.version}</span><span>Autosaved locally</span></footer>}
  </section>;
}

export function StrategyReviewPanel() {
  const strategy = useWorkbench((state) => state.strategy);
  const review = useWorkbench((state) => state.reviewHunk);
  return <div className="review-workspace" data-testid="strategy-diff-review" data-major-panel>
    <div className="review-summary"><div><small>DETERMINISTIC PROPOSAL</small><b>proposal/demo-risk-parity-v2</b></div><span>2 hunks · {strategy.acceptedHunks.length} accepted · {strategy.rejectedHunks.length} rejected</span><TruthMark detail="Proposal fixture"/></div>
    <MonacoCode diff />
    <div className="hunks"><Hunk id="weights" title="HUNK 1 · 调整因子权重" accepted={strategy.acceptedHunks.includes("weights")} rejected={strategy.rejectedHunks.includes("weights")} on={review}/><Hunk id="allocation" title="HUNK 2 · 风险平价分配" accepted={strategy.acceptedHunks.includes("allocation")} rejected={strategy.rejectedHunks.includes("allocation")} on={review}/></div>
    <details className="proposal-contract"><summary>查看 Proposal contract</summary><pre>{strategyProposal}</pre></details>
  </div>;
}

function Hunk({ id, title, accepted, rejected, on }: { id: string; title: string; accepted: boolean; rejected: boolean; on: (id: string, decision: "accept" | "reject") => void }) {
  return <div data-hunk={id}><div><b>{title}</b><span>{accepted ? "ACCEPTED" : rejected ? "REJECTED" : "PENDING"}</span></div><button className={accepted ? "active" : ""} onClick={() => on(id, "accept")}>接受</button><button className={rejected ? "danger" : ""} onClick={() => on(id, "reject")}>拒绝</button></div>;
}
