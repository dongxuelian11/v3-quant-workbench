const { app, BrowserWindow } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const screenshots = path.resolve(root, "deliverables", "screenshots");
const electronData = path.resolve(root, "deliverables", "electron-user-data");
const labs = ["research", "strategy", "model", "backtest", "result"];
const expectedTitles = ["Research Lab", "Strategy Lab", "Model Lab", "Backtest Lab", "Result Lab"];

fs.mkdirSync(electronData, { recursive: true });
app.setPath("userData", electronData);
app.setPath("cache", path.resolve(electronData, "cache"));
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("no-sandbox");

app.whenReady().then(async () => {
  fs.mkdirSync(screenshots, { recursive: true });
  // Load the real compiled Electron main process so IPC registration and the
  // typed preload bridge are exercised together.
  require(path.resolve(root, "dist/apps/desktop/src/main.js"));
  for (let attempt = 0; attempt < 30 && BrowserWindow.getAllWindows().length === 0; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const win = BrowserWindow.getAllWindows()[0];
  if (!win) throw new Error("Electron main process did not create a BrowserWindow");
  await new Promise((resolve) => setTimeout(resolve, 250));
  const seen = [];
  for (let index = 0; index < labs.length; index += 1) {
    const lab = labs[index];
    let title;
    for (let attempt = 0; attempt < 20 && !title; attempt += 1) {
      title = await win.webContents.executeJavaScript(`document.querySelector('h1')?.textContent`);
      if (!title) await new Promise((resolve) => setTimeout(resolve, 50));
    }
    if (title !== expectedTitles[index]) throw new Error(`Expected ${expectedTitles[index]}, got ${title}`);
    seen.push({ lab, title });
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.resolve(screenshots, `lab-${String(index + 1).padStart(2, "0")}-${lab}.png`), image.toPNG());
    if (index < labs.length - 1) {
      await win.webContents.executeJavaScript(`document.querySelector('[data-lab="${labs[index + 1]}"]')?.click()`);
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  const state = await win.webContents.executeJavaScript(`window.v3Desktop.getBackendStatus()`);
  if (state.availability !== "unavailable" || state.formalOutputAllowed !== false) throw new Error("Backend truthfulness guard failed");
  fs.writeFileSync(path.resolve(screenshots, "shell-smoke.json"), JSON.stringify({ seen, backendStatus: state }, null, 2));
  await win.close();
  app.quit();
}).catch((error) => {
  console.error(error);
  app.exit(1);
});
