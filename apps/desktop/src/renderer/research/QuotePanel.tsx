import { defaultShortcuts, matchesShortcut, shortcutTargetBlocked } from "./shortcuts";
import React, { useEffect, useRef, useState } from "react";
import type { JobEvent, ScreenFilter, QuoteCatalog, QuoteInstrument, QuoteMembers, QuoteStatus, Watchlist, WorkspacePanel } from "../../../../../packages/contracts/src/research";
import { request, errorText, useResearch } from "./state";
import { useWorkspace, useObjectPanel } from "./workspace";
import { ChartWorkspace } from "./ChartWorkspace";
import { PriceChart } from "./PriceChart";
import { useChartVisible,tradingHours } from "./useIntradayQuote";
import { MarketSnapshotTable } from "./MarketSnapshotTable";
import { Empty, requestText } from "./ui";

const defaultInstrument: QuoteInstrument = { kind: "index", symbol: "SH000300", name: "沪深300" };
const kinds = { stock: "股票", index: "指数", industry: "行业", concept: "概念" };
const keyOf = (value: QuoteInstrument) => `${value.kind}:${value.symbol}`;
const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
const autoAttempts = new Set<string>();
// A category's first fetch survives search changes and component unmounts.
const catalogLoads = new Map<string, Promise<QuoteCatalog>>();
export function ensureQuoteCatalog(kind:string,refresh=false):Promise<QuoteCatalog> {
  const previous=catalogLoads.get(kind);
  if(previous&&!refresh)return previous;
  const pending=(previous?previous.catch(()=>undefined):Promise.resolve()).then(()=>request<QuoteCatalog>("market.instruments",{kind,offset:0,limit:1,...(refresh?{refresh:true}:{loadIfMissing:true})}));
  catalogLoads.set(kind,pending);
  // Retain failures until explicit retry, with no unhandled rejected promise.
  void pending.catch(()=>undefined);
  return pending;
}

