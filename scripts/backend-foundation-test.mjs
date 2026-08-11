import { spawnSync } from "node:child_process";
import { delimiter, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const backendSource = resolve(root, "apps/backend/src");
const candidates = process.env.V3_PYTHON
  ? [[process.env.V3_PYTHON, []]]
  : process.platform === "win32"
    ? [["py", ["-3.14"]], ["python", []]]
    : [["python3", []], ["python", []]];

let selected;
for (const [command, prefix] of candidates) {
  const probe = spawnSync(command, [...prefix, "--version"], { encoding: "utf8" });
  const version = `${probe.stdout ?? ""}${probe.stderr ?? ""}`.trim();
  if (probe.status === 0 && /^Python 3\.14\./.test(version)) {
    selected = { command, prefix, version };
    break;
  }
}

if (!selected) {
  console.error("Canonical Backend Foundation tests require CPython 3.14.x. Set V3_PYTHON to an explicit interpreter when it is not on PATH.");
  process.exit(1);
}

console.log(`Using ${selected.version}; authority patch is 3.14.7.`);
const env = {
  ...process.env,
  PYTHONPATH: process.env.PYTHONPATH
    ? `${backendSource}${delimiter}${process.env.PYTHONPATH}`
    : backendSource
};

const suites = [
  "track_a0_truth_admission",
  "ws_a_contracts",
  "ws_b_catalog",
  "ws_c_artifact",
  "ws_d_task_workers",
  "ws_e_runtime",
  "br1_foundation_integration",
  "ws_f_data_truth",
  "track_c_factor_dataset_experiment",
  "track_d_ai_copilot",
  "track_e_model_prediction_runtime",
  "track_f_strategy_runtime",
  "track_g_ai_research_evidence_integration",
  "round3_w0_weight_seam",
  "track_h_portfolio_construction",
  "round3_track_i_risk_runtime",
  "track_j_a_share_backtest_core",
  "round3_integration_closure",
  "track_l_result_analytics",
  "track_m_generative_research_ui",
  "reviewer_integration"
];

for (const suite of suites) {
  const args = [
    ...selected.prefix,
    "-B",
    "-m",
    "unittest",
    "discover",
    "-s",
    `apps/backend/tests/${suite}`,
    "-t",
    "apps/backend/tests",
    "-v"
  ];
  const result = spawnSync(selected.command, args, { cwd: root, env, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const compile = spawnSync(
  selected.command,
  [...selected.prefix, "-m", "compileall", "-q", "apps/backend/src", "apps/backend/tests"],
  { cwd: root, env, stdio: "inherit" }
);
if (compile.status !== 0) process.exit(compile.status ?? 1);
console.log("Canonical Backend Foundation through Round 3 H/I/J and the Round 3 read-only integration closure: tests and compile gate passed.");
