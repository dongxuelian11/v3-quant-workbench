import React,{useEffect,useState} from 'react';
import type {QuoteCatalog} from '../../../../../packages/contracts/src/research';
import {errorText,request} from './state';
import {useWorkspace} from './workspace';
export function CommandStockSearch({query,close}:{query:string;close:()=>void}){
 const w=useWorkspace(),[catalog,setCatalog]=useState<QuoteCatalog|null>(null),[error,setError]=useState('');
 useEffect(()=>{let alive=true;setCatalog(null);setError('');if(!query.trim())return;const timer=setTimeout(()=>{void request<QuoteCatalog>('market.instruments',{kind:'stock',query:query.trim(),offset:0,limit:10}).then(value=>{if(alive)setCatalog(value);}).catch(e=>{if(alive)setError(errorText(e));});},180);return()=>{alive=false;clearTimeout(timer);};},[query]);
 if(!query.trim())return null;
 return <div className="r-tool-list" aria-label="本地证券搜索结果">{error&&<p role="alert">{error}</p>}{catalog?.items.map(instrument=><button key={instrument.symbol} onClick={()=>{w.open({kind:'quote',instrument,title:`${instrument.name??instrument.symbol} · 行情`});close();}}>{instrument.name??instrument.symbol}<span>{instrument.symbol}</span></button>)}{catalog&&!catalog.items.length&&<p className="r-note">本地证券目录没有匹配项。</p>}</div>;
}
