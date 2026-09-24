import React, { useEffect, useState } from "react";
import type { JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";
import { errorText, useResearch } from "./state";
import { DataTable, Field, tableLabel } from "./ui";

import { readScope, useResultExport } from "./readCancellation";

export interface TablePage extends ResearchTable { total: number; offset: number; limit: number }
export function PagedExperimentTable({ experimentId, table, onRow, initialSymbol = "", projectId: explicitProjectId }: { projectId?: string; experimentId: string; table: string; initialSymbol?: string; onRow?: (row: JsonObject) => void }) {
  const s = useResearch();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TablePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,setError]=useState("");
  const exporter=useResultExport(`${explicitProjectId??s.project?.id}:${experimentId}:${table}`);
  const [filters, setFilters] = useState({ symbol: initialSymbol, startDate: "", endDate: "" });
  const [draft, setDraft] = useState(filters);
  const limit = 200;
  useEffect(() => {
    let active = true;const reads=readScope();
    setLoading(true);setError("");
    setPage(null);
    void (async () => {
      const result = await reads.request<TablePage>("experiments.table", { projectId: explicitProjectId ?? s.project?.id, experimentId, table, offset, limit, ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) });
      if (active) setPage(result);
    })().catch(failure=>{if(active)setError(errorText(failure));}).finally(() => { if (active) setLoading(false); });
    return () => { active = false; reads.cancel(); };
  }, [explicitProjectId, s.project?.id, experimentId, table, offset, filters, s.revision]);
  useEffect(()=>{setOffset(0);setFilters({symbol:initialSymbol,startDate:"",endDate:""});setDraft({symbol:initialSymbol,startDate:"",endDate:""});},[experimentId,table,explicitProjectId,initialSymbol]);
  const exportAll=(format:"csv"|"xlsx")=>exporter.run({projectId:explicitProjectId??s.project?.id,experimentId,format,...(format==="csv"?{table}:{})},`${tableLabel(table)}.${format}`);
  return <section className="r-paged-table"><details><summary>{tableLabel(table)} · 按证券与日期筛选</summary><form onSubmit={e => { e.preventDefault(); setOffset(0); setFilters({ ...draft, symbol: draft.symbol.trim() }); }}><div className="r-form-grid"><Field label="证券代码"><input value={draft.symbol} onChange={e => setDraft({ ...draft, symbol: e.target.value })} /></Field><Field label="开始日期"><input type="date" value={draft.startDate} onChange={e => setDraft({ ...draft, startDate: e.target.value })} /></Field><Field label="结束日期"><input type="date" value={draft.endDate} onChange={e => setDraft({ ...draft, endDate: e.target.value })} /></Field></div><button disabled={!!draft.startDate && !!draft.endDate && draft.startDate > draft.endDate}>筛选完整表格</button></form></details>{error&&<p role="alert">{error}</p>}{loading ? <p role="status">正在读取 {tableLabel(table)}…</p> : page && <><DataTable table={page} onRow={onRow} /><div className="r-toolbar"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</button><span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.rows.length, page.total)} / ${page.total} 行` : "0 行"}</span><button disabled={offset + page.rows.length >= page.total || !page.rows.length} onClick={() => setOffset(offset + limit)}>下一页</button><span>表内搜索仅筛选当前页</span>{(["csv","xlsx"] as const).map(format=><button key={format} disabled={exporter.busy} onClick={()=>exportAll(format)}>{format==="xlsx"?"导出完整实验 Excel":"导出完整原表 CSV"}</button>)}</div></>}{exporter.busy&&<div className="r-toolbar" role="status"><span>{exporter.saving?"请选择保存位置…":exporter.cancelling?"正在请求中止导出…":"正在生成导出文件…"}</span>{!exporter.saving&&<button disabled={exporter.cancelling} onClick={exporter.cancel}>取消导出</button>}</div>}</section>;
}
