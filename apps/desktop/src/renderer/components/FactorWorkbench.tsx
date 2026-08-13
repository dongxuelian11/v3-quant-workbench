import React, { useEffect, useMemo, useRef, useState } from "react";
import * as monaco from "monaco-editor";
import { ensureV3MonacoTheme, V3_MONACO_SCROLLBAR_OPTIONS } from "../monacoPresentation";
import { Icon } from "./PresentationSystem";

ensureV3MonacoTheme();

export const USER_TDX_FORMULA = `MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN:CROSS(MA20,MA60) AND MA5>MA20;
`;

const UNSUPPORTED_TDX_FIXTURE = "X:EMA(CLOSE,5);";

type FactorRecord = {
  name: string;
  assetKey: string;
  assetVersionId: string;
  definitionVersionId: string;
  importReceiptId: string;
  outputType: "FLOAT_SERIES" | "BOOLEAN_SERIES";
  category: "price" | "signal";
  lookback: number;
  operators: string[];
};

const W0_FACTORS: readonly FactorRecord[] = [
  { name: "MJ", assetKey: "user.round5.mj", assetVersionId: "fav_sha256_2b5978b234c2f8d01562f82da11bd7e18344a0541e2e1ef9ae1c6a4d6edde46e", definitionVersionId: "fdv_sha256_68aa1c7664b82996b3af583c753de0d43c8c4c571b2c31d5a1df66eef9da5855", importReceiptId: "fir_sha256_ce9e384b3ed562f4f331c30fb59ed717717c1c262a0f4522b21c4160d77557bd", outputType: "FLOAT_SERIES", category: "price", lookback: 0, operators: ["DIVIDE@1.0.0", "MULTIPLY@1.0.0"] },
  { name: "MA5", assetKey: "user.round5.ma5", assetVersionId: "fav_sha256_e3cca3ab47c9fe2b6e0e551355d36efc99de65b891c1bcbcbc6f20df210857d4", definitionVersionId: "fdv_sha256_4571445745cf29477e0df6943e2aa4754872d8fbb147ee061cacd9cd84dc783c", importReceiptId: "fir_sha256_a6932bfb283727827f1026e614c624f44bd9c1b4f892a582b90bcc2994642cbb", outputType: "FLOAT_SERIES", category: "price", lookback: 5, operators: ["DIVIDE@1.0.0", "MULTIPLY@1.0.0", "SMA@1.0.0"] },
  { name: "MA20", assetKey: "user.round5.ma20", assetVersionId: "fav_sha256_98592bccbcb8085aa60c8f3a1989164c69c758591737837c00031d66e801d049", definitionVersionId: "fdv_sha256_ee52072558c25243c6ce2156eb5865a90f6ee8d74f334c9959977514de44a3bb", importReceiptId: "fir_sha256_25e8464361ad22982bd0612653f862483d327742b5f489a676baf9c318f3b223", outputType: "FLOAT_SERIES", category: "price", lookback: 20, operators: ["DIVIDE@1.0.0", "MULTIPLY@1.0.0", "SMA@1.0.0"] },
  { name: "MA60", assetKey: "user.round5.ma60", assetVersionId: "fav_sha256_4ed08c292d02c9db130f796c9e99ef586301a240145b087ff39116e8394bd1ee", definitionVersionId: "fdv_sha256_273f7e2784b15b6f5eed43becc5c57373487ac9d4b93d581e8bfb22f798f0251", importReceiptId: "fir_sha256_9e1c7a38ef8dfcf561db341574108333677bf77ea0ac96bc827bcedfaaea667e", outputType: "FLOAT_SERIES", category: "price", lookback: 60, operators: ["DIVIDE@1.0.0", "MULTIPLY@1.0.0", "SMA@1.0.0"] },
  { name: "GOLDEN", assetKey: "user.round5.golden", assetVersionId: "fav_sha256_6ce8cd1e21c97a1224c62cd44610fe7e7d92b78c2ea9163bbba7f4d209bcb548", definitionVersionId: "fdv_sha256_91e750eaa4ef83a96dac412ed2a88c1b247d2357f69b455d2f350ec9804acee1", importReceiptId: "fir_sha256_3035909624ad0accebf76a74c757c9d7aa38dd2d9a526901cbc3fc44941b94f1", outputType: "BOOLEAN_SERIES", category: "signal", lookback: 60, operators: ["AND@1.0.0", "CROSS@1.0.0", "DIVIDE@1.0.0", "GT@1.0.0", "MULTIPLY@1.0.0", "SMA@1.0.0"] }
] as const;

