import React, { useEffect, useMemo, useRef } from "react";
import { Background, Controls, Handle, Position, ReactFlow, useEdgesState, useNodesState, type NodeProps } from "@xyflow/react";
import * as monaco from "monaco-editor";
import { strategyProposal } from "../demo";
import { useWorkbench } from "../store";

monaco.languages.register({ id: "python" });
monaco.languages.setMonarchTokensProvider("python", { keywords: ["from", "import", "def", "return", "if", "else", "for", "in"], tokenizer: { root: [[/[a-zA-Z_]\w*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }], [/#.*$/, "comment"], [/\d+(\.\d+)?/, "number"], [/"[^\"]*"|'[^']*'/, "string"]] } });

const baseNodes = [
  { id: "universe", type: "strategy", position: { x: 30, y: 86 }, data: { kind: "UNIVERSE", label: "CN Large Cap @v12", detail: "1,842 symbols" } },
  { id: "factor-momentum", type: "strategy", position: { x: 270, y: 28 }, data: { kind: "FACTOR", label: "Momentum 12M", detail: "rank · winsorize" } },
  { id: "factor-quality", type: "strategy", position: { x: 270, y: 154 }, data: { kind: "FACTOR", label: "Quality Blend", detail: "threshold 0.35" } },
  { id: "combine", type: "strategy", position: { x: 510, y: 86 }, data: { kind: "COMBINE", label: "Weighted Signal", detail: "0.65 / 0.35" } },
  { id: "allocation", type: "strategy", position: { x: 750, y: 86 }, data: { kind: "ALLOCATION", label: "Equal Weight", detail: "Top 50 · Monthly" } }
];
const baseEdges = [{ id: "e1", source: "universe", target: "factor-momentum" }, { id: "e2", source: "universe", target: "factor-quality" }, { id: "e3", source: "factor-momentum", target: "combine" }, { id: "e4", source: "factor-quality", target: "combine" }, { id: "e5", source: "combine", target: "allocation" }];

function StrategyNode({ data, selected }: NodeProps) {
  const d = data as { kind: string; label: string; detail: string };
  return <div className={`strategy-node ${selected ? "selected" : ""}`}><Handle type="target" position={Position.Left}/><small>{d.kind}</small><b>{d.label}</b><span>{d.detail}</span><Handle type="source" position={Position.Right}/></div>;
}

function VisualEditor() {
  const [nodes, , onNodesChange] = useNodesState(baseNodes); const [edges, , onEdgesChange] = useEdgesState(baseEdges); const selectNode = useWorkbench((s) => s.selectNode);
  const nodeTypes = useMemo(() => ({ strategy: StrategyNode }), []);
  return <div className="flow-editor" data-testid="react-flow"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onNodeClick={(_, node) => selectNode(node.id, `策略节点 · ${String((node.data as {label:string}).label)}`)} fitView snapToGrid snapGrid={[12, 12]}><Background gap={18}/><Controls/></ReactFlow></div>;
}

function MonacoCode({ diff = false }: { diff?: boolean }) {
  const host = useRef<HTMLDivElement>(null); const code = useWorkbench((s) => s.strategy.code); const setCode = useWorkbench((s) => s.setStrategyCode);
  useEffect(() => {
    if (!host.current) return;
    if (diff) {
      const editor = monaco.editor.createDiffEditor(host.current, { theme: "vs-dark", automaticLayout: true, readOnly: true, renderSideBySide: true, minimap: { enabled: false }, fontSize: 12 });
      const original = monaco.editor.createModel(code, "python"); const modified = monaco.editor.createModel(code.replace("0.65 + rank(quality) * 0.35", "0.55 + rank(quality) * 0.45").replace("top_n(signal, 50).equal_weight()", "top_n(signal, 40).risk_parity(max_weight=0.04)"), "python"); editor.setModel({ original, modified });
      return () => { editor.dispose(); original.dispose(); modified.dispose(); };
    }
    const editor = monaco.editor.create(host.current, { value: code, language: "python", theme: "vs-dark", automaticLayout: true, minimap: { enabled: false }, fontSize: 13, lineNumbersMinChars: 3 });
    const d = editor.onDidBlurEditorText(() => setCode(editor.getValue())); return () => { d.dispose(); editor.dispose(); };
  }, [diff]);
  return <div ref={host} className={diff ? "monaco-diff" : "monaco-code"} data-testid={diff ? "monaco-diff" : "monaco-editor"}/>;
}

export function StrategyDraftPanel() {
  const mode = useWorkbench((s) => s.strategy.mode); const setMode = useWorkbench((s) => s.setStrategyMode); const strategy = useWorkbench((s) => s.strategy); const validate = useWorkbench((s) => s.validateStrategy); const handoff = useWorkbench((s) => s.createHandoff);
  return <section className="panel-page strategy-page"><div className="strategy-toolbar"><div className="mode-tabs">{(["visual", "code", "split"] as const).map((x) => <button data-strategy-mode={x} className={mode === x ? "active" : ""} onClick={() => setMode(x)} key={x}>{x === "visual" ? "Visual" : x === "code" ? "Code" : "Split"}</button>)}</div><span>StrategyDraft/demo-v{strategy.version} · 已持久化</span><button onClick={validate}>✓ 验证</button><button className="primary" onClick={handoff}>生成 BacktestHandoffDraft</button></div><div className={`strategy-canvas ${mode}`}>{mode !== "code" && <VisualEditor/>}{mode !== "visual" && <MonacoCode/>}</div><div className="strategy-status"><span className={strategy.validation === "valid" ? "ok" : strategy.validation === "invalid" ? "warn" : ""}>Validation: {strategy.validation}</span><span>Selected node: {strategy.selectedNodeId ?? "none"}</span><span>{strategy.handoffId ?? "尚未生成 handoff"}</span><span className="truth-chip">DEMO / NOT FORMAL FINANCIAL OUTPUT</span></div></section>;
}

export function StrategyReviewPanel() {
  const strategy = useWorkbench((s) => s.strategy); const review = useWorkbench((s) => s.reviewHunk);
  return <section className="panel-page review-page"><div className="section-head"><div><small>DETERMINISTIC PROPOSAL REVIEW</small><h2>Monaco Diff Editor</h2></div><span className="truth-chip">DEMO PROPOSAL</span></div><MonacoCode diff/><div className="hunks"><Hunk id="weights" title="HUNK 1 · 调整因子权重" accepted={strategy.acceptedHunks.includes("weights")} rejected={strategy.rejectedHunks.includes("weights")} on={review}/><Hunk id="allocation" title="HUNK 2 · 风险平价分配" accepted={strategy.acceptedHunks.includes("allocation")} rejected={strategy.rejectedHunks.includes("allocation")} on={review}/></div><details><summary>Proposal contract</summary><pre>{strategyProposal}</pre></details></section>;
}

function Hunk({ id, title, accepted, rejected, on }: { id: string; title: string; accepted: boolean; rejected: boolean; on: (id: string, decision: "accept"|"reject") => void }) {
  return <div data-hunk={id}><b>{title}</b><span>{accepted ? "ACCEPTED" : rejected ? "REJECTED" : "PENDING"}</span><button className={accepted ? "active" : ""} onClick={() => on(id, "accept")}>接受</button><button className={rejected ? "danger" : ""} onClick={() => on(id, "reject")}>拒绝</button></div>;
}
