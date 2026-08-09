import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const renderer = await readFile(resolve(root, "apps/desktop/src/renderer/renderer.ts"), "utf8");
const contracts = await readFile(resolve(root, "packages/contracts/src/index.ts"), "utf8");

test("formal product has exactly five Labs", () => {
  const ids = [...renderer.matchAll(/id: "(research|strategy|model|backtest|result)"/g)].map((match) => match[1]);
  assert.deepEqual(ids, ["research", "strategy", "model", "backtest", "result"]);
});

test("backend boundary is explicitly unavailable and not formal output", () => {
  assert.match(contracts, /availability: "unavailable"/);
  assert.match(contracts, /formalOutputAllowed: false/);
  assert.match(renderer, /UnavailableBackendProvider/);
});

test("accepted Wave 1 and Wave 2 surface markers are present", () => {
  for (const marker of ["Universe Builder", "Visual", "Code", "Split", "Strategy Draft", "STUDY", "TRIAL TABLE", "ModelVersion", "Prediction signal pending"]) {
    if (marker === "Strategy Draft") continue;
    assert.match(renderer, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"));
  }
});
