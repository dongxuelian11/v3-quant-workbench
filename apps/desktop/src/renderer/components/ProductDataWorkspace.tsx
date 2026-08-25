import React, { useState } from "react";
import { useProductRuntime } from "../productRuntimeStore";

export function ProductDataWorkspace() {
  const boundProject = useProductRuntime((state) => state.boundProject);
  const home = useProductRuntime((state) => state.dataHome);
  const task = useProductRuntime((state) => state.dataTask);
  const busy = useProductRuntime((state) => state.entryBusy);
  const error = useProductRuntime((state) => state.errorMessage);
  const importLocalData = useProductRuntime((state) => state.importLocalData);
  const [volumeUnit, setVolumeUnit] = useState<"SHARES" | "HANDS">("SHARES");
  const data = home?.data ?? null;

  return <main className="product-data-workspace" data-product-page="data">
    <header className="product-data-heading">
      <div>
        <small>DATA TRUTH · PRE_ALPHA</small>
        <h1>数据</h1>
        <p>本地文件由原生选择器读取，实际字节在 backend 校验并发布；界面不接收文件路径或行情数值。</p>
      </div>
      <div className="product-data-actions">
        <label>
          <span>源成交量单位</span>
          <select value={volumeUnit} disabled={busy} onChange={(event) => setVolumeUnit(event.target.value as "SHARES" | "HANDS")}>
            <option value="SHARES">股 · SHARES</option>
            <option value="HANDS">手 · HANDS</option>
          </select>
        </label>
        <button
          type="button"
          disabled={boundProject === null || home?.localImportState !== "AVAILABLE" || busy}
          onClick={() => { void importLocalData(volumeUnit); }}
        >{busy ? "正在导入…" : "导入 CSV / Parquet"}</button>
      </div>
    </header>

    <section className="product-data-state" aria-live="polite">
      <span className={`truth-state truth-state-${home?.dataState?.toLowerCase() ?? "unavailable"}`}>
        {home?.dataState ?? "UNAVAILABLE"}
      </span>
      <strong>{data === null ? "当前项目尚无可用 Snapshot" : data.displayName}</strong>
      <p>{data === null
        ? `原因：${home?.dataUnavailableReason ?? "PROJECT_HOME_NOT_AVAILABLE"}`
        : `${data.instrumentCount.toLocaleString("zh-CN")} 个标的 · ${data.rowCount.toLocaleString("zh-CN")} 行 · ${data.mediaType}`}</p>
      {task !== null && <p>最近导入 Task：{task.state}</p>}
      {error !== null && <p role="alert">{error}</p>}
    </section>

    {data !== null && <section className="product-data-facts" aria-label="当前 canonical 数据摘要">
      <dl>
        <div><dt>来源</dt><dd>本地用户提供 · {data.sourceType}</dd></div>
        <div><dt>数据真值</dt><dd>{data.truth} / {data.admission}</dd></div>
        <div><dt>日期覆盖</dt><dd>{data.dateCoverageStart} 至 {data.dateCoverageEnd}</dd></div>
        <div><dt>质量状态</dt><dd>{data.qualityStatus} · {data.validationProfileId}</dd></div>
        <div><dt>静态 Universe</dt><dd>{data.instrumentCount} 个标的 · {data.partitionCount} 个分区</dd></div>
        <div><dt>单位</dt><dd>{data.volumeUnit} · {data.amountUnit} · {data.adjustment}</dd></div>
        <div><dt>导入时间</dt><dd>{new Date(data.importedAt).toLocaleString("zh-CN")}</dd></div>
      </dl>
      <details>
        <summary>查看 canonical 标识与哈希</summary>
        <dl className="product-data-lineage">
          <div><dt>Snapshot</dt><dd>{data.snapshotId}</dd></div>
          <div><dt>静态 Universe</dt><dd>{data.universeVersionId}</dd></div>
          <div><dt>RawCapture</dt><dd>{data.rawCaptureId}</dd></div>
          <div><dt>Raw SHA-256</dt><dd>{data.rawContentHash}</dd></div>
          <div><dt>Normalized SHA-256</dt><dd>{data.normalizedPayloadHash}</dd></div>
          <div><dt>Raw Artifact</dt><dd>{data.rawArtifactId}</dd></div>
        </dl>
      </details>
    </section>}

    <footer className="product-data-limit">
      <strong>研究边界</strong>
      <span>LOCAL_USER_SUPPLIED · PIT_UNPROVABLE · NOT_FORMAL</span>
      <span>{data?.capabilityReasons.pit ?? "PIT_UNPROVABLE"} · {data?.capabilityReasons.revision ?? "PROVIDER_REVISION_UNKNOWN"}</span>
      <span>{data?.capabilityReasons.calendar ?? "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR"}</span>
      <span>{data?.capabilityReasons.status ?? "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED"}</span>
    </footer>
  </main>;
}
