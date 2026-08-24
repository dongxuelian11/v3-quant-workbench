import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { sanitizedBackendEnvironment } from "../../dist/apps/desktop/src/main/backendRuntime/processFactory.js";
import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { parseRound3ResearchEvidenceBundle } from "../../dist/packages/contracts/src/round3Evidence.js";
import { applyRound3ConnectionState, applyRound3EvidenceEvent, initialRound3AgentWorkspaceState } from "../../apps/desktop/src/renderer/round3Evidence.ts";
import { PERMISSION_SURFACE } from "../../apps/desktop/src/renderer/agentWorkspace.ts";

test("sanitized backend environment forwards the Windows product storage base and strips secrets and home paths", () => {
  const source = {
    PATH: "/usr/bin:/bin",
    SystemRoot: "C:\\Windows",
    WINDIR: "C:\\Windows",
    TEMP: "C:\\Users\\dev\\AppData\\Local\\Temp",
    TMP: "C:\\Users\\dev\\AppData\\Local\\Temp",
    APPDATA: "C:\\Users\\dev\\AppData\\Roaming",
    LOCALAPPDATA: "C:\\Users\\dev\\AppData\\Local",
    V3_PRODUCT_STORAGE_ROOT: "D:\\isolated-product-storage",
    SECRET_TOKEN: "do-not-forward",
    USERPROFILE: "C:\\Users\\dev",
    HOMEDRIVE: "C:",
    HOMEPATH: "\\Users\\dev",
    UNRELATED_V3_SECRET: "v3-do-not-forward"
  };
  const env = sanitizedBackendEnvironment(source);
  // Allowed exactly: OS/python basics, APPDATA (CPython per-user site/tzdata),
  // LOCALAPPDATA (B3 normal product storage base on win32), the explicit
  // V3_PRODUCT_STORAGE_ROOT override, and forced UTF-8/unbuffered CPython.
  assert.deepEqual({ ...env }, {
    PATH: source.PATH,
    SystemRoot: source.SystemRoot,
    WINDIR: source.WINDIR,
    TEMP: source.TEMP,
    TMP: source.TMP,
    APPDATA: source.APPDATA,
    LOCALAPPDATA: source.LOCALAPPDATA,
    V3_PRODUCT_STORAGE_ROOT: source.V3_PRODUCT_STORAGE_ROOT,
    PYTHONUTF8: "1",
    PYTHONUNBUFFERED: "1"
  });
});

