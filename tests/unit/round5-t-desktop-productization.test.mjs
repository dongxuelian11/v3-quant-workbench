import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { resolveAgentEvidenceRuntime } from "../../apps/desktop/src/main/agentEvidenceRuntime.ts";

const read = (path) => readFile(new URL(`../../${path}`, import.meta.url), "utf8");

test("Round 5 T custom chrome suppresses the native menu and exposes bounded controls", async () => {
  const [main, preload, contract, windowControls, css] = await Promise.all([
    read("apps/desktop/src/main.ts"), read("apps/desktop/src/preload.ts"), read("packages/contracts/src/index.ts"),
    read("apps/desktop/src/renderer/components/WindowControls.tsx"), read("apps/desktop/src/renderer/styles.css")
  ]);
  assert.match(main, /Menu\.setApplicationMenu\(null\)/);
  assert.match(main, /frame:\s*false/);
  assert.match(main, /titleBarStyle:\s*"hidden"/);
  for (const action of ["minimize", "toggle-maximize", "close"]) assert.match(contract, new RegExp(action));
  assert.match(preload, /window:control/);
  assert.match(preload, /window:state-changed/);
  assert.match(preload, /removeListener\(channel, receive\)/);
  assert.match(main, /mainWindow\.on\("maximize", publishWindowState\)/);
  assert.match(main, /mainWindow\.on\("unmaximize", publishWindowState\)/);
  assert.match(windowControls, /onWindowStateChanged/);
  assert.match(windowControls, /unsubscribe\(\)/);
  assert.match(windowControls, /data-window-control="minimize"/);
  assert.match(windowControls, /data-window-control="toggle-maximize"/);
  assert.match(windowControls, /data-window-control="close"/);
  assert.match(css, /-webkit-app-region:\s*drag/);
  assert.match(css, /-webkit-app-region:\s*no-drag/);
  assert.match(main, /title:\s*"V3 量化研究工作台"/);
  assert.doesNotMatch(main, /FR-1 Visual Restoration Candidate/);
});