const FORMULA_DOCUMENT_ID = "fdoc_sha256_91284e5fa45d8a82b50fdcfef6a80b95f8277e76ae9a4fca51a988309f4cf0ab";
const COMPATIBILITY_PROFILE_ID = "tdxcp_sha256_d0f71495ad1fdc57cab1c5079b76940dee32dcffd6aea3a6ced95b40cacc7e5f";
const DATA_PROFILE_ID = "tdxds_sha256_42c946afeb77a0e83080e927b1ee870a9bded7b57661e438881109bd0ce14173";

type Surface = "library" | "editor" | "draft";
type DetailTab = "概览" | "定义" | "评估" | "实验" | "证据 / Reviewer" | "版本 / 来源";

export function FactorWorkbench({ fixtureMode }: { fixtureMode: boolean }) {
  const [surface, setSurface] = useState<Surface>("library");
  return <section className="factor-workbench" data-testid="factor-workbench" data-fixture-mode={fixtureMode ? "DEVELOPMENT_INTEGRATION_FIXTURE" : "LIVE_READ_ONLY"}>
    <header className="factor-product-bar">
      <div><small>研究实验室 / FACTOR WORKSPACE</small><h1>因子研究</h1><span>定义、评估与来源保持精确绑定</span></div>
      <nav aria-label="因子工作区视图">
        <button className={surface === "library" ? "active" : ""} onClick={() => setSurface("library")}>因子库</button>
        <button className={surface === "editor" ? "active" : ""} onClick={() => setSurface("editor")}>TDX 公式</button>
        <button className={surface === "draft" ? "active" : ""} onClick={() => setSurface("draft")}>AI 创建</button>
      </nav>
      <span className={`connection-badge ${fixtureMode ? "fixture" : "unavailable"}`}>{fixtureMode ? "DEVELOPMENT / INTEGRATION FIXTURE" : "尚未接入 · NOT_CONNECTED"}</span>
    </header>
    {surface === "library" && <FactorLibrary fixtureMode={fixtureMode}/>}
    {surface === "editor" && <TdxEditor fixtureMode={fixtureMode}/>}
    {surface === "draft" && <AiDraft fixtureMode={fixtureMode}/>}
  </section>;
}

function FactorLibrary({ fixtureMode }: { fixtureMode: boolean }) {
  const factors = fixtureMode ? W0_FACTORS : [];
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("全部");
  const [selectedKey, setSelectedKey] = useState("user.round5.golden");
  const selected = factors.find((item) => item.assetKey === selectedKey) ?? factors[0];
  const filtered = useMemo(() => factors.filter((item) => (category === "全部" || item.category === category) && `${item.name} ${item.assetKey}`.toLowerCase().includes(query.toLowerCase())), [category, factors, query]);
  const categories = ["全部", "收藏", "最近使用", "我的因子", "内置", "AI 创建", "Alpha Mining 候选", "已评审", "候选", "已弃用", "price", "volume", "momentum", "reversal", "volatility", "liquidity", "value", "quality", "growth", "profitability", "sentiment", "technical", "custom"];

  return <div className="factor-library" data-testid="factor-library">
    <aside className="factor-categories v3-scroll-surface" data-scroll-surface="factor-categories" aria-label="因子分类"><div className="factor-pane-title"><b>分类与视图</b><small>仅显示当前数据支持项</small></div>{categories.map((item) => {
      const supported = item === "全部" || (fixtureMode && (item === "我的因子" || item === "候选" || item === "price"));
      return <button key={item} className={category === item ? "active" : ""} disabled={!supported} onClick={() => setCategory(item)}><span>{item}</span>{supported && fixtureMode ? <small>{item === "全部" || item === "我的因子" || item === "候选" ? 5 : 4}</small> : <small>—</small>}</button>;
    })}</aside>
    <section className="factor-list-pane v3-scroll-surface" data-scroll-surface="factor-list">
      <div className="factor-search"><Icon name="command" size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或精确 asset key" aria-label="搜索因子"/><select aria-label="因子生命周期" defaultValue="CANDIDATE"><option>CANDIDATE</option></select></div>
      {!fixtureMode ? <TruthEmpty title="因子目录尚未接入" detail="当前 main 没有桌面只读目录路由；未注入任何演示因子。"/> : <div className="factor-list" role="listbox" aria-label="因子列表">{filtered.map((factor) => <button role="option" aria-selected={factor.assetKey === selected?.assetKey} key={factor.assetKey} onClick={() => setSelectedKey(factor.assetKey)}>
        <span className="factor-glyph">{factor.outputType === "BOOLEAN_SERIES" ? "ƒ?" : "ƒx"}</span><span><b>{factor.name}</b><code>{factor.assetKey}</code><small>TDX_USER_FORMULA · 1d · lookback {factor.lookback}</small></span><span><em>CANDIDATE</em><small>{factor.outputType}</small><small>未评估</small></span>
      </button>)}</div>}
    </section>
    <aside className="factor-detail-pane v3-scroll-surface" data-scroll-surface="factor-detail">{selected ? <FactorDetail factor={selected}/> : <TruthEmpty title="未选择因子" detail="选择目录项以查看精确定义、评估与来源。"/>}</aside>
  </div>;
}

