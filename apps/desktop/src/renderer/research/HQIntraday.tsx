import * as echarts from "echarts";
import React, { useEffect, useRef, useState } from "react";
import { useTimeLink } from "./ChartTimeLink";
import type { QuoteStatus } from "../../../../../packages/contracts/src/research";

interface HQRequest { Name: string; PreventDefault: boolean; Request?: { Data?: { symbol?: string[] } }; }
interface HQPaint { IsShow:boolean;Data?:{Data:(number|null)[];DataOffset:number};Source?:{Data:{Time:number;AvPrice:number|null}[]};Draw:()=>void; }
interface HQTitle {ClassName?:string;IsShowAveragePrice:boolean;GetFormatTitle?:(data:unknown)=>{AryText?:{Text?:string;Title?:string}[]}|undefined;}
interface HQInstance { JSChartContainer?:{Draw:()=>void;UpdateFrameMaxMin:()=>void;ChartPaint?:HQPaint[];TitlePaint?:HQTitle[];ExtendChartPaint?:HQTitle[];ChartOperator:(option:Record<string,unknown>)=>void}; SetOption(option: Record<string, unknown>): void; ChangeSymbol(symbol: string): void; OnSize(): void; StopAutoUpdate(): void; ChartDestroy(): void; }
interface HQModule { Chart: { JS_ID:{JSCHART_EVENT_ID:{ON_MOUSE_MOVE:number};JSCHART_OPERATOR_ID:{OP_CORSSCURSOR_GOTO:number}}; JSChart: { Init(node: HTMLElement): HQInstance } }; }
export const hqSymbol = (symbol: string) => /^(SH|SZ)\d{6}$/.test(symbol) ? `${symbol.slice(2)}.${symbol.slice(0, 2).toLowerCase()}` : symbol;
function payload(quote: QuoteStatus | null) {
  const bars = quote?.bars.filter(bar => Number.isFinite(bar.timestamp) && typeof bar.close === "number" && Number.isFinite(bar.close)) ?? [];
  if (!quote || !bars.length) return { stock: [] };
  const lastDate = bars[bars.length - 1].date.slice(0, 10), day = bars.filter(bar => bar.date.startsWith(lastDate));
  return { stock: [{ symbol: hqSymbol(quote.instrument.symbol), name: quote.instrument.name ?? quote.instrument.symbol, date: Number(lastDate.replaceAll("-", "")), yclose: day[0].previousClose ?? null, minute: day.map(bar => ({ time: Number(bar.date.slice(11, 16).replace(":", "")), price: bar.close, open: bar.open, high: bar.high, low: bar.low, vol: bar.volume, amount: bar.amount ?? bar.turnover ?? null, avprice: bar.averagePrice ?? null })) }] };
}
function NativeHQIntraday({ quote, symbol }: { quote: QuoteStatus | null; symbol: string }) {
  const scope=useTimeLink(),link=useRef(scope);link.current=scope;
  const applying=useRef(false),averagePaint=useRef(new WeakSet<HQPaint>()),unitTitles=useRef(new WeakSet<HQTitle>());
  const node = useRef<HTMLDivElement>(null), instance = useRef<HQInstance | null>(null), latest = useRef(quote), currentSymbol = useRef(symbol);
  latest.current = quote?.instrument.symbol===symbol?quote:null; currentSymbol.current = symbol;
  const deliver = (callback: (data: unknown) => void, data: ReturnType<typeof payload>) => {
    const bars = data.stock[0]?.minute ?? [];
    const showAverage = bars.length > 0 && bars.some(bar => typeof bar.avprice === "number" && Number.isFinite(bar.avprice) && bar.avprice > 0);
    const container = instance.current?.JSChartContainer;
    if (container?.ChartPaint?.[1]) container.ChartPaint[1].IsShow = showAverage;
    if (container?.TitlePaint?.[0]) container.TitlePaint[0].IsShowAveragePrice = showAverage;
    container?.ExtendChartPaint?.filter(item => item.ClassName === "MinuteTooltipPaint").forEach(item => { item.IsShowAveragePrice = showAverage; });
    for(const title of [...(container?.TitlePaint??[]),...(container?.ExtendChartPaint??[]).filter(item=>item.ClassName==='MinuteTooltipPaint')]){
      if(!title.GetFormatTitle||unitTitles.current.has(title))continue;
      unitTitles.current.add(title);const format=title.GetFormatTitle.bind(title);
      title.GetFormatTitle=data=>{const result=format(data);const original=latest.current?.coverage?.volumeUnit??'来源单位';const unit=/^(SH|SZ)\d{6}$/.test(currentSymbol.current)?original==='股'?'手':`${original}/100`:original;
        result?.AryText?.forEach(item=>{if(item.Text)item.Text=item.Text.replace(/^量[:：]/,`量(${unit}):`);if(item.Title)item.Title=item.Title.replace(/^(成交量|量)[:：]?$/,`量(${unit}):`);});return result;};
    }
    callback(data);
    // HQ forward-fills missing averages and joins gaps. Restore source missingness,
    // then let its own paint draw each continuous segment separately.
    const paint=container?.ChartPaint?.[1],source=container?.ChartPaint?.[0]?.Source;
    if(paint?.Data&&source){
      const average=new Map(bars.map(bar=>[bar.time,typeof bar.avprice==='number'&&Number.isFinite(bar.avprice)&&bar.avprice>0?bar.avprice:null]));
      source.Data.forEach(bar=>{bar.AvPrice=average.get(bar.Time)??null;});
      paint.Data.Data=source.Data.map(bar=>bar.AvPrice);
      if(!averagePaint.current.has(paint)){
        const draw=paint.Draw.bind(paint);averagePaint.current.add(paint);
        paint.Draw=()=>{const bound=paint.Data;if(!bound||!paint.IsShow)return;const original=bound.Data;try{let start=0;while(start<original.length){while(start<original.length&&original[start]==null)start++;let end=start;while(end<original.length&&original[end]!=null)end++;if(end>start){bound.Data=original.map((value,index)=>index>=start&&index<end?value:null);draw();}start=end+1;}}finally{bound.Data=original;}};
      }
      container?.UpdateFrameMaxMin();container?.Draw();
    }
  };
  const receiver = useRef<((data: ReturnType<typeof payload>) => void) | null>(null), [error, setError] = useState("");
  useEffect(() => {
    let alive = true; let observer: ResizeObserver | undefined;let unlink:(()=>void)|undefined;
    // HQChart's bundled JS engine is loaded only when a time-sharing chart is opened.
    void import("hqchart").then(module => {
      if (!alive || !node.current) return;
      const api = module as unknown as HQModule, chart = api.Chart.JSChart.Init(node.current); instance.current = chart;
      chart.SetOption({ Type: "分钟走势图", Symbol: hqSymbol(currentSymbol.current), IsAutoUpdate: false, IsShowRightMenu: false, IsShowCorssCursor: true, DayCount: 1, Windows: [], EventCallback:[{event:api.Chart.JS_ID.JSCHART_EVENT_ID.ON_MOUSE_MOVE,callback:(_event:unknown,_data:unknown,sender:{GetCurrentKLineData?:()=>{Date:number;Time:number}})=>{if(applying.current)return;const bar=sender?.GetCurrentKLineData?.();if(!bar)return;const date=String(bar.Date),time=String(bar.Time).padStart(4,'0');const timestamp=Date.parse(`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T${time.slice(0,2)}:${time.slice(2)}:00+08:00`);if(link.current)link.current.link.publish(timestamp,link.current.source);}}], MinuteLine: { IsShowAveragePrice: false }, Border: { Left: 55, Right: 55, Top: 20, Bottom: 25 }, NetworkFilter: (request: HQRequest, callback: (data: unknown) => void) => {
        request.PreventDefault = true;
        if (request.Name !== "MinuteChartContainer::RequestMinuteData") { setError(`此图所需数据尚未接入：${request.Name}`); return; }
        const requested = request.Request?.Data?.symbol?.[0];
        receiver.current = data => { if (alive && (!requested || requested === hqSymbol(currentSymbol.current))) deliver(callback, data); };
        receiver.current(payload(latest.current));
      } });
      unlink=link.current?.link.subscribe((timestamp,source)=>{if(source===link.current?.source)return;const date=new Date(timestamp+8*3600000).toISOString().slice(0,10),bars=latest.current?.bars.filter(bar=>bar.date.startsWith(date))??[];let bar: (typeof bars)[number] | undefined;for(const value of bars)if(value.timestamp!=null&&value.timestamp<=timestamp)bar=value;if(!bar)return;applying.current=true;try{chart.JSChartContainer?.ChartOperator({ID:api.Chart.JS_ID.JSCHART_OPERATOR_ID.OP_CORSSCURSOR_GOTO,Date:Number(date.replaceAll('-','')),Time:Number(bar.date.slice(11,16).replace(':',''))});}finally{applying.current=false;}});
      observer = new ResizeObserver(() => chart.OnSize()); observer.observe(node.current); chart.OnSize();
    }).catch(error => { if (alive) setError(String(error)); });
    return () => { alive = false; unlink?.();observer?.disconnect(); receiver.current = null; instance.current?.StopAutoUpdate(); instance.current?.ChartDestroy(); instance.current = null; node.current?.replaceChildren(); };
  }, []);
  useEffect(() => { receiver.current = null; setError(""); instance.current?.ChangeSymbol(hqSymbol(symbol)); }, [symbol]);
  useEffect(() => { receiver.current?.(payload(latest.current)); }, [quote]);
  return <><div ref={node} className="r-intraday-canvas" aria-label={`${symbol} 分时走势图`}/>{error && <p role="alert">{error}</p>}</>;
}

