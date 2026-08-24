import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const { LocalDataSourceBroker } = await import(
  "../../dist/apps/desktop/src/main/productRuntime/localDataImport.js"
);
const { ProductBridge } = await import(
  "../../dist/apps/desktop/src/main/productRuntime/productBridge.js"
);
const { ProductBindingStore, productBindingPath } = await import(
  "../../dist/apps/desktop/src/main/productRuntime/bindingStore.js"
);

const PROJECT_ID = "prj_01ARZ3NDEKTSV4RRFFQ69G5FAV";
const CONTEXT_ID = "pcr_01ARZ3NDEKTSV4RRFFQ69G5FAW";
const SESSION_ID = "018f47f2-9b02-7cc0-8ee6-1b82e3d62c01";
const store = () => ({
  getProjectEventCursor() { return 0; },
  commitProjectEventCursor() { return Promise.resolve(); }
});

function transferControl(frames, expectedBytes) {
  let received = Buffer.alloc(0);
  const artifactSha = createHash("sha256").update(expectedBytes).digest("hex");
  const artifactId = `art_sha256_${artifactSha}`;
  return async (frame) => {
    frames.push(frame);
    if (frame.kind === "localData.beginTransfer") {
      return {
        kind: "localData.transferReady",
        transfer_id: "ldt_01ARZ3NDEKTSV4RRFFQ69G5FAX",
        next_offset: 0,
        max_chunk_bytes: 256 * 1024
      };
    }
    if (frame.kind === "localData.appendChunk") {
      const chunk = Buffer.from(frame.payload_base64, "base64");
      assert.ok(chunk.byteLength > 0 && chunk.byteLength <= 256 * 1024);
      assert.equal(frame.offset, received.byteLength);
      assert.equal(createHash("sha256").update(chunk).digest("hex"), frame.chunk_sha256);
      received = Buffer.concat([received, chunk]);
      return {
        kind: "localData.chunkAccepted",
        transfer_id: frame.transfer_id,
        next_offset: received.byteLength
      };
    }
    if (frame.kind === "localData.finishTransfer") {
      assert.deepEqual(received, expectedBytes);
      assert.equal(frame.expected_byte_size, expectedBytes.byteLength);
      assert.equal(frame.expected_sha256, createHash("sha256").update(expectedBytes).digest("hex"));
      return {
        kind: "localData.sourcePublished",
        transfer_id: frame.transfer_id,
        source: {
          artifact_id: artifactId,
          sha256: artifactSha,
          byte_size: expectedBytes.byteLength,
          media_type: "text/csv",
          display_name: "bars.csv"
        }
      };
    }
    if (frame.kind === "localData.abortTransfer") {
      return { kind: "localData.transferAborted", transfer_id: frame.transfer_id };
    }
    throw new Error(`unexpected local-data frame ${String(frame.kind)}`);
  };
}

test("ACC-C2-01 native source capability hides the path and streams bounded verified chunks", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-local-data-transfer-"));
  try {
    const file = join(dir, "bars.csv");
    const bytes = Buffer.alloc(600 * 1024 + 17, 0x61);
    await writeFile(file, bytes);
    const broker = new LocalDataSourceBroker({
      chooseFile: async () => file,
      tokenFactory: () => "ldc_01ARZ3NDEKTSV4RRFFQ69G5FAY"
    });

    const selection = await broker.chooseSource();
    assert.deepEqual(Object.keys(selection).sort(), ["byteSize", "capabilityToken", "displayName", "mediaType"]);
    assert.deepEqual(selection, {
      displayName: "bars.csv",
      byteSize: bytes.byteLength,
      mediaType: "text/csv",
      capabilityToken: "ldc_01ARZ3NDEKTSV4RRFFQ69G5FAY"
    });
    assert.equal(JSON.stringify(selection).includes(file), false, "renderer-visible selection must not contain a path");

    const frames = [];
    const source = await broker.transferSource({
      capabilityToken: selection.capabilityToken,
      projectId: PROJECT_ID,
      projectContextRevisionId: CONTEXT_ID
    }, transferControl(frames, bytes));

    assert.deepEqual(source, {
      artifactId: `art_sha256_${createHash("sha256").update(bytes).digest("hex")}`,
      sha256: createHash("sha256").update(bytes).digest("hex"),
      byteSize: bytes.byteLength,
      mediaType: "text/csv",
      displayName: "bars.csv"
    });
    assert.ok(frames.filter((frame) => frame.kind === "localData.appendChunk").length >= 3);
    assert.equal(JSON.stringify(frames).includes(file), false, "backend control frames must not carry the native path");
    await assert.rejects(
      () => broker.transferSource({
        capabilityToken: selection.capabilityToken,
        projectId: PROJECT_ID,
        projectContextRevisionId: CONTEXT_ID
      }, transferControl([], bytes)),
      (error) => error.code === "LOCAL_DATA_CAPABILITY_NOT_AVAILABLE"
    );
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C2-01 cancel, non-regular, reparse and replacement race fail before transfer", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-local-data-source-fences-"));
  try {
    const cancelled = new LocalDataSourceBroker({ chooseFile: async () => null });
    assert.equal(await cancelled.chooseSource(), null);

    const folder = join(dir, "folder.csv");
    await mkdir(folder);
    await assert.rejects(
      () => new LocalDataSourceBroker({ chooseFile: async () => folder }).chooseSource(),
      (error) => error.code === "LOCAL_DATA_SOURCE_NOT_REGULAR"
    );

    const file = join(dir, "bars.csv");
    await writeFile(file, "symbol,date,open,high,low,close,volume,amount\n");
    await assert.rejects(
      () => new LocalDataSourceBroker({
        chooseFile: async () => file,
        isReparsePoint: async () => true
      }).chooseSource(),
      (error) => error.code === "LOCAL_DATA_SOURCE_REPARSE_POINT"
    );

    const broker = new LocalDataSourceBroker({ chooseFile: async () => file });
    const selection = await broker.chooseSource();
    await writeFile(file, "replacement changes the exact source identity\n");
    let controlCalls = 0;
    await assert.rejects(
      () => broker.transferSource({
        capabilityToken: selection.capabilityToken,
        projectId: PROJECT_ID,
        projectContextRevisionId: CONTEXT_ID
      }, async () => { controlCalls += 1; throw new Error("must not transfer"); }),
      (error) => error.code === "LOCAL_DATA_SOURCE_CHANGED"
    );
    assert.equal(controlCalls, 0);
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});

