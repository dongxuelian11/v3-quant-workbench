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
  targetExposure: "目标仓位（比例，0–1）", estimatedCash: "估算现金（元）",
  estimatedActualWeight: "估算实际权重", riskContribution: "风险贡献", estimatedFees: "估算费用",
  actualWeight: "实际权重", pnl: "持仓损益", returnContribution: "收益贡献", targetRiskContribution: "目标风险贡献", actualRiskContribution: "实际风险贡献", contributionDeviation: "风险贡献偏差", baseValue: "基础值",
  candidates: "候选股票", target_weights: "目标组合", rebalance: "调仓清单", positions: "实际持仓", currentWeight: "当前权重", targetWeight: "目标权重", estimatedPrice: "估算价格", estimatedAmount: "估算金额", sellableQuantity: "可卖数量", costPrice: "成本价", reason: "原因", score: "评分", industry: "行业", tracking_error: "跟踪误差", monthly_returns: "月度收益", risk_contributions: "风险贡献", return_contributions: "收益贡献", industry_weights: "行业权重", trials: "寻优试参", windows: "验证窗口",
  mean: "日均收益", std: "日收益波动", annualized_return: "年化收益（算术）", excess_annualized_return: "年化超额收益（算术）", benchmark_total_return: "基准累计收益", information_ratio: "信息比率",
  total_cost_ratio: "费用比例合计", "valid:mse": "验证 MSE", "valid:r2": "验证 R²",
  "test:mse": "测试 MSE", "test:r2": "测试 R²", best_value: "最优目标值"
};
export function tableLabel(name: string) { return ({ industry: "行业权重", contribution: "持仓收益贡献", risk: "风险贡献", factor_contributions: "因子贡献", benchmark: "策略与基准净值", excess: "超额收益", drawdown: "策略与基准回撤", monthly: "月度收益" } as Record<string, string>)[name] ?? fieldLabel(name); }
export function fieldLabel(key: string, tableName = "") {
  const labels: Record<string, Record<string, string>> = {
    指数: { open: "开盘（点）", high: "最高（点）", low: "最低（点）", close: "收盘（点）", preclose: "昨收（点）" },
    benchmark: { portfolio: "策略净值", benchmark: "基准净值" },
    excess: { return: "日超额收益", cumulative: "累计超额收益" },
    drawdown: { portfolio: "策略回撤", benchmark: "基准回撤" },
    monthly: { portfolio: "策略月收益", benchmark: "基准月收益" }
  };
  if (labels[tableName]?.[key]) return labels[tableName][key];
  if (/trade|交易/i.test(tableName) && key === "value") return "成交金额（元）";
  if (/trade|交易/i.test(tableName) && key === "cost") return "交易费用（元）";
  if (key === "amount" && /trade|holding|交易|持仓/i.test(tableName)) return "实际股数";
  if (key === "adjustedPrice") return "前复权价格";
  if (key === "adjustedAmount") return "复权数量";
  const marketLabels: Record<string,string> = { observedStocks:"已覆盖股票数",changeCoveredStocks:"涨跌幅覆盖数",advances:"上涨家数",declines:"下跌家数",turnoverAmount:"成交额",fundNetAmount:"主力净流入",fundCoveredStocks:"资金流覆盖数",stocks:"股票数",meanChangeRatio:"平均涨跌幅",count:"家数",preclose:"昨收",rawClose:"收盘价（元）",close:"复权收盘价",volume:"成交量（股）",changeRatio:"涨跌幅（比例）",industry:"行业",pettm:"市盈率TTM",pbmrq:"市净率",fund_net_amount:"主力净流入（元）",fund_net_ratio:"主力净流入占比",chip_cost:"估算筹码平均成本（元）",chip_benefit:"估算获利比例",chip_cost_deviation:"原始价格偏离筹码成本",lhb_flag:"当日上榜",lhb_count:"当日上榜原因数",lhb_net_amount:"龙虎榜净买入（元）",financials:"财务",factors:"因子",flow:"资金流",chips:"筹码",events:"龙虎榜",seats:"机构 / 营业部",peTTM:"市盈率TTM",pbMRQ:"市净率",roeAvg:"平均净资产收益率",npMargin:"净利率",gpMargin:"毛利率",netProfit:"净利润（元）",epsTTM:"每股收益TTM",MBRevenue:"主营收入（元）",pubDate:"公告日期",statDate:"报告期",announcementDate:"公告日期",reportDate:"报告期",factorSource:"因子来源",factorProcessing:"处理口径",strategy_contributions:"策略贡献",allocation:"资金占比",targetWeight:"目标权重",netAmount:"净金额（元）",buyAmount:"买入金额（元）",sellAmount:"卖出金额（元）",detailType:"明细类型",listingDate:"上市日期",advancing:"上涨家数",declining:"下跌家数",unchanged:"平盘家数",total:"证券数" };
  return resultMetricLabels[key] ?? marketLabels[key] ?? fieldLabels[key] ?? key;
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
const priceFields = new Set(["rawClose","rawOpen","rawHigh","rawLow","rawPreclose","preclose","close","open","high","low","price","execution_price","trade_price","costPrice","estimatedPrice","adjustedPrice","chip_cost","chip_low70","chip_high70","chip_low90","chip_high90","epsTTM"]);
const moneyFields = new Set(["turnoverAmount","fundNetAmount","netProfit","MBRevenue","cash","equity","estimatedCash","estimatedAmount","netAmount","buyAmount","sellAmount","pnl","commission","fee","fees","estimatedFees"]);
const shareFields = new Set(["volume","totalShare","liqaShare","quantity","shares","sellableQuantity"]);
const fractionFields = new Set(["meanChangeRatio","changeRatio","chip_benefit","chip_concentration70","chip_concentration90","chip_cost_deviation","roeAvg","npMargin","netProfitMargin","gpMargin","YOYEquity","YOYAsset","YOYNI","YOYEPSBasic","YOYPNI","YOYRevenue","YOYLiability","liabilityToAsset","CAToAsset","NCAToAsset","tangibleAssetToAsset","CFOToOR","CFOToNP","CFOToGr","CFOToSales","CFOToAsset","CFOToProfit","weight","currentWeight","targetWeight","actualWeight","estimatedActualWeight","allocation","targetExposure","return","returns","daily_return","total_return","annual_return","max_drawdown","drawdown","turnover"]);
export function tableNumber(value: unknown, key: string): number | null {
  const known = priceFields.has(key) || moneyFields.has(key) || shareFields.has(key) || fractionFields.has(key) || /_amount(?:5|20)?$|_ratio(?:5|20)?$/.test(key) || ["amount","rawTurn","turn","pctChg","peTTM","pettm","pbMRQ","pbmrq","psTTM","pcfNcfTTM","currentRatio","quickRatio","cashRatio","assetToEquity","ebitToInterest"].includes(key);
  if (!known || value == null || typeof value === "string" && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
  const number = typeof value === "number" || typeof value === "string" ? Number(value) : NaN;
  return Number.isFinite(number) ? number : null;
}
export function tableValue(value: unknown, key: string, tableName = "") {
  if (/trade|交易/i.test(tableName) && ["value", "cost"].includes(key) && typeof value === "number") return value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (["symbol","code","instrument"].includes(key)) return value == null ? "—" : String(value);
  if (/date|At$|time/i.test(key)) return valueText(value, key);
  const number = tableNumber(value,key); if (number === null) return valueText(value,key);
  const compact = (unit: string) => Math.abs(number) >= 1e12 ? `${(number/1e12).toFixed(2)}万亿${unit}` : Math.abs(number) >= 1e8 ? `${(number/1e8).toFixed(2)}亿${unit}` : Math.abs(number) >= 1e4 ? `${(number/1e4).toFixed(2)}万${unit}` : `${number.toLocaleString("zh-CN",{maximumFractionDigits:unit==="股"?0:2})}${unit}`;
  if (shareFields.has(key) || key === "amount" && /trade|holding|交易|持仓/i.test(tableName)) return compact("股");
  if (priceFields.has(key)) return number.toFixed(2);
  if (moneyFields.has(key) || key === "amount" || /_amount(?:5|20)?$/.test(key)) return compact("元");
  if (fractionFields.has(key) || /_ratio(?:5|20)?$/.test(key)) return `${(number*100).toFixed(2)}%`;
  if (["rawTurn","turn","pctChg"].includes(key)) return `${number.toFixed(2)}%`;
  return number.toLocaleString("zh-CN",{maximumFractionDigits:2});
}
/** Print wide records in column groups; all rows and columns remain in the report. */
export function tableReportHtml({ title, table, description }: { title: string; table: ResearchTable; description: string }): string {
  const escape=(value:unknown)=>String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]!));
  const locator=table.columns.filter(key=>["symbol","instrument","code","date","trade_date","announcementDate","pubDate","reportDate","statDate"].includes(key)).slice(0,3);
  const remaining=table.columns.filter(key=>!locator.includes(key)); const groups:string[][]=[];
  for(let index=0;index<remaining.length;index+=6)groups.push([...locator,...remaining.slice(index,index+6)]);
  if(!groups.length)groups.push(locator);
  const sections=groups.map((columns,index)=>`<section><h1>${escape(title)}</h1><p>${escape(description)}</p><h2>列组 ${index+1} / ${groups.length} · ${columns.length} 列 · ${table.rows.length} 行</h2><table><thead><tr>${columns.map(key=>`<th>${escape(table.fieldLabels?.[key]??fieldLabel(key,table.name))}</th>`).join("")}</tr></thead><tbody>${table.rows.map(row=>`<tr>${columns.map(key=>`<td class="${tableNumber(row[key],key)!==null?"number":""}">${escape(tableValue(row[key],key,table.name))}</td>`).join("")}</tr>`).join("")}</tbody></table></section>`).join("");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>@page{size:A4 landscape;margin:12mm}*{box-sizing:border-box}body{margin:0;color:#202733;font:9.5pt "Microsoft YaHei","Segoe UI",sans-serif;line-height:1.5}h1{font-size:17pt;margin:0 0 5mm}h2{font-size:11pt;margin:4mm 0 3mm}p{font-size:9pt;color:#596574;margin:0 0 3mm}section+section{break-before:page}table{width:100%;border-collapse:collapse;table-layout:fixed}thead{display:table-header-group}th,td{border:0.2mm solid #d6dce4;padding:2mm;text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:normal}th{font-weight:600;background:#edf1f6}tr{break-inside:avoid}.number{text-align:right;font-variant-numeric:tabular-nums}</style></head><body>${sections}</body></html>`;
}
export function DataTable({ table, onRow }: { table: ResearchTable; onRow?: (row: JsonObject) => void }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");
  const [selectedRow, setSelectedRow] = useState(0);
  const data = useMemo(() => table.rows.filter(row => !filter || Object.values(row).some(v => valueText(v).toLowerCase().includes(filter.toLowerCase()))), [table.rows, filter]);
  const columns = useMemo(() => table.columns.map(key => ({ id: key, accessorFn: (row: JsonObject) => tableNumber(row[key], key) ?? row[key], header: table.fieldLabels?.[key] ?? fieldLabel(key, table.name), cell: (info: { getValue: () => unknown }) => tableValue(info.getValue(), key, table.name) })), [table.columns, table.name, table.fieldLabels]);
  const grid = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  return <section className="r-table-section"><div className="r-toolbar"><strong>{tableLabel(table.name)}</strong><span>{data.length} 行预览</span><input aria-label={`筛选${table.name}`} placeholder="筛选表格…" value={filter} onChange={e => setFilter(e.target.value)} /></div>{!data.length ? <Empty title="暂无记录">尚未产生可显示的数据。</Empty> : <div className="r-table-scroll" tabIndex={onRow ? 0 : undefined} aria-label={onRow ? `${table.name}，方向键选择，回车查看` : undefined} onKeyDown={e => { if (!onRow) return; const rows = grid.getRowModel().rows; if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const next = Math.max(0, Math.min(rows.length - 1, selectedRow + (e.key === "ArrowDown" ? 1 : -1))); setSelectedRow(next); if (rows[next]) onRow(rows[next].original); } else if (e.key === "Enter" && rows[selectedRow]) { e.preventDefault(); onRow(rows[selectedRow].original); } }}><table><thead>{grid.getHeaderGroups().map(g => <tr key={g.id}>{g.headers.map(h => <th key={h.id}><button onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}{h.column.getIsSorted() === "asc" ? " ↑" : h.column.getIsSorted() === "desc" ? " ↓" : ""}</button></th>)}</tr>)}</thead><tbody>{grid.getRowModel().rows.map((r, index) => <tr key={r.id} className={onRow && selectedRow === index ? "selected" : ""} onClick={() => { setSelectedRow(index); onRow?.(r.original); }}>{r.getVisibleCells().map((c, i) => <td key={c.id} className={typeof c.getValue() === "number" ? "r-number" : undefined}>{onRow && i === 0 ? <button className="r-link" onClick={e => { e.stopPropagation(); onRow(r.original); }}>{flexRender(c.column.columnDef.cell, c.getContext())}</button> : flexRender(c.column.columnDef.cell, c.getContext())}</td>)}</tr>)}</tbody></table></div>}</section>;
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
  useEffect(() => { chart.current?.setOption({ color: ["#3564df", "#169b91", "#8c75d7", "#d28c32", "#b75870"], textStyle: { fontFamily: "Segoe UI, Microsoft YaHei, sans-serif", color: getComputedStyle(document.documentElement).color }, ...option }, true); }, [option]);
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

