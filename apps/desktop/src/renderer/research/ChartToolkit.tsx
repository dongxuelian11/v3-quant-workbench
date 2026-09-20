import React, { useEffect, useRef, useState } from "react";
import { getSupportedIndicators, registerOverlay, type Chart, type Indicator, type OverlayCreate, type OverlayEvent, type OverlayMode, type Point } from "klinecharts";
import { arrow, fibonacciExtension, measure, rect } from "@klinecharts/extension";

[arrow,fibonacciExtension,measure,rect].forEach(template=>registerOverlay(template));
export interface ChartPreferences { axis:"normal"|"logarithm"; continuous?:boolean; magnet?:OverlayMode; indicators:{name:string;calcParams:number[];paneId:string;height?:number}[] }
const groups=[
  ["线条",[["segment","趋势线"],["rayLine","射线"],["straightLine","直线"],["horizontalStraightLine","水平线"],["verticalStraightLine","垂直线"]]],
  ["通道与比例",[["priceChannelLine","价格通道"],["parallelStraightLine","平行线"],["fibonacciLine","斐波那契回撤"],["fibonacciExtension","斐波那契扩展"]]],
  ["标记与测量",[["rect","区间框"],["arrow","箭头"],["measure","测量"],["research_note","文字批注"]]],
] as const;
const mainIndicators=new Set(["MA","EMA","BOLL","SAR"]);

const indicatorInfo:Record<string,{title:string;parameters?:string[]}>={
  MA:{title:"移动平均"},EMA:{title:"指数移动平均"},BOLL:{title:"布林带",parameters:["计算周期","标准差倍数"]},
  SAR:{title:"抛物线转向",parameters:["初始加速因子（%）","递增步长（%）","加速上限（%）"]},
  VOL:{title:"成交量"},MACD:{title:"指数平滑异同",parameters:["快速周期","慢速周期","信号周期"]},
  KDJ:{title:"随机指标",parameters:["观察周期","K 平滑周期","D 平滑周期"]},RSI:{title:"相对强弱"},
  AVP:{title:"原始成交均价"},EMV:{title:"简易波动指标"}
};
function parameterInfo(name:string,index:number){return {label:indicatorInfo[name]?.parameters?.[index]??`周期 ${index+1}`,integer:name!=="SAR"&&!(name==="BOLL"&&index===1)};}

function measureText(points:Partial<Point>[]) {const [a,b]=points;if(a?.value==null||b?.value==null)return [];const delta=b.value-a.value;return [`价差 ${delta.toFixed(2)}${a.value?`（${(delta/a.value*100).toFixed(2)}%）`:""}`,a.timestamp&&b.timestamp?`${Math.abs(Math.round((b.timestamp-a.timestamp)/86400000))} 个自然日`:""];}
function Icon({kind}:{kind:string}) {const path=kind==="settings"?"M3 7h18M3 17h18M9 3v8M15 13v8":kind==="indicators"?"M3 19V5m0 14h18M6 15l4-7 4 4 6-9":kind==="rect"?"M4 5h16v14H4z":kind==="horizontalStraightLine"?"M3 12h18":kind==="verticalStraightLine"?"M12 3v18":kind==="research_note"?"M4 5h16M12 5v15M8 20h8":kind==="measure"?"M3 17 17 3l4 4L7 21zM8 14l2 2M12 10l2 2":kind.includes("fibonacci")?"M3 5h18M3 10h12M3 14h18M3 19h12":kind.includes("Line")&&kind!=="straightLine"&&kind!=="rayLine"?"M3 15 18 3M6 21 21 9":"M4 20 20 4M4 16v4h4M16 4h4v4";return <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={path}/></svg>;}
export function allocatePaneHeights(current:number[],budget:number):number[] {
  if(!current.length||budget<=0)return current;
  const minimum=Math.min(48,Math.max(1,Math.floor(budget/current.length)));
  const desired=current.map(height=>Math.max(minimum,height));
  if(desired.reduce((sum,height)=>sum+height,0)<=budget)return desired;
  const remaining=Math.max(0,budget-minimum*current.length);
  const weights=desired.map(height=>height-minimum),total=weights.reduce((sum,weight)=>sum+weight,0);
  return desired.map((_,index)=>minimum+Math.floor(total?remaining*weights[index]/total:remaining/current.length));
}

