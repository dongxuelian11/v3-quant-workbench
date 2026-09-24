import React, { useEffect, useRef, useState } from "react";
import type {
  DataImportFileOptions,
  DataImportOptions,
  DataImportPreview,
  DataImportPreviewFile,
  DataImportPriceBasis,
  DataImportResult,
  DataImportUnits,
  ExperimentDetails,
  JobEvent,
  JsonObject
} from "../../../../../packages/contracts/src/research";
import { errorText, request, useResearch } from "./state";
import "./dataImport.css";

type DataImportPanelProps = {
  projectId: string | null;
  strategyId?: string;
  dataset?: string;
  kind?: string;
  className?: string;
  disabled?: boolean;
};

type ImportTask = { job: JobEvent; options: DataImportOptions };
type ImportPolicy = NonNullable<DataImportOptions["conflictPolicy"]>;

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "处理中",
  completed: "任务结束",
  failed: "任务失败",
  cancelled: "已取消",
  interrupted: "已中断"
};
const resultStatusLabels: Record<DataImportResult["status"], string> = {
  completed: "全部完成",
  partial: "部分完成",
  failed: "全部失败"
};
const datasetChoices = [
  ["auto", "自动识别"],
  ["prices", "日线行情"],
  ["financials", "财务"],
  ["membership", "股票池成员版本"],
  ["corporate_actions", "分红送转"],
  ["benchmark_weights", "基准权重"],
  ["fund_flow", "资金流"],
  ["chips", "筹码"],
  ["lhb", "龙虎榜"],
  ["industry", "行业"]
] as const;
const policyLabels: Record<ImportPolicy, string> = {
  fill_missing: "默认补缺（保留已有非空值）",
  replace: "替换冲突值"
};
const volumeUnitChoices = [
  ["unknown", "未知（不换算）"],
  ["shares", "股"],
  ["lots", "手"]
] as const;
const amountUnitChoices = [
  ["unknown", "未知（不换算）"],
  ["CNY", "元"],
  ["ten_thousand_CNY", "万元"]
] as const;
const priceBasisChoices: { value: DataImportPriceBasis; label: string }[] = [
  { value: "unknown", label: "未知（不自动复权）" },
  { value: "unadjusted", label: "未复权" },
  { value: "forward_adjusted", label: "前复权" },
  { value: "backward_adjusted", label: "后复权" }
];

function displayName(path: string) { return path.split(/[\\/]/).pop() || path; }
function formatCount(value: number | undefined) { return value ?? "未提供"; }
function importMessage(message: string) {
  return /^(Unknown datetime string format|time data .*doesn.t match format|Out of bounds nanosecond timestamp)/i.test(message)
    ? "日期格式无法识别或超出范围，请修正日期列后重试。" : message;
}
function unitLabel(value: string | undefined) {
  const labels: Record<string, string> = { unknown: "未知", shares: "股", lots: "手", CNY: "元", ten_thousand_CNY: "万元" };
  return value ? labels[value] ?? value : "未提供";
}
function resultFromDetails(details: ExperimentDetails | null): DataImportResult | null {
  const value = details?.details as JsonObject | undefined;
  if (!value || typeof value.status !== "string" || !Array.isArray(value.imports) || !Array.isArray(value.failedFiles)) return null;
  return value as unknown as DataImportResult;
}
function supportsPolicy(file: DataImportPreviewFile, policy: ImportPolicy) {
  if (file.kind === "membership") return true;
  return (file.supportedConflictPolicies ?? []).includes(policy);
}
function fileOptionsFromPreview(file: DataImportPreviewFile, existing?: DataImportFileOptions): DataImportFileOptions {
  return {
    file: file.file,
    ...(existing?.dataset ? { dataset: existing.dataset } : file.kind ? { dataset: file.kind } : {}),
    mapping: existing?.mapping ?? Object.fromEntries((file.columns ?? []).map(column => [column.source, column.target])),
    units: existing?.units ?? file.units ?? { volume: "unknown", amount: "unknown" },
    priceBasis: existing?.priceBasis ?? file.priceBasis ?? "unknown"
  };
}
function optionsFromJob(job: JobEvent): DataImportOptions {
  const saved = job.spec?.parameters as unknown as DataImportOptions;
  return {
    ...saved,
    projectId: job.projectId ?? saved.projectId ?? null,
    ...(job.strategyId ?? saved.strategyId ? { strategyId: job.strategyId ?? saved.strategyId } : {})
  };
}

