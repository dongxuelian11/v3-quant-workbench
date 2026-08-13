import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

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
  assert.match(windowControls, /data-window-control="minimize"/);
  assert.match(windowControls, /data-window-control="toggle-maximize"/);
  assert.match(windowControls, /data-window-control="close"/);
  assert.match(css, /-webkit-app-region:\s*drag/);
  assert.match(css, /-webkit-app-region:\s*no-drag/);
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
  assert.match(source, /boolean \/ signal-compatible（非 1\/0）/);
  assert.match(source, /VOL.*canonical shares × 0\.01.*hands/s);
  assert.match(source, /UNSUPPORTED_CANONICAL_OPERATOR/);
  assert.match(source, /仅编辑；无 JS\/TS 公式 VM/);
  assert.doesNotMatch(source, /new Function|eval\(|mathjs/);
});

test("AI factor creation remains L1 draft with L2 and L3 unavailable", async () => {
  const source = await read("apps/desktop/src/renderer/components/FactorWorkbench.tsx");
  assert.match(source, /data-authority="L1_DRAFT"/);
  assert.match(source, /REQUIRES USER CONFIRMATION/);
  assert.match(source, /非 Canonical FactorDefinitionVersion/);
  assert.match(source, /L2 EXECUTE <b>拒绝/);
  assert.match(source, /L3 PUBLISH <b>拒绝/);
  assert.match(source, /执行（L2 不可用）/);
  assert.match(source, /发布（L3 不可用）/);
});

test("Apple accessibility fallbacks and Chinese-first navigation are explicit", async () => {
  const [app, css] = await Promise.all([read("apps/desktop/src/renderer/App.tsx"), read("apps/desktop/src/renderer/styles.css")]);
  assert.match(app, /Agent 工作区/);
  for (const [id, label] of [["research", "研究"], ["strategy", "策略"], ["model", "模型"], ["backtest", "回测"], ["result", "结果"]]) assert.match(app, new RegExp(`id: "${id}", zh: "${label}"`));
  assert.match(app, /\{active\.zh\}实验室/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /prefers-reduced-transparency:\s*reduce/);
  assert.match(css, /prefers-contrast:\s*more/);
});