test("packaged production denies every environment-only development fixture request", () => {
  const development = resolveAgentEvidenceRuntime(false, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.deepEqual(development, {
    mode: "DEVELOPMENT_INTEGRATION_FIXTURE",
    backendModule: "v3_backend.adapters.round3_evidence.development_runtime",
    fixtureDeniedByPackaging: false
  });

  const unpackagedDefault = resolveAgentEvidenceRuntime(false, undefined);
  assert.equal(unpackagedDefault.mode, "LIVE_READ_ONLY");
  assert.equal(unpackagedDefault.backendModule, "v3_backend.runtime.bootstrap");

  const packagedFixture = resolveAgentEvidenceRuntime(true, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.equal(packagedFixture.mode, "LIVE_READ_ONLY");
  assert.equal(packagedFixture.backendModule, "v3_backend.runtime.bootstrap");
  assert.equal(packagedFixture.fixtureDeniedByPackaging, true);

  for (const fixtureLikeValue of ["development_integration_fixture", "DEVELOPMENT_INTEGRATION_FIXTURE,DEMO", " DEVELOPMENT_INTEGRATION_FIXTURE ", "DEVELOPMENT_INTEGRATION_FIXTURE DEVELOPMENT_INTEGRATION_FIXTURE"]) {
    const resolution = resolveAgentEvidenceRuntime(true, fixtureLikeValue);
    assert.equal(resolution.mode, "LIVE_READ_ONLY");
    assert.equal(resolution.backendModule, "v3_backend.runtime.bootstrap");
  }
});

test("shared scrollbar system covers native overflow and Monaco without old coarse rules", async () => {
  const [css, factors, monacoPresentation, strategy] = await Promise.all([
    read("apps/desktop/src/renderer/styles.css"),
    read("apps/desktop/src/renderer/components/FactorWorkbench.tsx"),
    read("apps/desktop/src/renderer/monacoPresentation.tsx"),
    read("apps/desktop/src/renderer/components/StrategyPanels.tsx")
  ]);
  for (const token of ["--v3-scrollbar-size", "--v3-scrollbar-thumb-idle", "--v3-scrollbar-thumb-hover", "--v3-scrollbar-thumb-active", "--v3-scrollbar-track", "--v3-scrollbar-radius"]) assert.match(css, new RegExp(token));
  assert.match(css, /::-webkit-scrollbar\s*\{[^}]*width:\s*var\(--v3-scrollbar-size\);[^}]*height:\s*var\(--v3-scrollbar-size\)/s);
  assert.match(css, /::-webkit-scrollbar-thumb:active/);
  assert.match(css, /::-webkit-scrollbar-button\s*\{[^}]*display:\s*none/s);
  assert.match(css, /scrollbar-color:\s*var\(--v3-scrollbar-thumb-idle\)\s*var\(--v3-scrollbar-track\)/);
  assert.match(css, /prefers-contrast:\s*more[\s\S]*--v3-scrollbar-thumb-active/);
  assert.match(css, /monaco-scrollable-element\s*>\s*\.scrollbar\s*>\s*\.slider/);
  for (const surface of ["factor-categories", "factor-list", "factor-detail", "tdx-analysis", "ai-draft-request", "ai-draft-review"]) assert.match(factors, new RegExp(`data-scroll-surface="${surface}"`));
  for (const option of ["verticalScrollbarSize: 7", "horizontalScrollbarSize: 7", "verticalSliderSize: 5", "horizontalSliderSize: 5", "alwaysConsumeMouseWheel: false", "useShadows: false"]) assert.match(monacoPresentation, new RegExp(option));
  assert.match(factors, /scrollbar:\s*V3_MONACO_SCROLLBAR_OPTIONS/);
  assert.match(strategy, /scrollbar:\s*V3_MONACO_SCROLLBAR_OPTIONS/);
  assert.doesNotMatch(css, /scrollbar-color:\s*#3a4355/);
});

test("Factor Library preserves exact W0 identity and contextual evaluation truth", async () => {
  const source = await read("apps/desktop/src/renderer/components/FactorWorkbench.tsx");
  assert.match(source, /user\.round5\.golden/);
  assert.match(source, /fdv_sha256_91e750eaa4ef83a96dac412ed2a88c1b247d2357f69b455d2f350ec9804acee1/);
  assert.match(source, /Evaluation context.*不存在/);
  assert.match(source, /Universe \/ period \/ horizon \/ label \/ Evaluation ID/);
  assert.match(source, /未评估/);
  assert.doesNotMatch(source, /IC Mean|ICIR\s*[:=]\s*[0-9]/);
  assert.match(source, /DEVELOPMENT_INTEGRATION_FIXTURE/);
  assert.match(source, /尚未接入 · NOT_CONNECTED/);
});

test("TDX fixture is typed and the renderer does not claim a formula VM", async () => {
  const source = await read("apps/desktop/src/renderer/components/FactorWorkbench.tsx");
  for (const line of ["MJ:=AMOUNT/VOL/100;", "MA5:=MA(MJ,5);", "MA20:=MA(MJ,20);", "MA60:=MA(MJ,60);", "GOLDEN:CROSS(MA20,MA60) AND MA5>MA20;"]) assert.ok(source.includes(line));
  assert.match(source, /GOLDEN.*BOOLEAN_SERIES/s);
  assert.match(source, /布尔 \/ 信号兼容（非 1\/0）/);
  assert.match(source, /VOL.*canonical shares × 0\.01.*hands/s);
  assert.match(source, /UNSUPPORTED_CANONICAL_OPERATOR/);
  assert.match(source, /仅编辑；无 JS\/TS 公式 VM/);
  assert.doesNotMatch(source, /new Function|eval\(|mathjs/);
});

test("AI factor creation remains L1 draft with L2 and L3 unavailable", async () => {
  const source = await read("apps/desktop/src/renderer/components/FactorWorkbench.tsx");
  assert.match(source, /data-authority="L1_DRAFT"/);
  assert.match(source, /需要用户确认/);
  assert.match(source, /非规范 FactorDefinitionVersion/);
  assert.match(source, /L2 EXECUTE <b>拒绝/);
  assert.match(source, /L3 PUBLISH <b>拒绝/);
  assert.match(source, /执行（L2 不可用）/);
  assert.match(source, /发布（L3 不可用）/);
});

test("Apple accessibility fallbacks and Chinese-first navigation are explicit", async () => {
  const [app, css] = await Promise.all([read("apps/desktop/src/renderer/App.tsx"), read("apps/desktop/src/renderer/styles.css")]);
  assert.match(app, /智能体工作区/);
  for (const [id, label] of [["research", "研究"], ["strategy", "策略"], ["model", "模型"], ["backtest", "回测"], ["result", "结果"]]) assert.match(app, new RegExp(`id: "${id}", zh: "${label}"`));
  assert.match(app, /\{active\.zh\}实验室/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /prefers-reduced-transparency:\s*reduce/);
  assert.match(css, /prefers-contrast:\s*more/);
});

test("A4 whole-product Chinese-first census removes known ordinary English chrome while preserving canonical tokens", async () => {
  const [app, workbench, factor, strategy, model, backtest, result, css, census] = await Promise.all([
    read("apps/desktop/src/renderer/App.tsx"),
    read("apps/desktop/src/renderer/components/Workbench.tsx"),
    read("apps/desktop/src/renderer/components/FactorWorkbench.tsx"),
    read("apps/desktop/src/renderer/components/StrategyPanels.tsx"),
    read("apps/desktop/src/renderer/components/ModelPanels.tsx"),
    read("apps/desktop/src/renderer/components/BacktestResultPanels.tsx"),
    read("apps/desktop/src/renderer/components/ResultAnalyticsPanel.tsx"),
    read("apps/desktop/src/renderer/styles.css"),
    read("docs/research/round5-t/CHINESE_FIRST_UI_CENSUS.md")
  ]);

  for (const oldLabel of ["Agent Workspace", "FACTOR WORKSPACE", "NATURAL LANGUAGE · L1", "REQUIRES USER CONFIRMATION"]) {
    assert.doesNotMatch(`${app}\n${factor}`, new RegExp(oldLabel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  for (const oldLabel of ["MODEL LAB · PHASED WORKFLOW", "BACKTEST EXPERIMENT", "Deterministic Result Lab"]) {
    assert.doesNotMatch(`${model}\n${backtest}\n${result}`, new RegExp(oldLabel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(strategy, />Visual<|>Code<|>Split<|>Diff</);
  for (const lab of ["research", "strategy", "model", "backtest", "result"]) assert.match(workbench, new RegExp(`\\b${lab}: \\[|activeLab === "${lab}"`));
  for (const token of ["FactorDefinitionVersion", "BOOLEAN_SERIES", "NOT_CONNECTED", "L1_DRAFT", "L2 EXECUTE", "L3 PUBLISH"]) assert.match(factor, new RegExp(token));
  assert.doesNotMatch(factor, /new Function|eval\(|mathjs/);
  assert.match(css, /Systemic A4 — Chinese-first, low-chrome whole-product hierarchy/);
  assert.match(css, /\.id-block\s*\{[\s\S]*?border:\s*0;/);
  assert.match(census, /Class A[\s\S]*Class B[\s\S]*Class C/);
});