function ImportTaskResult({
  job,
  options,
  busy,
  onRetry
}: {
  job: JobEvent;
  options: DataImportOptions;
  busy: boolean;
  onRetry: (options: DataImportOptions, file: string) => Promise<void>;
}) {
  const s = useResearch();
  const [details, setDetails] = useState<ExperimentDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [retryingFiles, setRetryingFiles] = useState<string[]>([]);
  async function retryFile(file: string) {
    if (busy || retryingFiles.includes(file)) return;
    setRetryingFiles(current => [...current, file]);
    try {
      await onRetry(options, file);
    } finally {
      setRetryingFiles(current => current.filter(item => item !== file));
    }
  }
  useEffect(() => {
    let active = true;
    if (!job.experimentId || !["completed", "failed", "cancelled", "interrupted"].includes(job.status)) return;
    setLoading(true);
    setError("");
    void request<ExperimentDetails>("experiments.get", {
      ...(job.projectId ? { projectId: job.projectId } : {}),
      ...(job.strategyId ? { strategyId: job.strategyId } : {}),
      experimentId: job.experimentId
    }).then(value => {
      if (!active) return;
      setDetails(value);
      void s.refresh();
    }).catch(reason => { if (active) setError(errorText(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [job.id, job.status, job.experimentId, job.projectId, job.strategyId, reload]);
  const result = resultFromDetails(details);
  const listedFailedFiles = result?.failedFiles ?? [];
  const failedFiles = listedFailedFiles.length
    ? listedFailedFiles
    : result?.imports.filter(item => item.status === "failed").map(item => item.file) ?? [];
  return <article className="r-data-import-task">
    <div className="r-toolbar">
      <strong>{!job.name || job.name === "data.import" ? "数据导入" : job.name}</strong>
      <span>{statusLabels[job.status] ?? job.status}</span>
      <progress max={1} value={Math.max(0, Math.min(1, job.progress))} />
    </div>
    {job.message && <p className="r-note">{job.message}</p>}
    {loading && <p role="status">正在读取逐文件导入结果…</p>}
    {error && <p role="alert">{error} <button type="button" onClick={() => setReload(value => value + 1)}>重试读取结果</button></p>}
    {!loading && !error && ["completed", "failed", "cancelled", "interrupted"].includes(job.status) && !job.experimentId &&
      <p role="alert">任务结束但未返回实验明细，当前没有逐文件结果可展示或重试。</p>}
    {!loading && !error && details && !result && <p role="alert">实验明细中没有可读取的逐文件导入结果。</p>}
    {result && <>
      <p className="r-data-import-result-status">导入结果：{resultStatusLabels[result.status] ?? result.status} · 成功文件 {formatCount(result.completedFiles)} · 失败文件 {failedFiles.length}</p>
      {result.warnings.map((warning, index) => <p className="r-note" key={"warning-" + index}>{warning}</p>)}
      <ul className="r-data-import-result-list">
        {result.imports.map(item => <li key={item.file}>
          <strong>{displayName(item.file)} · {item.status === "completed" ? "完成" : "失败"}</strong>
          {item.message && <p role={item.status === "failed" ? "alert" : undefined}>{importMessage(item.message)}</p>}
          {item.status === "completed" && <p>{[
            item.importedRows !== undefined ? `本文件 ${item.importedRows} 行` : null,
            item.totalRows !== undefined ? `当前数据集 ${item.totalRows} 行` : null,
            item.newRows !== undefined ? `新增 ${item.newRows} 行` : null,
            item.filledCells !== undefined ? `补缺 ${item.filledCells} 个单元格` : null,
            item.conflictRows !== undefined ? `冲突 ${item.conflictRows} 行` : null,
            item.replacedRows !== undefined ? `替换 ${item.replacedRows} 行` : null
          ].filter(Boolean).join(" · ")}</p>}
        </li>)}
      </ul>
      {failedFiles.length > 0 && <div className="r-data-import-retries">
        <strong>仅重试失败文件</strong>
        {failedFiles.map(file => <button type="button" key={file} disabled={busy || retryingFiles.includes(file)} onClick={() => void retryFile(file)}>{retryingFiles.includes(file) ? "正在提交重试…" : "按原设置重试 " + displayName(file)}</button>)}
      </div>}
    </>}
  </article>;
}

export function DataImportPanel({ projectId, strategyId, dataset, kind, className, disabled }: DataImportPanelProps) {
  const s = useResearch();
  const dialog = useRef<HTMLDialogElement>(null);
  const submitLock = useRef(false);
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<string[]>([]);
  const [includedFiles, setIncludedFiles] = useState<string[]>([]);
  const [preview, setPreview] = useState<DataImportPreview | null>(null);
  const [fileOptions, setFileOptions] = useState<DataImportFileOptions[]>([]);
  const [previewOptions, setPreviewOptions] = useState<DataImportOptions | null>(null);
  const [conflictPolicy, setConflictPolicy] = useState<ImportPolicy>("fill_missing");
  const [replaceConfirmed, setReplaceConfirmed] = useState(false);
  const [previewDirty, setPreviewDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submittedRuns, setSubmittedRuns] = useState<ImportTask[]>([]);
  const [visibleTasks, setVisibleTasks] = useState(4);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  async function requestPreview(
    targetFiles: string[],
    currentOptions: DataImportFileOptions[] = fileOptions,
    policy: ImportPolicy = conflictPolicy
  ) {
    if (!targetFiles.length) return;
    setBusy(true);
    setError("");
    setPreviewOptions(null);
    setPreviewDirty(true);
    try {
      const requestedFileOptions = currentOptions
        .filter(option => targetFiles.includes(option.file))
        .map(option => ({
          ...option,
          ...(option.mapping ? { mapping: { ...option.mapping } } : {}),
          ...(option.units ? { units: { ...option.units } } : {})
        }));
      const options: DataImportOptions = {
        projectId,
        ...(strategyId ? { strategyId } : {}),
        files: [...targetFiles],
        ...(kind !== undefined ? { kind } : { dataset: dataset === "flow" ? "fund_flow" : dataset ?? "auto" }),
        conflictPolicy: policy,
        ...(requestedFileOptions.length ? { fileOptions: requestedFileOptions } : {})
      };
      const response = await request<DataImportPreview>("data.import.preview", options);
      setPreview(response);
      setPreviewOptions(options);
      setFileOptions(response.files.map(file => fileOptionsFromPreview(file, requestedFileOptions.find(option => option.file === file.file))));
      setIncludedFiles(response.files.filter(file => file.status === "ready").map(file => file.file));
      setPreviewDirty(false);
      setReplaceConfirmed(false);
    } catch (reason) {
      setPreviewDirty(true);
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function pickFiles() {
    setError("");
    try {
      const chosen = await window.v3Research!.chooseFiles();
      if (!chosen.length) return;
      setFiles(chosen);
      setIncludedFiles([]);
      setPreview(null);
      setPreviewOptions(null);
      setFileOptions([]);
      setPreviewDirty(false);
      setConflictPolicy("fill_missing");
      setReplaceConfirmed(false);
      await requestPreview(chosen, [], "fill_missing");
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  async function openAndPickFiles() {
    setOpen(true);
    await pickFiles();
  }

  function updateFileOption(file: string, patch: Partial<DataImportFileOptions>) {
    setFileOptions(current => current.map(option => option.file === file ? { ...option, ...patch, file } : option));
    setPreviewDirty(true);
    setReplaceConfirmed(false);
  }

  function setFileMapping(file: DataImportPreviewFile, source: string, target: string) {
    const current = fileOptions.find(option => option.file === file.file) ?? fileOptionsFromPreview(file);
    updateFileOption(file.file, { mapping: { ...(current.mapping ?? {}), [source]: target } });
  }

  const previewedFiles = preview?.files ?? [];
  const selectedReadyFiles = previewedFiles.filter(file => file.status === "ready" && includedFiles.includes(file.file));
  const unsupportedPolicyFiles = selectedReadyFiles.filter(file => !supportsPolicy(file, conflictPolicy));
  const canSubmit = !!previewOptions && previewOptions.conflictPolicy === conflictPolicy &&
    selectedReadyFiles.length > 0 && !previewDirty && !busy &&
    unsupportedPolicyFiles.length === 0 && (conflictPolicy !== "replace" || replaceConfirmed);

  async function submitOptions(options: DataImportOptions) {
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true);
    setError("");
    try {
      const parameters = options as unknown as JsonObject;
      const targetProjectId = options.projectId === undefined ? projectId : options.projectId;
      const targetStrategyId = options.strategyId ?? strategyId;
      const job = await request<JobEvent>("jobs.submit", {
        spec: {
          ...(targetProjectId ? { projectId: targetProjectId } : {}),
          ...(targetStrategyId ? { strategyId: targetStrategyId } : {}),
          kind: "data.import",
          parameters
        }
      });
      setSubmittedRuns(current => [{ job, options }, ...current.filter(run => run.job.id !== job.id)]);
      if (!targetProjectId) s.setNotice("共享数据导入已提交，任务和逐文件结果会在此显示。");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  }

  async function submitSelected() {
    if (!previewOptions || !canSubmit) return;
    const selected = previewedFiles.filter(file => file.status === "ready" && includedFiles.includes(file.file));
    const selectedPaths = selected.map(file => file.file);
    const options: DataImportOptions = {
      ...previewOptions,
      files: selectedPaths,
      ...(previewOptions.fileOptions
        ? { fileOptions: previewOptions.fileOptions.filter(option => selectedPaths.includes(option.file)) }
        : {}),
      ...(previewOptions.conflictPolicy === "replace" ? { replaceConfirmed: true } : {})
    };
    await submitOptions(options);
  }

  async function retryFailedFile(original: DataImportOptions, file: string) {
    const options: DataImportOptions = {
      ...original,
      files: [file],
      ...(original.fileOptions ? { fileOptions: original.fileOptions.filter(option => option.file === file) } : {})
    };
    await submitOptions(options);
  }

  const taskMap = new Map<string, JobEvent>();
  const currentTaskIds = new Map(submittedRuns.map(run => [run.job.id, run]));
  for (const job of s.jobs) {
    const inScope = job.kind === "data.import" && (projectId
      ? job.projectId === projectId && (!strategyId || (job.strategyId ?? job.spec?.parameters.strategyId) === strategyId)
      : !job.projectId);
    if (inScope) taskMap.set(job.id, job);
  }
  for (const run of submittedRuns) if (!taskMap.has(run.job.id)) taskMap.set(run.job.id, run.job);
  const taskEvents = [...taskMap.values()].sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt)).slice(0, visibleTasks);

  const policyOptions: ImportPolicy[] = ["fill_missing", "replace"];

  return <>
    <button type="button" className={className} disabled={disabled || busy} onClick={() => void openAndPickFiles()}>导入 CSV / Excel / Parquet</button>
    <dialog ref={dialog} className="r-dialog r-data-import-dialog" onCancel={event => { event.preventDefault(); if (!busy) setOpen(false); }}>
      <header className="r-toolbar">
        <div><h2>导入本地数据</h2><p className="r-note">先逐文件预览。默认只补空缺，已有非空冲突不会被覆盖。</p></div>
        <button type="button" disabled={busy} onClick={() => setOpen(false)}>关闭</button>
      </header>
      {error && <p role="alert">{error}</p>}
      <div className="r-toolbar">
        <button type="button" disabled={busy} onClick={() => void pickFiles()}>选择文件并预览</button>
        <button type="button" disabled={busy || !files.length} onClick={() => void requestPreview(files)}>重新检查预览</button>
      </div>
      {busy && <p role="status">正在检查或提交…</p>}
      {preview && <>
        {preview.warnings.map((warning, index) => <p role="status" className="r-note" key={"preview-warning-" + index}>{warning}</p>)}
        <p className="r-note">已识别 {preview.files.length} 个文件；可导入的文件需保持勾选。未识别单位不会自动换算或复权。</p>
        <div className="r-data-import-files">
          {preview.files.map(file => {
            const option = fileOptions.find(item => item.file === file.file) ?? fileOptionsFromPreview(file);
            const mapping = option.mapping ?? {};
            const columns = file.columns ?? [];
            const sample = file.sample ?? [];
            const previewUnits = file.units ?? {};
            const mappingRows = columns.length ? columns : Object.entries(mapping).map(([source, target]) => ({ source, target }));
            const merge = file.merge;
            return <section className="r-data-import-file" key={file.file}>
              <header className="r-toolbar">
                <label><input type="checkbox" checked={includedFiles.includes(file.file)} disabled={busy || file.status !== "ready"} onChange={event => setIncludedFiles(current => event.target.checked ? [...new Set([...current, file.file])] : current.filter(path => path !== file.file))} />导入此文件</label>
                <strong>{file.fileName}</strong>
                <span>{file.status === "ready" ? "预览可用" : "预览失败"}</span>
                {file.rows !== undefined && <span>{file.rows} 行</span>}
              </header>
              {file.message && <p role={file.status === "failed" ? "alert" : undefined}>{importMessage(file.message)}</p>}
              {file.kind === "membership" && <p className="r-note">成员数据会保留为新版本，不与旧版本合并或覆盖。</p>}
              {merge && <p className="r-note">合并预览：新增行 {formatCount(merge.newRows)} · 已有行 {formatCount(merge.existingRows)} · 冲突行 {formatCount(merge.conflictRows)} · 可补空单元格 {formatCount(merge.fillableCells)}</p>}
              {file.outputUnits && <p className="r-note">预览输出单位：成交量 {unitLabel(file.outputUnits.volume)} · 成交额 {unitLabel(file.outputUnits.amount)}</p>}
              {file.warnings.map((warning, index) => <p className="r-note" key={file.file + "-warning-" + index}>{warning}</p>)}
              <>
                <div className="r-data-import-fields">
                  <label>数据集
                    <select value={option.dataset ?? file.kind ?? (kind ?? (dataset === "flow" ? "fund_flow" : dataset) ?? "auto")} disabled={busy} onChange={event => updateFileOption(file.file, { dataset: event.target.value })}>
                      {datasetChoices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label>输入成交量单位
                    <select value={option.units?.volume ?? previewUnits.volume ?? "unknown"} disabled={busy} onChange={event => updateFileOption(file.file, { units: { ...option.units, volume: event.target.value as DataImportUnits["volume"] } })}>
                      {volumeUnitChoices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label>输入成交额单位
                    <select value={option.units?.amount ?? previewUnits.amount ?? "unknown"} disabled={busy} onChange={event => updateFileOption(file.file, { units: { ...option.units, amount: event.target.value as DataImportUnits["amount"] } })}>
                      {amountUnitChoices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </label>
                  <label>价格复权口径
                    <select value={option.priceBasis ?? file.priceBasis ?? "unknown"} disabled={busy} onChange={event => updateFileOption(file.file, { priceBasis: event.target.value as DataImportPriceBasis })}>
                      {priceBasisChoices.map(choice => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                    </select>
                  </label>
                </div>
                {mappingRows.length > 0
                  ? <div className="r-data-import-columns"><strong>字段映射</strong>{mappingRows.map(column => <label key={file.file + "-" + column.source}><span>{column.source}</span><span aria-hidden="true">→</span><input aria-label={file.fileName + " 字段 " + column.source + " 的目标字段"} value={mapping[column.source] ?? column.target} disabled={busy} onChange={event => setFileMapping(file, column.source, event.target.value)} /></label>)}</div>
                  : <p className="r-note">预览没有读取到字段，无法设置映射；请重新选择该文件后再配置。</p>}
                {sample.length > 0 && <details><summary>只读样例 · {sample.length} 行</summary><pre>{JSON.stringify(sample, null, 2)}</pre></details>}
              </>
            </section>;
          })}
        </div>
        {previewDirty && <p role="status">字段、单位或复权设置已变化；请重新检查后再导入。</p>}
        <fieldset className="r-data-import-policy" disabled={busy}>
          <legend>处理已有数据</legend>
          {policyOptions.map(policy => <label key={policy}>
            <input type="radio" name={"data-import-policy-" + (projectId ?? "shared")} value={policy} checked={conflictPolicy === policy} onChange={() => {
              if (conflictPolicy === policy) return;
              setConflictPolicy(policy);
              setPreviewDirty(true);
              setPreviewOptions(null);
              setReplaceConfirmed(false);
              void requestPreview(files, fileOptions, policy);
            }} />
            {policyLabels[policy]}
          </label>)}
          {unsupportedPolicyFiles.length > 0 && <p role="alert">所选文件不支持“{policyLabels[conflictPolicy]}”：{unsupportedPolicyFiles.map(file => file.fileName).join("、")}。请取消这些文件或改选受支持的策略；不会自动替换。</p>}
          {selectedReadyFiles.some(file => file.kind !== "membership" && !supportsPolicy(file, "fill_missing")) && <p role="alert">部分适配器不支持默认补缺；必须显式选择其支持的策略，默认补缺不会静默变成覆盖。</p>}
          {conflictPolicy === "replace" && <label className="r-data-import-confirm"><input type="checkbox" checked={replaceConfirmed} disabled={busy} onChange={event => setReplaceConfirmed(event.target.checked)} />我确认用本次文件内容替换所选数据中的冲突值。</label>}
          {selectedReadyFiles.some(file => file.kind === "membership") && <p className="r-note">股票池成员导入始终生成独立成员版本；通用行合并策略不会改写旧成员版本。</p>}
        </fieldset>
        <div className="r-toolbar">
          <span>本次选择 {selectedReadyFiles.length} / {preview.files.length} 个可预览文件</span>
          <button type="button" className="r-primary" disabled={!canSubmit} onClick={() => void submitSelected()}>{busy ? "提交中…" : conflictPolicy === "replace" ? "确认替换并导入" : "补缺并导入"}</button>
        </div>
      </>}
      {!preview && !busy && <p className="r-note">选择 CSV、Excel 或 Parquet 文件后，先检查字段、单位、复权口径和与现有数据的冲突。</p>}
      {taskEvents.length > 0 && <section className="r-data-import-history"><h3>导入任务与逐文件结果</h3>{taskEvents.map(job => {
        const submitted = currentTaskIds.get(job.id);
        const options = submitted?.options ?? optionsFromJob(job);
        return <ImportTaskResult key={job.id} job={job} options={options} busy={busy} onRetry={(original, file) => retryFailedFile(original, file)} />;
      })}{taskMap.size > visibleTasks && <button type="button" onClick={() => setVisibleTasks(count => count + 4)}>展开更多导入任务</button>}</section>}
    </dialog>
  </>;
}