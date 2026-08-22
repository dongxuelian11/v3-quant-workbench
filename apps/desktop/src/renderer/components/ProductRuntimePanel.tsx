import React, { useEffect, useState } from "react";
import { capabilityTruth, describeError, useProductRuntime, type ProductSurfaceState } from "../productRuntimeStore";
import type { ProductResearchSubmitIntent } from "../../../../../packages/contracts/src/index";

/**
 * LIVE B3 product runtime surface. Every state shown here is capability-driven
 * canonical truth read through the typed product bridge — no fixture numbers,
 * no demo charts, no async-worker overclaim. submitBacktest remains a bounded
 * synchronous in-process executor: REQUEST_IN_FLIGHT is transport state only.
 */

const SURFACE_COPY: Record<ProductSurfaceState, string> = {
  BACKEND_STARTING: "后端启动中 · BACKEND_STARTING",
  BACKEND_READY: "后端就绪 · BACKEND_READY",
  BACKEND_RECONNECTING: "后端重连中 · BACKEND_RECONNECTING",
  BACKEND_DISCONNECTED: "后端未连接 · BACKEND_DISCONNECTED",
  NO_CANONICAL_PROJECT_BOUND: "尚未绑定 canonical 项目 · NO_CANONICAL_PROJECT_BOUND",
  PROJECT_BOUND: "已绑定 canonical 项目 · PROJECT_BOUND",
  CANONICAL_RUN_SPEC_REQUIRED: "需要 canonical 运行规格 · CANONICAL_RUN_SPEC_REQUIRED",
  REQUEST_IN_FLIGHT: "请求执行中 · REQUEST_IN_FLIGHT（不可取消 / 无实时进度 / 不可续跑）",
  TASK_AVAILABLE: "Canonical 任务已读取 · TASK_AVAILABLE",
  RESULT_AVAILABLE: "Canonical 结果已读取 · RESULT_AVAILABLE",
  CAPABILITY_UNAVAILABLE: "能力不可用 · CAPABILITY_UNAVAILABLE",
  PRODUCT_OPERATION_SET_INCOMPLETE: "产品操作集不完整 · PRODUCT_OPERATION_SET_INCOMPLETE",
  ERROR: "产品运行时错误 · ERROR"
};

function CapabilityBadge({ label, code }: { label: string; code: string }) {
  const capabilities = useProductRuntime((state) => state.capabilities);
  const truth = capabilityTruth(capabilities, code);
  const tone = truth.truth_state === "FORMAL" ? "ok" : truth.truth_state === "DEMO" ? "warn" : "unavailable";
  const reason = truth.reason_code ? ` · ${truth.reason_code}` : "";
  return <span className={`connection-badge ${tone}`} title={`${code} · ${truth.truth_state}${reason}`}>{label} · {truth.truth_state}{reason}</span>;
}

