import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  root: resolve(import.meta.dirname, "apps/desktop/src/renderer"),
  base: "./",
  build: {
    outDir: resolve(import.meta.dirname, "dist/apps/desktop/src/renderer"),
    emptyOutDir: false,
    sourcemap: true,
    target: "chrome142"
  }
});
