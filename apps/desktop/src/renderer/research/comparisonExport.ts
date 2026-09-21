import type {ExperimentDetails} from '../../../../../packages/contracts/src/research';
export function comparisonRows(details:ExperimentDetails[]){
 const metrics=[...new Set(details.flatMap(detail=>Object.keys(detail.experiment.metrics)))];
 const columns=['实验名称','实验ID','项目ID','策略ID','研究类型','创建时间','摘要','输入参数（含日期与范围）',...metrics.map(key=>`指标:${key}`)];
 const rows=details.map(({experiment:e})=>[e.name,e.id,e.projectId??'',e.strategyId??'',e.kind,e.createdAt,e.summary,JSON.stringify(e.parameters),...metrics.map(key=>e.metrics[key]??'')]);
 return {columns,rows};
}
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export function comparisonCsv(details:ExperimentDetails[]){
 const {columns,rows}=comparisonRows(details);
 const cell=(value:unknown)=>{const text=String(value??'');return `"${(/^[=+@\-\t\r]/.test(text)&&typeof value!=='number'?"'"+text:text).replace(/"/g,'""')}"`;};
 return '\ufeff'+[columns,...rows].map(row=>row.map(cell).join(',')).join('\r\n');
}
export function comparisonHtml(details:ExperimentDetails[]){
 return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>body{font:13px "Microsoft YaHei",sans-serif;padding:28px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:5px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}section{break-before:page}section:first-of-type{break-before:auto}</style><h1>实验比较 · ${details.length} 个实验</h1><p>范围：当前比较的实验身份、保存指标与完整输入参数。指标保留原始数值单位；不包含完整成交明细或走势，缺失指标留空。</p>${details.map(({experiment:e})=>`<section><h2>${escape(e.name)}</h2><p>实验ID：${escape(e.id)} · 项目ID：${escape(e.projectId)} · 策略ID：${escape(e.strategyId)}</p><p>${escape(e.kind)} · ${escape(e.createdAt)}</p><p>${escape(e.summary)}</p><table><tr><th>指标</th><th>原始值</th></tr>${Object.entries(e.metrics).map(([key,value])=>`<tr><td>${escape(key)}</td><td>${escape(value)}</td></tr>`).join('')}</table><h3>输入参数（含日期与范围）</h3><pre>${escape(JSON.stringify(e.parameters,null,2))}</pre></section>`).join('')}</html>`;
}
