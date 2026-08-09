const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const phase = process.env.V3_SMOKE_PHASE || "capture";
const screenshots = path.resolve(root, "deliverables", "visual-restoration-screenshots");
const electronData = path.resolve(root, "deliverables", "electron-user-data-fr1-visual");
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
  const image = await win.webContents.capturePage();
  fs.writeFileSync(path.resolve(screenshots, name), image.toPNG());
  geometry.push(await measurement(win, name));
}

app.whenReady().then(async () => {
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let index = 0; index < 80 && BrowserWindow.getAllWindows().length === 0; index += 1) await delay(100);
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) throw new Error("Main process did not create BrowserWindow");
  const consoleErrors = [];
  win.webContents.on("console-message", (_event, details) => { if (details && details.level === "error") consoleErrors.push(details.message); });
  await waitFor(win, "Boolean(document.querySelector('[data-testid=app-shell]'))", "renderer hydration");
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
    const once = await evaluate(win, "(async()=>{const command={id:'smoke-exactly-once-visual-001',name:'study.resume',issuedAt:new Date().toISOString()};return [await window.v3Desktop.executeCommand(command),await window.v3Desktop.executeCommand(command)]})()");
    if (!once[0].accepted || !once[1].duplicate || once[1].executionCount !== 1) throw new Error(`Exactly-once failed ${JSON.stringify(once)}`);

    await click(win, "[data-lab='backtest']", 800);
    if (!await evaluate(win, "Boolean(document.querySelector('[data-truth-classification]'))")) throw new Error("Backtest provenance missing");
    await shot(win, geometry, "12-backtest-review.png", [1536, 864]);
    await click(win, "[data-lab='result']", 800);
    if (!await evaluate(win, "document.body.innerText.includes('DEMO · 非正式金融输出')")) throw new Error("Result truth label missing");
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
