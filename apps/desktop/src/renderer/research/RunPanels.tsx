import React, { useState } from "react";
import type { JsonObject } from "../../../../../packages/contracts/src/research";
import { useResearch } from "./state";
import { CodeEditor, Field, Heading } from "./ui";

function objectText(text: string): JsonObject { const v: unknown = JSON.parse(text); if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("参数必须是 JSON 对象。"); return v as JsonObject; }
export function FactorSelection() {
  const s = useResearch();
  return <section><div className="r-toolbar"><h3>参与因子</h3><button onClick={() => s.setPage("factors")}>前往因子库 →</button></div><div className="r-chips">{s.factors.map(f => <label key={f.id}><input type="checkbox" checked={s.selectedFactors.includes(f.id)} onChange={() => s.setSelectedFactors(ids => ids.includes(f.id) ? ids.filter(id => id !== f.id) : [...ids, f.id])} />{f.name}</label>)}</div><p className="r-note">已选 {s.selectedFactors.length} 个因子。计算与校验由研究服务完成。</p></section>;
}
export function StrategyPanel({ run = false }: { run?: boolean }) {
  const s = useResearch();
  const saved = (s.project!.settings.backtest ?? {}) as JsonObject;
  const [template, setTemplate] = useState(String(saved.template ?? "multi_factor"));
  const [topN, setTopN] = useState(Number(saved.topN ?? 30)); const [rebalance, setRebalance] = useState(String(saved.rebalance ?? "weekly"));
  const [capital, setCapital] = useState(Number(saved.capital ?? 1000000));
  const [buy, setBuy] = useState(Number(saved.commissionBuy ?? 0.0003)); const [sell, setSell] = useState(Number(saved.commissionSell ?? 0.0003));
  const [minFee, setMinFee] = useState(Number(saved.minFee ?? 5)); const [slippage, setSlippage] = useState(Number(saved.slippage ?? 0.001));
  const [weights, setWeights] = useState(JSON.stringify(saved.weights ?? {}, null, 2));
  const [code, setCode] = useState(String(saved.code ?? "")); const [model, setModel] = useState(String(saved.modelExperimentId ?? ""));
  const parameters = (): JsonObject => ({ template, factorIds: s.selectedFactors, weights: objectText(weights), topN, rebalance, capital, commissionBuy: buy, commissionSell: sell, minFee, slippage, ...(model ? { modelExperimentId: model } : {}), ...(code.trim() ? { code } : {}) });
  const save = async () => { const p = parameters(); await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, backtest: p } }); return p; };
  return <div className="r-page"><Heading title={run ? "策略回测" : "策略模板"} description="多头组合 · 参数可调整。每次运行保存独立实验及输入参数。" /><div className="r-form-grid"><Field label="组合模板"><select value={template} onChange={e => setTemplate(e.target.value)}><option value="single_factor">单因子排序</option><option value="multi_factor">多因子加权</option><option value="model_score">模型评分</option></select></Field><Field label="持仓数量"><input type="number" min={1} value={topN} onChange={e => setTopN(Number(e.target.value))} /></Field><Field label="调仓频率"><select value={rebalance} onChange={e => setRebalance(e.target.value)}><option value="daily">每日</option><option value="weekly">每周</option><option value="monthly">每月</option></select></Field><Field label="初始资金（元）"><input type="number" min={1} value={capital} onChange={e => setCapital(Number(e.target.value))} /></Field></div>
    {template === "model_score" ? <Field label="模型实验"><select value={model} onChange={e => setModel(e.target.value)}><option value="">选择已完成的模型实验</option>{s.experiments.filter(e => e.kind === "model.train").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field> : <FactorSelection />}
    <details open={run}><summary>交易成本与权重</summary><div className="r-form-grid"><Field label="买入佣金比例"><input type="number" min={0} step={0.0001} value={buy} onChange={e => setBuy(Number(e.target.value))} /></Field><Field label="卖出佣金比例"><input type="number" min={0} step={0.0001} value={sell} onChange={e => setSell(Number(e.target.value))} /></Field><Field label="最低佣金（元）"><input type="number" min={0} value={minFee} onChange={e => setMinFee(Number(e.target.value))} /></Field><Field label="滑点比例"><input type="number" min={0} step={0.0001} value={slippage} onChange={e => setSlippage(Number(e.target.value))} /></Field></div><Field label="因子权重 JSON（留空对象使用后端默认权重）"><textarea rows={3} value={weights} onChange={e => setWeights(e.target.value)} /></Field></details>
    <details><summary>Python 策略编辑</summary><p className="r-note">代码提交到后端执行；后端不支持的代码接口会返回明确错误。</p><CodeEditor value={code} onChange={setCode} /></details><div className="r-toolbar"><button onClick={() => void s.act(async () => { await save(); s.setNotice("策略参数已保存"); })}>保存参数</button><button className="r-primary" disabled={topN < 1 || capital <= 0 || (template === "model_score" ? !model : !s.selectedFactors.length)} onClick={() => void s.act(async () => { await s.submit("backtest.run", await save()); })}>运行回测</button></div><Optimization target="backtest" getParameters={parameters} disabled={topN < 1 || capital <= 0 || (template === "model_score" ? !model : !s.selectedFactors.length)} /></div>;
}
export function ModelPanel() {
  const s = useResearch(); const saved = (s.project!.settings.model ?? {}) as JsonObject;
  const [model, setModel] = useState(String(saved.model ?? "lightgbm"));
  const dateKeys = ["trainStart", "trainEnd", "validStart", "validEnd", "testStart", "testEnd"] as const;
  const labels = ["训练开始", "训练结束", "验证开始", "验证结束", "测试开始", "测试结束"];
  const [dates, setDates] = useState<Record<string, string>>(() => Object.fromEntries(dateKeys.map(k => [k, String(saved[k] ?? "")])));
  const [horizon, setHorizon] = useState(Number(saved.labelHorizon ?? 5));
  const [hyper, setHyper] = useState(JSON.stringify(saved.hyperparameters ?? {}, null, 2));
  const parameters = (): JsonObject => ({ model, factorIds: s.selectedFactors, ...dates, labelHorizon: horizon, hyperparameters: objectText(hyper) });
  const ordered = dateKeys.every(k => dates[k]) && dates.trainStart <= dates.trainEnd && dates.trainEnd < dates.validStart && dates.validStart <= dates.validEnd && dates.validEnd < dates.testStart && dates.testStart <= dates.testEnd;
  return <div className="r-page"><Heading title="模型训练" description="按时间分离训练、验证与测试；寻优只使用验证区间。" /><div className="r-form-grid"><Field label="模型"><select value={model} onChange={e => setModel(e.target.value)}><option value="lightgbm">LightGBM</option><option value="ridge">Ridge</option></select></Field><Field label="预测周期（交易日）"><input type="number" min={1} value={horizon} onChange={e => setHorizon(Number(e.target.value))} /></Field>{dateKeys.map((key, i) => <Field key={key} label={labels[i]}><input type="date" value={dates[key]} onChange={e => setDates({ ...dates, [key]: e.target.value })} /></Field>)}</div>{!ordered && <p className="r-note">请填写完整、互不重叠的训练 → 验证 → 测试区间。</p>}<FactorSelection /><details><summary>高级模型参数</summary><Field label="超参数 JSON"><textarea rows={7} value={hyper} onChange={e => setHyper(e.target.value)} /></Field></details><div className="r-toolbar"><button onClick={() => void s.act(async () => { await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, model: parameters() } }); s.setNotice("模型设置已保存"); })}>保存设置</button><button className="r-primary" disabled={!ordered || !s.selectedFactors.length || horizon < 1} onClick={() => void s.act(async () => { const p = parameters(); await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, model: p } }); await s.submit("model.train", p); })}>训练模型</button></div><Optimization target="model" getParameters={parameters} disabled={!ordered || !s.selectedFactors.length} /></div>;
}
interface SearchRow { key: string; type: "choices" | "int" | "float"; choices: string; low: number; high: number; step: string; log: boolean }
function Optimization({ target, getParameters, disabled = false }: { target: "backtest" | "model"; getParameters: () => JsonObject; disabled?: boolean }) {
  const s = useResearch(); const [sampler, setSampler] = useState("grid"); const [trials, setTrials] = useState(20);
  const [rows, setRows] = useState<SearchRow[]>([{ key: target === "backtest" ? "topN" : getParameters().model === "ridge" ? "hyperparameters.alpha" : "hyperparameters.learning_rate", type: "choices", choices: "", low: 0, high: 1, step: "", log: false }]);
  const update = (index: number, patch: Partial<SearchRow>) => setRows(items => items.map((r, i) => i === index ? { ...r, ...patch } : r));
  const searchSpace = (): JsonObject => {
    const result: JsonObject = {};
    for (const row of rows) {
      const key = row.key.trim(); if (!key || key in result) throw new Error("搜索参数名不能为空或重复。");
      if (sampler === "grid" || row.type === "choices") {
        const choices = row.choices.split(/[,，]/).map(v => v.trim()).filter(Boolean).map(v => { try { return JSON.parse(v); } catch { return v; } });
        if (!choices.length) throw new Error(`请填写 ${key} 的候选值。`); result[key] = choices;
      } else {
        if (row.low >= row.high || row.log && row.low <= 0) throw new Error(`${key} 的范围无效。`);
        if (row.step && Number(row.step) <= 0) throw new Error(`${key} 的步长必须大于零。`);
        result[key] = { type: row.type, low: row.low, high: row.high, ...(row.step ? { step: Number(row.step) } : {}), log: row.log };
      }
    }
    return result;
  };
  return <details><summary>参数寻优 · 网格 / TPE</summary><div className="r-form-grid"><Field label="搜索方法"><select value={sampler} onChange={e => setSampler(e.target.value)}><option value="grid">网格搜索</option><option value="tpe">TPE 自动优化</option></select></Field><Field label="试验次数"><input type="number" min={1} value={trials} onChange={e => setTrials(Number(e.target.value))} /></Field></div>{rows.map((row, i) => <div className="r-search-row" key={i}><div className="r-form-grid"><Field label="参数名称"><input value={row.key} onChange={e => update(i, { key: e.target.value })} /></Field>{sampler === "tpe" && <Field label="搜索类型"><select value={row.type} onChange={e => update(i, { type: e.target.value as SearchRow["type"] })}><option value="choices">候选值</option><option value="int">整数范围</option><option value="float">连续范围</option></select></Field>}</div>{sampler === "grid" || row.type === "choices" ? <Field label="候选值（逗号分隔）"><input value={row.choices} onChange={e => update(i, { choices: e.target.value })} placeholder={target === "backtest" ? "例如：10,20,30" : "例如：0.01,0.05,0.1"} /></Field> : <div className="r-form-grid"><Field label="下限"><input type="number" value={row.low} onChange={e => update(i, { low: Number(e.target.value) })} /></Field><Field label="上限"><input type="number" value={row.high} onChange={e => update(i, { high: Number(e.target.value) })} /></Field><Field label="步长（可选）"><input type="number" min={0} value={row.step} onChange={e => update(i, { step: e.target.value })} /></Field><label className="r-check"><input type="checkbox" checked={row.log} onChange={e => update(i, { log: e.target.checked })} />对数搜索</label></div>}<button disabled={rows.length === 1} onClick={() => setRows(items => items.filter((_, n) => n !== i))}>移除此参数</button></div>)}<div className="r-toolbar"><button onClick={() => setRows(items => [...items, { key: "", type: "choices", choices: "", low: 0, high: 1, step: "", log: false }])}>添加搜索参数</button><button className="r-primary" disabled={disabled || trials < 1} onClick={() => void s.act(() => s.submit("optimize.run", { target, sampler, trials, baseParameters: getParameters(), searchSpace: searchSpace() }))}>开始寻优</button></div></details>;
}


