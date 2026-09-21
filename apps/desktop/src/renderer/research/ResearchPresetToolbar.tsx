import React, { useEffect, useState } from 'react';
import type { JsonObject, ResearchPreset } from '../../../../../packages/contracts/src/research';
import { errorText, request } from './state';
import { requestText } from './ui';
export const presetLabels={factorProcessing:'因子处理',costs:'交易成本',portfolio:'组合约束',validation:'验证方式'};
export function ResearchPresetToolbar({category,value,onChange}:{category:ResearchPreset['category'];value:JsonObject;onChange:(value:JsonObject)=>void}) {
  const [items,setItems]=useState<ResearchPreset[]>([]),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  async function load(){try{setItems(await request<ResearchPreset[]>('researchPresets.list',{category}));}catch(e){setError(errorText(e));}}
  useEffect(()=>{void load();},[category]);
  return <><div className="r-toolbar"><select aria-label={`${presetLabels[category]}预设`} value={selected} onChange={event=>setSelected(event.target.value)} onFocus={()=>void load()}><option value="">选择{presetLabels[category]}预设</option>{items.map(item=><option key={item.id} value={item.id}>{item.name} · v{item.revision}</option>)}</select><button disabled={!selected||busy} onClick={()=>{const item=items.find(item=>item.id===selected);if(!item)return;onChange({...value,...structuredClone(item.value)});setNotice('已复制到当前草稿；旧研究及预设保持不变。');}}>复制到当前草稿</button><button disabled={busy} onClick={()=>{setBusy(true);setError('');void (async()=>{const name=await requestText('另存研究预设名称',presetLabels[category]);if(!name?.trim())return;const item=await request<ResearchPreset>('researchPresets.save',{preset:{name:name.trim(),category,value}});await load();setSelected(item.id);setNotice('当前配置已另存为预设。');})().catch(e=>setError(errorText(e))).finally(()=>setBusy(false));}}>另存当前配置</button></div>{error&&<p role="alert">{error}</p>}{notice&&<p className="r-note" role="status">{notice}</p>}</>;
}
