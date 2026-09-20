import { defineConfig } from "vite";
import { resolve } from "node:path";
import { cp, readFile } from "node:fs/promises";
import { patchKlinecharts } from "./scripts/patch-klinecharts.mjs";

await patchKlinecharts();

// PDF.js loads CMaps, standard fonts and image decoders on demand, including offline installations.
const pdfResources = ["cmaps", "standard_fonts", "wasm", "iccs"];
const pdfRoot = resolve(import.meta.dirname, "node_modules/pdfjs-dist");
const rendererOutput = resolve(import.meta.dirname, "dist/apps/desktop/src/renderer");
const pdfAssets = {
  name: "v3-pdf-assets",
  configureServer(server) {
    server.middlewares.use("/pdf-assets", (req, res, next) => {
      const name = (req.url ?? "").split("?")[0].replace(/^\//, "");
      if (!/^(cmaps|standard_fonts|wasm|iccs)\/[\w.-]+$/.test(name)) return next();
      void readFile(resolve(pdfRoot, name)).then(data => {
        res.setHeader("Content-Type", name.endsWith(".wasm") ? "application/wasm" : name.endsWith(".js") ? "text/javascript" : "application/octet-stream");
        res.end(data);
      }).catch(() => { res.statusCode = 404; res.end(); });
    });
  },
  async writeBundle() {
    await Promise.all(pdfResources.map(name => cp(resolve(pdfRoot, name), resolve(rendererOutput, "pdf-assets", name), { recursive: true })));
  },
};

export default defineConfig({
  plugins: [pdfAssets],
  root: resolve(import.meta.dirname, "apps/desktop/src/renderer"),
  base: "./",
  build: {
    outDir: resolve(import.meta.dirname, "dist/apps/desktop/src/renderer"),
    emptyOutDir: false,
    sourcemap: true,
    target: "chrome142"
  }
});
