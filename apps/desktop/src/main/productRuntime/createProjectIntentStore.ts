import { createHash, randomBytes } from "node:crypto";
import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";

const CREATE_INTENT_SCHEMA_VERSION = 1;
const INTENT_HASH_PATTERN = /^[0-9a-f]{64}$/;
const IDEMPOTENCY_KEY_PATTERN = /^v3-desktop:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DEFINITIVE_CREATE_REJECTION_CODES = new Set([
  "INVALID_ARGUMENT",
  "IDEMPOTENCY_CONFLICT",
]);

export interface CreateProjectIntent {
  readonly displayName: string;
  readonly notes: string | null;
}

export interface PendingCreateProjectIntent {
  readonly schemaVersion: 1;
  readonly intentHash: string;
  readonly idempotencyKey: string;
  readonly createdAt: string;
}

export class CreateProjectIntentStoreError extends Error {
  readonly code: string;
  override readonly cause?: unknown;

  constructor(code: string, message: string, cause?: unknown) {
    super(message);
    this.name = "CreateProjectIntentStoreError";
    this.code = code;
    this.cause = cause;
  }
}

function errorCodeOf(error: unknown): string | null {
  if (error !== null && typeof error === "object" && "code" in error && typeof error.code === "string") {
    return error.code;
  }
  return null;
}

function uuidV4(): string {
  const bytes = randomBytes(16);
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function createProjectIntentHash(intent: CreateProjectIntent): string {
  const canonical = JSON.stringify({
    display_name: intent.displayName,
    notes: intent.notes,
  });
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

export function parsePendingCreateProjectIntent(raw: unknown): PendingCreateProjectIntent | null {
  if (raw === null || Array.isArray(raw) || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  if (
    Object.keys(record).sort().join(",") !==
    "createdAt,idempotencyKey,intentHash,schemaVersion"
  ) return null;
  if (record.schemaVersion !== CREATE_INTENT_SCHEMA_VERSION) return null;
  if (typeof record.intentHash !== "string" || !INTENT_HASH_PATTERN.test(record.intentHash)) return null;
  if (typeof record.idempotencyKey !== "string" || !IDEMPOTENCY_KEY_PATTERN.test(record.idempotencyKey)) return null;
  if (typeof record.createdAt !== "string" || Number.isNaN(Date.parse(record.createdAt))) return null;
  return Object.freeze({
    schemaVersion: CREATE_INTENT_SCHEMA_VERSION,
    intentHash: record.intentHash,
    idempotencyKey: record.idempotencyKey,
    createdAt: record.createdAt,
  });
}

/**
 * One small main-process-owned record for an unresolved create intent.
 *
 * The record is durably written before transport. Unknown transport outcomes
 * deliberately leave it in place, so the same semantic intent reuses the
 * backend idempotency key after a retry or Electron restart. A different
 * explicit intent replaces the record with a fresh random key; keys are never
 * permanently derived from display text.
 */
export class CreateProjectIntentStore {
  private chain: Promise<unknown> = Promise.resolve();
  readonly path: string;

  constructor(path: string) {
    this.path = path;
  }

  reserve(intent: CreateProjectIntent): Promise<PendingCreateProjectIntent> {
    return this.enqueue(async () => {
      const intentHash = createProjectIntentHash(intent);
      const existing = await this.readCurrent();
      if (existing?.intentHash === intentHash) return existing;
      const pending: PendingCreateProjectIntent = Object.freeze({
        schemaVersion: CREATE_INTENT_SCHEMA_VERSION,
        intentHash,
        idempotencyKey: `v3-desktop:${uuidV4()}`,
        createdAt: new Date().toISOString(),
      });
      await this.persist(pending);
      return pending;
    });
  }

  load(): Promise<PendingCreateProjectIntent | null> {
    return this.enqueue(() => this.readCurrent());
  }

  clearIfMatches(idempotencyKey: string): Promise<void> {
    return this.enqueue(async () => {
      const existing = await this.readCurrent();
      if (existing === null || existing.idempotencyKey !== idempotencyKey) return;
      try {
        await unlink(this.path);
      } catch (error) {
        if (errorCodeOf(error) === "ENOENT") return;
        throw new CreateProjectIntentStoreError(
          "CREATE_PROJECT_INTENT_CLEAR_FAILED",
          "could not clear the confirmed create-project intent",
          error,
        );
      }
    });
  }

  private enqueue<T>(task: () => Promise<T>): Promise<T> {
    const result = this.chain.then(task, task);
    this.chain = result.then(() => undefined, () => undefined);
    return result;
  }

  private async readCurrent(): Promise<PendingCreateProjectIntent | null> {
    let raw: string;
    try {
      raw = await readFile(this.path, "utf8");
    } catch (error) {
      if (errorCodeOf(error) === "ENOENT") return null;
      throw new CreateProjectIntentStoreError(
        "CREATE_PROJECT_INTENT_READ_FAILED",
        "could not read the create-project intent store",
        error,
      );
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw new CreateProjectIntentStoreError(
        "CREATE_PROJECT_INTENT_CORRUPT",
        "create-project intent store is not valid JSON; refusing a new key",
        error,
      );
    }
    const record = parsePendingCreateProjectIntent(parsed);
    if (record === null) {
      throw new CreateProjectIntentStoreError(
        "CREATE_PROJECT_INTENT_CORRUPT",
        "create-project intent store shape is invalid; refusing a new key",
      );
    }
    return record;
  }

  private async persist(pending: PendingCreateProjectIntent): Promise<void> {
    const temporary = `${this.path}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
    try {
      await mkdir(dirname(this.path), { recursive: true });
      const handle = await open(temporary, "wx");
      try {
        await handle.writeFile(JSON.stringify(pending, null, 2), "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await rename(temporary, this.path);
    } catch (error) {
      try { await unlink(temporary); } catch { /* best effort */ }
      throw new CreateProjectIntentStoreError(
        "CREATE_PROJECT_INTENT_WRITE_FAILED",
        "could not persist create-project intent before transport",
        error,
      );
    }
  }
}

/** Exact retry lifecycle used by ProductBridge.createProject. */
export async function runCreateProjectIntent<TTransport, TConfirmed>(
  store: CreateProjectIntentStore,
  intent: CreateProjectIntent,
  send: (idempotencyKey: string) => Promise<TTransport>,
  confirm: (response: TTransport) => TConfirmed,
): Promise<TConfirmed> {
  const pending = await store.reserve(intent);
  let response: TTransport;
  try {
    response = await send(pending.idempotencyKey);
  } catch (error) {
    if (DEFINITIVE_CREATE_REJECTION_CODES.has(errorCodeOf(error) ?? "")) {
      await store.clearIfMatches(pending.idempotencyKey);
    }
    throw error;
  }
  // Confirmation runs before clear. A malformed/ambiguous response may have
  // followed a backend commit, so it must retain the same retry key.
  const confirmed = confirm(response);
  await store.clearIfMatches(pending.idempotencyKey);
  return confirmed;
}

export function createProjectIntentPath(userDataPath: string): string {
  return join(userDataPath, "v3-product-create-intent.json");
}