export function ProductRuntimePanel() {
  const surface = useProductRuntime((state) => state.surface);
  const status = useProductRuntime((state) => state.status);
  const boundProject = useProductRuntime((state) => state.boundProject);
  const projects = useProductRuntime((state) => state.projects);
  const runSpecs = useProductRuntime((state) => state.runSpecs);
  const entryBusy = useProductRuntime((state) => state.entryBusy);
  const lastImport = useProductRuntime((state) => state.lastImport);
  const lastResearch = useProductRuntime((state) => state.lastResearch);
  const researchDiscoveryState = useProductRuntime((state) => state.researchDiscoveryState);
  const recoveredResearchTaskId = useProductRuntime((state) => state.recoveredResearchTaskId);
  const runSpecId = useProductRuntime((state) => state.runSpecId);
  const inflight = useProductRuntime((state) => state.inflight);
  const task = useProductRuntime((state) => state.task);
  const result = useProductRuntime((state) => state.result);
  const artifactDescriptor = useProductRuntime((state) => state.artifactDescriptor);
  const errorMessage = useProductRuntime((state) => state.errorMessage);
  const refresh = useProductRuntime((state) => state.refresh);
  const setRunSpecId = useProductRuntime((state) => state.setRunSpecId);
  const submitRunSpec = useProductRuntime((state) => state.submitRunSpec);
  const createProjectAndBind = useProductRuntime((state) => state.createProjectAndBind);
  const importResearchPackage = useProductRuntime((state) => state.importResearchPackage);
  const submitResearch = useProductRuntime((state) => state.submitResearch);
  const [projectIdInput, setProjectIdInput] = useState("");
  const [revisionInput, setRevisionInput] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectNotes, setNewProjectNotes] = useState("");
  const [researchSymbol, setResearchSymbol] = useState("000001");
  const [researchStartDate, setResearchStartDate] = useState("20260106");
  const [researchEndDate, setResearchEndDate] = useState("20260107");

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void useProductRuntime.getState().refresh(); }, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  const backendReady = status?.backendState === "READY";
  const bound = boundProject !== null;
  const selectedEntry = runSpecs?.specs.find((item) => item.runSpecId === runSpecId.trim()) ?? null;
  const selectedExecutable = selectedEntry?.status === "EXECUTABLE";
  const canSubmit = backendReady && bound && selectedExecutable && !inflight;

  return <section className="panel-page product-runtime-panel" data-testid="product-runtime-panel" data-product-surface={surface}>
    <header className="analysis-header">
      <div className="analysis-title">
        <small>正式产品运行时 · B3 LIVE</small>
        <h1>Canonical 产品连接</h1>
        <p><span role="status" aria-live="polite" data-product-state={surface}>{SURFACE_COPY[surface]}</span></p>
      </div>
      <div className="experiment-trail">
        <span><small>后端</small>{status?.backendState ?? "UNKNOWN"}</span>
        <span><small>绑定</small>{bound ? boundProject.projectId : "未绑定"}</span>
        <span><small>Build</small>{status?.buildManifestId ?? "UNAVAILABLE"}</span>
        <button onClick={() => void refresh()} disabled={!status}>刷新状态</button>
      </div>
    </header>
    <div className="analysis-contextline">
      <CapabilityBadge label="项目会话" code="ProjectSessionService"/>
      <CapabilityBadge label="回测" code="BacktestService"/>
      <CapabilityBadge label="Artifact" code="ArtifactService"/>
      <CapabilityBadge label="Product Entry" code="ProductEntryService"/>
      <CapabilityBadge label="任务" code="TaskService"/>
      <CapabilityBadge label="结果" code="ResultService"/>
    </div>

    {!bound && backendReady && <div className="product-connect" data-testid="product-connect">
      <div className="section-head"><div><small>Clean-start 研究入口</small><h2>创建研究项目</h2></div></div>
      <p className="honest-note">canonical 项目 ID 与首个 ProjectContext 修订全部由后端铸造；本界面只提交有界的研究意图（名称/备注），不接受任何数值金融真值。</p>
      <label>项目名称<input value={newProjectName} onChange={(event) => setNewProjectName(event.target.value)} placeholder="例如：A 股动量研究" aria-label="新项目名称" disabled={entryBusy}/></label>
      <label>备注（可选）<input value={newProjectNotes} onChange={(event) => setNewProjectNotes(event.target.value)} placeholder="非金融元数据 · context_fields.notes" aria-label="新项目备注" disabled={entryBusy}/></label>
      <button className="primary" data-action="create-project" disabled={entryBusy || newProjectName.trim().length < 1} onClick={() => void createProjectAndBind(newProjectName.trim(), newProjectNotes.trim() === "" ? undefined : newProjectNotes.trim())}>
        {entryBusy ? "创建中…" : "创建研究项目"}
      </button>

      {(projects?.projects.length ?? 0) > 0 && <div className="section-head" style={{marginTop: 16}}><div><small>产品存储中的 canonical 项目</small><h2>绑定已有项目</h2></div></div>}
      {projects?.projects.map((item) => <div key={item.projectId} className="honest-note" style={{display: "flex", alignItems: "center", gap: 8}}>
        <span style={{flex: 1}} title={item.projectId}>{item.displayName} · {item.projectId.slice(0, 12)}…</span>
        <button disabled={entryBusy} onClick={() => void useProductRuntime.getState().connect(item.projectId, item.projectContextRevisionId)}>验证并绑定</button>
      </div>)}

      <details style={{marginTop: 12}}>
        <summary className="honest-note">高级：按 canonical ID 绑定</summary>
        <label>Project ID<input value={projectIdInput} onChange={(event) => setProjectIdInput(event.target.value)} placeholder="prj_…" aria-label="canonical project id"/></label>
        <label>Context Revision ID<input value={revisionInput} onChange={(event) => setRevisionInput(event.target.value)} placeholder="pcr_…" aria-label="canonical project context revision id"/></label>
        <button disabled={!projectIdInput.trim() || !revisionInput.trim()} onClick={() => void useProductRuntime.getState().connect(projectIdInput.trim(), revisionInput.trim())}>验证并绑定</button>
      </details>
    </div>}

    {bound && <div className="product-run" data-testid="product-run">
      <div className="section-head"><div><small>Product Entry · PRE_ALPHA / RESEARCH_ONLY</small><h2>从 canonical source 发起研究</h2></div></div>
      <p className="honest-note">这里只提交标的与日期意图。Provider、ConnectorVersion、原始字节、观察值与数值真值由 backend 解析并校验；当前结果明确标记为 PRODUCT_CONNECTED_CANDIDATE，不是 Formal Market State。</p>
      <div className="product-research-entry" data-testid="product-research-entry">
        <label>标的代码<input value={researchSymbol} onChange={(event) => setResearchSymbol(event.target.value)} inputMode="numeric" aria-label="研究标的代码" disabled={inflight || entryBusy}/></label>
        <label>开始日期<input value={researchStartDate} onChange={(event) => setResearchStartDate(event.target.value)} inputMode="numeric" aria-label="研究开始日期" disabled={inflight || entryBusy}/></label>
        <label>结束日期<input value={researchEndDate} onChange={(event) => setResearchEndDate(event.target.value)} inputMode="numeric" aria-label="研究结束日期" disabled={inflight || entryBusy}/></label>
        <button className="primary" data-action="submit-product-research" disabled={inflight || entryBusy || !/^[0-9]{6}$/.test(researchSymbol) || !/^[0-9]{8}$/.test(researchStartDate) || !/^[0-9]{8}$/.test(researchEndDate)} onClick={() => {
          const intent: ProductResearchSubmitIntent = { symbol: researchSymbol, startDate: researchStartDate, endDate: researchEndDate };
          void submitResearch(intent);
        }}>{inflight ? "研究请求中…" : "提交 Product Entry 研究"}</button>
      </div>
      {lastResearch && <p className="honest-note" data-testid="product-research-admission">已接受：{lastResearch.taskId} · {lastResearch.maturity} · {lastResearch.researchClassification.join(" / ")} · {lastResearch.truthAdmission.admission}</p>}
      {researchDiscoveryState === "RECOVERED" && recoveredResearchTaskId && <p className="honest-note" data-testid="product-research-recovered">已从 canonical TaskService 历史自动恢复：{recoveredResearchTaskId} · Result/Artifact 已重新读取</p>}

      <div className="section-head"><div><small>可执行 canonical 研究配置</small><h2>研究配置</h2></div></div>
      {runSpecs === null && <p className="honest-note">正在从 canonical 项目引用读取可运行研究配置…</p>}
      {runSpecs?.specs.length === 0 && <div data-testid="empty-run-specs">
        <p className="honest-note">尚无可执行 canonical RunSpec · RunSpec 执行路径仍需目标端已有 Source Authority；上方 Product Entry 研究入口是独立的 PRE_ALPHA research-only 路径。</p>
        <button data-action="import-research-package" disabled={entryBusy} onClick={() => void importResearchPackage()}>
          {entryBusy ? "验证绑定中…" : "绑定已验证研究包"}
        </button>
        <p className="honest-note">仅可使用本机已存在 canonical 来源权威的研究包；内容完整性不能替代来源权威。逐字节校验失败或来源权威缺失时不会注册。</p>
      </div>}
      {runSpecs !== null && runSpecs.specs.length > 0 && <ul style={{listStyle: "none", padding: 0}} data-testid="runspec-list">
        {runSpecs.specs.map((entry) => <li key={entry.artifactId} style={{display: "flex", alignItems: "center", gap: 8, padding: "4px 0"}}>
          <input type="radio" name="runspec" disabled={entry.status !== "EXECUTABLE"} checked={entry.status === "EXECUTABLE" && runSpecId.trim() === entry.runSpecId} onChange={() => { if (entry.runSpecId !== null) setRunSpecId(entry.runSpecId); }} aria-label={entry.status === "EXECUTABLE" ? `选择 ${entry.runSpecId}` : `不可选择 ${entry.artifactId}`}/>
          <span style={{flex: 1}} title={`${entry.runSpecId ?? "identity unavailable"} · ${entry.contentSha256 ?? "hash unavailable"}`}>
            {entry.runSpecId === null ? `${entry.artifactId.slice(0, 22)}…` : `${entry.runSpecId.slice(0, 22)}…`} · {entry.engineVersion ?? "metadata unavailable"}
          </span>
          <span className={`connection-badge ${entry.status === "EXECUTABLE" ? "ok" : "unavailable"}`}>
            {entry.status === "EXECUTABLE" ? "EXECUTABLE" : `UNAVAILABLE · ${entry.diagnostic ?? ""}`}
          </span>
          {entry.status !== "EXECUTABLE" && <button disabled={entryBusy} onClick={() => void importResearchPackage()}>绑定已验证研究包</button>}
        </li>)}
        <li><button data-action="import-research-package" disabled={entryBusy} onClick={() => void importResearchPackage()}>{entryBusy ? "验证绑定中…" : "绑定已验证研究包"}</button>
        <span className="honest-note"> 仅复用目标端已存在并可验证的 canonical 来源权威</span></li>
      </ul>}
      {lastImport && <p className="honest-note">最近导入：{lastImport.runSpecId.slice(0, 22)}… {lastImport.alreadyImported ? "（幂等重放）" : ""}</p>}
      <button className="primary" disabled={!canSubmit} onClick={() => void submitRunSpec()} data-action="submit-existing-runspec">
        {inflight ? "请求执行中 · REQUEST_IN_FLIGHT" : "执行既有 RunSpec"}
      </button>
      {!selectedExecutable && runSpecs !== null && runSpecs.specs.length > 0 && <p className="honest-note">提交需要先选择一个 EXECUTABLE 的 canonical RunSpec（经实际字节校验）。</p>}
      {task && <dl className="product-readout" data-testid="product-task-readout">
        <dt>Task</dt><dd>{task.taskId} · {task.state} · v{task.stateVersion}</dd>
        <dt>Run</dt><dd>{task.runId}</dd>
        <dt>结果 Artifact</dt><dd>{task.outputs["BACKTEST_RUN_RESULT"] ?? "无"}</dd>
        {result && <><dt>Result</dt><dd>{result.resultId} · {result.state}</dd></>}
        {artifactDescriptor && <><dt>SHA-256</dt><dd>{artifactDescriptor.sha256}</dd><dt>字节数</dt><dd>{artifactDescriptor.byteSize}</dd></>}
      </dl>}
    </div>}

    {surface === "BACKEND_DISCONNECTED" && <p className="honest-note">后端未连接：请确认 canonical backend（v3_backend.runtime.bootstrap）可启动。</p>}
    {surface === "BACKEND_RECONNECTING" && <p className="honest-note">后端连接已断开，正在进行有界重连；不会自动重放未知结果的非幂等操作。</p>}
    {errorMessage && <p className="honest-note error" role="alert">{errorMessage}</p>}
  </section>;
}
