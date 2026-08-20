const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

// Targeted Desktop<->B3 smoke: the normal packaged-style Electron main boots
// the canonical product bootstrap (no development fixture) against a
// test-prepared product storage root, then the renderer-exposed typed product
// bridge drives the real golden path: bind -> context -> submit existing
// canonical RunSpec -> Task/Result/Artifact re-query -> graceful close ->
// restart -> canonical recovery with stable identities.
const root = path.resolve(__dirname, "..");
const phase = process.env.V3_SMOKE_PHASE || "capture";
const electronData = path.resolve(root, process.env.V3_SMOKE_USER_DATA || "deliverables/electron-user-data-desktop-b3");
const markerPath = path.join(electronData, "desktop-b3-smoke-marker.json");
fs.mkdirSync(electronData, { recursive: true });
app.setPath("userData", electronData);
app.setPath("cache", path.resolve(electronData, "cache"));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("disable-dev-shm-usage");
app.commandLine.appendSwitch("no-sandbox");

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function evaluate(win, source) { return win.webContents.executeJavaScript(source, true); }
async function waitFor(win, source, label, attempts = 300) {
  for (let index = 0; index < attempts; index += 1) {
    if (await evaluate(win, source)) return;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${label}`);
}
function fail(error) {
  console.error(error);
  app.exit(1);
}

app.whenReady().then(async () => {
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let index = 0; index < 80 && BrowserWindow.getAllWindows().length === 0; index += 1) await delay(100);
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) throw new Error("main process did not create BrowserWindow");
  try {
    // LIVE product mode: the development integration fixture must be denied.
    await waitFor(win, "Boolean(document.querySelector('[data-testid=agent-workspace]'))", "renderer shell");
    const runtime = await evaluate(win, "window.v3Desktop.runtimeInfo()");
    if (runtime.agentEvidenceMode !== "LIVE_READ_ONLY") throw new Error(`LIVE path leaked into fixture mode: ${JSON.stringify(runtime)}`);

    const projectId = process.env.V3_SMOKE_PROJECT_ID;
    const pcrId = process.env.V3_SMOKE_PCR_ID;
    const runSpecId = process.env.V3_SMOKE_RUN_SPEC_ID;
    if (!projectId || !pcrId || !runSpecId) throw new Error("smoke requires V3_SMOKE_PROJECT_ID / V3_SMOKE_PCR_ID / V3_SMOKE_RUN_SPEC_ID");

    await waitFor(win, "window.v3ProductRuntime && window.v3ProductRuntime.getProductStatus().then((s)=>s.backendState==='READY').catch(()=>false)", "product backend READY");

    // Security boundary: no generic request(operationId, payload) exposure.
    const keys = await evaluate(win, "Object.keys(window.v3ProductRuntime).sort().join(',')");
    if (keys.split(",").some((key) => ["request", "invoke", "send", "operation"].includes(key))) {
      throw new Error(`product bridge exposes a generic transport seam: ${keys}`);
    }

    const statusBefore = await evaluate(win, "window.v3ProductRuntime.getProductStatus()");
    const caps = Object.fromEntries(statusBefore.capabilities.map((capability) => [capability.code, capability]));
    for (const service of ["ProjectSessionService", "ArtifactService", "BacktestService"]) {
      if (caps[service]?.truth_state !== "FORMAL") throw new Error(`${service} must be FORMAL`);
    }
    if (caps.TaskService?.truth_state !== "UNAVAILABLE" || caps.TaskService?.reason_code !== "PRODUCT_OPERATION_SET_INCOMPLETE") {
      throw new Error(`TaskService must be honestly incomplete: ${JSON.stringify(caps.TaskService)}`);
    }
    if (caps.ResultService?.truth_state !== "UNAVAILABLE" || caps.ResultService?.reason_code !== "PRODUCT_OPERATION_SET_INCOMPLETE") {
      throw new Error(`ResultService must be honestly incomplete: ${JSON.stringify(caps.ResultService)}`);
    }
    if (Object.values(caps).some((capability) => capability.truth_state === "DEMO")) throw new Error("DEMO capability present on the LIVE path");

    if (phase === "capture") {
      if (statusBefore.bindingState !== "NO_CANONICAL_PROJECT_BOUND" || statusBefore.boundProject !== null) {
        throw new Error(`clean storage must start unbound: ${JSON.stringify(statusBefore)}`);
      }
      // Invalid refs must fail closed and must not be persisted.
      const invalid = await evaluate(win, `window.v3ProductRuntime.connectExistingProject({projectId: ${JSON.stringify(projectId)}, projectContextRevisionId: "pcr_${"0".repeat(30)}"}).then(()=>({ok:true}), (error)=>({ok:false, code:(error&&error.code)||null,message:(error&&error.message)||String(error)}))`);
      if (invalid.ok) throw new Error("invalid context revision was accepted");
      const stillUnbound = await evaluate(win, "window.v3ProductRuntime.getBoundProject()");
      if (stillUnbound !== null) throw new Error("invalid binding was persisted");

      console.log("[desktop-b3-smoke] capture: connecting canonical project");
      const context = await evaluate(win, `window.v3ProductRuntime.connectExistingProject({projectId: ${JSON.stringify(projectId)}, projectContextRevisionId: ${JSON.stringify(pcrId)}})`);
      if (context.projectId !== projectId) throw new Error(`bound project mismatch: ${JSON.stringify(context)}`);
      const bound = await evaluate(win, "window.v3ProductRuntime.getBoundProject()");
      if (!bound || bound.projectId !== projectId || bound.projectContextRevisionId !== pcrId) throw new Error(`binding refs wrong: ${JSON.stringify(bound)}`);

      console.log("[desktop-b3-smoke] capture: submitting existing canonical RunSpec");
      const submitted = await evaluate(win, `window.v3ProductRuntime.submitExistingBacktestRunSpec(${JSON.stringify(runSpecId)})`);
      if (!submitted.taskId.startsWith("tsk_") || !submitted.runId.startsWith("run_")) throw new Error(`non-canonical task/run identity: ${JSON.stringify(submitted)}`);
      const task = await evaluate(win, `window.v3ProductRuntime.getTask(${JSON.stringify(submitted.taskId)})`);
      if (task.state !== "SUCCEEDED") throw new Error(`task did not reach SUCCEEDED: ${JSON.stringify(task)}`);
      const resultArtifactId = task.outputs.BACKTEST_RUN_RESULT;
      if (typeof resultArtifactId !== "string" || !resultArtifactId.startsWith("art_sha256_")) throw new Error(`missing canonical result artifact: ${JSON.stringify(task.outputs)}`);
      const events = await evaluate(win, "window.v3ProductRuntime.getTaskEvents(0, 500)");
      const types = new Set(events.items.map((item) => item.eventType));
      for (const required of ["TASK_QUEUED", "TASK_STARTED", "TASK_SUCCEEDED"]) {
        if (!types.has(required)) throw new Error(`missing durable task event ${required}`);
      }
      const resultId = task.resultId;
      if (!resultId || !resultId.startsWith("res_")) throw new Error(`Task read model did not resolve canonical result_id: ${JSON.stringify(task)}`);
      const result = await evaluate(win, `window.v3ProductRuntime.getResult(${JSON.stringify(resultId)})`);
      if (result.state !== "PENDING_RECONCILIATION") throw new Error(`result state wrong: ${JSON.stringify(result)}`);
      const descriptor = await evaluate(win, `window.v3ProductRuntime.getArtifactDescriptor(${JSON.stringify(resultArtifactId)})`);
      if (!/^[0-9a-f]{64}$/.test(descriptor.sha256)) throw new Error(`descriptor sha invalid: ${JSON.stringify(descriptor)}`);
      const ticket = await evaluate(win, `window.v3ProductRuntime.openArtifactStream(${JSON.stringify(resultArtifactId)})`);
      if (ticket.mode !== "STREAM_TICKET") throw new Error(`stream ticket wrong: ${JSON.stringify(ticket)}`);

      // Numeric caller bypass must be impossible: the typed bridge only takes
      // the canonical run spec id; malformed identities fail closed.
      const bypass = await evaluate(win, "window.v3ProductRuntime.submitExistingBacktestRunSpec('not-a-canonical-spec').then(()=>({ok:true}),(error)=>({ok:false, code:(error&&error.code)||null,message:(error&&error.message)||String(error)}))");
      if (bypass.ok) throw new Error("non-canonical run spec was accepted");

      fs.writeFileSync(markerPath, JSON.stringify({ taskId: submitted.taskId, runId: submitted.runId, resultId, resultArtifactId, sha256: descriptor.sha256, byteSize: descriptor.byteSize }, null, 2));
      console.log(`[desktop-b3-smoke] capture: golden path PASS (task=${submitted.taskId} result=${resultId} sha=${descriptor.sha256.slice(0, 12)}…)`);
    } else if (phase === "stale-restart") {
      // T5: canonical re-validation fails on restart -> BINDING_STALE must
      // fail closed everywhere; structured codes must survive the preload.
      console.log("[desktop-b3-smoke] stale-restart: waiting for stale re-validation");
      await waitFor(win,
        "window.v3ProductRuntime.getProductStatus().then((s)=>s.bindingState==='BINDING_STALE'&&s.boundProject===null).catch(()=>false)",
        "BINDING_STALE status after failed canonical re-validation", 200);
      const staleStatus = await evaluate(win, "window.v3ProductRuntime.getProductStatus()");
      if (staleStatus.backendState !== "READY") throw new Error(`stale phase backend not READY: ${JSON.stringify(staleStatus)}`);
      if (staleStatus.bindingState !== "BINDING_STALE" || staleStatus.boundProject !== null) {
        throw new Error(`stale status must fail closed: ${JSON.stringify(staleStatus)}`);
      }
      if ((await evaluate(win, "window.v3ProductRuntime.getBoundProject()")) !== null) {
        throw new Error("stale refs leaked through getBoundProject as admitted truth");
      }
      const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
      const blockedTask = await evaluate(win, `window.v3ProductRuntime.getTask(${JSON.stringify(marker.taskId)}).then(()=>({ok:true}),(error)=>({ok:false, code:(error&&error.code)||null,message:(error&&error.message)||String(error)}))`);
      if (blockedTask.ok || blockedTask.code !== "BINDING_STALE") {
        throw new Error(`stale getTask must fail closed with BINDING_STALE: ${JSON.stringify(blockedTask)}`);
      }
      const blockedSubmit = await evaluate(win, `window.v3ProductRuntime.submitExistingBacktestRunSpec(${JSON.stringify(runSpecId)}).then(()=>({ok:true}),(error)=>({ok:false, code:(error&&error.code)||null,message:(error&&error.message)||String(error)}))`);
      if (blockedSubmit.ok || blockedSubmit.code !== "BINDING_STALE") {
        throw new Error(`stale submit must fail closed with BINDING_STALE: ${JSON.stringify(blockedSubmit)}`);
      }
      // T6 (real transport): a valid structured backend error (frozen-pattern
      // rejection) must survive the preload verbatim, not degrade to generic.
      const invalidPcr = await evaluate(win, `window.v3ProductRuntime.connectExistingProject({projectId: ${JSON.stringify(projectId)}, projectContextRevisionId: "pcr_${"0".repeat(26)}"}).then(()=>({ok:true}),(error)=>({ok:false, code:(error&&error.code)||null,message:(error&&error.message)||String(error)}))`);
      if (invalidPcr.ok || typeof invalidPcr.code !== "string" || invalidPcr.code === "PRODUCT_BRIDGE_ERROR" || invalidPcr.code === "PRODUCT_BRIDGE_ERROR") {
        throw new Error(`structured backend error degraded in preload: ${JSON.stringify(invalidPcr)}`);
      }
      // Reconnect restores the admitted binding from the same canonical refs.
      const rebound = await evaluate(win, `window.v3ProductRuntime.connectExistingProject({projectId: ${JSON.stringify(projectId)}, projectContextRevisionId: ${JSON.stringify(pcrId)}})`);
      if (rebound.projectId !== projectId) throw new Error(`reconnect failed: ${JSON.stringify(rebound)}`);
      const afterReconnect = await evaluate(win, "window.v3ProductRuntime.getProductStatus()");
      if (afterReconnect.bindingState !== "PROJECT_BOUND" || afterReconnect.boundProject === null) {
        throw new Error(`reconnect did not restore PROJECT_BOUND: ${JSON.stringify(afterReconnect)}`);
      }
      console.log("[desktop-b3-smoke] stale-restart: BINDING_STALE fail-closed, structured errors preserved, reconnect restored binding PASS");
    } else {
      // Restart recovery: binding restored from canonical read state, no UI
      // event history involved.
      let attempts = 0;
      let status = await evaluate(win, "window.v3ProductRuntime.getProductStatus()");
      while (status.bindingState === "NO_CANONICAL_PROJECT_BOUND" && attempts < 50) {
        await delay(100);
        status = await evaluate(win, "window.v3ProductRuntime.getProductStatus()");
        attempts += 1;
      }
      if (status.bindingState !== "PROJECT_BOUND" || status.boundProject?.projectId !== projectId) {
        const probe = await evaluate(win, "(async()=>{try{const s=await window.v3ProductRuntime.restoreSession();return {ok:true,state:s.state}}catch(e){return {ok:false,code:(e&&e.code)||null,message:(e&&e.message)||String(e)}}})()");
        throw new Error(`restart did not restore canonical binding: ${JSON.stringify(status)} restoreSessionProbe=${JSON.stringify(probe)}`);
      }
      const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
      const restored = await evaluate(win, "window.v3ProductRuntime.restoreSession()");
      if (restored.projectId !== projectId) throw new Error(`restoreSession mismatch: ${JSON.stringify(restored)}`);
      const task = await evaluate(win, `window.v3ProductRuntime.getTask(${JSON.stringify(marker.taskId)})`);
      if (task.taskId !== marker.taskId || task.runId !== marker.runId || task.state !== "SUCCEEDED") {
        throw new Error(`restart task diverged: ${JSON.stringify(task)}`);
      }
      const result = await evaluate(win, `window.v3ProductRuntime.getResult(${JSON.stringify(marker.resultId)})`);
      if (result.resultId !== marker.resultId) throw new Error(`restart result diverged: ${JSON.stringify(result)}`);
      const descriptor = await evaluate(win, `window.v3ProductRuntime.getArtifactDescriptor(${JSON.stringify(marker.resultArtifactId)})`);
      if (descriptor.sha256 !== marker.sha256 || descriptor.byteSize !== marker.byteSize) {
        throw new Error(`restart artifact diverged: ${JSON.stringify(descriptor)}`);
      }
      const duplicate = await evaluate(win, "window.v3ProductRuntime.getBoundProject()");
      if (duplicate.sessionId !== status.boundProject.sessionId) throw new Error("session identity unstable across restart");
      console.log(`[desktop-b3-smoke] restart: canonical recovery PASS (task=${marker.taskId} sha stable=${marker.sha256.slice(0, 12)}…)`);
    }
    await win.close();
    app.quit();
  } catch (error) {
    fail(error);
  }
}).catch(fail);

app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
