import React, { useState } from "react";
import type { JsonObject } from "../../../../../packages/contracts/src/research";
import { useResearch } from "./state";
import { CodeEditor, Field, Heading } from "./ui";
import { completeStrategy, completeModel, object, factorProcessing, PortfolioEditor, CostsEditor, ValidationEditor, validateDates, NumberSetting, ChoiceSetting, validationDefaults } from "./configuration";

function datesValid(dates: JsonObject) { try { validateDates(dates); return true; } catch { return false; } }
function objectText(text: string): JsonObject { const v: unknown = JSON.parse(text); if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("参数必须是 JSON 对象。"); return v as JsonObject; }
function savedCustomFactors(settings: JsonObject): { id: string; name: string; expression: string }[] {
  if (!Array.isArray(settings.customFactors)) return [];
  return settings.customFactors.flatMap(factor => {
    if (!factor || typeof factor !== "object" || Array.isArray(factor)) return [];
    return typeof factor.id === "string" && typeof factor.name === "string" && typeof factor.expression === "string"
      ? [{ id: factor.id, name: factor.name, expression: factor.expression }] : [];
  });
}
export function FactorSelection() {
  const s = useResearch();
  const factors = [...s.factors, ...savedCustomFactors(s.project!.settings)];
  return <section><div className="r-toolbar"><h3>参与因子</h3><button onClick={() => s.setPage("factors")}>前往因子库 →</button></div><div className="r-chips">{factors.map(f => <label key={f.id}><input type="checkbox" checked={s.selectedFactors.includes(f.id)} onChange={() => s.setSelectedFactors(ids => ids.includes(f.id) ? ids.filter(id => id !== f.id) : [...ids, f.id])} />{f.name}</label>)}</div><p className="r-note">已选 {s.selectedFactors.length} 个因子。计算与校验由研究服务完成。</p></section>;
}
export function StrategyPanel({ run = false }: { run?: boolean }) {
  const s = useResearch();
  const saved = completeStrategy(s.project!.settings);
  const [template, setTemplate] = useState(String(saved.template ?? "multi_factor"));
  const [topN, setTopN] = useState(Number(saved.topN ?? 30)); const [rebalance, setRebalance] = useState(String(saved.rebalance ?? "weekly"));
  const [capital, setCapital] = useState(Number(saved.capital ?? 1000000));
  const [portfolio, setPortfolio] = useState(object(saved.portfolio)); const [costs, setCosts] = useState(object(saved.costs));
  const [benchmark, setBenchmark] = useState(String(object(s.project!.settings.backtest).benchmark ?? (s.project!.universe.source === "csi500" ? "csi500" : "csi300")));
  const [weights, setWeights] = useState<JsonObject>(object(saved.weights));
  const [code, setCode] = useState(String(saved.code ?? "")); const [model, setModel] = useState(String(saved.modelExperimentId ?? ""));
  const parameters = (): JsonObject => ({ template, factorIds: s.selectedFactors, customFactors: savedCustomFactors(s.project!.settings).filter(f => s.selectedFactors.includes(f.id)), weights, topN, rebalance, capital, portfolio, costs, benchmark, factorProcessing: factorProcessing(s.project!.settings), ...(model ? { modelExperimentId: model } : {}), ...(code.trim() ? { code } : {}) });
  const save = async () => { const p = parameters(); await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, backtest: p } }); return p; };
  return <div className="r-page"><Heading title={run ? "策略回测" : "策略模板"} description="多头组合 · 参数可调整。每次运行保存独立实验及输入参数。" /><div className="r-form-grid"><Field label="组合模板"><select value={template} onChange={e => setTemplate(e.target.value)}><option value="single_factor">单因子排序</option><option value="multi_factor">多因子加权</option><option value="model_score">模型评分</option></select></Field><Field label="持仓数量"><input type="number" min={1} value={topN} onChange={e => setTopN(Number(e.target.value))} /></Field><Field label="调仓频率"><select value={rebalance} onChange={e => setRebalance(e.target.value)}><option value="daily">每日</option><option value="weekly">每周</option><option value="monthly">每月</option></select></Field><Field label="初始资金（元）"><input type="number" min={1} value={capital} onChange={e => setCapital(Number(e.target.value))} /></Field></div>
    {template === "model_score" ? <Field label="模型实验"><select value={model} onChange={e => setModel(e.target.value)}><option value="">选择已完成的模型实验</option>{s.experiments.filter(e => e.kind === "model.train").map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></Field> : <FactorSelection />}
    <Field label="比较基准"><select value={benchmark} onChange={e => setBenchmark(e.target.value)}><option value="csi300">沪深300</option><option value="csi500">中证500</option></select></Field>
    {template === "multi_factor" && <section><h3>因子权重</h3><div className="r-form-grid">{s.selectedFactors.map(id => <Field key={id} label={s.factors.find(f => f.id === id)?.name ?? savedCustomFactors(s.project!.settings).find(f => f.id === id)?.name ?? id}><input type="number" step="any" value={weights[id] == null ? "" : Number(weights[id])} placeholder="默认权重" onChange={e => { const next = { ...weights }; if (e.target.value === "") delete next[id]; else next[id] = Number(e.target.value); setWeights(next); }} /></Field>)}</div></section>}
    <PortfolioEditor value={portfolio} onChange={setPortfolio} /><details open={run}><summary>交易成本与成交限制</summary><CostsEditor value={costs} onChange={setCosts} /></details>
    <details><summary>Python 策略编辑</summary><p className="r-note">代码提交到后端执行；后端不支持的代码接口会返回明确错误。</p><CodeEditor value={code} onChange={setCode} /></details><div className="r-toolbar"><button onClick={() => void s.act(async () => { await save(); s.setNotice("策略参数已保存"); })}>保存参数</button><button className="r-primary" disabled={topN < 1 || capital <= 0 || (template === "model_score" ? !model : !s.selectedFactors.length)} onClick={() => void s.act(async () => { await s.submit("backtest.run", await save()); })}>运行回测</button></div><Optimization target="backtest" getParameters={parameters} disabled={topN < 1 || capital <= 0 || (template === "model_score" ? !model : !s.selectedFactors.length)} /></div>;
}
export function ModelPanel() {
  const s = useResearch(); const saved = completeModel(s.project!.settings);
  const [model, setModel] = useState(String(saved.model ?? "lightgbm"));
  const dateKeys = ["trainStart", "trainEnd", "validStart", "validEnd", "testStart", "testEnd"] as const;
  const labels = ["训练开始", "训练结束", "验证开始", "验证结束", "测试开始", "测试结束"];
  const [dates, setDates] = useState<Record<string, string>>(() => Object.fromEntries(dateKeys.map(k => [k, String(saved[k] ?? "")])));
  const [horizon, setHorizon] = useState(Number(saved.labelHorizon ?? 5));
  const [validation, setValidation] = useState(object(saved.validation)); const [labelMode, setLabelMode] = useState(String(saved.labelMode));
  const [hyper, setHyper] = useState(JSON.stringify(saved.hyperparameters ?? {}, null, 2));
  const parameters = (): JsonObject => ({ model, factorIds: s.selectedFactors, customFactors: savedCustomFactors(s.project!.settings).filter(f => s.selectedFactors.includes(f.id)), ...dates, validation, labelMode, factorProcessing: factorProcessing(s.project!.settings), labelHorizon: horizon, hyperparameters: { ...(model === "ridge" ? { alpha: 1 } : { learning_rate: .1, num_leaves: 31, n_estimators: 100 }), ...objectText(hyper) } });
  const ordered = datesValid(dates);
  return <div className="r-page"><Heading title="模型训练" description="按时间分离训练、验证与测试；寻优只使用验证区间。" /><div className="r-form-grid"><Field label="模型"><select value={model} onChange={e => { setModel(e.target.value); setHyper(JSON.stringify(e.target.value === "ridge" ? { alpha: 1 } : { learning_rate: .1, num_leaves: 31, n_estimators: 100 }, null, 2)); }}><option value="lightgbm">LightGBM</option><option value="ridge">Ridge</option></select></Field><Field label="预测周期（交易日）"><input type="number" min={1} value={horizon} onChange={e => setHorizon(Number(e.target.value))} /></Field><Field label="收益标签"><select value={labelMode} onChange={e => setLabelMode(e.target.value)}><option value="next_open">下一开盘起算（交易标签）</option><option value="close">收盘到收盘（研究标签）</option></select></Field></div><ValidationEditor value={validation} onChange={setValidation} dates={dates} onDates={v => setDates(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(x ?? "")])))} />{!ordered && <p className="r-note">日期可全部留空，或填写完整且依次分离的三个区间。</p>}<div className="r-form-grid">{(model === "ridge" ? [["alpha", "正则强度", 1]] : [["learning_rate", "学习率", .1], ["num_leaves", "叶子数", 31], ["n_estimators", "迭代轮数", 100]]).map(([key, label, fallback]) => <Field key={String(key)} label={String(label)}><input type="number" min={0} step="any" value={(() => { try { return Number(objectText(hyper)[String(key)] ?? fallback); } catch { return ""; } })()} onChange={e => { try { setHyper(JSON.stringify({ ...objectText(hyper), [String(key)]: Number(e.target.value) }, null, 2)); } catch { s.setError("请先修正高级参数 JSON。"); } }} /></Field>)}</div><FactorSelection /><details><summary>高级模型参数</summary><Field label="超参数 JSON"><textarea rows={7} value={hyper} onChange={e => setHyper(e.target.value)} /></Field></details><div className="r-toolbar"><button onClick={() => void s.act(async () => { await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, model: parameters() } }); s.setNotice("模型设置已保存"); })}>保存设置</button><button className="r-primary" disabled={!ordered || !s.selectedFactors.length || horizon < 1} onClick={() => void s.act(async () => { const p = parameters(); await s.save({ settings: { ...s.project!.settings, selectedFactors: s.selectedFactors, model: p } }); await s.submit("model.train", p); })}>训练模型</button></div><Optimization key={model} target="model" getParameters={parameters} disabled={!ordered || !s.selectedFactors.length} /></div>;
}
interface SearchRow { key: string; type: "choices" | "int" | "float"; choices: string; low: number; high: number; step: string; log: boolean }
function Optimization({ target, getParameters, disabled = false }: { target: "backtest" | "model"; getParameters: () => JsonObject; disabled?: boolean }) {
  const s = useResearch(); const [validation, setValidation] = useState<JsonObject>({ ...validationDefaults }); const [dates, setDates] = useState<Record<string, string>>({ trainStart: "", trainEnd: "", validStart: "", validEnd: "", testStart: "", testEnd: "" }); const [objective, setObjective] = useState(target === "model" ? "valid:mse" : "valid:information_ratio"); const [sampler, setSampler] = useState("grid"); const [trials, setTrials] = useState(20);
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
  return <details><summary>参数寻优 · 网格 / TPE</summary><Field label="验证集目标"><select value={objective} onChange={e => setObjective(e.target.value)}>{(target === "model" ? [["valid:mse", "验证集 MSE"], ["valid:ic", "验证集 IC"]] : [["valid:information_ratio", "验证集信息比率"], ["valid:annualized_return", "验证集年化收益"], ["valid:sharpe", "验证集夏普比率"]]).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field><p className="r-note">寻优使用下方独立验证窗口；测试集不参与选参。完成后在实验结果中明确应用最佳参数，再运行独立测试。</p><ValidationEditor value={validation} onChange={setValidation} dates={dates} onDates={v => setDates(Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(x ?? "")])))} /><div className="r-form-grid"><Field label="搜索方法"><select value={sampler} onChange={e => setSampler(e.target.value)}><option value="grid">网格搜索</option><option value="tpe">TPE 自动优化</option></select></Field><Field label="试验次数"><input type="number" min={1} value={trials} onChange={e => setTrials(Number(e.target.value))} /></Field></div>{rows.map((row, i) => <div className="r-search-row" key={i}><div className="r-form-grid"><Field label="参数名称"><input value={row.key} onChange={e => update(i, { key: e.target.value })} /></Field>{sampler === "tpe" && <Field label="搜索类型"><select value={row.type} onChange={e => update(i, { type: e.target.value as SearchRow["type"] })}><option value="choices">候选值</option><option value="int">整数范围</option><option value="float">连续范围</option></select></Field>}</div>{sampler === "grid" || row.type === "choices" ? <Field label="候选值（逗号分隔）"><input value={row.choices} onChange={e => update(i, { choices: e.target.value })} placeholder={target === "backtest" ? "例如：10,20,30" : "例如：0.01,0.05,0.1"} /></Field> : <div className="r-form-grid"><Field label="下限"><input type="number" value={row.low} onChange={e => update(i, { low: Number(e.target.value) })} /></Field><Field label="上限"><input type="number" value={row.high} onChange={e => update(i, { high: Number(e.target.value) })} /></Field><Field label="步长（可选）"><input type="number" min={0} value={row.step} onChange={e => update(i, { step: e.target.value })} /></Field><label className="r-check"><input type="checkbox" checked={row.log} onChange={e => update(i, { log: e.target.checked })} />对数搜索</label></div>}<button disabled={rows.length === 1} onClick={() => setRows(items => items.filter((_, n) => n !== i))}>移除此参数</button></div>)}<div className="r-toolbar"><button onClick={() => setRows(items => [...items, { key: "", type: "choices", choices: "", low: 0, high: 1, step: "", log: false }])}>添加搜索参数</button><button className="r-primary" disabled={disabled || trials < 1 || !datesValid(dates)} onClick={() => void s.act(() => s.submit("optimize.run", { target, sampler, trials, objective, validation: { ...validation, ...dates }, baseParameters: getParameters(), searchSpace: searchSpace() }))}>开始寻优</button></div></details>;
}