function FactorDetail({ factor }: { factor: FactorRecord }) {
  const [tab, setTab] = useState<DetailTab>("概览");
  const tabs: DetailTab[] = ["概览", "定义", "评估", "实验", "证据 / Reviewer", "版本 / 来源"];
  return <div className="factor-detail" data-factor-key={factor.assetKey}>
    <header><div><small>FACTOR ASSET · CANDIDATE</small><h2>{factor.name}</h2><code>{factor.assetKey}</code></div><span className="truth-state candidate">候选 · 非正式真值</span></header>
    <nav aria-label="因子详情">{tabs.map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}</button>)}</nav>
    <div className="factor-detail-body">
      {tab === "概览" && <><FactGrid facts={[['来源族','TDX_USER_FORMULA'],['生命周期','CANDIDATE'],['输出类型',factor.outputType],['频率','1d'],['Lookback',String(factor.lookback)],['兼容性','SUPPORTED / exact W0 fixture']]}/><TruthCallout tone="warning" title="未评估" detail="没有 Universe、period、horizon/label 与 Evaluation ID；因此不展示 IC/ICIR。"/></>}
      {tab === "定义" && <><IdBlock label="FactorDefinitionVersion" value={factor.definitionVersionId}/><pre>{USER_TDX_FORMULA}</pre><FactGrid facts={[['Operators',factor.operators.join(', ')],['数据依赖','amount, volume'],['Source language','TDX'],['Canonical IR','由 current-main W0 translator 生成；UI 不计算']]}/></>}
      {tab === "评估" && <TruthEmpty title="未评估" detail="Evaluation context 不存在：Universe / period / horizon / label / Evaluation ID 均不可用。"/>}
      {tab === "实验" && <TruthEmpty title="没有绑定实验" detail="实验必须绑定精确 FactorDefinitionVersion；当前 fixture 未声明 Experiment。"/>}
      {tab === "证据 / Reviewer" && <TruthEmpty title="Reviewer：NOT_RUN" detail="没有 ReviewerFinding；不会用 UI 状态推断评审通过。"/>}
      {tab === "版本 / 来源" && <>
        <IdBlock label="FactorAssetVersion" value={factor.assetVersionId}/>
        <IdBlock label="FactorDefinitionVersion" value={factor.definitionVersionId}/>
        <IdBlock label="FactorImportReceipt" value={factor.importReceiptId}/>
        <IdBlock label="FormulaDocumentVersion" value={FORMULA_DOCUMENT_ID}/>
        <IdBlock label="CompatibilityProfile" value={COMPATIBILITY_PROFILE_ID}/>
        <IdBlock label="DataSemanticProfile" value={DATA_PROFILE_ID}/>
        <FactGrid facts={[["来源语言","TDX"],["输出类型",factor.outputType],["Canonical IR","current-main W0 translator 生成；UI 不计算"],["Reviewer","NOT_RUN"]]}/>
        <TruthCallout tone="warning" title="版本链只读" detail="这些精确 ID 来自 current-main W0 fixture；候选状态不等于 canonical admission。"/>
      </>}
    </div>
  </div>;
}

