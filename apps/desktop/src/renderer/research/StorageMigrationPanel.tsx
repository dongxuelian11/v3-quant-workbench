import React, { useEffect, useRef, useState } from "react";
import type { StorageMigrationPreview, StorageMigrationState } from "../../../../../packages/contracts/src/research";
import { errorText, request } from "./state";
import "./storageMigration.css";

export type EffectiveStoragePaths = {
  dataDirectory: string;
  newProjectDirectory: string;
  message?: string;
};
type Props = {
  refreshEffectiveStorage: () => Promise<EffectiveStoragePaths | null>;
  onSettled: () => void;
};

const activeStatuses: StorageMigrationState["status"][] = ["waiting", "copying", "verifying", "switching"];
const cancellableStatuses: StorageMigrationState["status"][] = ["waiting", "copying", "verifying", "failed"];
const terminalStatuses: StorageMigrationState["status"][] = ["completed", "failed", "cancelled"];
const statusLabels: Record<StorageMigrationState["status"], string> = {
  waiting: "等待写入结束", copying: "正在复制", verifying: "正在校验",
  switching: "正在切换目录", completed: "迁移完成", failed: "迁移失败", cancelled: "后端已取消"
};
const groupLabels: Record<string, string> = {
  data: "研究数据", experiments: "实验与固定输入", cache: "可重建缓存",
  exports: "导出文件", shared: "共享数据", reports: "研报原文与资料",
  quotes: "行情缓存", minutes: "分钟行情", "market-snapshot": "市场快照"
};
const referenceLabels: Record<string, string> = {
  redirect: "迁移后关联到新目录", keep: "保留原位置", blocked: "阻止迁移"
};
const jobLabels: Record<string, string> = {
  queued: "排队中", running: "运行中", interrupted: "等待恢复",
  completed: "已完成", failed: "失败", cancelled: "已取消"
};

function isActive(state: StorageMigrationState | null) {
  return !!state && activeStatuses.includes(state.status);
}
function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return "未提供";
  if (value < 1024) return value + " B";
  if (value < 1024 ** 2) return (value / 1024).toFixed(1) + " KB";
  if (value < 1024 ** 3) return (value / 1024 ** 2).toFixed(1) + " MB";
  return (value / 1024 ** 3).toFixed(2) + " GB";
}
function bounded(value: number) { return Math.max(0, Math.min(1, value)); }

