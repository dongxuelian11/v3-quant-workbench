const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, ".."); const phase = process.env.V3_SMOKE_PHASE || "capture";
const screenshots = path.resolve(root, "deliverables", "screenshots"); const electronData = path.resolve(root, "deliverables", "electron-user-data-fr1");
fs.mkdirSync(screenshots, { recursive: true }); fs.mkdirSync(electronData, { recursive: true });
app.setPath("userData", electronData); app.setPath("cache", path.resolve(electronData, "cache")); app.disableHardwareAcceleration(); app.commandLine.appendSwitch("disable-gpu"); app.commandLine.appendSwitch("disable-gpu-compositing"); app.commandLine.appendSwitch("no-sandbox");

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function evaluate(win, source) { return win.webContents.executeJavaScript(source, true); }
async function click(win, selector) { const ok = await evaluate(win, `(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return false;e.click();return true})()`); if (!ok) throw new Error(`Missing selector ${selector}`); await delay(500); }
async function clickText(win, text) { const ok = await evaluate(win, `(()=>{const e=Array.from(document.querySelectorAll('button,.dv-tab')).find(x=>x.textContent&&x.textContent.includes(${JSON.stringify(text)}));if(!e)return false;e.click();return true})()`); if (!ok) throw new Error(`Missing text ${text}`); await delay(600); }
async function shot(win, name, size) { if (size) { win.setSize(size[0], size[1]); await delay(350); } const image = await win.webContents.capturePage(); fs.writeFileSync(path.resolve(screenshots, name), image.toPNG()); }

