import assert from "node:assert/strict";
import test from "node:test";

import { PRODUCT_NAVIGATION, selectCurrentProjectLabel } from "../../apps/desktop/src/renderer/productShellModel.ts";

test("PRODUCT navigation enables only the connected Home and gives every deferred page a reason", () => {
  assert.deepEqual(PRODUCT_NAVIGATION.map((item) => item.id), ["home", "data", "research", "backtest", "results"]);
  assert.deepEqual(PRODUCT_NAVIGATION.filter((item) => item.available).map((item) => item.id), ["home"]);
  for (const item of PRODUCT_NAVIGATION.filter((candidate) => !candidate.available)) {
    assert.match(item.reason, /^NOT_AVAILABLE · V1_1_C[23]_[A-Z_]+_NOT_CONNECTED$/);
  }
});

test("Home labels only the currently bound project and never falls back to another project", () => {
  const projects = [
    { projectId: "prj_A", displayName: "项目 A" },
    { projectId: "prj_B", displayName: "项目 B" },
  ];
  assert.equal(selectCurrentProjectLabel({ projectId: "prj_B" }, projects), "项目 B");
  assert.equal(selectCurrentProjectLabel({ projectId: "prj_C" }, projects), "prj_C");
  assert.equal(selectCurrentProjectLabel(null, projects), "尚未绑定");
});