export function useChartToolkit(chart:React.RefObject<Chart|null>,node:React.RefObject<HTMLDivElement|null>,onSave:()=>void) {
  const [panel,setPanel]=useState<"draw"|"settings"|"indicators"|null>(null),[tool,setTool]=useState("");
  const [continuous,setContinuous]=useState(true),[magnet,setMagnet]=useState<OverlayMode>("normal"),[note,setNote]=useState("");
  const [selected,setSelected]=useState<string|null>(null),[version,setVersion]=useState(0),[search,setSearch]=useState("");
  const [axis,setAxis]=useState<"normal"|"logarithm">("normal"),[focused,setFocused]=useState(false);
  const pending=useRef<string|null>(null),hovered=useRef<string|null>(null),restoring=useRef(false);
  const state=useRef({tool,continuous,magnet,note});state.current={tool,continuous,magnet,note};
  const save=useRef(onSave);save.current=onSave;
  const history=useRef<OverlayCreate[][]>([]),position=useRef(-1);
  const palette=useRef<HTMLDivElement>(null),completedId=useRef<string|null>(null);
  useEffect(()=>{const outside=(event:PointerEvent)=>{if(palette.current&&!palette.current.contains(event.target as Node))setPanel(null);};window.addEventListener("pointerdown",outside);return()=>window.removeEventListener("pointerdown",outside);},[]);
  const snapshot=()=>chart.current?.getOverlays().filter(o=>o.groupId!=="research-trade"&&o.id!==pending.current).map(o=>({id:o.id,name:o.name,paneId:o.paneId,points:o.points,extendData:typeof o.extendData==="function"?null:o.extendData??null,styles:o.styles,lock:o.lock,visible:o.visible,mode:o.mode,modeSensitivity:o.modeSensitivity}))??[];
  const changed=()=>{if(restoring.current)return;const next=snapshot();if(JSON.stringify(next)!==JSON.stringify(history.current[position.current])){history.current=history.current.slice(0,position.current+1);history.current.push(structuredClone(next));if(history.current.length>21)history.current.shift();position.current=history.current.length-1;}setVersion(v=>v+1);save.current();};
  const callbacks=(item:OverlayCreate):OverlayCreate=>({...item,...(item.name==="measure"?{extendData:measureText}:{}),
    onMouseEnter:event=>{hovered.current=event.overlay.id;},onMouseLeave:()=>{hovered.current=null;},
    onSelected:event=>{if(completedId.current!==event.overlay.id)setSelected(event.overlay.id);},onClick:event=>{if(completedId.current!==event.overlay.id)setSelected(event.overlay.id);},onDeselected:()=>setSelected(null),
    onPressedMoveEnd:changed,onRemoved:()=>{if(restoring.current)return;const instance=chart.current;setSelected(null);queueMicrotask(()=>{if(chart.current===instance)changed();});},
    onRightClick:event=>{event.preventDefault?.();setSelected(event.overlay.id);},
    onDrawEnd:event=>{completedId.current=event.overlay.id;pending.current=null;hovered.current=event.overlay.id;if(!state.current.continuous){state.current.tool="";setTool("");}changed();}});
  const cancel=()=>{const id=pending.current;pending.current=null;if(id){restoring.current=true;chart.current?.removeOverlay({id});restoring.current=false;}state.current.tool="";setTool("");};
  const install=(items:OverlayCreate[],reset=true)=>{cancel();restoring.current=true;chart.current?.getOverlays().filter(o=>o.groupId!=="research-trade").forEach(o=>chart.current?.removeOverlay({id:o.id}));if(items.length)chart.current?.createOverlay(items.map(callbacks));restoring.current=false;setSelected(null);hovered.current=null;if(reset){history.current=[structuredClone(snapshot())];position.current=0;}setVersion(v=>v+1);};
  const undo=(direction:number)=>{cancel();const next=position.current+direction;if(next<0||next>=history.current.length)return;position.current=next;install(history.current[next],false);save.current();};
  const begin=(event:React.MouseEvent<HTMLDivElement>)=>{if(event.button!==0)return;completedId.current=null;node.current?.focus({preventScroll:true});const name=state.current.tool;if(!name||pending.current||hovered.current)return;const id=chart.current?.createOverlay(callbacks({name,mode:state.current.magnet,...(name==="research_note"?{extendData:state.current.note}:{})}));pending.current=typeof id==="string"?id:null;};
  const choose=(name:string)=>{cancel();state.current.tool=name;setTool(name);setSelected(null);hovered.current=null;setPanel(null);node.current?.focus({preventScroll:true});};
  const modify=(patch:Partial<OverlayCreate>)=>{if(!selected)return;chart.current?.overrideOverlay({id:selected,...patch});changed();};
  const current=chart.current?.getOverlays({id:selected??""}).find(o=>o.groupId!=="research-trade");
  const preferences=():ChartPreferences=>({axis,continuous:state.current.continuous,magnet:state.current.magnet,indicators:(chart.current?.getIndicators()??[]).map(i=>{const pane=chart.current?.getPaneOptions(i.paneId);return {name:i.name,calcParams:i.calcParams.filter((v):v is number=>typeof v==="number"),paneId:i.paneId,...(pane&&!Array.isArray(pane)?{height:pane.height}:{})};})});
  const axisRef=useRef(axis);axisRef.current=axis;
  const prefsSnapshot=():ChartPreferences=>({...preferences(),axis:axisRef.current});
  const layoutFrame=useRef(0);
  useEffect(()=>()=>cancelAnimationFrame(layoutFrame.current),[]);
  const refreshIndicators=(persist=true)=>{const instance=chart.current;fitPanes();setVersion(v=>v+1);cancelAnimationFrame(layoutFrame.current);layoutFrame.current=requestAnimationFrame(()=>{if(!instance||chart.current!==instance)return;fitPanes();setVersion(v=>v+1);if(persist)save.current();});};
  const applyPreferences=(prefs?:ChartPreferences)=>{const instance=chart.current;if(!instance)return;const loaded:ChartPreferences=prefs?.indicators?prefs:{axis:"normal",indicators:[{name:"VOL",calcParams:[],paneId:"research-vol",height:100}]};setContinuous(loaded.continuous??true);setMagnet(loaded.magnet??"normal");instance.removeIndicator();for(const entry of loaded.indicators){if(!getSupportedIndicators().includes(entry.name))continue;instance.createIndicator({name:entry.name,paneId:mainIndicators.has(entry.name)?"candle_pane":entry.paneId,...(entry.calcParams.length?{calcParams:entry.calcParams}:{})},true);if(!mainIndicators.has(entry.name))instance.setPaneOptions({id:entry.paneId,height:entry.height??100,minHeight:50,dragEnabled:true});}axisRef.current=loaded.axis;setAxis(loaded.axis);instance.overrideYAxis({paneId:"candle_pane",name:loaded.axis});refreshIndicators(false);};
  const toggleIndicator=(name:string)=>{const instance=chart.current;if(!instance)return;if(instance.getIndicators({name}).length)instance.removeIndicator({name});else{if(name==="AVP"&&instance.getDataList().some(bar=>typeof bar.turnover!=="number"||!Number.isFinite(bar.turnover)))return;const paneId=mainIndicators.has(name)?"candle_pane":`research-${name.toLowerCase()}`;instance.createIndicator({name,paneId},true);if(paneId!=="candle_pane")instance.setPaneOptions({id:paneId,height:100,minHeight:50,dragEnabled:true});}refreshIndicators();};
  const latest=()=>{chart.current?.setBarSpace(8);chart.current?.setOffsetRightDistance(50);chart.current?.scrollToRealTime();};
  const key=(event:React.KeyboardEvent)=>{if((event.target as HTMLElement).closest("input,textarea,select,[contenteditable=true]"))return;const control=event.ctrlKey||event.metaKey;if(event.key==="Escape"){event.stopPropagation();cancel();setPanel(null);setSelected(null);setFocused(false);}else if(control&&event.key.toLowerCase()==="z"){event.preventDefault();event.stopPropagation();undo(event.shiftKey?1:-1);}else if(event.key==="Delete"&&selected){event.preventDefault();chart.current?.removeOverlay({id:selected});}else if(event.key==="+"||event.key==="="){event.preventDefault();chart.current?.zoomAtCoordinate(1);}else if(event.key==="-"){event.preventDefault();chart.current?.zoomAtCoordinate(-1);}else if(event.key==="End"){event.preventDefault();latest();}};
  const indicatorRows=chart.current?.getIndicators()??[];
  const all=snapshot(),hidden=all.length>0&&all.every(o=>o.visible===false),locked=all.length>0&&all.every(o=>o.lock);
  const batch=(patch:Partial<OverlayCreate>)=>{all.forEach(o=>chart.current?.overrideOverlay({id:o.id,...patch}));changed();};
  const controls=(extra:React.ReactNode)=><div className="r-chart-palette" ref={palette} data-version={version}>
    {([["draw","绘图工具"],["indicators","指标"],["settings","图表设置"]] as const).map(([id,label])=><button key={id} title={label} aria-label={label} className={id==="draw"&&tool?"active":""} aria-expanded={panel===id} onClick={()=>setPanel(value=>value===id?null:id)}><Icon kind={id}/></button>)}
    {indicatorRows.some(i=>{const pane=chart.current?.getPaneOptions(i.paneId);return i.paneId!=="candle_pane"&&pane&&!Array.isArray(pane)&&pane.height<45;})&&<button title="副图空间较小，打开指标后可单独放大查看" aria-label="放大副图查看" onClick={()=>setPanel("indicators")}>↗</button>}
    {tool&&<button aria-label="退出绘图，回到光标" title="退出绘图 · Esc" onClick={cancel}>↖</button>}
    {panel&&<div className="r-chart-popover" role="dialog" aria-label={panel==="draw"?"绘图工具":panel==="indicators"?"指标":"图表设置"}>
      <div className="r-chart-popover-title"><strong>{panel==="draw"?"绘图工具":panel==="indicators"?"指标":"图表设置"}</strong><button aria-label="关闭图表浮层" onClick={()=>setPanel(null)}>×</button></div>
      {panel==="draw"?<><button aria-pressed={!tool} onClick={cancel}>↖ 光标</button>{groups.map(([label,items])=><div key={label}><small>{label}</small><div className="r-drawing-grid">{items.map(([name,title])=><button key={name} disabled={!chart.current?.getDataList().length||name==="research_note"&&!note.trim()} aria-pressed={tool===name} onClick={()=>choose(name)}><Icon kind={name}/>{title}</button>)}</div></div>)}
        <input aria-label="批注文字" placeholder="文字批注内容" value={note} onChange={e=>setNote(e.target.value)}/><label><input type="checkbox" checked={continuous} onChange={e=>{state.current.continuous=e.target.checked;setContinuous(e.target.checked);save.current();}}/>连续绘制</label>
        <label>磁吸<select aria-label="绘图磁吸" value={magnet} onChange={e=>{state.current.magnet=e.target.value as OverlayMode;setMagnet(e.target.value as OverlayMode);save.current();if(pending.current)chart.current?.overrideOverlay({id:pending.current,mode:e.target.value as OverlayMode});}}><option value="normal">关闭</option><option value="weak_magnet">弱磁吸</option><option value="strong_magnet">强磁吸</option></select></label>
        <div className="r-drawing-grid"><button disabled={position.current<=0} onClick={()=>undo(-1)}>撤销</button><button disabled={position.current>=history.current.length-1} onClick={()=>undo(1)}>重做</button><button disabled={!all.length} onClick={()=>batch({visible:hidden})}>{hidden?"显示批注":"隐藏批注"}</button><button disabled={!all.length} onClick={()=>batch({lock:!locked})}>{locked?"解锁批注":"锁定批注"}</button></div><button disabled={!all.length} onClick={()=>{cancel();restoring.current=true;all.forEach(o=>chart.current?.removeOverlay({id:o.id}));restoring.current=false;changed();}}>清除用户批注</button>
      </>:panel==="indicators"?<><input aria-label="搜索指标" placeholder="MA / MACD / RSI…" value={search} onChange={e=>setSearch(e.target.value)}/><div className="r-indicator-list">{getSupportedIndicators().filter(name=>`${name} ${indicatorInfo[name]?.title??""}`.toLowerCase().includes(search.trim().toLowerCase())).sort((a,b)=>Number(!["MA","EMA","BOLL","SAR","VOL","MACD","KDJ","RSI"].includes(a))-Number(!["MA","EMA","BOLL","SAR","VOL","MACD","KDJ","RSI"].includes(b))).map(name=>{const unavailable=name==="AVP"&&(!chart.current?.getDataList().length||chart.current.getDataList().some(bar=>typeof bar.turnover!=="number"));return <button key={name} disabled={unavailable} title={unavailable?"当前行情缺少成交额":indicatorInfo[name]?.title??name} aria-pressed={indicatorRows.some(i=>i.name===name)} onClick={()=>toggleIndicator(name)}>{name}{unavailable?" · 缺成交额":""}</button>;})}</div>{indicatorRows.map(indicator=><IndicatorSettings key={indicator.id} indicator={indicator} chart={chart.current!} changed={()=>refreshIndicators()}/>)}<p className="r-note">拖动分隔线可调整高度。副图较多时，可用下方每幅副图的“单独放大”完整查看，再恢复布局。</p></>:<>
        <div className="r-drawing-grid"><button onClick={()=>chart.current?.zoomAtCoordinate(1)}>放大 ＋</button><button onClick={()=>chart.current?.zoomAtCoordinate(-1)}>缩小 −</button><button onClick={latest}>重置 / 最近</button><button onClick={()=>{setFocused(value=>!value);setPanel(null);}}>{focused?"退出专注":"图表专注"}</button></div>
        <label>价格坐标<select aria-label="价格坐标" value={axis} onChange={e=>{const value=e.target.value as "normal"|"logarithm";axisRef.current=value;setAxis(value);chart.current?.overrideYAxis({paneId:"candle_pane",name:value});save.current();}}><option value="normal">线性</option><option value="logarithm">对数</option></select></label>{extra}<p className="r-note">图表聚焦时：＋/− 缩放，End 最近，Ctrl Z 撤销，Ctrl Shift Z 重做，Delete 删除选中批注，Esc 退出绘图。滚轮缩放，拖动查看历史。</p>
      </>}
    </div>}
    {current&&!panel&&<div className="r-chart-popover r-overlay-properties" role="dialog" aria-label="选中批注属性"><div className="r-chart-popover-title"><strong>批注属性</strong><button aria-label="关闭批注属性" onClick={()=>setSelected(null)}>×</button></div>
      <label>颜色<input type="color" aria-label="批注颜色" value={current.styles?.line?.color??"#267774"} onChange={e=>modify({styles:{...current.styles,line:{...current.styles?.line,color:e.target.value},polygon:{...current.styles?.polygon,borderColor:e.target.value},text:{...current.styles?.text,color:e.target.value},...(current.name==="measure"?{lineColor:e.target.value,tipBackgroundColor:e.target.value}:{})}})}/></label>
      <label>线宽<input aria-label="批注线宽" type="number" min={1} max={8} value={current.styles?.line?.size??1} onChange={e=>modify({styles:{...current.styles,line:{...current.styles?.line,size:Math.max(1,Math.min(8,Number(e.target.value)))},polygon:{...current.styles?.polygon,borderSize:Math.max(1,Math.min(8,Number(e.target.value)))}}})}/></label>
      <select aria-label="批注线型" value={current.styles?.line?.style??"solid"} onChange={e=>modify({styles:{...current.styles,line:{...current.styles?.line,style:e.target.value as "solid"|"dashed",dashedValue:[4,4]},polygon:{...current.styles?.polygon,borderStyle:e.target.value as "solid"|"dashed",borderDashedValue:[4,4]}}})}><option value="solid">实线</option><option value="dashed">虚线</option></select>
      <button onClick={()=>modify({lock:!current.lock})}>{current.lock?"解锁":"锁定"}</button><button onClick={()=>chart.current?.removeOverlay({id:current.id})}>删除批注</button>
    </div>}
  </div>;
  const fitPanes=()=>{const instance=chart.current;if(!instance)return;const panes=instance.getPaneOptions();if(!Array.isArray(panes))return;if(panes.some(p=>p.state==="maximize"))return;const sub=panes.filter(p=>p.id!=="candle_pane"&&p.id!=="x_axis_pane");const budget=(node.current?.clientHeight??400)*.45;const heights=allocatePaneHeights(sub.map(p=>p.height),budget);sub.forEach((pane,index)=>{const height=heights[index];if(Math.abs(pane.height-height)>1)instance.setPaneOptions({id:pane.id,height,minHeight:Math.min(24,height),dragEnabled:true});});};
  const reconcileTurnover=()=>{const instance=chart.current;if(!instance)return;const bars=instance.getDataList();if(!bars.length||bars.some(bar=>typeof bar.turnover!=="number"||!Number.isFinite(bar.turnover))){instance.removeIndicator({name:"AVP"});setVersion(v=>v+1);}};
  return {snapshot,install,changed,callbacks,reconcileTurnover,fitPanes,preferences:prefsSnapshot,applyPreferences,controls,begin,key,focused,tool,cancel,close:()=>setPanel(null),palette};
}
function IndicatorSettings({indicator,chart,changed}:{indicator:Indicator;chart:Chart;changed:()=>void}) {
  const pane=chart.getPaneOptions(indicator.paneId),first=chart.getDataList()[0];
  const firstDate=first?new Date(first.timestamp+8*3600000).toISOString().slice(0,10):"暂无数据";
  return <section className="r-indicator-settings"><strong>{indicator.name}{indicatorInfo[indicator.name]?` · ${indicatorInfo[indicator.name].title}`:""}</strong><button onClick={()=>{chart.removeIndicator({id:indicator.id});changed();}}>移除</button>
    {indicator.name==="AVP"&&<p className="r-note">原始成交均价 · 已加载区间起算：{firstDate}。不随复权口径改变；向前加载历史后起点随之更新。</p>}
    {indicator.calcParams.map((value,index)=>{if(typeof value!=="number")return null;const meta=parameterInfo(indicator.name,index);return <label key={index}>{meta.label}<input aria-label={`${indicator.name} ${meta.label}`} type="number" value={value} min={meta.integer?1:.01} step={meta.integer?1:.01} onChange={e=>{const number=Number(e.target.value);const valid=Number.isFinite(number)&&number>0&&(!meta.integer||Number.isInteger(number));e.currentTarget.setCustomValidity(valid?"":meta.integer?"请输入正整数周期":"请输入大于零的数值");if(!valid)return;const calcParams=[...indicator.calcParams];calcParams[index]=number;chart.overrideIndicator({name:indicator.name,id:indicator.id,calcParams});changed();}} onBlur={e=>e.currentTarget.reportValidity()}/></label>;})}
    {indicator.paneId!=="candle_pane"&&pane&&!Array.isArray(pane)&&<><button onClick={()=>{chart.setPaneOptions({id:indicator.paneId,state:pane.state==="maximize"?"normal":"maximize"});changed();}}>{pane.state==="maximize"?"恢复布局":"单独放大"}</button><label>副图高度<input aria-label={`${indicator.name} 副图高度`} type="number" min={16} max={400} value={pane.height} onChange={e=>{const height=Number(e.target.value);if(!Number.isFinite(height))return;chart.setPaneOptions({id:indicator.paneId,height:Math.max(16,Math.min(400,height)),dragEnabled:true});changed();}}/></label></>}
  </section>;
}
