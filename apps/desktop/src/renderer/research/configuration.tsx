import React, { useState } from "react";
import type { JsonObject, JsonValue } from "../../../../../packages/contracts/src/research";
import { Field } from "./ui";
import { useResearch } from "./state";

export const object = (value: JsonValue | undefined): JsonObject => value && typeof value === "object" && !Array.isArray(value) ? value : {};
export const factorDefaults: JsonObject = { directions: {}, winsorize: "mad", madScale: 3, standardize: true, neutralizeIndustry: false, neutralizeSize: false };
export const portfolioDefaults: JsonObject = { method: "equal", grossExposure: .95, maxWeight: null, industryCap: null, turnoverLimit: null, lookback: 252, minObservations: 126, riskAversion: 3, returnSource: "historical" };
export const costsDefaults: JsonObject = { commissionBuy: .0003, commissionSell: .0003, minCommission: 5, stampDuty: "historical", transferFee: .00001, slippage: .001, volumeParticipation: .1 };
export const validationDefaults: JsonObject = { mode: "single", trainYears: 3, validMonths: 6, testMonths: 1, stepMonths: 1 };
export function factorProcessing(settings: JsonObject) { return { ...factorDefaults, ...object(settings.factorProcessing) }; }
export function customFactors(settings: JsonObject) {
  return Array.isArray(settings.customFactors) ? settings.customFactors.flatMap(f => {
    const c = object(f);
    return typeof c.id === "string" && typeof c.name === "string" && typeof c.expression === "string" ? [{ id: c.id, name: c.name, expression: c.expression }] : [];
  }) : [];
}
export function completeStrategy(settings: JsonObject, source = object(settings.backtest)): JsonObject {
  return { template: "multi_factor", factorIds: settings.selectedFactors ?? [], topN: 30, rebalance: "weekly", capital: 1000000, benchmark: "csi300", ...source,
    customFactors: source.customFactors ?? customFactors(settings), factorProcessing: source.factorProcessing ?? factorProcessing(settings),
    portfolio: { ...portfolioDefaults, ...object(source.portfolio) }, costs: { ...costsDefaults, commissionBuy: source.commissionBuy ?? .0003, commissionSell: source.commissionSell ?? .0003, minCommission: source.minFee ?? 5, slippage: source.slippage ?? .001, ...object(source.costs) } };
}
export function completeModel(settings: JsonObject, source = object(settings.model)): JsonObject {
  return { model: "lightgbm", factorIds: settings.selectedFactors ?? [], trainStart: "", trainEnd: "", validStart: "", validEnd: "", testStart: "", testEnd: "", labelHorizon: 5, labelMode: "next_open", hyperparameters: {}, ...source,
    customFactors: source.customFactors ?? customFactors(settings), factorProcessing: source.factorProcessing ?? factorProcessing(settings), validation: { ...validationDefaults, ...object(source.validation) } };
}
interface EditorProps { value: JsonObject; onChange: (v: JsonObject) => void }
export function NumberSetting({ label, name, value, onChange, min = 0, max, step = "any", nullable = false }: EditorProps & { label: string; name: string; min?: number; max?: number; step?: number | "any"; nullable?: boolean }) {
  return <Field label={label}><input type="number" min={min} max={max} step={step} value={value[name] == null ? "" : Number(value[name])} placeholder={nullable ? "不限制" : undefined} onChange={e => onChange({ ...value, [name]: e.target.value === "" && nullable ? null : Number(e.target.value) })} /></Field>;
}
export function ChoiceSetting({ label, name, value, onChange, choices }: EditorProps & { label: string; name: string; choices: Record<string, string> }) {
  return <Field label={label}><select value={String(value[name] ?? "")} onChange={e => onChange({ ...value, [name]: e.target.value })}>{Object.entries(choices).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></Field>;
}
export function ToggleSetting({ label, name, value, onChange }: EditorProps & { label: string; name: string }) {
  return <label className="r-check"><input type="checkbox" checked={value[name] === true} onChange={e => onChange({ ...value, [name]: e.target.checked })} />{label}</label>;
}
export function PortfolioEditor({ value, onChange }: EditorProps) {
  const p = { value, onChange };
  return <section><h3>组合构建</h3><div className="r-form-grid"><ChoiceSetting {...p} label="权重方法" name="method" choices={{ equal: "等权", score: "非负排名评分", risk_parity: "风险平价", mean_variance: "均值方差" }} /><NumberSetting {...p} label="总仓位（0–1）" name="grossExposure" max={1} /><NumberSetting {...p} label="单股上限（0–1，可留空）" name="maxWeight" max={1} nullable /><NumberSetting {...p} label="行业上限（0–1，可留空）" name="industryCap" max={1} nullable /><NumberSetting {...p} label="换手上限（0–1，可留空）" name="turnoverLimit" max={1} nullable /></div>{["risk_parity", "mean_variance"].includes(String(value.method)) && <div className="r-form-grid"><NumberSetting {...p} label="历史窗口（交易日）" name="lookback" min={1} step={1} /><NumberSetting {...p} label="最少有效样本" name="minObservations" min={2} step={1} />{value.method === "mean_variance" && <><NumberSetting {...p} label="风险厌恶系数" name="riskAversion" min={0} /><ChoiceSetting {...p} label="预期收益来源" name="returnSource" choices={{ historical: "历史收益", model: "模型收益预测" }} /></>}</div>}<p className="r-note">约束不足时保留现金，冲突会显示原因。换手包含现金权重变化；不会自动放宽上限。</p></section>;
}
export function CostsEditor({ value, onChange }: EditorProps) {
  const p = { value, onChange };
  return <section><h3>交易成本与成交限制</h3><div className="r-form-grid"><NumberSetting {...p} label="买入佣金比例" name="commissionBuy" /><NumberSetting {...p} label="卖出佣金比例" name="commissionSell" /><NumberSetting {...p} label="最低佣金（元）" name="minCommission" /><Field label="印花税"><select value={value.stampDuty === "historical" ? "historical" : "custom"} onChange={e => onChange({ ...value, stampDuty: e.target.value === "historical" ? "historical" : .0005 })}><option value="historical">按历史日期</option><option value="custom">自定义比例</option></select></Field>{value.stampDuty !== "historical" && <NumberSetting {...p} label="自定义印花税比例" name="stampDuty" />}<NumberSetting {...p} label="过户费比例" name="transferFee" /><NumberSetting {...p} label="滑点比例" name="slippage" /><NumberSetting {...p} label="历史成交量参与上限（0–1）" name="volumeParticipation" max={1} /></div></section>;
}
export const dateKeys = ["trainStart", "trainEnd", "validStart", "validEnd", "testStart", "testEnd"] as const;
const dateLabels = ["训练开始", "训练结束", "验证开始", "验证结束", "测试开始", "测试结束"];
export function ValidationEditor({ value, onChange, dates, onDates }: EditorProps & { dates: JsonObject; onDates: (v: JsonObject) => void }) {
  return <section><ChoiceSetting value={value} onChange={onChange} label="验证方式" name="mode" choices={{ single: "单次时间划分", rolling: "滚动验证" }} />{value.mode === "rolling" && <div className="r-form-grid">{[["trainYears", "训练年数"], ["validMonths", "验证月数"], ["testMonths", "测试月数"], ["stepMonths", "滚动步长（月）"]].map(([name, label]) => <NumberSetting key={name} value={value} onChange={onChange} name={name} label={label} min={1} step={1} />)}</div>}<p className="r-note">日期全部留空时按交易日 70% / 15% / 15% 划分；自定义时填写完整六个日期。滚动按自然月对齐交易日。</p><div className="r-form-grid">{dateKeys.map((key, i) => <Field key={key} label={dateLabels[i]}><input type="date" value={String(dates[key] ?? "")} onChange={e => onDates({ ...dates, [key]: e.target.value })} /></Field>)}</div></section>;
}
export function validateDates(dates: JsonObject) {
  const v = dateKeys.map(k => String(dates[k] ?? ""));
  if (v.every(d => !d)) return;
  if (v.some(d => !d) || !(v[0] <= v[1] && v[1] < v[2] && v[2] <= v[3] && v[3] < v[4] && v[4] <= v[5])) throw new Error("请填写完整、按时间顺序且互不重叠的训练／验证／测试日期，或全部留空。");
}
export function FactorProcessingEditor() {
  const s = useResearch(); const [value, setValue] = useState(() => factorProcessing(s.project!.settings));
  const factors = [...s.factors, ...customFactors(s.project!.settings)].filter(f => s.selectedFactors.includes(f.id));
  return <details><summary>因子方向与预处理</summary><div className="r-form-grid"><ChoiceSetting value={value} onChange={setValue} name="winsorize" label="异常值处理" choices={{ mad: "MAD 去极值", none: "不处理" }} /><NumberSetting value={value} onChange={setValue} name="madScale" label="MAD 倍数" min={.1} /><ToggleSetting value={value} onChange={setValue} name="standardize" label="截面标准化" /><ToggleSetting value={value} onChange={setValue} name="neutralizeIndustry" label="行业中性化" /><ToggleSetting value={value} onChange={setValue} name="neutralizeSize" label="市值中性化（对数流通市值）" /></div><div className="r-table-scroll"><table><thead><tr><th>已选因子</th><th>方向</th></tr></thead><tbody>{factors.map(f => <tr key={f.id}><td>{f.name}</td><td><select aria-label={`${f.name}方向`} value={Number(object(value.directions)[f.id] ?? 1)} onChange={e => setValue({ ...value, directions: { ...object(value.directions), [f.id]: Number(e.target.value) } })}><option value={1}>正向 · 越高越好</option><option value={-1}>反向 · 越低越好</option></select></td></tr>)}</tbody></table></div><p className="r-note">顺序：方向 → 去极值 → 中性化 → 标准化。历史行业或市值缺失以实际分析说明为准。</p><button onClick={() => void s.act(async () => { await s.save({ settings: { ...s.project!.settings, factorProcessing: value } }); s.setNotice("因子处理设置已保存"); })}>保存因子处理设置</button></details>;
}
