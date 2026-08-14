const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const phase = process.env.V3_SMOKE_PHASE || "capture";
const screenshots = path.resolve(root, "deliverables", "visual-restoration-screenshots");
// Run-unique userData keeps the smoke re-runnable now that the durable
// event cursor survives restarts: a fixed directory would skip the
// fixture evidence replay on every run after the first.
const electronData = path.resolve(root, process.env.V3_SMOKE_USER_DATA || "deliverables/electron-user-data-fr1-visual");
fs.mkdirSync(screenshots, { recursive: true });
fs.mkdirSync(electronData, { recursive: true });
app.setPath("userData", electronData);
app.setPath("cache", path.resolve(electronData, "cache"));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("no-sandbox");

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function evaluate(win, source) { return win.webContents.executeJavaScript(source, true); }
async function click(win, selector, wait = 500) {
  const ok = await evaluate(win, `(()=>{const element=document.querySelector(${JSON.stringify(selector)});if(!element)return false;element.click();return true})()`);
  if (!ok) throw new Error(`Missing selector ${selector}`);
  await delay(wait);
}
async function clickText(win, text, wait = 500) {
  const ok = await evaluate(win, `(()=>{const element=Array.from(document.querySelectorAll('button,.dv-tab')).find((candidate)=>candidate.textContent&&candidate.textContent.includes(${JSON.stringify(text)}));if(!element)return false;element.click();return true})()`);
  if (!ok) throw new Error(`Missing text ${text}`);
  await delay(wait);
}
async function waitFor(win, source, label, attempts = 120) {
  for (let index = 0; index < attempts; index += 1) {
    if (await evaluate(win, source)) return;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${label}`);
}
async function measurement(win, name) {
  return evaluate(win, `(()=>{
    const visible=(element)=>{if(!element)return false;const style=getComputedStyle(element);const rect=element.getBoundingClientRect();return style.display!=='none'&&style.visibility!=='hidden'&&rect.width>0&&rect.height>0};
    const rect=(element)=>{if(!element)return null;const value=element.getBoundingClientRect();return {x:Math.round(value.x),y:Math.round(value.y),width:Math.round(value.width),height:Math.round(value.height)}};
    const primary=document.querySelector('[data-primary-panel]');
    const canvas=Array.from(document.querySelectorAll('[data-primary-canvas]')).find(visible)??null;
    const nav=document.querySelector('[data-nav-width]');
    const inspector=document.querySelector('[data-inspector-width]');
    return {
      screenshot:${JSON.stringify(name)},
      viewport_css_width:window.innerWidth,
      viewport_css_height:window.innerHeight,
      dpr:window.devicePixelRatio,
      nav_width:rect(nav)?.width??0,
      inspector_width:rect(inspector)?.width??0,
      inspector_state:visible(inspector)?'open':'closed',
      primary_panel_id:primary?.getAttribute('data-primary-panel')??null,
      primary_panel_dimensions:rect(primary),
      primary_canvas_dimensions:rect(canvas),
      simultaneously_visible_major_panels:Array.from(document.querySelectorAll('[data-major-panel]')).filter(visible).length,
      truth_label_presentation_mode:document.querySelector('[data-truth-label-mode]')?.getAttribute('data-truth-label-mode')??'contextual'
    };
  })()`);
}
async function shot(win, geometry, name, size) {
  if (size) {
    win.setContentSize(size[0], size[1]);
    await delay(850);
  }
  win.webContents.invalidate();
  await delay(120);
  const bounds = win.getContentBounds();
  const image = await win.webContents.capturePage({ x: 0, y: 0, width: bounds.width, height: bounds.height }, { stayHidden: false, stayAwake: true });
  fs.writeFileSync(path.resolve(screenshots, name), image.toPNG());
  geometry.push(await measurement(win, name));
}

app.whenReady().then(async () => {
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let index = 0; index < 80 && BrowserWindow.getAllWindows().length === 0; index += 1) await delay(100);
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) throw new Error("Main process did not create BrowserWindow");
  const consoleErrors = [];
  const preloadErrors = [];
  win.webContents.on("console-message", (_event, details) => { if (details && details.level === "error") consoleErrors.push(details.message); });
  win.webContents.on("preload-error", (_event, preloadPath, error) => preloadErrors.push({ preloadPath, message: error.message, stack: error.stack }));
  try {
    await waitFor(win, "Boolean(document.querySelector('[data-testid=app-shell]'))", "renderer hydration");
  } catch (error) {
    const page = await evaluate(win, "({url:location.href,readyState:document.readyState,body:document.body?.innerText??'',html:document.body?.innerHTML?.slice(0,1000)??'',scripts:Array.from(document.scripts).map((item)=>({src:item.src,type:item.type})),resources:performance.getEntriesByType('resource').map((item)=>({name:item.name,transferSize:item.transferSize}))})");
    error.message += `; page=${JSON.stringify(page)}; consoleErrors=${JSON.stringify(consoleErrors)}; preloadErrors=${JSON.stringify(preloadErrors)}`;
    throw error;
  }
  if (phase === "capture") {
    await evaluate(win, "window.v3Desktop.resetWorkspace()");
    await evaluate(win, "window.localStorage.removeItem('v3-layout-contract')");
    win.reload();
    await waitFor(win, "Boolean(document.querySelector('[data-testid=app-shell]'))", "renderer hydration after reset");
  }
  const prefs = win.webContents.getLastWebPreferences();
  if (process.versions.electron !== "39.8.10") throw new Error(`Electron ${process.versions.electron}`);
  if (prefs.contextIsolation !== true || prefs.nodeIntegration !== false || prefs.sandbox !== true || prefs.webSecurity !== true) throw new Error(`Security preferences invalid ${JSON.stringify(prefs)}`);

  if (phase === "restart") {
    const geometryPath = path.resolve(screenshots, "layout-geometry.json");
    const geometry = fs.existsSync(geometryPath) ? JSON.parse(fs.readFileSync(geometryPath, "utf8")) : [];
    win.setContentSize(1920, 1080);
    await delay(900);
    // The durable event cursor resumes > 0 after capture, so the fixture
    // evidence is correctly NOT re-replayed: the truthful restarted
    // boundary is LIVE_READ_ONLY_NO_EVIDENCE with a READY connection.
    await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace][data-connection-state=READY]'))", "canonical Round 3 Agent Workspace after restart");
    const restartedBoundary = await evaluate(win, "document.querySelector('[data-testid=agent-workspace]')?.getAttribute('data-boundary')");
    if (!["LIVE_READ_ONLY_NO_EVIDENCE", "DEVELOPMENT_INTEGRATION_FIXTURE"].includes(restartedBoundary)) throw new Error(`unexpected restart boundary ${restartedBoundary}`);
    await click(win, "[data-lab='research']", 900);
    await waitFor(win, "document.querySelectorAll('.dv-tab').length>=3", "restored multi-panel Dockview layout");
    const restored = await evaluate(win, "({lab:document.querySelector('[data-lab-workbench]')?.getAttribute('data-lab-workbench'),panelTabs:document.querySelectorAll('.dv-tab').length,layoutContract:localStorage.getItem('v3-layout-contract')})");
    if (restored.lab !== "research" || restored.panelTabs < 3 || restored.layoutContract !== "precision-workbench-v3") throw new Error(`Restart state not restored ${JSON.stringify(restored)}`);
    await shot(win, geometry, "15-workbench-restored-layout-after-restart.png", [1920, 1080]);
    fs.writeFileSync(geometryPath, JSON.stringify(geometry, null, 2));
    fs.writeFileSync(path.resolve(screenshots, "restart-result.json"), JSON.stringify({ restored, electron: process.versions.electron, prefs, consoleErrors }, null, 2));
  } else {
    const geometry = [];
    const interactionEvidence = {};
    if (await evaluate(win, "document.querySelectorAll('[data-lab]').length") !== 5) throw new Error("Five-Lab navigation contract failed");
    try {
      await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace][data-boundary=DEVELOPMENT_INTEGRATION_FIXTURE][data-connection-state=READY]'))", "canonical Round 3 Agent Workspace");
    } catch (error) {
      const state = await evaluate(win, "Promise.all([window.v3Desktop.runtimeInfo(),window.v3BackendRuntime.getEvidenceSnapshot()]).then(([runtime,snapshot])=>({runtime,snapshot,boundary:document.querySelector('[data-testid=agent-workspace]')?.getAttribute('data-boundary'),connection:document.querySelector('[data-testid=agent-workspace]')?.getAttribute('data-connection-state'),body:document.body.innerText.slice(0,2000)}))");
      error.message += `; state=${JSON.stringify(state)}`;
      throw error;
    }
    const exactEvidenceIds = [
      "pint_sha256_011e48a40e65b1ff92213b5ce1a4895f0412f91c0b534f8aa78c03e49df96a9e",
      "pint_sha256_146f74ad6f8d8d2be0d21e3590f573125a7e57d566f9fc4357b30a74a23789de",
      "twv_sha256_208750185bacf5ce2758e4ba1eff8ecbfea197f792d5894954d02565ffc4bc32",
      "twv_sha256_9d9d92d3de1d30e4149879183aab5b2bdf2f0e93227526054e477d8bc86ffabd",
      "rawv_sha256_2afb77846c2f39a7c92ef883767416b336bf4a9c8762a3636c68eb749bfa0efb",
      "rawv_sha256_d088399d897adb9b91d1126d5bc68415a6633a180017de5d43949f01a0579eaa",
      "rdr_sha256_b732c998ff2c2f65f81303c128dc0f368059eacb91d66b4321f36e915de339e4",
      "rdr_sha256_f0c13729801864cb98a96f9ae3bf30e17d0ad2e390db2203529f10324c51c8ec",
      "btrs_sha256_30a3debc8b915903d748c6e5613375a1219bed7ca8397f9a3539a49ddcebf7ba",
      "btrr_sha256_e21779419581527099a019c32512b3e10c3c74ca962cfd266f7a63c689d1722d"
    ];
    interactionEvidence.agentWorkspace = await evaluate(win, `(()=>{
      const permissions=Array.from(document.querySelectorAll('.permission-strip > div')).map((item)=>({level:item.querySelector('span')?.textContent,status:item.querySelector('b')?.textContent,allowed:item.getAttribute('data-allowed')}));
      const actionLabels=Array.from(document.querySelectorAll('button')).map((button)=>button.textContent?.trim()??'');
      return {
        defaultSurface:document.querySelector('[data-testid=app-shell]')?.getAttribute('data-default-surface'),
        boundary:document.querySelector('[data-testid=agent-workspace]')?.getAttribute('data-boundary'),
        connection:document.querySelector('[data-testid=agent-workspace]')?.getAttribute('data-connection-state'),
        navigator:Boolean(document.querySelector('[data-testid=research-session-navigator]')),
        inspector:Boolean(document.querySelector('[data-testid=evidence-inspector]')),
        artifactViewer:Boolean(document.querySelector('[data-testid=artifact-viewer]')),
        timeline:Boolean(document.querySelector('[data-testid=agent-timeline]')),
        permissions,
        forbiddenActions:actionLabels.filter((label)=>/^(Execute|Publish)$/i.test(label)),
        agentRoles:Array.from(document.querySelectorAll('[data-agent-role]')).map((item)=>item.getAttribute('data-agent-role')),
        statementSessions:Array.from(document.querySelectorAll('[data-statement-id]')).map((item)=>item.getAttribute('data-session-id')),
        timelineSessions:Array.from(document.querySelectorAll('[data-timeline-id]')).map((item)=>item.getAttribute('data-session-id')),
        timelineStates:Array.from(document.querySelectorAll('[data-timeline-id]')).map((item)=>({state:item.getAttribute('data-timeline-state'),successClass:item.classList.contains('success'),title:item.querySelector('strong')?.textContent})),
        evidenceIds:Array.from(document.querySelectorAll('[data-evidence-object-id]')).map((item)=>item.getAttribute('data-evidence-object-id')),
        evidenceKinds:Array.from(document.querySelectorAll('[data-evidence-object-id]')).map((item)=>item.querySelector('span')?.textContent),
        connectionSlots:Array.from(document.querySelectorAll('.future-slots > div')).map((item)=>({object:item.querySelector('b')?.textContent,status:item.querySelector('span')?.textContent,owner:item.querySelector('small')?.textContent}))
      };
    })()`);
    const permissionContract = JSON.stringify(interactionEvidence.agentWorkspace.permissions) === JSON.stringify([
      { level: "L0_READ", status: "AVAILABLE", allowed: "true" },
      { level: "L1_DRAFT", status: "AVAILABLE", allowed: "true" },
      { level: "L2_EXECUTE", status: "DENIED", allowed: "false" },
      { level: "L3_PUBLISH", status: "DENIED", allowed: "false" }
    ]);
    const defaultSessionId = "session-view-round3-integration-001";
    const evidenceKindCounts = Object.fromEntries(["PortfolioIntent","TargetWeightVector","RiskAdjustedWeightVector","RiskDecisionReport","BacktestRunSpec","BacktestRunResult"].map((kind)=>[kind,interactionEvidence.agentWorkspace.evidenceKinds.filter((value)=>value===kind).length]));
    if (interactionEvidence.agentWorkspace.defaultSurface !== "agent" || interactionEvidence.agentWorkspace.boundary !== "DEVELOPMENT_INTEGRATION_FIXTURE" || interactionEvidence.agentWorkspace.connection !== "READY" || !interactionEvidence.agentWorkspace.navigator || !interactionEvidence.agentWorkspace.inspector || !interactionEvidence.agentWorkspace.artifactViewer || !interactionEvidence.agentWorkspace.timeline || !permissionContract || interactionEvidence.agentWorkspace.forbiddenActions.length || interactionEvidence.agentWorkspace.agentRoles.length || interactionEvidence.agentWorkspace.statementSessions.length || interactionEvidence.agentWorkspace.timelineSessions.some((item)=>item!==defaultSessionId) || JSON.stringify(interactionEvidence.agentWorkspace.evidenceIds)!==JSON.stringify(exactEvidenceIds) || JSON.stringify(evidenceKindCounts)!==JSON.stringify({PortfolioIntent:2,TargetWeightVector:2,RiskAdjustedWeightVector:2,RiskDecisionReport:2,BacktestRunSpec:1,BacktestRunResult:1}) || interactionEvidence.agentWorkspace.timelineStates.length!==10 || interactionEvidence.agentWorkspace.timelineStates.some((item)=>item.state!=="PRE_ALPHA"||item.successClass||/executed|succeeded/i.test(item.title??'')) || JSON.stringify(interactionEvidence.agentWorkspace.connectionSlots.map((item)=>item.owner))!==JSON.stringify(["CANONICAL_H","CANONICAL_I","CANONICAL_J"]) || interactionEvidence.agentWorkspace.connectionSlots.some((item)=>item.status!=="CONNECTED_READ_ONLY_MAIN_CONTRACT")) throw new Error(`Agent workspace contract failed ${JSON.stringify(interactionEvidence.agentWorkspace)}`);
    await evaluate(win, `(()=>{const input=document.querySelector('textarea[aria-label="Research question"]');const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;setter.call(input,'Audit the exact dataset evidence before drafting a conclusion.');input.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
    await clickText(win, "Save L1 draft", 300);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=local-agent-draft]'))", "saved local L1 draft");
    await click(win, `[data-evidence-object-id='${exactEvidenceIds[2]}']`, 250);
    if (!await evaluate(win, "document.querySelector('.open-in-lab')?.textContent==='Open in Strategy Lab'")) throw new Error("TargetWeightVector Open-in-Lab route label is not Strategy");
    await click(win, ".open-in-lab", 500);
    if (await evaluate(win, "document.querySelector('[data-lab-workbench]')?.getAttribute('data-lab-workbench')") !== "strategy") throw new Error("TargetWeightVector did not route to Strategy Lab");
    await click(win, "[data-surface='agent']", 400);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace]'))", "return from TargetWeightVector Strategy route");
    for (const exactId of exactEvidenceIds.slice(2)) {
      await click(win, `[data-evidence-object-id='${exactId}']`, 250);
      const binding = await evaluate(win, `(()=>({objectId:document.querySelector('.exact-object-id code')?.textContent,artifactId:document.querySelector('[data-testid=artifact-viewer]')?.getAttribute('data-artifact-id'),truth:Array.from(document.querySelectorAll('.truth-admission-grid b')).map((item)=>item.textContent)}))()`);
      if (binding.objectId!==exactId || binding.artifactId!==exactId || binding.truth.join(',')!=="NOT_FORMAL,PRE_ALPHA,NOT_RUN") throw new Error(`Exact canonical evidence binding failed ${JSON.stringify(binding)}`);
      if (exactId===exactEvidenceIds[8]) {
        const runSpecText=await evaluate(win,"document.querySelector('[data-testid=artifact-viewer]')?.textContent??''");
        if (!runSpecText.includes(exactEvidenceIds[4]) || !runSpecText.includes(exactEvidenceIds[5]) || !runSpecText.includes('2026-01-06T01:00:00+00:00') || !runSpecText.includes('2026-01-07T01:00:00+00:00')) throw new Error(`RunSpec multi-rebalance schedule rendering failed ${runSpecText}`);
      }
    }
    interactionEvidence.evidenceInspector = await evaluate(win, `(()=>({objectId:document.querySelector('.exact-object-id code')?.textContent,truth:Array.from(document.querySelectorAll('.truth-admission-grid b')).map((item)=>item.textContent)}))()`);
    interactionEvidence.backtestResult = await evaluate(win, `(()=>({renderer:document.querySelector('[data-testid=artifact-viewer]')?.getAttribute('data-renderer'),actual:Boolean(document.querySelector('[data-testid=canonical-backtest-result]')),body:document.querySelector('[data-testid=canonical-backtest-result]')?.textContent}))()`);
    if (interactionEvidence.evidenceInspector.objectId !== exactEvidenceIds[9] || interactionEvidence.evidenceInspector.truth.join(',') !== 'NOT_FORMAL,PRE_ALPHA,NOT_RUN' || interactionEvidence.backtestResult.renderer !== 'backtest-result' || !interactionEvidence.backtestResult.actual || !interactionEvidence.backtestResult.body.includes(exactEvidenceIds[9]) || !interactionEvidence.backtestResult.body.includes(exactEvidenceIds[8])) throw new Error(`Canonical BacktestRunResult rendering failed ${JSON.stringify(interactionEvidence)}`);
    await shot(win, geometry, "00-round3-canonical-agent-workspace.png", [1920, 1080]);
    await click(win, ".open-in-lab", 700);
    if (await evaluate(win, "document.querySelector('[data-lab-workbench]')?.getAttribute('data-lab-workbench')") !== "result") throw new Error("Canonical BacktestRunResult did not route to Result Lab");
    await click(win, "[data-surface='agent']", 500);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace]'))", "return to Agent Workspace");
    await click(win, "[data-lab='research']", 700);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=research-echart]'))", "Research ECharts");
    await shot(win, geometry, "01-research-default-chart-first.png", [1536, 864]);

    await click(win, "[data-research-event='evt-earnings']");
    await waitFor(win, "Boolean(document.querySelector('[data-testid=inspector]'))", "event Inspector");
    await shot(win, geometry, "02-research-selected-event-inspector.png", [1536, 864]);
    await click(win, "[data-testid=inspector] .inspector-head button");

    await click(win, "[data-action='research-universe']");
    if (await evaluate(win, "document.querySelectorAll('[data-universe-mode]').length") !== 9) throw new Error("Nine Universe constructors missing");
    await click(win, "[data-universe-mode='csv-tsv-import']");
    if (!await evaluate(win, "document.body.innerText.includes('未解析：INVALID-X')")) throw new Error("CSV unresolved preview missing");
    await shot(win, geometry, "03-research-universe-builder-focused.png", [1536, 864]);
    await click(win, "[data-action='universe-close']");

    await click(win, "[data-action='research-analytics']");
    await shot(win, geometry, "04-research-secondary-analytics-expanded.png", [1536, 864]);
    await click(win, ".analytics-drawer .drawer-head button");

    await click(win, "[data-lab='strategy']", 900);
    await waitFor(win, "Boolean(document.querySelector('.react-flow'))", "React Flow");
    await shot(win, geometry, "05-strategy-visual-mode.png", [1536, 864]);
    await click(win, "[data-strategy-mode='code']", 900);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=monaco-editor] .monaco-editor'))", "Monaco code editor");
    await shot(win, geometry, "06-strategy-code-mode.png", [1536, 864]);
    await click(win, "[data-strategy-mode='split']", 900);
    await waitFor(win, "Boolean(document.querySelector('.react-flow'))&&Boolean(document.querySelector('[data-testid=monaco-editor] .monaco-editor'))", "Strategy split mode");
    await shot(win, geometry, "07-strategy-split-mode.png", [1536, 864]);
    await click(win, "[data-strategy-mode='diff']", 900);
    await waitFor(win, "Boolean(document.querySelector('[data-testid=monaco-diff] .monaco-diff-editor'))", "Monaco Diff");
    await click(win, "[data-hunk='weights'] button", 300);
    await shot(win, geometry, "08-strategy-proposal-diff-review.png", [1536, 864]);

    await click(win, "[data-lab='model']", 900);
    await click(win, "[data-model-phase='configure']", 500);
    if (await evaluate(win, "document.querySelectorAll('[data-model-family]').length") !== 7) throw new Error("Seven model families missing");
    await shot(win, geometry, "09-model-dataset-family-run-workflow.png", [1536, 864]);
    await click(win, "[data-model-phase='study']", 700);
    await clickText(win, "Importance", 400);
    await shot(win, geometry, "10-model-study-trial-hpo-workflow.png", [1536, 864]);
    await click(win, "[data-model-phase='version']", 700);
    await click(win, "[data-model-version-tab='signal']", 400);
    await shot(win, geometry, "11-model-version-signal-handoff.png", [1536, 864]);
    // The command ledger now survives workspace resets by design, so the
    // exactly-once probe uses a run-unique id to stay re-runnable.
    const once = await evaluate(win, `(async()=>{const command={id:'smoke-exactly-once-visual-001-${Date.now().toString(36)}',name:'study.resume',issuedAt:new Date().toISOString()};return [await window.v3Desktop.executeCommand(command),await window.v3Desktop.executeCommand(command)]})()`);
    if (!once[0].accepted || !once[1].duplicate || once[1].executionCount !== 1) throw new Error(`Exactly-once failed ${JSON.stringify(once)}`);

    await click(win, "[data-lab='backtest']", 800);
    if (!await evaluate(win, "Boolean(document.querySelector('[data-truth-classification]'))")) throw new Error("Backtest provenance missing");
    await shot(win, geometry, "12-backtest-review.png", [1536, 864]);
    await evaluate(win, "history.replaceState(null,'',location.pathname+'?resultAnalyticsFixture=development')");
    await click(win, "[data-lab='result']", 800);
    interactionEvidence.resultAnalytics = await evaluate(win, "(()=>{const surface=document.querySelector('[data-result-analytics-id]');const chart=document.querySelector('[data-testid=result-analytics-chart]');return {analyticsId:surface?.getAttribute('data-result-analytics-id')??null,resultId:surface?.getAttribute('data-result-id')??null,policyId:surface?.getAttribute('data-policy-id')??null,benchmarkId:surface?.getAttribute('data-benchmark-id')??null,truth:document.body.innerText.includes('NOT_FORMAL · PRE_ALPHA'),policy:document.body.innerText.includes('A_SHARE_DAILY_RESEARCH_V0'),developmentBoundary:document.body.innerText.includes('DEVELOPMENT / INTEGRATION FIXTURE'),chartBound:Boolean(chart),chartAnalyticsId:chart?.getAttribute('data-analytics-id')??null}})()");
    const resultAnalytics = interactionEvidence.resultAnalytics;
    if (!resultAnalytics.analyticsId?.startsWith("bra_sha256_") || !resultAnalytics.resultId?.startsWith("btrr_sha256_") || !resultAnalytics.policyId?.startsWith("rap_sha256_") || !resultAnalytics.benchmarkId?.startsWith("bmsv_sha256_") || !resultAnalytics.truth || !resultAnalytics.policy || !resultAnalytics.developmentBoundary || !resultAnalytics.chartBound || resultAnalytics.chartAnalyticsId !== resultAnalytics.analyticsId) throw new Error(`Result Analytics identity/truth/policy/chart binding missing ${JSON.stringify(resultAnalytics)}`);
    await shot(win, geometry, "13-result-review.png", [1536, 864]);

    await evaluate(win, "document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true}))");
    await waitFor(win, "Boolean(document.querySelector('.command-palette'))", "keyboard-opened command palette");
    interactionEvidence.commandPalette = await evaluate(win, "(()=>{const input=document.querySelector('.command-palette input');return {openedByKeyboard:Boolean(document.querySelector('.command-palette')),inputFocused:document.activeElement===input,activeElement:document.activeElement?.tagName??null}})()");
    if (!interactionEvidence.commandPalette.inputFocused) throw new Error(`Command palette focus failed ${JSON.stringify(interactionEvidence.commandPalette)}`);
    await shot(win, geometry, "18-command-palette.png", [1536, 864]);
    await evaluate(win, "document.querySelector('.palette-backdrop')?.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}))");
    await waitFor(win, "!document.querySelector('.command-palette')", "command palette close");

    await click(win, "[data-lab='research']", 900);
    await click(win, "[data-action='dock-preset']", 1000);
    await waitFor(win, "document.querySelectorAll('.dv-tab').length>=3", "Research multi-panel preset");
    await shot(win, geometry, "14-workbench-multi-panel-research-preset.png", [1920, 1080]);

    await click(win, "[data-action='dock-reset']", 900);
    await waitFor(win, "document.querySelectorAll('.dv-tab').length===1", "Research default layout reset");
    await shot(win, geometry, "16-research-1280x720-compact-safe.png", [1280, 720]);
    await click(win, "[data-research-event='evt-earnings']", 300);
    await shot(win, geometry, "19-research-1280x720-inspector-overlay.png", [1280, 720]);
    await click(win, "[data-testid=inspector] .inspector-head button", 300);
    await shot(win, geometry, "17-research-1920x1080-wide.png", [1920, 1080]);
    await click(win, "[data-research-event='evt-earnings']", 300);
    await shot(win, geometry, "20-research-1920x1080-inspector-dock.png", [1920, 1080]);
    await click(win, "[data-testid=inspector] .inspector-head button", 300);

    await click(win, "[data-action='dock-preset']", 1000);
    await waitFor(win, "document.querySelectorAll('.dv-tab').length>=3", "final persisted Research preset");
    interactionEvidence.keyboardTraversal = await evaluate(win, `(()=>{const items=Array.from(document.querySelectorAll('button,input,select,summary,[tabindex]')).filter((element)=>{const rect=element.getBoundingClientRect();const style=getComputedStyle(element);const hiddenDisclosure=element.closest('details:not([open])');return element.isConnected&&(!hiddenDisclosure||element.matches('summary'))&&!element.matches(':disabled')&&element.tabIndex>=0&&style.display!=='none'&&style.visibility!=='hidden'&&rect.width>0&&rect.height>0});let attempted=0;let focused=0;const rejected=[];for(const item of items){if(!item.isConnected||item.matches(':disabled'))continue;attempted+=1;item.focus();if(document.activeElement===item)focused+=1;else rejected.push({tag:item.tagName,label:(item.getAttribute('aria-label')||item.textContent||item.getAttribute('data-testid')||'').trim().slice(0,80)})}const coverage=attempted===0?0:focused/attempted;return {focusableCount:items.length,attemptedCount:attempted,focusedCount:focused,coverageRatio:Number(coverage.toFixed(3)),rejected,lastFocused:document.activeElement?.textContent?.trim().slice(0,80)??document.activeElement?.tagName??null,representativeTraversalPass:coverage>=0.9}})()`);
    interactionEvidence.dockview = await evaluate(win, `(()=>{const tab=document.querySelector('.dv-tab');if(!tab)return {tabFound:false};tab.focus();return {tabFound:true,focusable:document.activeElement===tab,tabCount:document.querySelectorAll('.dv-tab').length}})()`);
    interactionEvidence.motion = await evaluate(win, `(()=>{const button=document.querySelector('button');return {defaultTransition:getComputedStyle(button).transitionDuration,reducedMotionRulePresent:Array.from(document.styleSheets).some((sheet)=>{try{return Array.from(sheet.cssRules).some((rule)=>rule.media?.mediaText?.includes('prefers-reduced-motion'))}catch{return false}})}})()`);
    win.webContents.debugger.attach("1.3");
    await win.webContents.debugger.sendCommand("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    interactionEvidence.reducedMotion = await evaluate(win, `(()=>{const operations=document.querySelector('.operations');return {mediaMatches:matchMedia('(prefers-reduced-motion: reduce)').matches,operationsTransition:operations?getComputedStyle(operations).transitionDuration:null}})()`);
    await win.webContents.debugger.sendCommand("Emulation.setEmulatedMedia", { features: [] });
    win.webContents.debugger.detach();
    if (!interactionEvidence.keyboardTraversal.representativeTraversalPass || !interactionEvidence.dockview.focusable || !interactionEvidence.motion.reducedMotionRulePresent || !interactionEvidence.reducedMotion.mediaMatches || interactionEvidence.reducedMotion.operationsTransition !== "0s") throw new Error(`Keyboard/motion evidence failed ${JSON.stringify(interactionEvidence)}`);
    await delay(900);
    fs.writeFileSync(path.resolve(screenshots, "layout-geometry.json"), JSON.stringify(geometry, null, 2));
    fs.writeFileSync(path.resolve(screenshots, "capture-result.json"), JSON.stringify({ electron: process.versions.electron, prefs, consoleErrors, screenshotCount: geometry.length, interactionEvidence }, null, 2));
  }
  await win.close();
  app.quit();
}).catch((error) => { console.error(error); app.exit(1); });
