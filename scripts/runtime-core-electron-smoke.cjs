const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

// Minimal runtime-core smoke: Electron main + real backend Python child +
// authenticated handshake + replay + command idempotency + durable cursor +
// graceful shutdown handshake + restart persistence. No visual evidence.
const root = path.resolve(__dirname, "..");
const phase = process.env.V3_SMOKE_PHASE || "capture";
// Run-unique userData keeps the smoke re-runnable: the durable command
// ledger intentionally survives restarts, so a fixed directory would make
// the first command execution of a second run a duplicate.
const electronData = path.resolve(root, process.env.V3_SMOKE_USER_DATA || "deliverables/electron-user-data-runtime-core");
fs.mkdirSync(electronData, { recursive: true });
app.setPath("userData", electronData);
app.setPath("cache", path.resolve(electronData, "cache"));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
// Dockerized/container Linux runners frequently ship a tiny or
// permission-restricted /dev/shm; Chromium then fails to start the
// renderer. This switch is a no-op on Windows.
app.commandLine.appendSwitch("disable-dev-shm-usage");
app.commandLine.appendSwitch("no-sandbox");

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function evaluate(win, source) { return win.webContents.executeJavaScript(source, true); }
async function waitFor(win, source, label, attempts = 200) {
  for (let index = 0; index < attempts; index += 1) {
    if (await evaluate(win, source)) return;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

app.whenReady().then(async () => {
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let index = 0; index < 80 && BrowserWindow.getAllWindows().length === 0; index += 1) await delay(100);
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) throw new Error("Main process did not create BrowserWindow");
  try {
    const command = { id: "runtime-core-smoke-001", name: "study.resume", issuedAt: new Date().toISOString() };
    if (phase === "capture") {
      await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace][data-connection-state=READY]'))", "authenticated backend handshake + replay READY");
      const runtime = await evaluate(win, "window.v3Desktop.runtimeInfo()");
      if (runtime.agentEvidenceMode !== "DEVELOPMENT_INTEGRATION_FIXTURE") throw new Error(`fixture mode not bound ${JSON.stringify(runtime)}`);
      const [first, second] = await evaluate(win, `(async()=>{const command=${JSON.stringify(command)};return [await window.v3Desktop.executeCommand(command),await window.v3Desktop.executeCommand(command)]})()`);
      if (!first.accepted || !second.duplicate || second.executionCount !== 1) throw new Error(`exactly-once failed ${JSON.stringify([first, second])}`);
      await waitFor(win, "window.v3Desktop.runtimeInfo().then((info)=>info.durableEventCursor===1)", "durable event cursor commit after replay");
      const info = await evaluate(win, "window.v3Desktop.runtimeInfo()");
      if (!(info.persistenceRevision >= 2)) throw new Error(`workspace persistence revision did not advance ${JSON.stringify(info)}`);
      const workspace = await evaluate(win, "window.v3Desktop.loadWorkspace()");
      if (workspace.savedAt === null || !Array.isArray(workspace.executedCommandIds) || !workspace.executedCommandIds.includes(command.id)) {
        throw new Error(`workspace persistence failed ${JSON.stringify(workspace)}`);
      }
      console.log(`[runtime-core-smoke] capture: handshake READY, command accepted then duplicated, durable cursor=1, workspace persisted`);
    } else {
      await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace][data-connection-state=READY]'))", "restart handshake + replay READY");
      const replay = await evaluate(win, `window.v3Desktop.executeCommand(${JSON.stringify(command)})`);
      if (!replay.duplicate || replay.executionCount !== 1) throw new Error(`restart duplicate failed ${JSON.stringify(replay)}`);
      const info = await evaluate(win, "window.v3Desktop.runtimeInfo()");
      if (!(info.durableEventCursor >= 1)) throw new Error(`durable cursor did not resume across restart ${JSON.stringify(info)}`);
      const workspace = await evaluate(win, "window.v3Desktop.loadWorkspace()");
      if (workspace.savedAt === null || !workspace.executedCommandIds.includes(command.id)) {
        throw new Error(`workspace restart persistence failed ${JSON.stringify(workspace)}`);
      }
      console.log(`[runtime-core-smoke] restart: command duplicate persisted, durable cursor resumed at ${info.durableEventCursor}, workspace persisted`);
    }
    await win.close();
    app.quit();
  } catch (error) {
    console.error(error);
    app.exit(1);
  }
});
