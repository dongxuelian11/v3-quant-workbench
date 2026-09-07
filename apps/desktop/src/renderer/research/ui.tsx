import React, { useEffect, useMemo, useRef, useState } from "react";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type SortingState } from "@tanstack/react-table";
import * as echarts from "echarts";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import type { JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) { return <div className="r-empty"><span className="r-empty-mark" aria-hidden="true">∿</span><h3>{title}</h3><p>{children}</p></div>; }
export function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="r-field"><span>{label}</span>{children}</label>; }
export function Heading({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) { return <header className="r-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{children}</header>; }
const fieldLabels: Record<string, string> = { name: "名称", rows: "行数", symbols: "股票数", startDate: "开始日期", endDate: "结束日期", missingValues: "缺失值", date: "日期", trade_date: "成交日期", symbol: "证券", instrument: "证券", code: "证券代码", open: "开盘", high: "最高", low: "最低", close: "收盘", volume: "成交量", amount: "成交额", side: "方向", direction: "方向", price: "成交价", execution_price: "成交价", trade_price: "成交价", quantity: "数量", shares: "股数", weight: "权重", cash: "现金", equity: "资产净值", net_value: "净值", nav: "净值", returns: "收益率", daily_return: "日收益率", benchmark: "基准", drawdown: "回撤", turnover: "换手率", commission: "佣金", fee: "费用", fees: "费用", slippage: "滑点", factor: "因子", factor_id: "因子", quantile: "分组", period: "周期", holding: "持仓", holdings: "持仓", type: "类型", path: "文件路径", createdAt: "创建日期", status: "状态", ic: "IC", rank_ic: "Rank IC", mean_ic: "平均 IC", ic_std: "IC 标准差", icir: "ICIR", total_return: "累计收益率", annual_return: "年化收益率", sharpe: "夏普比率", max_drawdown: "最大回撤" };
const resultMetricLabels: Record<string, string> = {
  estimatedActualWeight: "估算实际权重", riskContribution: "风险贡献", estimatedFees: "估算费用",
  actualWeight: "实际权重", pnl: "持仓损益", returnContribution: "收益贡献", targetRiskContribution: "目标风险贡献", actualRiskContribution: "实际风险贡献", contributionDeviation: "风险贡献偏差", baseValue: "基础值",
  candidates: "候选股票", target_weights: "目标组合", rebalance: "调仓清单", positions: "实际持仓", currentWeight: "当前权重", targetWeight: "目标权重", estimatedPrice: "估算价格", estimatedAmount: "估算金额", sellableQuantity: "可卖数量", costPrice: "成本价", reason: "原因", score: "评分", industry: "行业", tracking_error: "跟踪误差", monthly_returns: "月度收益", risk_contributions: "风险贡献", return_contributions: "收益贡献", industry_weights: "行业权重", trials: "寻优试参", windows: "验证窗口",
  mean: "日均收益", std: "日收益波动", annualized_return: "年化收益", information_ratio: "信息比率",
  total_cost_ratio: "费用比例合计", "valid:mse": "验证 MSE", "valid:r2": "验证 R²",
  "test:mse": "测试 MSE", "test:r2": "测试 R²", best_value: "最优目标值"
};
export function tableLabel(name: string) { return ({ industry: "行业权重", contribution: "持仓收益贡献", risk: "风险贡献", factor_contributions: "因子贡献", benchmark: "策略与基准净值", excess: "超额收益", drawdown: "策略与基准回撤", monthly: "月度收益" } as Record<string, string>)[name] ?? fieldLabel(name); }
export function fieldLabel(key: string, tableName = "") {
  const labels: Record<string, Record<string, string>> = {
    benchmark: { portfolio: "策略净值", benchmark: "基准净值" },
    excess: { return: "日超额收益", cumulative: "累计超额收益" },
    drawdown: { portfolio: "策略回撤", benchmark: "基准回撤" },
    monthly: { portfolio: "策略月收益", benchmark: "基准月收益" }
  };
  if (labels[tableName]?.[key]) return labels[tableName][key];
  if (key === "amount" && /trade|holding|交易|持仓/i.test(tableName)) return "实际股数";
  if (key === "adjustedPrice") return "前复权价格";
  if (key === "adjustedAmount") return "复权数量";
  return resultMetricLabels[key] ?? fieldLabels[key] ?? key;
}
export function tradeDirection(value: unknown): string | null {
  if (value === 1 || value === "1" || typeof value === "string" && /^(buy|买入)$/i.test(value)) return "买入";
  if (value === 0 || value === "0" || typeof value === "string" && /^(sell|卖出)$/i.test(value)) return "卖出";
  return typeof value === "string" && value.trim() ? value : null;
}
export function valueText(v: unknown, key = "") {
  if (v == null) return "—";
  if (key === "side" || key === "direction") return tradeDirection(v) ?? String(v);
  if (typeof v === "number") return Number.isFinite(v) ? v.toLocaleString("zh-CN", { maximumFractionDigits: 6 }) : "—";
  if (typeof v === "object") return JSON.stringify(v);
  const text = String(v);
  if (/^\d{4}-\d{2}-\d{2}(T|\s|$)/.test(text) && /date|At$|time/i.test(key)) return text.slice(0, 10);
  return text;
}
export function DataTable({ table, onRow }: { table: ResearchTable; onRow?: (row: JsonObject) => void }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");
  const data = useMemo(() => table.rows.filter(row => !filter || Object.values(row).some(v => valueText(v).toLowerCase().includes(filter.toLowerCase()))), [table.rows, filter]);
  const columns = useMemo(() => table.columns.map(key => ({ id: key, accessorFn: (row: JsonObject) => row[key], header: fieldLabel(key, table.name), cell: (info: { getValue: () => unknown }) => valueText(info.getValue(), key) })), [table.columns, table.name]);
  const grid = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  return <section className="r-table-section"><div className="r-toolbar"><strong>{tableLabel(table.name)}</strong><span>{data.length} 行预览</span><input aria-label={`筛选${table.name}`} placeholder="筛选表格…" value={filter} onChange={e => setFilter(e.target.value)} /></div>{!data.length ? <Empty title="暂无记录">尚未产生可显示的数据。</Empty> : <div className="r-table-scroll"><table><thead>{grid.getHeaderGroups().map(g => <tr key={g.id}>{g.headers.map(h => <th key={h.id}><button onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}{h.column.getIsSorted() === "asc" ? " ↑" : h.column.getIsSorted() === "desc" ? " ↓" : ""}</button></th>)}</tr>)}</thead><tbody>{grid.getRowModel().rows.map(r => <tr key={r.id} onClick={() => onRow?.(r.original)}>{r.getVisibleCells().map((c, i) => <td key={c.id}>{onRow && i === 0 ? <button className="r-link" onClick={e => { e.stopPropagation(); onRow(r.original); }}>{flexRender(c.column.columnDef.cell, c.getContext())}</button> : flexRender(c.column.columnDef.cell, c.getContext())}</td>)}</tr>)}</tbody></table></div>}</section>;
}
export function Plot({ option, title, onImage }: { option: echarts.EChartsOption; title: string; onImage?: (url: string) => void }) {
  const node = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!node.current) return;
    const instance = echarts.init(node.current, undefined, { renderer: "canvas" }); chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize()); observer.observe(node.current);
    return () => { observer.disconnect(); instance.dispose(); chart.current = null; };
  }, []);
  useEffect(() => { chart.current?.setOption({ color: ["#3564df", "#169b91", "#8c75d7", "#d28c32", "#b75870"], textStyle: { fontFamily: "Segoe UI, Microsoft YaHei, sans-serif" }, ...option }, true); }, [option]);
  return <section className="r-plot"><div className="r-toolbar"><h3>{title}</h3>{onImage && <button onClick={() => { const url = chart.current?.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fff" }); if (url) onImage(url); }}>导出图片</button>}</div><div ref={node} role="img" aria-label={title} style={{ height: 300, width: "100%" }} /></section>;
}
export function CodeEditor({ value, onChange, language = "python", label = "Python 代码" }: { value: string; onChange: (s: string) => void; language?: string; label?: string }) {
  const node = useRef<HTMLDivElement>(null);
  const callback = useRef(onChange); callback.current = onChange;
  const editor = useRef<import("monaco-editor").editor.IStandaloneCodeEditor | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
    void import("monaco-editor").then(monaco => {
      if (disposed || !node.current) return;
      const model = monaco.editor.createModel(value, language);
      const instance = monaco.editor.create(node.current, { model, theme: "vs", automaticLayout: true, minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false, wordWrap: "on", ariaLabel: label });
      editor.current = instance;
      const listener = instance.onDidChangeModelContent(() => callback.current(instance.getValue()));
      cleanup = () => { listener.dispose(); instance.dispose(); model.dispose(); editor.current = null; };
    }).catch(() => { if (!disposed) setFailed(true); });
    return () => { disposed = true; cleanup?.(); };
  }, [language]);
  useEffect(() => { if (editor.current && editor.current.getValue() !== value) editor.current.setValue(value); }, [value]);
  return failed ? <textarea aria-label={label} value={value} onChange={e => onChange(e.target.value)} rows={12} /> : <div className="r-code" ref={node} style={{ height: 260 }} />;
}
