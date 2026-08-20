// Clean-start Product Runtime executable research smoke.
// The Python boundary injects only a provider response; Product Entry itself
// receives closed source refs and never receives observations or numeric truth.
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, delimiter, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const storageRoot = mkdtempSync(resolve(tmpdir(), "v3-product-research-smoke-"));
const python = process.env.V3_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
const result = spawnSync(
  python,
  [resolve(root, "scripts/product_research_smoke_python.py"), storageRoot],
  {
    env: { ...process.env, PYTHONPATH: `${root}${delimiter}${resolve(root, "apps/backend/src")}` },
    encoding: "utf8",
  },
);
try {
  if (result.status !== 0) {
    console.error(result.stdout ?? "");
    console.error(result.stderr ?? "");
    process.exit(result.status ?? 1);
  }
  const evidence = JSON.parse((result.stdout ?? "").trim());
  if (evidence.status !== "PASS" || evidence.truth_state !== "DEMO" || evidence.maturity !== "PRODUCT_CONNECTED_CANDIDATE") {
    throw new Error("research smoke returned an unadmitted truth state");
  }
  console.log(JSON.stringify(evidence, null, 2));
  console.log("smoke:product-research PASS");
} finally {
  rmSync(storageRoot, { recursive: true, force: true });
}
