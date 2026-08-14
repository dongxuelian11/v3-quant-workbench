const { app } = require("electron");
const path = require("node:path");

// Second-instance probe: loads the product main with the same userData as
// the primary instance. The product main takes its single-instance decision
// before any WorkspaceStore access; when the primary holds the lock, the
// require below exits this process immediately without reading or writing
// the shared store.
const root = path.resolve(__dirname, "..");
app.setPath("userData", path.resolve(root, process.env.V3_SMOKE_USER_DATA || "deliverables/electron-user-data-runtime-core"));
app.setPath("cache", path.resolve(app.getPath("userData"), "cache"));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("disable-dev-shm-usage");
app.commandLine.appendSwitch("no-sandbox");

require(path.resolve(root, "dist/apps/desktop/src/main.js"));

// Reaching this point means the single-instance lock was not enforced and
// the product main proceeded toward WorkspaceStore access.
setTimeout(() => {
  console.error("SECONDARY_INSTANCE_BYPASSED_SINGLE_INSTANCE_LOCK");
  app.exit(1);
}, 8000);