interface TextPromptRequest { title: string; initial: string; resolve: (value: string | null) => void; }
/** Electron does not implement window.prompt; this stays inside the renderer. */
export function requestText(title: string, initial = ""): Promise<string | null> {
  return new Promise(resolve => window.dispatchEvent(new CustomEvent<TextPromptRequest>("v3-text-prompt", { detail: { title, initial, resolve } })));
}
export function TextPromptHost() {
  const [prompt, setPrompt] = useState<TextPromptRequest | null>(null);
  const current = useRef<TextPromptRequest | null>(null); const dialog = useRef<HTMLDialogElement>(null); const input = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  useEffect(() => {
    const receive = (event: Event) => { const next = (event as CustomEvent<TextPromptRequest>).detail; current.current?.resolve(null); current.current = next; setValue(next.initial); setPrompt(next); };
    window.addEventListener("v3-text-prompt", receive);
    return () => { window.removeEventListener("v3-text-prompt", receive); current.current?.resolve(null); current.current = null; };
  }, []);
  useEffect(() => { if (prompt) { dialog.current?.showModal(); input.current?.focus(); input.current?.select(); } }, [prompt]);
  function finish(result: string | null) { const active = current.current; current.current = null; dialog.current?.close(); setPrompt(null); active?.resolve(result); }
  if (!prompt) return null;
  return <dialog ref={dialog} className="r-dialog r-text-prompt" aria-labelledby="r-text-prompt-title" onCancel={event => { event.preventDefault(); finish(null); }}><form onSubmit={event => { event.preventDefault(); if (value.trim()) finish(value.trim()); }}><h2 id="r-text-prompt-title">{prompt.title}</h2><Field label="名称"><input ref={input} autoFocus value={value} onChange={event => setValue(event.target.value)} /></Field><div className="r-toolbar"><button type="button" onClick={() => finish(null)}>取消</button><button className="r-primary" type="submit" disabled={!value.trim()}>确定</button></div></form></dialog>;
}
