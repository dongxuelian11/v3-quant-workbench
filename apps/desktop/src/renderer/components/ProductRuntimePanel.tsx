import React, { useEffect, useState } from "react";
import { capabilityTruth, describeError, useProductRuntime, type ProductSurfaceState } from "../productRuntimeStore";

/**
 * LIVE B3 product runtime surface. Every state shown here is capability-driven
 * canonical truth read through the typed product bridge — no fixture numbers,
 * no demo charts, no async-worker overclaim. submitBacktest remains a bounded
 * synchronous in-process executor: REQUEST_IN_FLIGHT is transport state only.
 */

const SURFACE_COPY: Record<ProductSurfaceState, string> = {
  BACKEND_STARTING: "后端启动中 · BACKEND_STARTING",
  BACKEND_READY: "后端就绪 · BACKEND_READY",
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
  const runSpecId = useProductRuntime((state) => state.runSpecId);
  const inflight = useProductRuntime((state) => state.inflight);
  const task = useProductRuntime((state) => state.task);
  const result = useProductRuntime((state) => state.result);
  const artifactDescriptor = useProductRuntime((state) => state.artifactDescriptor);
  const errorMessage = useProductRuntime((state) => state.errorMessage);
  const refresh = useProductRuntime((state) => state.refresh);
  const setRunSpecId = useProductRuntime((state) => state.setRunSpecId);
  const submitRunSpec = useProductRuntime((state) => state.submitRunSpec);
  const [projectIdInput, setProjectIdInput] = useState("");
  const [revisionInput, setRevisionInput] = useState("");

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { void useProductRuntime.getState().refresh(); }, 4000);
    return () => clearInterval(timer);
  }, [refresh]);

  const backendReady = status?.backendState === "READY";
  const bound = boundProject !== null;
  const canSubmit = backendReady && bound && /^btrs_sha256_[0-9a-f]{64}$/.test(runSpecId.trim()) && !inflight;

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
        <button onClick={() => void refresh()} disabled={!status}>刷新状态</button>
      </div>
    </header>
    <div className="analysis-contextline">
      <CapabilityBadge label="项目会话" code="ProjectSessionService"/>
      <CapabilityBadge label="回测" code="BacktestService"/>
      <CapabilityBadge label="Artifact" code="ArtifactService"/>
      <CapabilityBadge label="任务" code="TaskService"/>
      <CapabilityBadge label="结果" code="ResultService"/>
    </div>

    {!bound && backendReady && <div className="product-connect" data-testid="product-connect">
      <div className="section-head"><div><small>绑定已存在的 canonical 项目</small><h2>项目创建入口尚未产品化 · PROJECT_AUTHORING = NOT_AVAILABLE</h2></div></div>
      <p className="honest-note">当前 frozen ASL 不提供 createProject / importProject。只能绑定产品存储中已存在的 canonical 项目；无效引用不会被持久化。</p>
      <label>Project ID<input value={projectIdInput} onChange={(event) => setProjectIdInput(event.target.value)} placeholder="prj_…" aria-label="canonical project id"/></label>
      <label>Context Revision ID<input value={revisionInput} onChange={(event) => setRevisionInput(event.target.value)} placeholder="pcr_…" aria-label="canonical project context revision id"/></label>
      <button className="primary" disabled={!projectIdInput.trim() || !revisionInput.trim()} onClick={() => void useProductRuntime.getState().connect(projectIdInput.trim(), revisionInput.trim())}>验证并绑定</button>
    </div>}

    {bound && <div className="product-run" data-testid="product-run">
      <div className="section-head"><div><small>既有 canonical RunSpec 执行</small><h2>RunSpec 创作入口尚未产品化 · RUN_SPEC_AUTHORING = NOT_AVAILABLE</h2></div></div>
      <p className="honest-note">仅接受已存在的 canonical run_spec_id（btrs_sha256_…）；不接受任何数值观测/收益/权重输入。当前执行为受限同步进程内执行：无并发 worker、不可实时取消、无断点续跑。</p>
      <label>Canonical Run Spec ID<input value={runSpecId} onChange={(event) => setRunSpecId(event.target.value)} placeholder="btrs_sha256_…" aria-label="canonical run spec id" disabled={inflight}/></label>
      <button className="primary" disabled={!canSubmit} onClick={() => void submitRunSpec()} data-action="submit-existing-runspec">
        {inflight ? "请求执行中 · REQUEST_IN_FLIGHT" : "执行既有 RunSpec"}
      </button>
      {task && <dl className="product-readout" data-testid="product-task-readout">
        <dt>Task</dt><dd>{task.taskId} · {task.state} · v{task.stateVersion}</dd>
        <dt>Run</dt><dd>{task.runId}</dd>
        <dt>结果 Artifact</dt><dd>{task.outputs["BACKTEST_RUN_RESULT"] ?? "无"}</dd>
        {result && <><dt>Result</dt><dd>{result.resultId} · {result.state}</dd></>}
        {artifactDescriptor && <><dt>SHA-256</dt><dd>{artifactDescriptor.sha256}</dd><dt>字节数</dt><dd>{artifactDescriptor.byteSize}</dd></>}
      </dl>}
    </div>}

    {surface === "BACKEND_DISCONNECTED" && <p className="honest-note">后端未连接：请确认 canonical backend（v3_backend.runtime.bootstrap）可启动。</p>}
    {errorMessage && <p className="honest-note error" role="alert">{errorMessage}</p>}
  </section>;
}
