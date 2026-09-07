import React, { useEffect, useMemo, useRef, useState } from "react";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type SortingState } from "@tanstack/react-table";
import * as echarts from "echarts";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import type { JsonObject, ResearchTable } from "../../../../../packages/contracts/src/research";

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) { return <div className="r-empty"><span className="r-empty-mark" aria-hidden="true">∿</span><h3>{title}</h3><p>{children}</p></div>; }
export function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="r-field"><span>{label}</span>{children}</label>; }
export function Heading({ title, description, children }: { title: string; description?: string; children?: React.ReactNode }) { return <header className="r-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{children}</header>; }
export function valueText(v: unknown) { return v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v); }
export function DataTable({ table, onRow }: { table: ResearchTable; onRow?: (row: JsonObject) => void }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");
  const data = useMemo(() => table.rows.filter(row => !filter || Object.values(row).some(v => valueText(v).toLowerCase().includes(filter.toLowerCase()))), [table.rows, filter]);
  const columns = useMemo(() => table.columns.map(key => ({ id: key, accessorFn: (row: JsonObject) => row[key], header: key, cell: (info: { getValue: () => unknown }) => valueText(info.getValue()) })), [table.columns]);
  const grid = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() });
  return <section className="r-table-section"><div className="r-toolbar"><strong>{table.name}</strong><span>{data.length} 行预览</span><input aria-label={`筛选${table.name}`} placeholder="筛选表格…" value={filter} onChange={e => setFilter(e.target.value)} /></div>{!data.length ? <Empty title="暂无记录">尚未产生可显示的数据。</Empty> : <div className="r-table-scroll"><table><thead>{grid.getHeaderGroups().map(g => <tr key={g.id}>{g.headers.map(h => <th key={h.id}><button onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}{h.column.getIsSorted() === "asc" ? " ↑" : h.column.getIsSorted() === "desc" ? " ↓" : ""}</button></th>)}</tr>)}</thead><tbody>{grid.getRowModel().rows.map(r => <tr key={r.id} onClick={() => onRow?.(r.original)}>{r.getVisibleCells().map((c, i) => <td key={c.id}>{onRow && i === 0 ? <button className="r-link" onClick={e => { e.stopPropagation(); onRow(r.original); }}>{flexRender(c.column.columnDef.cell, c.getContext())}</button> : flexRender(c.column.columnDef.cell, c.getContext())}</td>)}</tr>)}</tbody></table></div>}</section>;
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