export function StorageMigrationPanel({ refreshEffectiveStorage, onSettled }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const requestIds = useRef(new Map<string, string>());
  const actionLock = useRef(false);
  const statusRevision = useRef(0);
  const statusLock = useRef(false);
  const previewRead = useRef<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [open, setOpen] = useState(false);
  const [targetDirectory, setTargetDirectory] = useState("");
  const [currentDirectory, setCurrentDirectory] = useState<string | null>(null);
  const [currentDirectoryLoading, setCurrentDirectoryLoading] = useState(false);
  const [preview, setPreview] = useState<StorageMigrationPreview | null>(null);
  const [migration, setMigration] = useState<StorageMigrationState | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusLoading, setStatusLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  async function readCurrentDirectory() {
    setCurrentDirectory(null);
    setCurrentDirectoryLoading(true);
    try {
      const value = await refreshEffectiveStorage();
      setCurrentDirectory(value?.dataDirectory ?? null);
      return value;
    } catch (reason) {
      setError(errorText(reason));
      return null;
    } finally {
      setCurrentDirectoryLoading(false);
    }
  }

  async function acceptMigration(value: StorageMigrationState | null) {
    setMigration(value);
    setNotice("");
    if (value) setPreview(null);
    if (!value || !terminalStatuses.includes(value.status)) return;
    requestIds.current.delete(value.targetDirectory);
    // Read after the terminal state so a just-completed switch cannot leave the old path visible.
    await readCurrentDirectory();
    onSettled();
  }

  async function openPanel() {
    setOpen(true);
    if (statusLock.current || actionLock.current) return;
    statusLock.current = true;
    setError("");
    setNotice("");
    setStatusLoading(true);
    const revision = ++statusRevision.current;
    try {
      await readCurrentDirectory();
      const restored = await request<StorageMigrationState | null>(
        "storage.migration.status",
        migration?.id ? { migrationId: migration.id } : {}
      );
      if (revision !== statusRevision.current) return;
      await acceptMigration(restored);
      if (restored?.targetDirectory) setTargetDirectory(restored.targetDirectory);
      if (!restored) setNotice("当前没有可恢复的迁移任务。");
    } catch (reason) {
      if (revision === statusRevision.current) setError(errorText(reason));
    } finally {
      statusLock.current = false;
      setStatusLoading(false);
    }
  }

  async function perform(action: () => Promise<void>) {
    if (actionLock.current || statusLock.current) return;
    actionLock.current = true;
    statusRevision.current += 1;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function chooseTarget() {
    await perform(async () => {
      const selected = await window.v3Research!.chooseDirectory({ purpose: "data" });
      if (selected) {
        setTargetDirectory(selected);
        setPreview(null);
      }
    });
  }

  async function checkMigration() {
    const target = targetDirectory.trim();
    if (!target || isActive(migration)) return;
    await perform(async () => {
      setPreview(null);
      const readId = crypto.randomUUID();
      previewRead.current = readId;
      setChecking(true);
      try {
        const result = await request<StorageMigrationPreview>("storage.migration.preview", { targetDirectory: target, readId });
        if (previewRead.current !== readId) return;
        setPreview(result);
        setTargetDirectory(result.targetDirectory);
        setNotice(result.canStart ? "检查完成，可以按预览结果启动迁移。" : "后端阻止了启动，请先查看空间、引用和阻塞项。");
      } catch (reason) {
        if (previewRead.current === readId) throw reason;
      } finally {
        previewRead.current = null;
        setChecking(false);
      }
    });
  }

  async function stopPreview() {
    const readId = previewRead.current;
    if (!readId) return;
    try {
      await request("reads.cancel", { readId });
      previewRead.current = null;
      setNotice("已请求停止检查；尚未开始迁移。");
    } catch (reason) { setError(errorText(reason)); }
  }

  async function startMigration() {
    if (!preview?.canStart || preview.targetDirectory !== targetDirectory || isActive(migration)) return;
    await perform(async () => {
      let requestId = requestIds.current.get(preview.targetDirectory);
      if (!requestId) {
        requestId = crypto.randomUUID();
        requestIds.current.set(preview.targetDirectory, requestId);
      }
      const state = await request<StorageMigrationState>("storage.migration.start", {
        targetDirectory: preview.targetDirectory,
        requestId
      });
      await acceptMigration(state);
      setNotice(state.message || "迁移已提交，进度以服务端状态为准。");
    });
  }

  async function refreshStatus() {
    if (statusLock.current || actionLock.current) return;
    statusLock.current = true;
    setStatusLoading(true);
    setError("");
    const revision = ++statusRevision.current;
    try {
      const state = await request<StorageMigrationState | null>(
        "storage.migration.status",
        migration?.id ? { migrationId: migration.id } : {}
      );
      if (revision !== statusRevision.current) return;
      await acceptMigration(state);
      setNotice(state ? "迁移状态已刷新。" : "当前没有可恢复的迁移任务。");
    } catch (reason) {
      if (revision === statusRevision.current) setError(errorText(reason));
    } finally {
      statusLock.current = false;
      setStatusLoading(false);
    }
  }

  async function resumeMigration() {
    if (!migration?.canResume || migration.status !== "failed") return;
    await perform(async () => {
      const state = await request<StorageMigrationState>("storage.migration.resume", { migrationId: migration.id });
      await acceptMigration(state);
      setNotice(state.message || "已请求继续迁移；进度以服务端状态为准。");
    });
  }

  async function cancelMigration() {
    if (!migration || !cancellableStatuses.includes(migration.status)) return;
    await perform(async () => {
      const state = await request<StorageMigrationState>("storage.migration.cancel", { migrationId: migration.id });
      await acceptMigration(state);
      setNotice(state.message || "取消请求已返回；当前阶段以服务端状态为准。");
    });
  }

  useEffect(() => {
    if (!open || !migration || !activeStatuses.includes(migration.status)) return;
    let stopped = false;
    let inFlight = false;
    const poll = async () => {
      if (stopped || inFlight || actionLock.current || statusLoading) return;
      inFlight = true;
      const revision = statusRevision.current;
      try {
        const state = await request<StorageMigrationState | null>("storage.migration.status", { migrationId: migration.id });
        if (!stopped && revision === statusRevision.current) await acceptMigration(state);
      } catch (reason) {
        if (!stopped && revision === statusRevision.current) setError(errorText(reason));
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => { void poll(); }, 1800);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [open, migration?.id, migration?.status, statusLoading]);

  const migrationActive = isActive(migration);
  const previewMatchesTarget = !!preview && preview.targetDirectory === targetDirectory;
  const progress = migration
    ? migration.bytesTotal > 0
      ? bounded(migration.bytesCopied / migration.bytesTotal)
      : migration.filesTotal > 0
        ? bounded(migration.filesVerified / migration.filesTotal)
        : null
    : null;

  return <>
    <button type="button" className="r-secondary" onClick={() => void openPanel()}>
      {migrationActive ? "查看目录迁移进度" : "迁移现有数据…"}
    </button>
    <dialog ref={dialog} className="r-dialog r-storage-migration-dialog" onCancel={event => { event.preventDefault(); setOpen(false); }}>
      <header className="r-toolbar">
        <div><h2>迁移现有数据目录</h2><p className="r-note">先检查文件、空间和引用；只有服务端报告切换完成后才会更新有效目录。</p></div>
        <button type="button" onClick={() => setOpen(false)}>关闭</button>
      </header>

      <section className="r-storage-migration-current">
        <strong>当前有效数据目录</strong>
        <p className="r-storage-migration-path">{currentDirectoryLoading ? "正在读取…" : currentDirectory ?? "服务未返回当前有效目录"}</p>
        {migration?.status === "failed" && <p role="alert">后端报告迁移失败。当前目录以本次设置读取结果为准；不能仅凭失败状态判断切换是否发生或源目录是否可用。</p>}
      </section>

      {migration && <section className="r-storage-migration-state">
        <div className="r-toolbar">
          <h3>{statusLabels[migration.status]}</h3>
          <button type="button" disabled={busy || statusLoading} onClick={() => void refreshStatus()}>{statusLoading ? "正在读取…" : "刷新状态"}</button>
        </div>
        <p role={migration.status === "failed" ? "alert" : "status"}>{migration.message}</p>
        {progress !== null && <progress className="r-storage-migration-progress" max={1} value={progress} />}
        <p>已复制 {formatBytes(migration.bytesCopied)} / {formatBytes(migration.bytesTotal)} · 已校验 {migration.filesVerified} / {migration.filesTotal} 个文件</p>
        {migration.blockers.length > 0 && <div role="alert"><strong>当前阻塞项</strong><ul>{migration.blockers.map((item, i) => <li key={"state-blocker-" + i}>{item}</li>)}</ul></div>}
        {migration.warnings.length > 0 && <div className="r-note"><strong>提示</strong><ul>{migration.warnings.map((item, i) => <li key={"state-warning-" + i}>{item}</li>)}</ul></div>}
        {migration.status === "switching" && <p role="status">正在切换目录，此阶段不可取消；等待服务端确认结果。</p>}
        {migration.status === "failed" && migration.canResume && <button type="button" disabled={busy || statusLoading} onClick={() => void resumeMigration()}>继续迁移</button>}
        {cancellableStatuses.includes(migration.status) && <button type="button" disabled={busy || statusLoading} onClick={() => void cancelMigration()}>{busy ? "正在请求取消…" : "请求取消迁移"}</button>}
      </section>}

      {!migrationActive && migration?.status !== "failed" && <>
        <section className="r-storage-migration-target">
          <h3>目标目录</h3>
          <div className="r-toolbar">
            <input aria-label="迁移目标目录" disabled={busy || statusLoading} value={targetDirectory} onChange={event => { setTargetDirectory(event.target.value); setPreview(null); }} />
            <button type="button" disabled={busy || statusLoading} onClick={() => void chooseTarget()}>选择目录…</button>
          </div>
          <button type="button" disabled={busy || statusLoading || !targetDirectory.trim()} onClick={() => void checkMigration()}>{checking ? "正在检查…" : "检查迁移条件"}</button>
          {checking && <button type="button" onClick={() => void stopPreview()}>停止检查</button>}
        </section>

        {preview && <section className="r-storage-migration-preview">
          <h3>迁移预览</h3>
          <div className="r-storage-migration-paths">
            <div><strong>来源</strong><p className="r-storage-migration-path">{preview.sourceDirectory}</p></div>
            <div><strong>目标</strong><p className="r-storage-migration-path">{preview.targetDirectory}</p></div>
          </div>
          <dl className="r-storage-migration-metrics">
            <div><dt>所需空间</dt><dd>{formatBytes(preview.requiredBytes)}</dd></div>
            <div><dt>目标可用空间</dt><dd>{formatBytes(preview.availableBytes)}</dd></div>
            <div><dt>文件数</dt><dd>{preview.fileCount}</dd></div>
          </dl>
          {preview.blockers.length > 0
            ? <div role="alert"><strong>暂不能启动</strong><ul>{preview.blockers.map((item, i) => <li key={"preview-blocker-" + i}>{item}</li>)}</ul></div>
            : !preview.canStart && <p role="alert">后端暂不允许启动，但没有返回具体阻塞原因；请刷新检查结果或稍后重试。</p>}
          {preview.copyGroups.length > 0 && <div>
            <h4>将复制的内容</h4>
            <div className="r-storage-migration-table-wrap"><table>
              <thead><tr><th>内容</th><th>来源</th><th>目标</th><th>大小</th><th>文件</th></tr></thead>
              <tbody>{preview.copyGroups.map((group, i) => <tr key={group.kind + "-" + i}>
                <th>{groupLabels[group.kind] ?? "其他文件组"}</th><td className="r-storage-migration-path">{group.source}</td>
                <td className="r-storage-migration-path">{group.target}</td><td>{formatBytes(group.bytes)}</td><td>{group.files}</td>
              </tr>)}</tbody>
            </table></div>
          </div>}
          {preview.references.length > 0 && <details>
            <summary>资料引用处理 · {preview.references.length} 项</summary>
            <ul className="r-storage-migration-references">{preview.references.map((ref, i) => <li key={ref.kind + "-" + ref.id + "-" + i}>
              <strong>{ref.kind} · {ref.id}</strong><span>{referenceLabels[ref.action] ?? "由后端处理"}</span><span>{ref.reason}</span>
            </li>)}</ul>
          </details>}
          {preview.affectedJobs.length > 0 && <div><h4>受影响任务</h4><ul>
            {preview.affectedJobs.map(job => <li key={job.id}>{job.name} · {jobLabels[job.status] ?? job.status}</li>)}
          </ul></div>}
          <button type="button" className="r-primary" disabled={busy || statusLoading || !preview.canStart || !previewMatchesTarget || migrationActive} onClick={() => void startMigration()}>开始复制与校验</button>
        </section>}
      </>}

      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
    </dialog>
  </>;
}