export function QuoteDirectory() {
  const w = useWorkspace(),panel=useObjectPanel();const [catalogVersion,setCatalogVersion]=useState(0); const [query, setQuery] = useState(""); const [kind, setKind] = useState("stock"); const [offset, setOffset] = useState(0);
  const [catalog, setCatalog] = useState<QuoteCatalog | null>(null); const [error, setError] = useState("");const [loading,setLoading]=useState(false);
  useEffect(() => { let alive = true;setCatalog(null);setError("");setLoading(true);const timer=setTimeout(()=>{void ensureQuoteCatalog(kind).then(()=>request<QuoteCatalog>("market.instruments",{kind,query,offset,limit:50})).then(value=>{if(alive){setCatalog(value);setError(Object.values(value.errors??{}).join("；"));}}).catch(e=>{if(alive)setError(errorText(e));}).finally(()=>{if(alive)setLoading(false);});},150);return()=>{alive=false;clearTimeout(timer);};},[kind,query,offset,catalogVersion]);
  return <details><summary>证券与指数 · 查看行情</summary><div className="r-toolbar"><select aria-label="数据中心行情类型" value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}>{Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select><input placeholder="名称 / 代码 / 拼音" aria-label="数据中心证券搜索" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }}/></div>{loading&&<p role="status">正在加载目录…</p>}{error && <p role="alert">{error}</p>}{!loading&&!error&&catalog&&!catalog.items.length&&<p className="r-note">{query?"没有匹配证券":"目录暂无记录"}</p>}<div className="r-start-projects">{catalog?.items.map(instrument => <button key={keyOf(instrument)} onClick={() => w.open({ kind: "quote", projectId:panel?.projectId,strategyId:panel?.strategyId,experimentId:panel?.experimentId,date:panel?.date,instrument, symbol:instrument.symbol,title: `${instrument.name ?? instrument.symbol} · 行情` })}>{instrument.name ?? instrument.symbol} · {instrument.symbol}　查看行情 →</button>)}</div><div className="r-toolbar"><button disabled={!offset} onClick={() => setOffset(value => Math.max(0, value - 50))}>上页</button><span>{catalog?.total ?? 0} 项</span><button disabled={loading} onClick={()=>{void ensureQuoteCatalog(kind,true).catch(()=>undefined);setCatalogVersion(v=>v+1);}}>重试 / 刷新目录</button><button disabled={offset + 50 >= (catalog?.total ?? 0)} onClick={() => setOffset(value => value + 50)}>下页</button></div></details>;
}
export function QuotePanel({ panel }: { panel: WorkspacePanel }) {
  const s = useResearch(), w = useWorkspace();
  const root=useRef<HTMLDivElement>(null),visible=useChartVisible(root);
  const instrument = panel.instrument ?? defaultInstrument, instrumentKey = keyOf(instrument);
  const [kind, setKind] = useState<QuoteInstrument["kind"]>(panel.quoteList?.kind??instrument.kind);
  const [categoryViews,setCategoryViews]=useState<Partial<Record<QuoteInstrument["kind"],{query:string;offset:number;watchlistId:string}>>>(panel.quoteList?.categories??{});
  const category=categoryViews[kind]??{query:"",offset:0,watchlistId:""}, {query,offset,watchlistId}=category;
  const setQuery=(query:string)=>setCategoryViews(values=>({...values,[kind]:{...(values[kind]??category),query}}));
  const setOffset=(value:number|((previous:number)=>number))=>setCategoryViews(values=>({...values,[kind]:{...(values[kind]??category),offset:typeof value==="function"?value(values[kind]?.offset??0):value}}));
  const setWatchlistId=(watchlistId:string)=>setCategoryViews(values=>({...values,[kind]:{...(values[kind]??category),watchlistId,offset:0}}));
  const [catalog, setCatalog] = useState<QuoteCatalog | null>(null);
  const [catalogLoading,setCatalogLoading]=useState(false),[catalogError,setCatalogError]=useState("");
  const [quote, setQuote] = useState<QuoteStatus | null>(null), [error, setError] = useState("");
  const [refreshVersion, setRefreshVersion] = useState(0), [busy, setBusy] = useState(false), [job, setJob] = useState<JobEvent | null>(null);
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [memberMinChange, setMemberMinChange] = useState(""), [memberMinAmount, setMemberMinAmount] = useState("");
  const memberFilters: ScreenFilter[] = [...(memberMinChange !== "" ? [{field:"pctChange",operator:"gte" as const,value:Number(memberMinChange)}] : []), ...(memberMinAmount !== "" ? [{field:"amount",operator:"gte" as const,value:Number(memberMinAmount)*10000}] : [])];
  const [members, setMembers] = useState<QuoteMembers | null>(null), [memberOffset, setMemberOffset] = useState(0), [memberQuery, setMemberQuery] = useState("");
  const [memberLoading,setMemberLoading]=useState(false),[memberError,setMemberError]=useState(""),[membersPaused,setMembersPaused]=useState(false);
  const memberRequestKey=`${instrumentKey}:${memberQuery}:${memberMinChange}:${memberMinAmount}:${memberOffset}`;
  const memberCurrent=useRef(memberRequestKey),memberPending=useRef<string|null>(null);memberCurrent.current=memberRequestKey;
  const loadMembers=async(refresh=false)=>{const key=memberRequestKey;if(memberPending.current===key)return;memberPending.current=key;setMemberLoading(true);setMemberError("");try{const value=await request<QuoteMembers>("market.members",{instrument,query:memberQuery,filters:memberFilters,offset:memberOffset,limit:100,refresh});if(memberCurrent.current===key){setMembers(value);if(value.status==="source_error")setMemberError(value.message??"来源未完成，已有成员缓存保留。");}}catch(error){if(memberCurrent.current===key)setMemberError(errorText(error));}finally{if(memberPending.current===key)memberPending.current=null;if(memberCurrent.current===key)setMemberLoading(false);}};
  const [historyStart, setHistoryStart] = useState("2015-01-01"), [listVisible, setListVisible] = useState(panel.quoteList?.visible??true);
  const [listWidth,setListWidth]=useState(panel.quoteList?.width??230);
  const listPersistence=useRef(w.updatePanel);listPersistence.current=w.updatePanel;
  useEffect(()=>{const timer=setTimeout(()=>listPersistence.current(panel.id,{quoteList:{visible:listVisible,width:listWidth,kind,categories:categoryViews}}),180);return()=>clearTimeout(timer);},[panel.id,listVisible,listWidth,kind,categoryViews]);
  useEffect(()=>{const key=(event:KeyboardEvent)=>{if(shortcutTargetBlocked(event)||!matchesShortcut(event,w.preferences.shortcuts?.quoteList??defaultShortcuts.quoteList)||w.active?.id!==panel.id)return;event.preventDefault();setListVisible(value=>!value);};document.addEventListener("keydown",key);return()=>document.removeEventListener("keydown",key);},[w.active?.id,panel.id,w.preferences.shortcuts?.quoteList]);
  function resizeList(event:React.PointerEvent<HTMLDivElement>){event.preventDefault();const handle=event.currentTarget,origin=event.clientX,initial=listWidth;handle.setPointerCapture(event.pointerId);handle.onpointermove=move=>setListWidth(Math.max(180,Math.min(420,initial+move.clientX-origin)));const end=()=>{handle.onpointermove=null;handle.onpointerup=null;handle.onpointercancel=null;};handle.onpointerup=end;handle.onpointercancel=end;}
  const historyJobs = useRef(new Set<string>());
  const historyRanges = useRef(new Set<string>());
  const currentKey = useRef(instrumentKey); currentKey.current = instrumentKey;
  async function importMicrocap(directory: boolean) {
    const target=instrument, key=instrumentKey;
    setBusy(true);setError("");
    try {
      const bridge=window.v3Research;
      if(!bridge)throw new Error("桌面文件选择服务不可用，请在桌面应用中重试。");
      const path=directory?await bridge.chooseDirectory({purpose:"tdx"}):(await bridge.chooseFiles({purpose:"quote"}))[0];
      if(!path)return;
      const value=await request<QuoteStatus>("market.quote.import",{instrument:target,...(directory?{tdxDirectory:path}:{filePath:path})});
      if(currentKey.current!==key)return;
      setQuote(value);setRefreshVersion(v=>v+1);s.setNotice("已读取本机行情文件；不表示在线行情已连接。");
    } catch(e) {if(currentKey.current===key)setError(`导入未完成，已有行情保留：${errorText(e)}`);}
    finally {if(currentKey.current===key)setBusy(false);}
  }
  const pick = (value: QuoteInstrument) => { setJob(null); w.updatePanel(panel.id, { instrument: value, symbol:value.symbol, date:undefined, title: `${value.name ?? value.symbol} · 行情` }); };
  async function refreshCurrentQuote(){if(panel.experimentId||quote?.historyAvailable===false)return;const key=instrumentKey;setBusy(true);setError("");try{const value=await request<QuoteStatus>("market.quote",{instrument,refresh:true});if(currentKey.current!==key)return;setQuote(value);if(value.status==='source_error')setError(value.message??"行情来源未完成");if(value.bars.length)setRefreshVersion(v=>v+1);}catch(error){if(currentKey.current===key)setError(errorText(error));}finally{if(currentKey.current===key)setBusy(false);}}
  async function update(startDate?: string) {
    if(quote?.historyAvailable===false)return;
    const target = instrument, key = instrumentKey; setBusy(true); setError("");
    try { const event = await request<JobEvent>("jobs.submit", { spec: { kind: "data.update", name: `${target.name ?? target.symbol} · 行情更新`, parameters: { quoteOnly: true, instrument: target, ...(startDate ? { startDate } : {}), endDate: today() } } }); if (currentKey.current === key) setJob(event); }
    catch (e) { if (currentKey.current === key) setError(errorText(e)); } finally { if (currentKey.current === key) setBusy(false); }
  }
  const [catalogVersion,setCatalogVersion]=useState(0);
  useEffect(() => {
    let alive = true; setCatalog(null);setCatalogLoading(true);setCatalogError("");
    const timer = setTimeout(() => void (async()=>{
      await ensureQuoteCatalog(kind);if(!alive)return;
      const complete = !!watchlistId && !!query.trim();
      let cursor = complete ? 0 : offset; const items: QuoteInstrument[] = [];
      while(alive){
        const page = await request<QuoteCatalog>("market.instruments",{kind,query,offset:cursor,limit:complete?500:100});
        if(alive&&page.errors&&Object.keys(page.errors).length)setCatalogError(Object.values(page.errors).join("；"));
        if(!alive)return;items.push(...page.items);cursor+=page.items.length;
        if(!complete || cursor>=page.total){setCatalog({...page,items});return;}
        if(!page.items.length)throw new Error("行情目录分页未返回剩余记录，请重试搜索。");
      }
    })().catch(e=>{if(alive)setCatalogError(errorText(e));}).finally(()=>{if(alive)setCatalogLoading(false);}),150);
    return()=>{alive=false;clearTimeout(timer);};
  },[kind,query,offset,watchlistId,catalogVersion]);
  useEffect(() => { void request<Watchlist[]>("watchlists.list").then(setWatchlists).catch(e => setError(errorText(e))); }, []);
  useEffect(()=>{setQuote(null);setError("");setJob(null);setBusy(false);},[instrumentKey]);
  useEffect(() => {
    let alive = true;
    void request<QuoteStatus>("market.quote", { instrument }).then(value => {
      if (!alive) return; setQuote(value);
      const attempt = `${instrumentKey}:${today()}`;
      // At most one daily attempt in this runtime; a successful holiday query has its own timestamp.

    }).catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; };
  }, [instrumentKey, refreshVersion]);
  useEffect(() => {
    if (!job) return;
    const latest = s.jobs.find(event => event.id === job.id);
    if (!latest || latest.updatedAt === job.updatedAt && latest.status === job.status) return;
    setJob(latest);
    if (["completed", "failed", "cancelled", "interrupted"].includes(latest.status) && !historyJobs.current.has(latest.id)) { if(latest.status === "completed")setRefreshVersion(value => value + 1); setError(latest.status === "completed" ? "" : latest.message); }
  }, [s.jobs, job]);
  useEffect(() => { setMemberOffset(0); setMemberQuery(""); }, [instrumentKey]);
  useEffect(()=>{setMembers(null);setMemberError("");if(!["industry","concept"].includes(instrument.kind))return;const timer=setTimeout(()=>void loadMembers(false),150);return()=>clearTimeout(timer);},[memberRequestKey,refreshVersion]);
  useEffect(()=>{if(!visible||membersPaused||memberError||!["industry","concept"].includes(instrument.kind))return;const timer=setInterval(()=>{if(tradingHours())void loadMembers(true);},60000);return()=>clearInterval(timer);},[visible,membersPaused,memberError,memberRequestKey]);
  const selectedList = watchlists.find(value => value.id === watchlistId);
  const items = selectedList ? [...(selectedList.instruments ?? []), ...selectedList.symbols.filter(symbol => !selectedList.instruments?.some(item => item.kind === "stock" && item.symbol === symbol)).map((symbol): QuoteInstrument => ({ kind: "stock", symbol }))].filter(item => item.kind === kind && (!query.trim() || catalog?.items.some(match=>keyOf(match)===keyOf(item)))) : catalog?.items ?? [];
  const running = busy || !!job && ["running", "queued"].includes(job.status);
  async function loadHistory(beforeDate: string) {
    const rangeKey = `${instrumentKey}:${beforeDate}`;
    if (historyRanges.current.has(rangeKey)) return;
    const boundary = new Date(`${beforeDate}T00:00:00Z`);
    const endDate = new Date(boundary.getTime() - 86400000).toISOString().slice(0, 10);
    const startDate = new Date(boundary.getTime() - 366 * 86400000).toISOString().slice(0, 10);
    const targetKey = instrumentKey;
    let waitingId = ""; const received = new Map<string, JobEvent>();
    let settle: (event: JobEvent) => void = () => {};
    const off = window.v3Research?.onEvent(event => { received.set(event.id,event); if(event.id===waitingId)settle(event); });
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError("");setBusy(true);
    try {
      const submitted = await request<JobEvent>("jobs.submit", {spec:{kind:"data.update",name:`${instrument.name??instrument.symbol} · 更早历史`,parameters:{quoteOnly:true,instrument,startDate,endDate}}});
      waitingId=submitted.id;historyJobs.current.add(submitted.id);
      if(currentKey.current===targetKey)setJob(submitted);
      await new Promise<void>((resolve,reject)=>{
        settle=event=>{if(currentKey.current===targetKey)setJob(event);if(event.status==="completed")resolve();else if(["failed","cancelled","interrupted"].includes(event.status))reject(new Error(event.message));};
        timer=setTimeout(()=>reject(new Error("历史行情仍未完成，请在任务栏查看进度并稍后重试。")),180000);
        settle(received.get(submitted.id)??submitted);
      });
      historyRanges.current.add(rangeKey);
      if(currentKey.current===targetKey)setQuote(await request("market.quote",{instrument}));
    } catch(e) {if(currentKey.current===targetKey)setError(errorText(e));throw e;}
    finally{off?.();if(timer)clearTimeout(timer);if(currentKey.current===targetKey)setBusy(false);}
  }
  async function saveMembers() {
    const name = await requestText("带日期的成分名单名称", `${instrument.name ?? instrument.symbol} · ${members?.asOfDate ?? today()}`); if (!name?.trim()) return;
    const rows = []; let cursor = 0; let date: string | null = null; let source = "";
    while (true) { const page = await request<QuoteMembers>("market.members", { instrument, query: memberQuery, filters: memberFilters, offset: cursor, limit: 500, refresh: false }); if (cursor && page.asOfDate !== date) throw new Error("成分日期已变化，请重新保存名单。"); date = page.asOfDate; source = page.source; rows.push(...page.rows); cursor += page.rows.length; if (cursor >= page.total) break; if (!page.rows.length) throw new Error("未读取完整成员名单。"); }
    if (!date) throw new Error("成员名单没有来源日期，暂不能保存带日期名单。");
    await request("watchlists.save", { watchlist: { id: crypto.randomUUID(), name: name.trim(), symbols: rows.map(row => String(row.symbol ?? row.code)), asOfDate: date, source } }); setWatchlists(await request("watchlists.list")); s.setNotice(`已保存 ${rows.length} 只当前成员 · ${date}`);
  }
  return <div ref={root} className="r-quote-workspace"><div className="r-toolbar r-quote-heading"><button title={`证券列表 · ${w.preferences.shortcuts?.quoteList??defaultShortcuts.quoteList}`} aria-keyshortcuts={(w.preferences.shortcuts?.quoteList??defaultShortcuts.quoteList).replace("Ctrl","Control")} aria-expanded={listVisible} onClick={() => setListVisible(value => !value)}>证券列表</button><strong>{instrument.name ?? instrument.symbol}</strong>{instrument.symbol==="TDX880823"&&!panel.experimentId&&<><button disabled={running} onClick={()=>void importMicrocap(false)}>导入行情文件</button><button disabled={running} onClick={()=>void importMicrocap(true)}>读取通达信目录</button></>}<span>{instrument.symbol} · {kinds[instrument.kind]}</span><span className="r-spacer"/><button disabled={running||!!panel.experimentId||quote?.historyAvailable===false} onClick={() => void refreshCurrentQuote()}>{running ? "更新中…" : "更新当前行情"}</button><button onClick={() => void s.act(async () => { const name = await requestText("自选组名称", "我的行情自选"); if (!name?.trim()) return; const existing = watchlists.find(value => value.name === name.trim()); const instruments = [...(existing?.instruments ?? [])]; if (!instruments.some(value => keyOf(value) === instrumentKey)) instruments.push(instrument); await request("watchlists.save", { watchlist: { ...existing, id: existing?.id ?? crypto.randomUUID(), name: name.trim(), instruments, symbols: [...new Set([...(existing?.symbols ?? []), ...(instrument.kind === "stock" ? [instrument.symbol] : [])])] } }); setWatchlists(await request("watchlists.list")); })}>加入自选</button></div>{error && <p role="alert">{error}</p>}<div className="r-quote-content"><aside hidden={!listVisible} style={{width:listWidth}} className="r-quote-list"><nav className="r-subtabs">{Object.entries(kinds).map(([key, title]) => <button key={key} className={kind === key ? "active" : ""} onClick={() => { setKind(key as QuoteInstrument["kind"]); }}>{title}</button>)}</nav><input aria-label="搜索行情证券" placeholder="名称 / 代码 / 拼音" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} /><select aria-label="行情自选组" value={watchlistId} onChange={e => setWatchlistId(e.target.value)}><option value="">全部证券</option>{watchlists.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}</select><div className="r-quote-instruments" role="listbox" aria-label="行情证券" onKeyDown={e => { if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)) return; e.preventDefault(); const buttons = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>("button")); const index = buttons.indexOf(document.activeElement as HTMLButtonElement); const next = e.key === "Home" ? 0 : e.key === "End" ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (e.key === "ArrowDown" ? 1 : -1))); buttons[next]?.focus();if(items[next])pick(items[next]); }}>{items.map(value => <button role="option" aria-selected={keyOf(value) === instrumentKey} key={keyOf(value)} onClick={() => pick(value)}><strong>{value.name ?? value.symbol}</strong><small>{value.symbol}</small></button>)}</div>{catalogLoading&&<p role="status">正在加载{ kinds[kind] }目录…</p>}{catalogError&&<p role="alert">目录来源暂不可用：{catalogError}</p>}{!catalogLoading&&!catalogError&&!items.length&&<p className="r-note">{query.trim()?"没有匹配的证券，请调整搜索。":catalog?.message||"目录暂无记录，可手动重试。"}</p>}<div className="r-toolbar"><button disabled={!offset || !!watchlistId} onClick={() => setOffset(value => Math.max(0, value - 100))}>上页</button><button disabled={!!watchlistId || offset + 100 >= (catalog?.total ?? 0)} onClick={() => setOffset(value => value + 100)}>下页</button><button disabled={catalogLoading} onClick={()=>{void ensureQuoteCatalog(kind,true).catch(()=>undefined);setCatalogVersion(value=>value+1);}}>重试 / 刷新目录</button></div></aside>{listVisible&&<div className="r-quote-list-resize" role="separator" tabIndex={0} aria-label="调整证券列表宽度" aria-orientation="vertical" aria-valuemin={180} aria-valuemax={420} aria-valuenow={listWidth} onPointerDown={resizeList} onKeyDown={event=>{if(event.key!=="ArrowLeft"&&event.key!=="ArrowRight")return;event.preventDefault();setListWidth(value=>Math.max(180,Math.min(420,value+(event.key==="ArrowRight"?10:-10))));}}/>}<div className={`r-quote-chart${quote?.historyAvailable===false?" r-history-unavailable":""}`}><p className="r-note">{quote ? `${quote.coverage.startDate ?? "—"} — ${quote.coverage.endDate ?? "—"} · ${quote.coverage.rows} 根日线 · ${quote.coverage.source} · 价格${quote.coverage.priceUnit} / 成交量${quote.coverage.volumeUnit}` : "正在读取本地行情…"}{job && ` · ${job.message}`}</p>{quote?.historyAvailable===false?<p className="r-note">{quote.message||"此来源仅提供当前板块资料，不提供历史行情。请查看下方当前成员。"}</p>:<ChartWorkspace fixedDate={!!panel.experimentId} onDailyQuote={(target,value)=>{if(keyOf(target)===currentKey.current)setQuote(value);}} annotationProjectId={panel.projectId} instrument={instrument} renderDaily={(target,revision)=><PriceChart asOfDate={panel.experimentId?panel.date:undefined} annotationProjectId={panel.projectId} symbol={target.symbol} instrument={target} embedded onBarSelect={date=>w.updatePanel(panel.id,{date,symbol:target.symbol,instrument:target})} adjustedAvailable={keyOf(target)===instrumentKey&&!!quote&&!(target.kind==='stock'&&quote.coverage.source.startsWith('akshare/eastmoney'))} onHistoryNeeded={keyOf(target)===instrumentKey?loadHistory:undefined} refreshVersion={revision+(keyOf(target)===instrumentKey?refreshVersion:0)} priceBasis={target.kind==='stock'?'adjusted':'raw'}/>}/>}<details hidden={quote?.historyAvailable===false} className="r-quote-history"><summary>历史行情补取</summary><div className="r-toolbar"><input type="date" aria-label="补取历史开始日期" value={historyStart} onChange={e => setHistoryStart(e.target.value)}/><button disabled={running || !historyStart || historyStart > today()} onClick={() => void update(historyStart)}>补取当前标的历史</button><span>保留已存行情，仅更新当前标的。</span></div></details>{["industry", "concept"].includes(instrument.kind) && <details className="r-quote-members" open><summary>当前成员 · {members?.asOfDate ?? "日期未提供"} · {members?.total ?? 0} 只</summary><div className="r-toolbar"><input aria-label="搜索板块成员" value={memberQuery} onChange={e => { setMemberQuery(e.target.value); setMemberOffset(0); }} placeholder="搜索成员"/><input type="number" aria-label="成员最低涨跌幅百分比" placeholder="最低涨跌幅（%）" value={memberMinChange} onChange={e=>{setMemberMinChange(e.target.value);setMemberOffset(0);}}/><input type="number" min={0} aria-label="成员最低成交额万元" placeholder="最低成交额（万元）" value={memberMinAmount} onChange={e=>{setMemberMinAmount(e.target.value);setMemberOffset(0);}}/><button disabled={memberLoading} onClick={()=>void loadMembers(true)}>{memberLoading?"正在读取成员…":"更新成员"}</button><button aria-pressed={membersPaused} onClick={()=>setMembersPaused(value=>!value)}>{membersPaused?"恢复成员刷新":"暂停成员刷新"}</button><span className="r-note">交易时段每60秒 · 隐藏暂停</span><button disabled={!members?.rows.length} onClick={() => void s.act(saveMembers)}>保存带日期名单</button></div>{memberLoading&&<p role="status">正在请求当前成员，已有列表保留…</p>}{memberError&&<p role="alert">{memberError} · 自动重试已暂停，可手动更新。</p>}<p className="r-note">当前成员名单不能代表历史成员。{members?.source} {members?.message}</p>{members?.rows.length ? <MarketSnapshotTable name="当前成员" rows={members.rows} onRow={row => w.open({ kind: "quote", projectId:panel.projectId,strategyId:panel.strategyId,experimentId:panel.experimentId,date:panel.date, title: `${row.name ?? row.symbol} · 行情`, instrument: { kind: "stock", symbol: String(row.symbol ?? row.code), name: String(row.name ?? row.symbol) } })}/> : <Empty title="暂无当前成员资料"/>}<div className="r-toolbar"><button disabled={!memberOffset} onClick={() => setMemberOffset(value => Math.max(0, value - 100))}>上页</button><button disabled={memberOffset + 100 >= (members?.total ?? 0)} onClick={() => setMemberOffset(value => value + 100)}>下页</button></div></details>}</div></div></div>;
}