function AbsoluteIntraday({quote,symbol}:{quote:QuoteStatus;symbol:string}) {
  const node=useRef<HTMLDivElement>(null),chart=useRef<echarts.ECharts|null>(null);
  const scope=useTimeLink(),link=useRef(scope),latest=useRef(quote),applying=useRef(false);
  link.current=scope;latest.current=quote;
  useEffect(()=>{
    if(!node.current)return;
    const value=echarts.init(node.current);chart.current=value;
    const currentBars=()=>{const date=latest.current.bars.at(-1)?.date.slice(0,10);return latest.current.bars.filter(bar=>bar.date.startsWith(date??'')&&Number.isFinite(bar.close));};
    const move=(raw:unknown)=>{
      if(applying.current)return;
      const event=raw as {axesInfo?:{axisDim?:string;value?:number|string}[]};
      const axis=event.axesInfo?.find(axis=>axis.axisDim==='x'),bars=currentBars();
      const index=typeof axis?.value==='number'?Math.round(axis.value):bars.findIndex(bar=>bar.date.slice(11,16)===axis?.value);
      const timestamp=bars[index]?.timestamp;
      if(timestamp!=null)link.current?.link.publish(timestamp,link.current.source);
    };
    value.on('updateAxisPointer',move);
    const off=link.current?.link.subscribe((timestamp,source)=>{
      if(source===link.current?.source)return;
      const date=new Date(timestamp+8*3600000).toISOString().slice(0,10),bars=currentBars();let index=-1;
      bars.forEach((bar,i)=>{if(bar.date.startsWith(date)&&bar.timestamp!=null&&bar.timestamp<=timestamp)index=i;});
      if(index<0)return;
      const point=value.convertToPixel({seriesIndex:1},[index,bars[index].close]);
      if(!Array.isArray(point)||!point.every(Number.isFinite))return;
      applying.current=true;
      try{value.dispatchAction({type:'updateAxisPointer',x:point[0],y:point[1]});value.dispatchAction({type:'showTip',seriesIndex:1,dataIndex:index});}
      finally{applying.current=false;}
    });
    const observer=new ResizeObserver(()=>value.resize());observer.observe(node.current);
    return()=>{off?.();value.off('updateAxisPointer',move);observer.disconnect();value.dispose();chart.current=null;};
  },[]);
  useEffect(()=>{const date=quote.bars.at(-1)?.date.slice(0,10);const bars=quote.bars.filter(bar=>bar.date.startsWith(date??'')&&typeof bar.close==='number'&&Number.isFinite(bar.close));chart.current?.setOption({animation:false,tooltip:{trigger:'axis'},axisPointer:{link:[{xAxisIndex:'all'}]},grid:[{left:65,right:16,top:12,bottom:'30%'},{left:65,right:16,top:'76%',bottom:24}],xAxis:[{type:'category',data:bars.map(bar=>bar.date.slice(11,16)),axisLabel:{show:false}},{type:'category',gridIndex:1,data:bars.map(bar=>bar.date.slice(11,16))}],yAxis:[{type:'value',scale:true},{type:'value',gridIndex:1,splitNumber:1,axisLabel:{formatter:(value:number)=>Math.abs(value)>=1e8?`${(value/1e8).toFixed(1)}亿`:Math.abs(value)>=1e4?`${(value/1e4).toFixed(0)}万`:String(value)}}],series:[{name:'来源均价',type:'line',showSymbol:false,connectNulls:false,data:bars.map(bar=>typeof bar.averagePrice==='number'&&Number.isFinite(bar.averagePrice)&&bar.averagePrice>0?bar.averagePrice:null),lineStyle:{width:1.5,color:'#bd8429'}},{name:'价格',type:'line',showSymbol:false,connectNulls:false,data:bars.map(bar=>bar.close),lineStyle:{width:1.5,color:'#267774'}},{name:`成交量（${quote.coverage?.volumeUnit??'来源单位'}）`,type:'bar',xAxisIndex:1,yAxisIndex:1,data:bars.map(bar=>typeof bar.volume==='number'&&Number.isFinite(bar.volume)?bar.volume:null),itemStyle:{color:'#6b9d99'}}]},true);},[quote]);
  return <><span className="r-note" style={{fontSize:11,margin:'0 6px'}}>缺少昨收：显示绝对价格，涨跌幅与昨收参考线不可用。</span><div ref={node} className="r-intraday-canvas" aria-label={`${symbol} 分时绝对价格与成交量`}/></>;
}
export function HQIntraday({quote,symbol}:{quote:QuoteStatus|null;symbol:string}) {
  const current=quote?.instrument.symbol===symbol?quote:null;
  const day=current?.bars.at(-1)?.date.slice(0,10),previous=current?.bars.find(bar=>bar.date.startsWith(day??''))?.previousClose;
  return current?.bars.length&&!(typeof previous==='number'&&Number.isFinite(previous)&&previous>0)?<AbsoluteIntraday quote={current} symbol={symbol}/>:<NativeHQIntraday quote={current} symbol={symbol}/>;
}