app.whenReady().then(async () => {
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let i=0;i<80&&BrowserWindow.getAllWindows().length===0;i++) await delay(100);
  const win=BrowserWindow.getAllWindows()[0]; if(!win) throw new Error("Main process did not create BrowserWindow");
  const consoleErrors=[]; win.webContents.on("console-message", (_event, details) => { if(details && details.level === "error") consoleErrors.push(details.message); });
  let ready=false; for(let i=0;i<120;i++){if(await evaluate(win,"Boolean(document.querySelector('[data-testid=app-shell]'))")){ready=true;break}await delay(100)}
  if(!ready){const diagnostic=await evaluate(win,"({url:location.href,body:document.body.innerHTML,title:document.title})");throw new Error(`Renderer did not hydrate ${JSON.stringify(diagnostic)} console=${JSON.stringify(consoleErrors)}`)}
  if(phase==="capture"){await evaluate(win,"window.v3Desktop.resetWorkspace()");win.reload();ready=false;for(let i=0;i<120;i++){if(await evaluate(win,"Boolean(document.querySelector('[data-testid=app-shell]'))")){ready=true;break}await delay(100)}if(!ready)throw new Error("Renderer did not hydrate after deterministic reset")}
  const prefs=win.webContents.getLastWebPreferences();
  if(process.versions.electron!=="39.8.10")throw new Error(`Electron ${process.versions.electron}`);
  if(prefs.contextIsolation!==true||prefs.nodeIntegration!==false||prefs.sandbox!==true||prefs.webSecurity!==true)throw new Error(`Security preferences invalid ${JSON.stringify(prefs)}`);
  if(phase==="restart"){
    const restored=await evaluate(win,"({lab:document.querySelector('[data-lab-workbench]')?.getAttribute('data-lab-workbench'),study:document.body.innerText.includes('RUNNING')})");
    if(restored.lab!=="model"||!restored.study)throw new Error(`Restart state not restored ${JSON.stringify(restored)}`);
    await shot(win,"14-restart-restored-layout-state.png",[1440,900]);
    fs.writeFileSync(path.resolve(screenshots,"restart-result.json"),JSON.stringify({restored,electron:process.versions.electron,prefs,consoleErrors},null,2));
  }else{
    if(await evaluate(win,"document.querySelectorAll('[data-lab]').length")!==5)throw new Error("Five-Lab navigation contract failed");
    await shot(win,"01-research-overview-chart-tree.png",[1440,900]);
    await clickText(win,"Universe Builder"); if(await evaluate(win,"document.querySelectorAll('[data-universe-mode]').length")!==9)throw new Error("Nine Universe constructors missing"); await click(win,"[data-universe-mode='csv-tsv-import']"); if(!await evaluate(win,"document.body.innerText.includes('未解析：INVALID-X')"))throw new Error("CSV unresolved preview missing"); await shot(win,"02-universe-builder-nine-modes-import.png",[1280,720]);
    await click(win,".symbol-grid button:not(.unresolved)"); await shot(win,"03-research-linked-selection-inspector.png",[1440,900]);
    await click(win,"[data-lab='strategy']"); if(!await evaluate(win,"Boolean(document.querySelector('.react-flow'))"))throw new Error("React Flow missing"); await shot(win,"04-strategy-react-flow-visual.png",[1440,900]);
    await click(win,"[data-strategy-mode='code']"); if(!await evaluate(win,"Boolean(document.querySelector('[data-testid=monaco-editor] .monaco-editor'))"))throw new Error("Monaco editor missing"); await shot(win,"05-strategy-monaco-code.png",[1280,720]);
    await click(win,"[data-strategy-mode='split']"); await clickText(win,"Proposal Diff"); if(!await evaluate(win,"Boolean(document.querySelector('[data-testid=monaco-diff] .monaco-diff-editor'))"))throw new Error("Monaco Diff missing"); await click(win,"[data-hunk='weights'] button"); await clickText(win,"验证"); await clickText(win,"生成 BacktestHandoffDraft"); if(!await evaluate(win,"document.body.innerText.includes('BacktestHandoffDraft/demo-v')"))throw new Error("Strategy handoff missing"); await shot(win,"06-strategy-split-monaco-diff.png",[1920,1080]);
    await click(win,"[data-lab='model']"); if(await evaluate(win,"document.querySelectorAll('[data-model-family]').length")!==7)throw new Error("Seven model families missing"); await shot(win,"07-model-dataset-runs-seven-families.png",[1440,900]);
    await click(win,"[data-model-family='XGBoost']"); await clickText(win,"Importance"); await shot(win,"08-model-study-trial-hpo.png",[1440,900]);
    await clickText(win,"PredictionSignalVersion"); await shot(win,"09-model-version-signal-handoff.png",[1440,900]);
    const once=await evaluate(win,"(async()=>{const c={id:'smoke-exactly-once-001',name:'study.resume',issuedAt:new Date().toISOString()};return [await window.v3Desktop.executeCommand(c),await window.v3Desktop.executeCommand(c)]})()"); if(!once[0].accepted||!once[1].duplicate||once[1].executionCount!==1)throw new Error(`Exactly-once failed ${JSON.stringify(once)}`);
    await click(win,"[data-lab='backtest']"); if(!await evaluate(win,"document.body.innerText.includes('RECOVERED_FROM_PRODUCT_DESIGN_NOT_PRIOR_WAVE3_ACCEPTANCE')"))throw new Error("Backtest provenance missing"); await shot(win,"10-backtest-full-demo-surface.png",[1440,900]);
    await click(win,"[data-lab='result']"); if(!await evaluate(win,"document.body.innerText.includes('DEMO / NOT FORMAL FINANCIAL OUTPUT')"))throw new Error("Result truth label missing"); await shot(win,"11-result-full-demo-surface.png",[1440,900]);
    await evaluate(win,"document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',ctrlKey:true,bubbles:true}))"); await delay(400); await shot(win,"12-command-palette.png",[1280,720]); await click(win,".palette-backdrop");
    await click(win,"[data-lab='research']"); await click(win,"[data-action='dock-split']"); await shot(win,"13-dockview-split-docked-layout.png",[1920,1080]);
    await click(win,"[data-lab='model']"); await clickText(win,"Study / Trial / HPO"); await clickText(win,"Resume"); await delay(800);
    fs.writeFileSync(path.resolve(screenshots,"capture-result.json"),JSON.stringify({electron:process.versions.electron,prefs,consoleErrors},null,2));
  }
  await win.close(); app.quit();
}).catch((error)=>{console.error(error);app.exit(1)});
