import React, { useEffect, useState } from "react";
import type { ExperimentDetails, ExperimentComparison, ExperimentChange, PreviousExperimentComparison } from "../../../../../packages/contracts/src/research";
import { readScope, useResultExport } from "./readCancellation";
import { errorText, useResearch } from "./state";
import { useWorkspace } from "./workspace";
import "./comparison.css";
import { comparisonHtml } from "./comparisonExport";

export const comparisonStatus = { comparable: "记录口径一致", controlled_change: "策略参数有受控变化", incomparable: "不宜直接比较优劣", unknown: "可比性尚无法确认" };
export function savedComparison(detail: ExperimentDetails): ExperimentComparison | null {
  const value = detail.details.comparison;
  if (!value || typeof value !== "object" || Array.isArray(value) || value.version !== 1) return null;
  return value as unknown as ExperimentComparison;
}
const shown = (value: unknown, known = true) => !known ? "未记录" : value === null ? "空值" : typeof value === "object" ? JSON.stringify(value) : String(value);
function Changes({ title, rows }: { title: string; rows: ExperimentChange[] }) {
  if (!rows.length) return null;
  return <details open={rows.length<=3}><summary>{title} · {rows.length} 项</summary><div className="r-comparison-changes"><table><thead><tr><th>项目</th><th>基准实验</th><th>当前实验</th></tr></thead><tbody>{rows.map(row => <tr key={row.field}><th>{row.label}</th><td>{shown(row.before,row.beforeKnown)}</td><td>{shown(row.after,row.afterKnown)}</td></tr>)}</tbody></table></div></details>;
}
export function ComparisonDescription({ value }: { value: ExperimentComparison }) {
  return <div className="r-comparison-description">
    <strong>{comparisonStatus[value.comparability.status] ?? "未知比较状态"}</strong>
    {value.comparability.reasons.length > 0 && <ul>{value.comparability.reasons.map((reason,index) => <li key={`${reason.code}:${index}`}>{reason.message}</li>)}</ul>}
    <p>{value.inputEvidence.message}</p>
    <Changes title="策略与参数变化" rows={value.configurationChanges}/>
    <Changes title="研究范围与口径变化" rows={value.rangeChanges}/>
    <details><summary>本次比较的固定身份与输入证据</summary><p>基准实验：{value.baselineRef.projectId ?? "全局"} / {value.baselineRef.experimentId}<br/>当前实验：{value.ref.projectId ?? "全局"} / {value.ref.experimentId}</p><p>输入快照：基准 {value.inputEvidence.baseline.snapshotStatus === "available" ? "可用" : "未确认可用"}，当前 {value.inputEvidence.current.snapshotStatus === "available" ? "可用" : "未确认可用"}。来源版本一致不代表逐字节相同。</p></details>
  </div>;
}
export function ComparisonNotices({ details }: { details: ExperimentDetails[] }) {
  return <section className="r-comparison-notices" aria-label="比较范围与可比性">{details.map(detail => {
    const value = savedComparison(detail);
    const baseline=value?.ref.projectId===value?.baselineRef.projectId&&value?.ref.experimentId===value?.baselineRef.experimentId;
    return <article className={baseline?"r-comparison-baseline":""} key={`${detail.experiment.projectId}:${detail.experiment.id}`}><h3>{baseline?"比较基准 · ":""}{detail.experiment.name}</h3>{value ? baseline?<p className="r-note">其余实验均与这份固定结果比较。{value.inputEvidence.current.snapshotStatus==="available"?"输入快照可用。":"输入快照未确认可用。"}</p>:<ComparisonDescription value={value}/> : <p role="status">{typeof detail.details.comparisonWarning === "string" ? detail.details.comparisonWarning : "此结果未返回完整比较证据；不能据此认定两个实验的数据与口径相同。"}</p>}</article>;
  })}</section>;
}
export function PreviousComparison({ detail }: { detail: ExperimentDetails }) {
  const w = useWorkspace();
  const [result,setResult] = useState<PreviousExperimentComparison | null>(null), [failure,setFailure] = useState("");
  const [retry,setRetry] = useState(0);
  useEffect(() => {
    const reads=readScope(); let active=true;setResult(null);setFailure("");
    void reads.request<PreviousExperimentComparison>("experiments.previousComparison",{projectId:detail.experiment.projectId,experimentId:detail.experiment.id}).then(value=>{if(active)setResult(value);}).catch(error=>{if(active)setFailure(errorText(error));});
    return ()=>{active=false;reads.cancel();};
  },[detail.experiment.projectId,detail.experiment.id,retry]);
  return <section className="r-previous-comparison" aria-label="相对上一次成功实验的变化"><h3>相对上一次成功实验</h3>
    {failure ? <p role="alert">比较摘要读取失败：{failure} <button onClick={()=>setRetry(value=>value+1)}>重新读取</button></p> : !result ? <p role="status">正在读取同策略、同研究类型的前次结果…</p> : !result.previousRef || !result.comparison ? <p>没有更早的同策略、同研究类型成功实验；本次结果作为后续比较起点。</p> : <><ComparisonDescription value={result.comparison}/><button onClick={()=>w.open({kind:"compare",title:"与前次成功实验比较",experimentRefs:[result.previousRef!,result.currentRef].map(ref=>({kind:"experiment",projectId:ref.projectId??undefined,experimentId:ref.experimentId}))})}>展开两次实验的完整比较</button></>}
    <p className="r-note">只读取已保存结果，不重新运行研究。当前实验 {detail.experiment.id.slice(0,8)} · {new Date(detail.experiment.createdAt).toLocaleString("zh-CN")}</p>
  </section>;
}

export function ComparisonExports({ details }: { details: ExperimentDetails[] }) {
  const s=useResearch();
  const refs=details.map(detail=>({projectId:detail.experiment.projectId??null,experimentId:detail.experiment.id}));
  const exporter=useResultExport(JSON.stringify(refs));const [pdfBusy,setPdfBusy]=useState(false);
  const baselineRef=details[0] ? savedComparison(details[0])?.baselineRef : undefined;
  return <div className="r-toolbar" aria-label="导出当前比较">
    {(["csv","xlsx"] as const).map(format=><button key={format} disabled={details.length<2||exporter.busy||pdfBusy} onClick={()=>exporter.run({experiments:refs,baselineRef,format},`实验比较-${refs.length}项.${format}`)}>导出比较 {format==="csv"?"CSV":"Excel"}</button>)}
    <button disabled={details.length<2||exporter.busy||pdfBusy} onClick={()=>{setPdfBusy(true);void s.act(async()=>{try{const path=await window.v3Research!.exportFile({format:"pdf",html:comparisonHtml(details),suggestedName:`实验比较-${refs.length}项.pdf`});if(path)s.setNotice(`已导出比较：${path}`);}finally{setPdfBusy(false);}});}}>导出比较 PDF</button>
    {exporter.busy&&<span role="status">{exporter.saving?"请选择保存位置…":exporter.cancelling?"正在中止导出…":"正在生成完整比较…"}</span>}
    {exporter.busy&&!exporter.saving&&<button disabled={exporter.cancelling} onClick={exporter.cancel}>取消导出</button>}
  </div>;
}