test("real Python bootstrap completes framed authenticated handshake and graceful shutdown", { timeout: 15_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
  // Isolate the real product storage: the normal product bootstrap must never
  // read or create the developer's real %LOCALAPPDATA%/v3-quant-workbench/product.
  const priorStorageRoot = process.env.V3_PRODUCT_STORAGE_ROOT;
  const storageRoot = await mkdtemp(join(tmpdir(), "v3-product-runtime-test-"));
  process.env.V3_PRODUCT_STORAGE_ROOT = storageRoot;
  try {
    const supervisor = new BackendSupervisor({
      pythonExecutable: process.env.V3_TEST_PYTHON ?? "python",
      backendWorkingDirectory: resolve(root, "apps/backend/src"),
      desktopVersion: "0.1.0-test",
      handshakeTimeoutMs: 10_000,
      requestTimeoutMs: 2_000,
      autoReconnect: false
    });
    const diagnostics = [];
    supervisor.on("diagnostic", (item) => diagnostics.push(item));
    await supervisor.start();
    assert.equal(supervisor.state, "READY");
    assert.equal(supervisor.capabilities.length, 18);
    // B3: the normal production bootstrap binds the real product composition.
    // Only fully bound services are FORMAL; partial TaskService and every other
    // incomplete service stay honestly UNAVAILABLE on the normal path.
    assert.deepEqual(
      supervisor.capabilities.filter((item) => item.truth_state === "FORMAL").map((item) => item.code).sort(),
      ["ArtifactService", "BacktestService", "ProductEntryService", "ProjectSessionService"]
    );
    const taskCapability = supervisor.capabilities.find((item) => item.code === "TaskService");
    assert.equal(taskCapability?.truth_state, "UNAVAILABLE");
    assert.equal(taskCapability?.reason_code, "PRODUCT_OPERATION_SET_INCOMPLETE");
    assert.equal(supervisor.capabilities.some((item) => item.truth_state === "DEMO"), false);
    assert.equal(
      supervisor.capabilities.every((item) => item.truth_state === "FORMAL" || item.truth_state === "UNAVAILABLE"),
      true
    );
    const health = await supervisor.getHealth();
    assert.equal(health.state, "READY");
    await supervisor.shutdown(5_000);
    assert.equal(supervisor.state, "STOPPED");
    assert.deepEqual(diagnostics, []);
  } finally {
    if (priorStorageRoot === undefined) delete process.env.V3_PRODUCT_STORAGE_ROOT;
    else process.env.V3_PRODUCT_STORAGE_ROOT = priorStorageRoot;
    await rm(storageRoot, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("real canonical two-rebalance H/I/J graph crosses Python backend, WS-E transport, parser, and Agent Workspace", { timeout: 15_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
  const supervisor = new BackendSupervisor({
    pythonExecutable: process.env.V3_TEST_PYTHON ?? "python",
    backendWorkingDirectory: resolve(root, "apps/backend/src"),
    backendModule: "v3_backend.adapters.round3_evidence.development_runtime",
    desktopVersion: "0.1.0-round3-test",
    projectContext: {
      projectId: "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      projectContextRevisionId: "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAV",
      lastDurableProjectEventSequence: 0
    },
    handshakeTimeoutMs: 10_000,
    requestTimeoutMs: 2_000,
    autoReconnect: false
  });
  const events = [];
  const diagnostics = [];
  supervisor.on("event", (event) => events.push(event));
  supervisor.on("diagnostic", (item) => diagnostics.push(item));
  try {
    await supervisor.start();
  } catch (error) {
    error.message += `; diagnostics=${JSON.stringify(diagnostics)}`;
    throw error;
  }
  assert.equal(supervisor.state, "READY");
  assert.equal(events.length, 1);
  assert.equal(events[0].event_type, "round3.research.evidence.bundle.v1");

  const bundle = parseRound3ResearchEvidenceBundle(events[0].body);
  assert.equal(bundle.source_mode, "DEVELOPMENT_INTEGRATION_FIXTURE");
  const exactEvidenceIds = [
    "pint_sha256_011e48a40e65b1ff92213b5ce1a4895f0412f91c0b534f8aa78c03e49df96a9e",
    "pint_sha256_146f74ad6f8d8d2be0d21e3590f573125a7e57d566f9fc4357b30a74a23789de",
    "twv_sha256_208750185bacf5ce2758e4ba1eff8ecbfea197f792d5894954d02565ffc4bc32",
    "twv_sha256_9d9d92d3de1d30e4149879183aab5b2bdf2f0e93227526054e477d8bc86ffabd",
    "rawv_sha256_2afb77846c2f39a7c92ef883767416b336bf4a9c8762a3636c68eb749bfa0efb",
    "rawv_sha256_d088399d897adb9b91d1126d5bc68415a6633a180017de5d43949f01a0579eaa",
    "rdr_sha256_b732c998ff2c2f65f81303c128dc0f368059eacb91d66b4321f36e915de339e4",
    "rdr_sha256_f0c13729801864cb98a96f9ae3bf30e17d0ad2e390db2203529f10324c51c8ec",
    "btrs_sha256_30a3debc8b915903d748c6e5613375a1219bed7ca8397f9a3539a49ddcebf7ba",
    "btrr_sha256_e21779419581527099a019c32512b3e10c3c74ca962cfd266f7a63c689d1722d"
  ];
  assert.deepEqual(bundle.projections.map((item) => item.source_object_id), exactEvidenceIds);
  assert.deepEqual(bundle.schedule_bindings.map((item) => [item.schedule_index, item.effective_at, item.risk_adjusted_weight_vector_id]), [
    [0, "2026-01-06T01:00:00+00:00", "rawv_sha256_d088399d897adb9b91d1126d5bc68415a6633a180017de5d43949f01a0579eaa"],
    [1, "2026-01-07T01:00:00+00:00", "rawv_sha256_2afb77846c2f39a7c92ef883767416b336bf4a9c8762a3636c68eb749bfa0efb"]
  ]);
  assert.equal(bundle.lineage_edges.length, 11);
  assert.equal(bundle.projections.every((item) => item.validation_state === "NOT_RUN"), true);
  assert.equal(bundle.projections.every((item) => item.canonical_admission_state === "PRE_ALPHA"), true);
  const unknown = structuredClone(events[0].body);
  unknown.shadow_finance_contract = {};
  assert.throws(() => parseRound3ResearchEvidenceBundle(unknown), /closed wire shape/);
  const mismatched = structuredClone(events[0].body);
  mismatched.projections[2].source_content_sha256 = "f".repeat(64);
  assert.throws(() => parseRound3ResearchEvidenceBundle(mismatched), /source ID\/hash mismatch/);
  const unknownKind = structuredClone(events[0].body);
  unknownKind.projections[0].source_artifact_type = "ShadowPortfolio";
  assert.throws(() => parseRound3ResearchEvidenceBundle(unknownKind), /unknown Round 3 evidence kind/);
  const unknownRenderer = structuredClone(events[0].body);
  unknownRenderer.projections[0].renderer_key = "arbitrary-html";
  unknownRenderer.projections[0].renderer_payload.renderer = "arbitrary-html";
  assert.throws(() => parseRound3ResearchEvidenceBundle(unknownRenderer), /unknown Round 3 renderer/);
  const unsupportedSchema = structuredClone(events[0].body);
  unsupportedSchema.bundle_schema_version = "v3.round3_research_evidence_bundle/2.0.0";
  assert.throws(() => parseRound3ResearchEvidenceBundle(unsupportedSchema), /unsupported Round 3 bundle schema/);
  const duplicate = structuredClone(events[0].body);
  duplicate.projections.splice(1, 0, structuredClone(duplicate.projections[0]));
  assert.throws(() => parseRound3ResearchEvidenceBundle(duplicate), /duplicate canonical/);
  const missingScheduledRisk = structuredClone(events[0].body);
  missingScheduledRisk.projections.splice(4, 1);
  assert.throws(() => parseRound3ResearchEvidenceBundle(missingScheduledRisk), /missing exact RiskAdjusted evidence/);
  const orphanRisk = structuredClone(events[0].body);
  orphanRisk.schedule_bindings.splice(1, 1);
  assert.throws(() => parseRound3ResearchEvidenceBundle(orphanRisk), /orphan RiskAdjusted evidence/);
  const wrongChainEdge = structuredClone(events[0].body);
  wrongChainEdge.lineage_edges.find((item) => item.relation === "RISK_APPLICATION_TARGET_BINDING").target_object_id = "rawv_sha256_" + "0".repeat(64);
  assert.throws(() => parseRound3ResearchEvidenceBundle(wrongChainEdge), /missing, wrong, or extra edges/);
  const wrongReceiptBinding = structuredClone(events[0].body);
  const riskBEdge = wrongReceiptBinding.lineage_edges.find((item) => item.source_object_id === "twv_sha256_208750185bacf5ce2758e4ba1eff8ecbfea197f792d5894954d02565ffc4bc32" && item.relation === "RISK_APPLICATION_TARGET_BINDING");
  riskBEdge.binding_object_id = "rar_sha256_2d20d5593550d6835e43e378c69a4538d781c8f020b72b0fac815a98eda5eb9d";
  assert.throws(() => parseRound3ResearchEvidenceBundle(wrongReceiptBinding), /missing, wrong, or extra edges/);

  const connected = applyRound3ConnectionState(initialRound3AgentWorkspaceState(), "READY");
  const state = applyRound3EvidenceEvent(connected, events[0]);
  assert.equal(state.boundary.mode, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.deepEqual(state.data.sessions[0].evidenceIds, bundle.projections.map((item) => item.source_object_id));
  assert.deepEqual(
    Object.fromEntries(["TargetWeightVector", "RiskAdjustedWeightVector", "RiskDecisionReport", "BacktestRunSpec", "BacktestRunResult"].map((kind) => [kind, state.data.evidence.filter((item) => item.kind === kind).length])),
    { TargetWeightVector: 2, RiskAdjustedWeightVector: 2, RiskDecisionReport: 2, BacktestRunSpec: 1, BacktestRunResult: 1 }
  );
  assert.equal(state.data.artifacts.length, 10);
  assert.equal(state.data.timeline.length, 10);
  assert.equal(state.data.statements.length, 0);
  assert.equal(state.data.timeline.every((item) => item.authority === "EVIDENCE" && item.state === "PRE_ALPHA"), true);
  assert.equal(state.data.timeline.some((item) => /executed|succeeded/i.test(item.title)), false);
  assert.deepEqual(PERMISSION_SURFACE.filter((item) => item.allowed).map((item) => item.level), ["L0_READ", "L1_DRAFT"]);
  assert.deepEqual(PERMISSION_SURFACE.filter((item) => !item.allowed).map((item) => item.level), ["L2_EXECUTE", "L3_PUBLISH"]);
  await supervisor.shutdown(5_000);
});

test("production Agent Workspace state is explicit connected-empty or disconnected without demo substitution", () => {
  const initial = initialRound3AgentWorkspaceState();
  assert.equal(initial.boundary.mode, "BACKEND_DISCONNECTED");
  assert.deepEqual(initial.data.evidence, []);
  const connected = applyRound3ConnectionState(initial, "READY");
  assert.equal(connected.boundary.mode, "LIVE_READ_ONLY_NO_EVIDENCE");
  assert.equal(connected.boundary.source, "NO_CANONICAL_EVIDENCE_AVAILABLE");
  assert.deepEqual(connected.data.evidence, []);
});