test("ACC-C2-09 ProductBridge submits only the published project-scoped raw Artifact ref", async () => {
  const dir = await mkdtemp(join(tmpdir(), "v3-local-data-product-bridge-"));
  try {
    const file = join(dir, "bars.csv");
    const bytes = Buffer.from("symbol,date,open,high,low,close,volume,amount\n600519,20260105,1,2,1,2,100,200\n", "utf8");
    const artifactSha = createHash("sha256").update(bytes).digest("hex");
    const artifactId = `art_sha256_${artifactSha}`;
    await writeFile(file, bytes);
    const frames = [];
    const requests = [];
    const supervisor = {
      state: "READY",
      config: { desktopVersion: "1.1.0" },
      capabilities: [],
      localDataControl: transferControl(frames, bytes),
      async request(operationId, payload, options) {
        requests.push({ operationId, payload, options });
        return {
          request_id: "018f47f2-9b02-7cc0-8ee6-1b82e3d62c02",
          truth_state: "NOT_FORMAL",
          read_model: {
            read_model_version: "v3.product-entry-local-data/1.1",
            task_id: "tsk_01ARZ3NDEKTSV4RRFFQ69G5FAZ",
            run_id: "run_01ARZ3NDEKTSV4RRFFQ69G5FB0",
            accepted_state: "QUEUED",
            maturity: "PRODUCT_CONNECTED",
            truth: "NOT_FORMAL",
            admission: "PRE_ALPHA",
            checkpoint_resume: "UNAVAILABLE",
            retry: "NEW_ATTEMPT_SAME_RUN_FROM_START",
            source_artifact_id: artifactId
          }
        };
      }
    };
    const bindings = new ProductBindingStore(productBindingPath(dir));
    await bindings.persist({ projectId: PROJECT_ID, projectContextRevisionId: CONTEXT_ID, sessionId: SESSION_ID });
    const broker = new LocalDataSourceBroker({ chooseFile: async () => file });
    const bridge = new ProductBridge(supervisor, store(), bindings, async () => null, undefined, broker);
    bridge.recordBindingOutcome({ state: "PROJECT_BOUND" });

    const selection = await bridge.chooseLocalDataSource();
    const outcome = await bridge.importLocalDataset({
      capabilityToken: selection.capabilityToken,
      volumeUnit: "SHARES",
      amountUnit: "CNY",
      timezone: "Asia/Shanghai",
      adjustment: "UNADJUSTED"
    });
    assert.equal(outcome.taskId, "tsk_01ARZ3NDEKTSV4RRFFQ69G5FAZ");
    assert.equal(outcome.acceptedState, "QUEUED");
    assert.equal(requests.length, 1);
    assert.equal(requests[0].operationId, "ProductEntryService.v1.importLocalDataset");
    assert.deepEqual(requests[0].options, {
      contractVersion: "1.1.0",
      expectedApiVersion: "1.1",
      idempotencyKey: requests[0].payload.idempotency_key,
      timeoutMs: 30_000
    });
    assert.deepEqual(Object.keys(requests[0].payload).sort(), ["idempotency_key", "source"]);
    assert.deepEqual(requests[0].payload.source, {
      artifact_id: artifactId,
      sha256: artifactSha,
      byte_size: bytes.byteLength,
      media_type: "text/csv",
      display_name: "bars.csv",
      volume_unit: "SHARES",
      amount_unit: "CNY",
      timezone: "Asia/Shanghai",
      adjustment: "UNADJUSTED"
    });
    for (const forbidden of ["path", "raw_path", "payload_base64", "bars", "rows"]) {
      assert.equal(forbidden in requests[0].payload.source, false, `Product Entry source must not carry ${forbidden}`);
    }
  } finally {
    await rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
});
