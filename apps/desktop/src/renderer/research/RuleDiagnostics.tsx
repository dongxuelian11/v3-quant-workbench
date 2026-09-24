import React, { useEffect, useMemo, useState } from "react";
import type { ExperimentDetails, JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";
import { errorText, useResearch } from "./state";
import { DataTable, fieldLabel } from "./ui";
import { readScope, useResultExport } from "./readCancellation";
import type { TablePage } from "./PagedTable";

type R = Record<string, unknown>;
type Parsed = { ok: true; value: unknown } | { ok: false; message: string };
function record(value: unknown): R | null { return value && typeof value === "object" && !Array.isArray(value) ? value as R : null; }
function get(row: R, ...keys: string[]): unknown { for (const key of keys) if (Object.prototype.hasOwnProperty.call(row, key)) return row[key]; return undefined; }
function show(value: unknown): string {
  if (value === undefined) return "未记录";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" && !Number.isFinite(value)) return String(value);
  try { return JSON.stringify(value) ?? String(value); } catch { return String(value); }
}
function pretty(value: unknown): string { try { return JSON.stringify(value, null, 2) ?? String(value); } catch { return String(value); } }
function parse(raw: unknown): Parsed {
  if (typeof raw !== "string") return { ok: false, message: "字段没有保存为 JSON 文本。" };
  try { return { ok: true, value: JSON.parse(raw) as unknown }; }
  catch { return { ok: false, message: "JSON 无法解析；原始内容仍保留在下方。" }; }
}
function day(value: unknown): string { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : ""; }
function idOf(row: R): string {
  const value = get(row, "orderId", "order_id");
  return (typeof value === "string" || typeof value === "number") && String(value).trim() ? String(value) : "";
}
function idColumn(columns: string[]): string | undefined { return columns.find(key => ["orderid", "orderno"].includes(key.replace(/[^a-z0-9]/gi, "").toLowerCase())); }
function state(value: unknown, kind: "rule" | "condition" | "value" | "order" | "action"): string {
  const labels: Record<string, Record<string, string>> = {
    rule: { matched: "命中", not_matched: "未命中", unknown: "无法判定", skipped: "跳过" },
    condition: { true: "满足", false: "不满足", unknown: "无法判定", not_evaluated: "未求值" },
    value: { present: "有值", missing: "缺失", positive_infinity: "正无穷", negative_infinity: "负无穷", not_evaluated: "未求值" },
    order: { no_order: "未生成订单", filled: "全部成交", partial: "部分成交", rejected: "拒绝" },
    action: { entry: "入场", add: "加仓", reduce: "减仓", exit: "退出" }
  };
  return typeof value === "string" ? labels[kind][value] ?? value : show(value);
}
function tone(value: unknown): string {
  return value === "true" || value === "matched" ? "is-positive" : value === "false" || value === "not_matched" ? "is-negative" : value === "unknown" ? "is-unknown" : "is-muted";
}
function skip(value: unknown): string {
  if (value === "not_held") return "当前未持仓";
  if (value === "already_held") return "已经持仓";
  if (value === "exit_priority") return "退出或减仓优先级跳过";
  return value == null ? "" : show(value);
}
function suffix(value: unknown): string {
  if (value === "not_evaluated") return " · 未求值";
  if (value === "missing") return " · 缺失";
  if (value === "positive_infinity") return " · 正无穷";
  if (value === "negative_infinity") return " · 负无穷";
  return "";
}
function weight(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? (value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 }) + "%" : show(value);
}
function quantity(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 4 }) + " 股" : show(value);
}
function tableFor(detail: ExperimentDetails, kind: "trades" | "unfilled"): string | undefined {
  const pattern = kind === "trades" ? /(?:^|_)(?:trades?|交易)(?:\.|_|$)/i : /(?:^|_)(?:unfilled|未成交)(?:\.|_|$)/i;
  return detail.experiment.artifacts.find(item => item.type === "parquet" && pattern.test(item.name))?.name
    ?? detail.tables.find(item => pattern.test(item.name))?.name;
}
function Conditions({ raw, fieldName }: { raw: unknown; fieldName: (field: unknown) => string }) {
  const parsed = parse(raw);
  if (!parsed.ok) return <div className="r-diag-json"><strong>条件明细</strong><p role="status">{parsed.message}</p><pre>{show(raw)}</pre></div>;
  if (!Array.isArray(parsed.value)) return <div className="r-diag-json"><strong>条件明细</strong><p role="status">条件 JSON 已解析，但内容不是数组；不会按空条件处理。</p><pre>{pretty(parsed.value)}</pre></div>;
  if (!parsed.value.length) return <div className="r-diag-json"><strong>条件明细</strong><p>已保存的条件数组为空。</p></div>;
  const operators: Record<string, string> = { gt: "大于", gte: "大于等于", lt: "小于", lte: "小于等于", eq: "等于", ne: "不等于" };
  return <div className="r-diag-json"><strong>逐项条件</strong><div className="r-diag-conditions">{parsed.value.map((item, index) => {
    const condition = record(item);
    if (!condition) return <article className="r-diag-condition" key={index}><strong>条件 {index + 1}</strong><p>记录格式无法识别</p><pre>{pretty(item)}</pre></article>;
    const field = get(condition, "field"), op = get(condition, "op"), threshold = get(condition, "threshold");
    const conditionState = get(condition, "conditionState"), valueState = get(condition, "valueState");
    const thresholdState = get(condition, "thresholdState"), conditionIndex = get(condition, "conditionIndex");
    const opText = typeof op === "string" ? operators[op] ?? op : show(op);
    return <article className="r-diag-condition" key={index}>
      <header><strong>条件 {typeof conditionIndex === "number" && Number.isFinite(conditionIndex) ? String(conditionIndex + 1) : String(index + 1)} · {fieldName(field)}</strong>
        <span className={"r-diag-state " + tone(conditionState)}>{state(conditionState, "condition")}</span></header>
      <dl><div><dt>原始比较方式</dt><dd>{opText}</dd></div>
        <div><dt>原始阈值</dt><dd>{show(threshold) + suffix(thresholdState)}</dd></div>
        <div><dt>实际值</dt><dd>{show(get(condition, "value")) + suffix(valueState)}</dd></div></dl>
    </article>;
  })}</div></div>;
}
function Reasons({ label, raw }: { label: string; raw: unknown }) {
  const parsed = parse(raw);
  if (!parsed.ok) return <div className="r-diag-json"><strong>{label}</strong><p role="status">{parsed.message}</p><pre>{show(raw)}</pre></div>;
  if (parsed.value == null || Array.isArray(parsed.value) && !parsed.value.length) return <div className="r-diag-json"><strong>{label}</strong><p>未记录原因。</p></div>;
  if (Array.isArray(parsed.value)) return <div className="r-diag-json"><strong>{label}</strong><ul>{parsed.value.map((value, index) => <li key={index}>{show(value)}</li>)}</ul></div>;
  return <div className="r-diag-json"><strong>{label}</strong><pre>{pretty(parsed.value)}</pre></div>;
}

