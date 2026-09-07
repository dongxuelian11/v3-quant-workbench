import React, { useEffect, useState } from "react";
import type { JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";
import { request, useResearch } from "./state";
import { DataTable, Field } from "./ui";

export interface TablePage extends ResearchTable { total: number; offset: number; limit: number }
export function PagedExperimentTable({ experimentId, table, onRow }: { experimentId: string; table: string; onRow?: (row: JsonObject) => void }) {
  const s = useResearch();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<TablePage | null>(null);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({ symbol: "", startDate: "", endDate: "" });
  const [draft, setDraft] = useState(filters);
  const limit = 200;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setPage(null);
    void s.act(async () => {
      const result = await request<TablePage>("experiments.table", { projectId: s.project!.id, experimentId, table, offset, limit, ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)) });
      if (active) setPage(result);
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [s.project!.id, experimentId, table, offset, filters, s.revision]);
  return <section className="r-paged-table"><details><summary>{table} · 按证券与日期筛选</summary><form onSubmit={e => { e.preventDefault(); setOffset(0); setFilters({ ...draft, symbol: draft.symbol.trim() }); }}><div className="r-form-grid"><Field label="证券代码"><input value={draft.symbol} onChange={e => setDraft({ ...draft, symbol: e.target.value })} /></Field><Field label="开始日期"><input type="date" value={draft.startDate} onChange={e => setDraft({ ...draft, startDate: e.target.value })} /></Field><Field label="结束日期"><input type="date" value={draft.endDate} onChange={e => setDraft({ ...draft, endDate: e.target.value })} /></Field></div><button disabled={!!draft.startDate && !!draft.endDate && draft.startDate > draft.endDate}>筛选完整表格</button></form></details>{loading ? <p role="status">正在读取 {table}…</p> : page && <><DataTable table={page} onRow={onRow} /><div className="r-toolbar"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>上一页</button><span>{page.total ? `${page.offset + 1}–${Math.min(page.offset + page.rows.length, page.total)} / ${page.total} 行` : "0 行"}</span><button disabled={offset + page.rows.length >= page.total || !page.rows.length} onClick={() => setOffset(offset + limit)}>下一页</button><span>表内搜索仅筛选当前页</span></div></>}</section>;
}
