import assert from "node:assert/strict";
import { resolve } from "node:path";
import test from "node:test";

import { BackendSupervisor } from "../../dist/apps/desktop/src/main/backendRuntime/supervisor.js";
import { parseRound3ResearchEvidenceBundle } from "../../dist/packages/contracts/src/round3Evidence.js";
import { applyRound3ConnectionState, applyRound3EvidenceEvent, initialRound3AgentWorkspaceState } from "../../dist/apps/desktop/src/renderer/round3Evidence.js";
import { PERMISSION_SURFACE } from "../../dist/apps/desktop/src/renderer/agentWorkspace.js";

test("real Python bootstrap completes framed authenticated handshake and graceful shutdown", { timeout: 15_000 }, async () => {
  const root = resolve(import.meta.dirname, "../..");
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
  assert.equal(supervisor.capabilities.length, 17);
  assert.equal(supervisor.capabilities.every((item) => item.truth_state === "UNAVAILABLE"), true);
  const health = await supervisor.getHealth();
  assert.equal(health.state, "READY");
  await supervisor.shutdown(5_000);
  assert.equal(supervisor.state, "STOPPED");
  assert.deepEqual(diagnostics, []);
});

test("real canonical H/I/J chain crosses Python backend, WS-E transport, parser, and Agent Workspace projection", { timeout: 15_000 }, async () => {
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
  assert.deepEqual(bundle.projections.map((item) => item.source_object_id), [
    "pint_sha256_011e48a40e65b1ff92213b5ce1a4895f0412f91c0b534f8aa78c03e49df96a9e",
    "twv_sha256_7e9aa3d18cd1d4c1ea2dca665fdd760c866907c2043be3c467dc25df1152b9cd",
    "rawv_sha256_d6f24bd4402608eb8a7c844137162c68d8effd9ad535509efe4cf586203ff2fa",
    "rdr_sha256_060f64b4c30726126071aa15d407c1731ebf6fbec78d2d2494471117ec56cdf0",
    "btrs_sha256_d39992efac79dd077ab0919b59bc4072adb0f987c624c25bbfd019fef31490be",
    "btrr_sha256_4f08d474405ec0a5451bfc898851848db37a893479bf6e51af0afaf9ed06c09f"
  ]);
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

  const connected = applyRound3ConnectionState(initialRound3AgentWorkspaceState(), "READY");
  const state = applyRound3EvidenceEvent(connected, events[0]);
  assert.equal(state.boundary.mode, "DEVELOPMENT_INTEGRATION_FIXTURE");
  assert.deepEqual(state.data.sessions[0].evidenceIds, bundle.projections.map((item) => item.source_object_id));
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
