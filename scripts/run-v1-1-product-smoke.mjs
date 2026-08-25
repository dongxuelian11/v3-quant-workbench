import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";

const mode = process.argv[2];
if (!["data", "factor", "backtest", "result"].includes(mode)) {
  throw new Error("usage: run-v1-1-product-smoke.mjs <data|factor|backtest|result>");
}

const root = resolve(import.meta.dirname, "..");
const python = process.env.V3_TEST_PYTHON
  ?? process.env.V3_PYTHON
  ?? (process.platform === "win32" ? "python" : "python3");
const parent = resolve(process.env.V3_SMOKE_TEMP_ROOT ?? tmpdir());
await mkdir(parent, { recursive: true });
const storage = await mkdtemp(join(parent, `v3-v1-1-${mode}-smoke-`));
const env = {
  ...process.env,
  PYTHONDONTWRITEBYTECODE: "1",
  PYTHONPATH: [resolve(root, "apps", "backend", "src"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(delimiter),
  TMP: parent,
  TEMP: parent
};

try {
  const result = spawnSync(
    python,
    [
      resolve(root, "scripts", mode === "backtest" || mode === "result"
        ? "v1_1_product_c3_smoke.py"
        : `v1_1_product_${mode}_smoke.py`),
      storage,
      mode
    ],
    { cwd: root, env, encoding: "utf8" }
  );
  if (result.status !== 0) {
    throw new Error(`${mode} smoke failed:\n${result.stdout ?? ""}\n${result.stderr ?? ""}`);
  }
  const evidence = JSON.parse((result.stdout ?? "").trim());
  if (evidence.status !== "PASS" || evidence.truth !== "NOT_FORMAL" || evidence.admission !== "PRE_ALPHA") {
    throw new Error(`${mode} smoke returned an invalid truth envelope`);
  }
  console.log(JSON.stringify(evidence, null, 2));
  console.log(`smoke:product-${mode} PASS`);
} finally {
  await rm(storage, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}
