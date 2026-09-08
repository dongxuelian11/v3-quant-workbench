import React, { useEffect, useMemo, useState } from "react";
import type { ExperimentDetails, JsonObject } from "../../../../../packages/contracts/src/research";
import { request, errorText } from "./state";
import { DataTable, Empty, tradeDirection } from "./ui";
import { PriceChart, type TradeMarker } from "./PriceChart";
import type { TablePage } from "./PagedTable";
import { object } from "./configuration";

export function BacktestAssumptions({ detail }: { detail: ExperimentDetails }) {
  if (detail.experiment.kind !== "backtest.run") return null;
  const costs = object(detail.experiment.parameters.costs);
  const percent = (value: unknown) => typeof value === "number" ? `${(value * 100).toLocaleString("zh-CN", { maximumFractionDigits: 4 })}%` : "未记录";
  const revised = detail.details.slippageRounding === "buy_up_sell_down";
  return <details className="r-backtest-assumptions"><summary>本次回测的成交与费用口径</summary>
    <p>T 日收盘后生成信号，下一交易日开盘模拟成交。日线成交近似不包含逐笔撮合与排队。</p>
    <p>买入佣金 {percent(costs.commissionBuy)}；卖出佣金 {percent(costs.commissionSell)}；单笔最低佣金 {typeof costs.minCommission === "number" ? `${costs.minCommission} 元` : "未记录"}。</p>
    <p>印花税：{costs.stampDuty === "historical" ? "按成交日期采用历史卖出税率" : percent(costs.stampDuty)}。过户费：{percent(costs.transferFee)}，为本次固定配置。</p>
    <p>滑点 {percent(costs.slippage)}；{revised ? "原始成交价按 0.01 元取整，买入向上、卖出向下，并限制在当日涨跌停范围内。" : "这是旧成交模型保存的实验；本次规则修正不会重写它，重新运行才能得到修正后的结果。"}</p>
    <p>成交量上限采用信号日已知成交量的 {percent(costs.volumeParticipation)}；费用与未成交原因保存在交易明细中。</p>
    {typeof detail.experiment.parameters.code === "string" && detail.experiment.parameters.code.trim() && <p>该实验使用自定义 Python；代码可访问完整行情，是否引用未来数据需要检查具体实现。</p>}
  </details>;
}

function stockOf(row?: JsonObject) { return String(row?.symbol ?? row?.instrument ?? row?.code ?? ""); }
function dateOf(row?: JsonObject) { return String(row?.date ?? row?.trade_date ?? "").slice(0, 10); }
function marker(row: JsonObject, index?: number): TradeMarker | null {
  const price = row.price ?? row.execution_price ?? row.trade_price;
  const side = tradeDirection(row.side ?? row.direction), date = dateOf(row);
  if (!date || typeof price !== "number" || !Number.isFinite(price) || !side) return null;
  return { id:index === undefined ? undefined : String(index), date, price, side, quantity: typeof row.amount === "number" ? row.amount : undefined,
    adjustedPrice: typeof row.adjustedPrice === "number" ? row.adjustedPrice : undefined };
}

