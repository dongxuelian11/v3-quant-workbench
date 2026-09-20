import React, { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { errorText } from "./state";

GlobalWorkerOptions.workerSrc = workerUrl;

/** A single visible page keeps long research PDFs bounded in memory. */
export function ReportPdf({ reportId, page, onPage }: { reportId: string; page: number; onPage: (page: number) => void }) {
  const host = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [width, setWidth] = useState(600), [zoom, setZoom] = useState(1);
  const [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const selectedPage = Math.max(1, Math.min(page, document?.numPages ?? page));
  useEffect(() => {
    let alive = true, task: ReturnType<typeof getDocument> | undefined;
    setDocument(null);setError("");setLoading(true);
    void (async () => {
      const bridge = window.v3Research;
      if (!bridge) throw new Error("桌面原文读取服务不可用。");
      const data = await bridge.readReportDocument(reportId);
      if (!alive) return;
      const base = new URL("./pdf-assets/", window.document.baseURI).href;
      task = getDocument({ data: new Uint8Array(data), cMapUrl: `${base}cmaps/`, cMapPacked: true, standardFontDataUrl: `${base}standard_fonts/`, wasmUrl: `${base}wasm/`, iccUrl: `${base}iccs/`, useWasm: false });
      const pdf = await task.promise;
      if (alive) setDocument(pdf);
    })().catch(e => { if (alive) { setError(errorText(e));setLoading(false); } });
    return () => { alive = false;void task?.destroy(); };
  }, [reportId]);
  useEffect(() => {
    const node = host.current;if (!node) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(200, node.clientWidth - 32)));
    observer.observe(node);return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!document || !canvas.current) return;
    let alive = true, render: RenderTask | undefined;
    const node = canvas.current;
    setLoading(true);setError("");
    void document.getPage(selectedPage).then(async pdfPage => {
      if (!alive) return;
      const original = pdfPage.getViewport({ scale: 1 });
      const viewport = pdfPage.getViewport({ scale: width / original.width * zoom });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      node.width = Math.ceil(viewport.width * ratio);node.height = Math.ceil(viewport.height * ratio);
      node.style.width = `${viewport.width}px`;node.style.height = `${viewport.height}px`;
      render = pdfPage.render({ canvas: node, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
      await render.promise;
      if (alive) setLoading(false);
    }).catch(e => { if (alive) { setError(errorText(e));setLoading(false); } });
    return () => { alive = false;render?.cancel(); };
  }, [document, selectedPage, width, zoom]);
  return <section className="r-report-pdf"><div className="r-toolbar"><button disabled={!document || selectedPage <= 1} onClick={() => onPage(selectedPage - 1)}>上一页</button><label>第 <input aria-label="研报页码" type="number" min={1} max={document?.numPages ?? 1} value={selectedPage} onChange={e => { const value = Number(e.target.value);if (Number.isInteger(value) && value >= 1 && value <= (document?.numPages ?? 1)) onPage(value); }} /> 页 / {document?.numPages ?? "—"}</label><button disabled={!document || selectedPage >= document.numPages} onClick={() => onPage(selectedPage + 1)}>下一页</button><select aria-label="原文缩放" value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={1}>适合宽度</option><option value={1.25}>125%</option><option value={1.5}>150%</option><option value={2}>200%</option></select></div>{error && <p role="alert">原文暂不能显示：{error}</p>}<div ref={host} className="r-report-paper" aria-busy={loading}>{loading && <p role="status">正在读取第 {selectedPage} 页…</p>}<canvas ref={canvas} hidden={!!error} aria-label={`研报原文第 ${selectedPage} 页`} /></div></section>;
}