type FixtureAnalysis = { state: "PASSED" | "UNSUPPORTED" | "NOT_CONNECTED"; title: string; detail: string };
function contractFixtureAnalysis(source: string, fixtureMode: boolean): FixtureAnalysis {
  if (!fixtureMode) return { state: "NOT_CONNECTED", title: "尚未接入", detail: "生产只读模式没有 parser/translator 路由；不在前端解析或执行公式。" };
  if (source === USER_TDX_FORMULA) return { state: "PASSED", title: "W0 合同 fixture · 已验证", detail: "current-main W0 测试生成的确定性投影；不是浏览器内解析结果。" };
  if (source === UNSUPPORTED_TDX_FIXTURE) return { state: "UNSUPPORTED", title: "不支持函数 · EMA", detail: "UNSUPPORTED_CANONICAL_OPERATOR（current-main W0 合同 fixture）" };
  return { state: "NOT_CONNECTED", title: "未验证草案", detail: "源文本已编辑；等待后端 parser/translator 接口，未伪造成功状态。" };
}

function TdxEditor({ fixtureMode }: { fixtureMode: boolean }) {
  const [source, setSource] = useState(USER_TDX_FORMULA);
  const analysis = contractFixtureAnalysis(source, fixtureMode);
  return <div className="tdx-workspace" data-testid="tdx-editor" data-parse-state={analysis.state}>
    <section className="tdx-editor-pane"><header><div><small>TDX SOURCE · L1 DRAFT</small><b>用户公式</b></div><div><button onClick={() => setSource(USER_TDX_FORMULA)}>载入 W0 fixture</button><button onClick={() => setSource(UNSUPPORTED_TDX_FIXTURE)}>不支持函数状态</button></div></header><FormulaEditor source={source} onChange={setSource}/><footer><span>UTF-8 · 中文标识符</span><span>仅编辑；无 JS/TS 公式 VM</span></footer></section>
    <aside className="tdx-analysis-pane v3-scroll-surface" data-scroll-surface="tdx-analysis"><header><small>DETERMINISTIC VALIDATION PREVIEW</small><h2>{analysis.title}</h2><p>{analysis.detail}</p></header>
      {analysis.state === "PASSED" ? <><section><h3>命名输出</h3><div className="output-grid">{W0_FACTORS.map((item) => <div key={item.name}><b>{item.name}</b><span>{item.outputType}</span><small>{item.name === "GOLDEN" ? "boolean / signal-compatible（非 1/0）" : `numeric · lookback ${item.lookback}`}</small></div>)}</div></section><section><h3>静态分析</h3><FactGrid facts={[['最大 lookback','60'],['数据依赖','amount, volume'],['Operator','AND, CROSS, DIVIDE, GT, MULTIPLY, SMA'],['Unsupported','无']]}/></section><section><h3>TDX 数据语义</h3><p><code>VOL</code> = 手（100 股）；canonical shares × 0.01 → hands。<code>AMOUNT</code> = CNY。原始 <code>AMOUNT/VOL/100</code> 保持不变。</p><IdBlock label="Compatibility profile" value={COMPATIBILITY_PROFILE_ID}/><IdBlock label="Data semantic profile" value={DATA_PROFILE_ID}/></section></> : <TruthCallout tone={analysis.state === "UNSUPPORTED" ? "danger" : "warning"} title={analysis.state} detail="没有生成 Canonical IR、FactorDefinitionVersion 或执行结果。"/>}
    </aside>
  </div>;
}