type OrderResult = { label: string; status: "loading" | "ready" | "empty" | "unavailable" | "error"; table?: ResearchTable; message?: string };
export function RuleDiagnostics({ detail, symbol, signalDate, startDate, endDate, linkedOrderId, linkedExecutionDate, onSignalDateChange, onSignalDateResolved }: {
  detail: ExperimentDetails; symbol: string; signalDate: string; startDate?: string; endDate?: string;
  linkedOrderId?: string; linkedExecutionDate?: string; onSignalDateChange: (date: string) => void; onSignalDateResolved: (date: string) => void;
}) {
  const experiment = detail.experiment, capability = record(detail.details.ruleDiagnostics);
  const research = useResearch();
  const factorNames = useMemo(() => {
    const names = new Map<string, string>(research.factors.map(factor => [factor.id, factor.name] as const));
    if (Array.isArray(experiment.parameters.customFactors)) for (const value of experiment.parameters.customFactors) {
      const saved = record(value);
      if (typeof saved?.id === "string" && typeof saved.name === "string") names.set(saved.id, saved.name);
    }
    return names;
  }, [experiment.parameters.customFactors, research.factors]);
  const fieldName = (field: unknown) => {
    if (typeof field !== "string") return show(field);
    const label = factorNames.get(field) ?? fieldLabel(field, "rule_diagnostics");
    return label === field ? field : label + " · " + field;
  };
  const capabilityStatus = capability?.status, available = capabilityStatus === "available" && capability?.artifact === "rule_diagnostics" && capability.version === 1;
  const rowCount = capability?.rowCount;
  const exporter = useResultExport((experiment.projectId ?? "") + ":" + experiment.id + ":rule_diagnostics");
  const [offset, setOffset] = useState(0), [page, setPage] = useState<TablePage | null>(null);
  const [loading, setLoading] = useState(false), [failure, setFailure] = useState("");
  const [lookupStatus, setLookupStatus] = useState("");
  const [inspectedOrder, setInspectedOrder] = useState<{ id: string; executionDate: string } | null>(() => linkedOrderId ? { id: linkedOrderId, executionDate: linkedExecutionDate ?? "" } : null);
  const [orderResults, setOrderResults] = useState<OrderResult[]>([]);
  const orderTables = useMemo(() => [
    { label: "实际成交", table: tableFor(detail, "trades") },
    { label: "未成交记录", table: tableFor(detail, "unfilled") }
  ], [detail]);

  useEffect(() => {
    let active = true;
    const reads = readScope();
    setPage(null); setFailure("");
    if (!available || !symbol || !signalDate) { setLoading(false); return () => { active = false; reads.cancel(); }; }
    setLoading(true);
    void reads.request<TablePage>("experiments.table", {
      projectId: experiment.projectId, experimentId: experiment.id, table: "rule_diagnostics",
      symbol, startDate: signalDate, endDate: signalDate, offset, limit: 50
    }).then(result => { if (active) setPage(result); })
      .catch(error => { if (active) setFailure(errorText(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; reads.cancel(); };
  }, [available, experiment.id, experiment.projectId, offset, signalDate, symbol]);

  useEffect(() => {
    let active = true;
    const reads = readScope();
    setLookupStatus("");
    if (!available || signalDate || !linkedOrderId || !symbol) return () => { active = false; reads.cancel(); };
    setLookupStatus("正在按订单关联的诊断记录定位信号日…");
    void (async () => {
      let currentOffset = 0, total = 0;
      const dates = new Set<string>();
      while (active) {
        const result = await reads.request<TablePage>("experiments.table", {
          projectId: experiment.projectId, experimentId: experiment.id, table: "rule_diagnostics",
          symbol, orderId: linkedOrderId, offset: currentOffset, limit: 200
        });
        if (!active) return;
        for (const row of result.rows) if (idOf(row) === linkedOrderId) {
          const signal = day(row.date); if (signal) dates.add(signal);
        }
        total = result.total; currentOffset += result.rows.length;
        if (currentOffset >= total) break;
        if (!result.rows.length) throw new Error("订单关联诊断分页没有返回剩余行。");
      }
      if (!active) return;
      if (dates.size === 1) {
        const found = [...dates][0];
        setLookupStatus("已从订单关联诊断记录定位信号日：" + found);
        onSignalDateResolved(found);
      } else if (dates.size > 1) setLookupStatus("该订单关联多个信号日；请从日期控件选择要查看的信号日。");
      else setLookupStatus("没有从该订单的诊断记录中定位到信号日；请手动选择信号日。");
    })().catch(error => { if (active) setLookupStatus("按订单号定位信号日失败：" + errorText(error)); });
    return () => { active = false; reads.cancel(); };
  }, [available, experiment.id, experiment.projectId, linkedOrderId, signalDate, symbol]);

  useEffect(() => {
    let active = true;
    const reads = readScope();
    if (!inspectedOrder) { setOrderResults([]); return () => { active = false; reads.cancel(); }; }
    setOrderResults(orderTables.map(item => ({ label: item.label, status: "loading" as const })));
    void Promise.all(orderTables.map(async (item): Promise<OrderResult | null> => {
      if (!item.table) return { label: item.label, status: "unavailable" as const, message: "此实验没有保存对应的数据表。" };
      try {
        let currentOffset = 0, total = 0, columns: string[] = [];
        const matchingRows: JsonObject[] = [];
        do {
          const executionDate = day(inspectedOrder.executionDate);
          const result = await reads.request<TablePage>("experiments.table", {
            projectId: experiment.projectId, experimentId: experiment.id, table: item.table,
            symbol, orderId: inspectedOrder.id, ...(executionDate ? { startDate: executionDate, endDate: executionDate } : {}),
            offset: currentOffset, limit: 200
          });
          if (!active) return null;
          columns = result.columns; total = result.total;
          const idField = idColumn(columns);
          if (!idField) return { label: item.label, status: "unavailable" as const, message: "数据表未提供订单号字段，无法核对这条关联。" };
          matchingRows.push(...result.rows.filter(row => idOf(row) === inspectedOrder.id));
          currentOffset += result.rows.length;
          if (currentOffset >= total) break;
          if (!result.rows.length) throw new Error("订单记录分页没有返回剩余行。");
        } while (active);
        if (!active) return null;
        if (matchingRows.length) return { label: item.label, status: "ready" as const, table: { name: item.label === "实际成交" ? "实际交易" : item.label, columns, rows: matchingRows } };
        if (total === 0) return { label: item.label, status: "empty" as const, message: "该数据表没有返回此订单的记录。" };
        return { label: item.label, status: "unavailable" as const, message: "候选记录中没有匹配的订单号；未显示无法确认关联的行。" };
      } catch (error) { return active ? { label: item.label, status: "error" as const, message: errorText(error) } : null; }
    })).then(results => { if (active) setOrderResults(results.filter((result): result is OrderResult => result !== null)); });
    return () => { active = false; reads.cancel(); };
  }, [experiment.id, experiment.projectId, inspectedOrder?.id, inspectedOrder?.executionDate, orderTables, symbol]);

  const ruleDisplay = (row: R) => {
    const rawIndex = get(row, "ruleIndex", "rule_index");
    const index = typeof rawIndex === "number" && Number.isInteger(rawIndex) ? rawIndex : undefined;
    const displayIndex = index === undefined ? show(rawIndex) : String(index + 1);
    const savedRules = experiment.parameters.rules;
    const savedRule = index !== undefined && Array.isArray(savedRules) ? record(savedRules[index]) : null;
    const name = typeof savedRule?.name === "string" && savedRule.name.trim() ? savedRule.name : "";
    const id = show(get(row, "ruleId", "rule_id"));
    return { title: name ? name + " · #" + displayIndex : "规则 #" + displayIndex, id };
  };
  const exportAll = (format: "csv" | "xlsx") => {
    exporter.run({ projectId: experiment.projectId, experimentId: experiment.id, table: "rule_diagnostics", format }, experiment.id + "-规则诊断." + format);
  };
  const rows = page?.rows ?? [];
  return <section className="r-rule-diagnostics" aria-label="逐条规则诊断">
    <header className="r-diag-heading"><div><h3>逐条规则诊断</h3>
      <p className="r-note">规则判断按信号日归档；成交结果按执行日记录。订单关联展示的是净订单整体结果，不表示某条规则单独造成成交。</p></div>
      {available && typeof rowCount === "number" && Number.isFinite(rowCount) && <span className="r-tag">共 {rowCount.toLocaleString("zh-CN")} 条诊断</span>}
    </header>
    {capabilityStatus === "not_applicable" ? <p role="status">本次实验不适用逐条规则诊断。</p>
      : capabilityStatus === "available" && capability?.version !== 1 ? <p role="status">规则诊断数据版本 {show(capability?.version)} 暂不受当前界面支持。</p>
      : !available ? <p role="status">{capabilityStatus === "available" ? "实验标记了规则诊断可用，但诊断表名称不符合当前接口约定。" : "这份实验没有可读取的规则诊断能力信息；旧实验可能未保存逐条诊断。"}</p>
      : <>
        <div className="r-diag-toolbar">
          <label>信号日<input type="date" aria-label="规则诊断信号日" min={startDate?.slice(0, 10)} max={endDate?.slice(0, 10)} value={signalDate} onChange={event => onSignalDateChange(event.target.value)} /></label>
          <button disabled={exporter.busy} onClick={() => exportAll("csv")}>导出全部诊断 CSV</button>
          <button disabled={exporter.busy} onClick={() => exportAll("xlsx")}>导出全部诊断 Excel</button>
          {page && <span role="status">{page.total.toLocaleString("zh-CN")} 条当日记录</span>}
        </div>
        {!signalDate ? <p role="status">{lookupStatus || "请选择信号日。成交日是实际执行日，不会自动代替信号日。"}</p>
          : failure ? <p role="alert">{failure}</p>
          : loading ? <p role="status">正在读取 {symbol} · {signalDate} 的规则诊断…</p>
          : page && !rows.length ? <p role="status">{symbol} 在信号日 {signalDate} 没有返回规则诊断记录。</p>
          : page && <div className="r-diag-results"><div className="r-diag-list">{rows.map((rawRow, index) => {
            const row = rawRow as R, orderId = idOf(row);
            const executionDate = day(get(row, "executionDate", "execution_date"));
            const skipReason = skip(get(row, "skipReason", "skip_reason")), ruleState = get(row, "ruleState", "rule_state");
            const display = ruleDisplay(row);
            return <article className="r-diag-card" key={show(get(row, "ruleId", "rule_id")) + ":" + show(get(row, "ruleIndex", "rule_index")) + ":" + index}>
              <header><div className="r-diag-titleline"><strong>{display.title}</strong>
                <span className={"r-diag-state " + tone(ruleState)}>{state(ruleState, "rule")}</span><span>{state(get(row, "action"), "action")}</span>
                {skipReason && <span className="r-diag-skip">跳过原因：{skipReason}</span>}</div></header>
              <details className="r-diag-record-id"><summary>记录标识</summary><p>规则 ID：<code>{display.id}</code></p></details>
              <dl className="r-diag-facts">
                <div><dt>信号日</dt><dd>{day(get(row, "date")) || signalDate}</dd></div><div><dt>执行日</dt><dd>{executionDate || "未记录"}</dd></div>
                <div><dt>规则目标权重变化</dt><dd>{weight(get(row, "beforeWeight", "before_weight"))} → {weight(get(row, "targetWeight", "target_weight"))}</dd></div>
                <div><dt>订单状态</dt><dd>{state(get(row, "orderState", "order_state"), "order")}</dd></div>
                <div><dt>请求数量</dt><dd>{quantity(get(row, "requestedQuantity", "requested_quantity"))}</dd></div>
                <div><dt>成交数量</dt><dd>{quantity(get(row, "filledQuantity", "filled_quantity"))}</dd></div>
              </dl>
              <Conditions raw={get(row, "conditionsJson", "conditions_json")} fieldName={fieldName} />
              <Reasons label="组合约束原因" raw={get(row, "constraintReasonsJson", "constraint_reasons_json")} />
              <Reasons label="订单原因" raw={get(row, "orderReasonsJson", "order_reasons_json")} />
              {orderId && <div className="r-diag-order-link"><span>订单号：<code>{orderId}</code></span><button onClick={() => setInspectedOrder({ id: orderId, executionDate })}>查看关联订单记录</button></div>}
            </article>;
          })}</div></div>}
        {page && <div className="r-toolbar r-diag-pagination"><button disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - (page.limit ?? 50)))}>上一页</button>
          <span>{rows.length ? (page.offset + 1) + "–" + (page.offset + rows.length) + " / " + page.total + " 行" : "当前页无记录 · 共 " + page.total + " 行"}</span>
          <button disabled={offset + rows.length >= page.total} onClick={() => setOffset(offset + (page.limit ?? 50))}>下一页</button></div>}
        {exporter.busy && <div className="r-toolbar" role="status"><span>{exporter.saving ? "请选择保存位置…" : exporter.cancelling ? "正在请求中止导出…" : "正在生成完整规则诊断…"}</span>{!exporter.saving && <button disabled={exporter.cancelling} onClick={exporter.cancel}>取消导出</button>}</div>}
        {inspectedOrder && <section className="r-diag-orders" aria-label="关联订单实际记录">
          <header><div><h4>订单整体记录 · <code>{inspectedOrder.id}</code></h4>
            <p className="r-note">{inspectedOrder.executionDate ? "执行日 " + inspectedOrder.executionDate + "。" : ""}同一净订单可能关联多条规则诊断；下表不表示某条规则单独造成订单。</p></div></header>
          <div className="r-diag-order-grid">{orderResults.map(result => <section className="r-diag-order-table" key={result.label}><h5>{result.label}</h5>
            {result.status === "loading" ? <p role="status">正在按订单号核对…</p>
              : result.status === "ready" && result.table ? <DataTable table={result.table} />
              : <p role={result.status === "error" ? "alert" : "status"}>{result.message}</p>}
          </section>)}</div>
        </section>}
      </>}
  </section>;
}