export function BacktestReplay({ detail, initialRow }: { detail: ExperimentDetails; initialRow?: JsonObject }) {
  const { experiment } = detail;
  const stocks = useMemo(() => {
    const saved = detail.details.replayStocks;
    if (Array.isArray(saved)) return saved.flatMap(value => {
      const row = object(value); return typeof row.symbol === "string" ? [{ symbol: row.symbol, name: typeof row.name === "string" ? row.name : "", count: Number(row.tradeCount ?? 0) }] : [];
    });
    // Old imported experiments may only have previews. Do not present them as a complete stock list.
    return [...new Set(detail.tables.flatMap(t => t.rows.map(stockOf)).filter(Boolean))].sort().map(symbol => ({ symbol, name: "", count: 0 }));
  }, [detail]);
  const [symbol, setSymbol] = useState(stockOf(initialRow) || stocks.find(s => s.count > 0)?.symbol || stocks[0]?.symbol || "");
  const [search, setSearch] = useState(""); const [tradedOnly, setTradedOnly] = useState(false);
  const [focusDate, setFocusDate] = useState(dateOf(initialRow)); const [focusedTrade,setFocusedTrade]=useState<TradeMarker|undefined>(initialRow?marker(initialRow)??undefined:undefined);
  const [rows, setRows] = useState<JsonObject[]>([]); const [loading, setLoading] = useState(false); const [failure, setFailure] = useState("");
  const [priceBasis, setPriceBasis] = useState<"raw" | "adjusted">("raw");
  const tradeTable = experiment.artifacts.find(a => a.type === "parquet" && /(?:^|_)(trades?|交易)(\.|$)/i.test(a.name))?.name;
  const range = object(detail.details.dateRange);
  const startDate = typeof range.startDate === "string" ? range.startDate : undefined;
  const endDate = typeof range.endDate === "string" ? range.endDate : undefined;
  const filtered = stocks.filter(s => (!tradedOnly || s.count > 0) && `${s.symbol} ${s.name}`.toLowerCase().includes(search.trim().toLowerCase()));
  const index = filtered.findIndex(s => s.symbol === symbol);
  const current = stocks.find(s => s.symbol === symbol);
  const choose = (next: string) => { setSymbol(next); setFocusDate(""); setFocusedTrade(undefined); };
  useEffect(() => { if (initialRow && stockOf(initialRow)) { setSymbol(stockOf(initialRow)); setFocusDate(dateOf(initialRow));setFocusedTrade(marker(initialRow)??undefined); } }, [initialRow]);
  useEffect(() => {
    let alive = true; setRows([]); setFailure("");
    if (!symbol || !tradeTable) { setLoading(false); return; }
    setLoading(true);
    void (async () => {
      const all: JsonObject[] = []; let offset = 0;
      while (alive) {
        const page = await request<TablePage>("experiments.table", { projectId: experiment.projectId, experimentId: experiment.id, table: tradeTable, symbol, offset, limit: 500 });
        if (!alive) return;
        all.push(...page.rows); offset += page.rows.length;
        if (offset >= page.total) break;
        if (!page.rows.length) throw new Error("成交记录读取中断，请重新打开这个实验。");
      }
      if (alive) setRows(all.sort((a, b) => dateOf(a).localeCompare(dateOf(b))));
    })().catch(e => { if (alive) setFailure(errorText(e)); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [experiment.id, experiment.projectId, symbol, tradeTable]);
  const markers = rows.flatMap((row,index) => { const value = marker(row,index); return value ? [value] : []; });
  const buys = markers.filter(x => x.side === "买入").length, sells = markers.filter(x => x.side === "卖出").length;
  if (!stocks.length) return <Empty title="这个实验尚未保存可回放的股票">回测成交、持仓及目标组合中记录的股票会出现在这里。</Empty>;
  return <section className="r-backtest-replay">
    <div className="r-replay-controls">
      <input aria-label="搜索回测股票" placeholder="搜索股票代码或名称" value={search} onChange={e => setSearch(e.target.value)} />
      <select aria-label="回放股票" value={symbol} onChange={e => choose(e.target.value)}>
        {current && index < 0 && <option value={symbol}>{current.name} {symbol}（当前）</option>}
        {filtered.map(s => <option key={s.symbol} value={s.symbol}>{s.name ? `${s.name} · ` : ""}{s.symbol} · {s.count} 笔成交</option>)}
      </select>
      <button disabled={index <= 0} onClick={() => choose(filtered[index - 1].symbol)}>上一只</button>
      <button disabled={index < 0 || index >= filtered.length - 1} onClick={() => choose(filtered[index + 1].symbol)}>下一只</button>
      <label className="r-check"><input type="checkbox" checked={tradedOnly} onChange={e => setTradedOnly(e.target.checked)} />仅有成交</label>
    </div>
    <div className="r-replay-summary"><strong>{current?.name} {symbol}</strong><span>全部已记录股票 {stocks.length} 只</span><span>{startDate ?? ""} — {endDate ?? ""}</span><span>买入 {buys} 笔 / 卖出 {sells} 笔</span></div>
    {!Array.isArray(detail.details.replayStocks) && <p className="r-note">旧实验只返回预览股票，尚不能确认名单完整。</p>}
    <div className="r-replay-controls"><label>价格口径 <select aria-label="回放价格口径" value={priceBasis} onChange={e => setPriceBasis(e.target.value as "raw" | "adjusted")}><option value="raw">不复权 · 实际成交价</option><option value="adjusted">前复权 · 连续走势</option></select></label><span className="r-note">红色“买”、绿色“卖”；标记来自实际模拟成交，价格已计入滑点。</span></div>
    <PriceChart key={symbol} symbol={symbol} embedded replayMode priceBasis={priceBasis} initialStartDate={startDate} initialEndDate={endDate} focusDate={focusDate || undefined} trades={markers} focusedTrade={focusedTrade} onTradeClick={trade => {setFocusDate(trade.date);setFocusedTrade(trade);}} />
    {failure ? <p role="alert">{failure}</p> : loading ? <p role="status">正在读取这只股票的全部成交…</p> : !rows.length ? <p className="r-note">该股票在本实验中没有实际成交，不绘制买卖标记。未成交原因可在“交易与持仓”中查看。</p> : <div className="r-replay-trades">
      <h3>成交明细 · 点击一行定位买卖点</h3>
      <DataTable table={{ name: "个股交易记录", columns: ["date", "direction", "price", "amount", "value", "cost"], rows }} onRow={row => {setFocusDate(dateOf(row));setFocusedTrade(marker(row,rows.indexOf(row))??undefined);}} />
      {focusDate && <p className="r-note">已定位 {focusDate}；金额为成交价 × 实际股数，费用另列。</p>}
    </div>}
  </section>;
}