function FormulaEditor({ source, onChange }: { source: string; onChange: (value: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  useEffect(() => {
    if (!host.current) return;
    if (!monaco.languages.getLanguages().some((item) => item.id === "tdx")) {
      monaco.languages.register({ id: "tdx" });
      monaco.languages.setMonarchTokensProvider("tdx", { tokenizer: { root: [[/[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }], [/\d+(?:\.\d+)?/, "number"], [/:=|:|>=|<=|!=|>|<|\+|-|\*|\//, "operator"], [/;/, "delimiter"]] }, keywords: ["AND", "OR", "NOT", "MA", "CROSS", "OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT"] });
    }
    const instance = monaco.editor.create(host.current, { value: source, language: "tdx", theme: "v3-quant", fontFamily: "Cascadia Mono, Consolas, Microsoft YaHei UI, monospace", fontSize: 13, lineHeight: 21, minimap: { enabled: false }, automaticLayout: true, scrollBeyondLastLine: false, renderLineHighlight: "all", padding: { top: 14 }, accessibilitySupport: "auto", overviewRulerLanes: 0, hideCursorInOverviewRuler: true, scrollbar: V3_MONACO_SCROLLBAR_OPTIONS });
    editor.current = instance;
    const subscription = instance.onDidChangeModelContent(() => onChange(instance.getValue()));
    return () => { subscription.dispose(); instance.dispose(); editor.current = null; };
  }, []);
  useEffect(() => { if (editor.current && editor.current.getValue() !== source) editor.current.setValue(source); }, [source]);
  return <div ref={host} className="monaco-host" aria-label="TDX 公式源代码编辑器"/>;
}

function AiDraft({ fixtureMode }: { fixtureMode: boolean }) {
  const [description, setDescription] = useState("寻找 MA20 上穿 MA60，且 MA5 位于 MA20 上方的量价信号");
  const [draftVisible, setDraftVisible] = useState(fixtureMode);
  const [receipt, setReceipt] = useState("等待用户审阅");
  return <div className="ai-draft-workspace" data-testid="ai-factor-draft" data-authority="L1_DRAFT">
    <section className="draft-request v3-scroll-surface" data-scroll-surface="ai-draft-request"><small>NATURAL LANGUAGE · L1</small><h2>自然语言描述</h2><textarea value={description} onChange={(event) => setDescription(event.target.value)} aria-label="自然语言因子描述"/><button disabled={!fixtureMode} onClick={() => { setDraftVisible(true); setReceipt("AI Draft 已载入；必须由用户确认"); }}><Icon name="pulse"/>生成 AI Draft</button><p>{fixtureMode ? "开发集成 fixture：不会调用模型或创建正式因子。" : "尚未接入 / NOT_CONNECTED：current main 没有 P Factor Agent API。"}</p>
      <div className="permission-stack"><span>L0 READ <b>允许</b></span><span>L1 DRAFT <b>允许</b></span><span>L2 EXECUTE <b>拒绝</b></span><span>L3 PUBLISH <b>拒绝</b></span></div>
    </section>
    <section className="draft-review v3-scroll-surface" data-scroll-surface="ai-draft-review">{draftVisible ? <><header><div><span className="truth-state draft">AI PROPOSAL · DRAFT</span><h2>黄金交叉量价草案</h2><p>非 Canonical FactorDefinitionVersion · 需要用户确认</p></div><span className="confirm-required">REQUIRES USER CONFIRMATION</span></header><pre>{USER_TDX_FORMULA}</pre><div className="draft-flow"><span>自然语言描述</span><i>→</i><span className="active">AI Draft</span><i>→</i><span>确定性验证预览</span><i>→</i><span>用户确认</span></div><TruthCallout tone="warning" title="验证边界" detail="当前内容只映射到已知 W0 fixture；没有后端创建路由，不会生成 canonical factor。"/><footer><span role="status">{receipt}</span><button onClick={() => setReceipt("用户已确认审阅意图；仍为 L1 DRAFT / NOT_CONNECTED")}>确认审阅意图（L1）</button><button disabled>执行（L2 不可用）</button><button disabled>发布（L3 不可用）</button></footer></> : <TruthEmpty title="AI Factor Agent 尚未接入" detail="不会导入未合并 P 分支，也不会在生产中回退到 fixture。"/>}</section>
  </div>;
}

function FactGrid({ facts }: { facts: [string, string][] }) { return <dl className="fact-grid">{facts.map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd>{value}</dd></React.Fragment>)}</dl>; }
function IdBlock({ label, value }: { label: string; value: string }) { return <div className="id-block"><small>{label}</small><code>{value}</code></div>; }
function TruthEmpty({ title, detail }: { title: string; detail: string }) { return <div className="truth-empty"><Icon name="inspector"/><b>{title}</b><p>{detail}</p></div>; }
function TruthCallout({ tone, title, detail }: { tone: "warning" | "danger"; title: string; detail: string }) { return <div className={`truth-callout ${tone}`}><b>{title}</b><p>{detail}</p></div>; }
