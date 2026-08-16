import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { ProductBindingRefs } from "../../../../../packages/contracts/src/index";

/**
 * Runtime-owned product binding persistence.
 *
 * The binding refs (projectId / projectContextRevisionId / sessionId) are
 * assumed-but-revalidatable pointers owned by the Electron main process.
 * They are deliberately stored OUTSIDE the renderer-visible workspace
 * snapshot: workspace:save can never overwrite or fabricate canonical
 * product bindings. Invalid or tampered files are discarded, never trusted.
 */

const BINDING_SCHEMA_VERSION = 1;
const MAX_ID_LENGTH = 200;
const ID_PATTERN = /^[A-Za-z0-9_\-]{1,200}$/;

export interface PersistedProductBinding extends ProductBindingRefs {
  readonly schemaVersion: number;
  readonly savedAt: string;
}

function validId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= MAX_ID_LENGTH && ID_PATTERN.test(value);
}

export function parsePersistedBinding(raw: unknown): PersistedProductBinding | null {
  if (raw === null || Array.isArray(raw) || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  if (record.schemaVersion !== BINDING_SCHEMA_VERSION) return null;
  if (!validId(record.projectId) || !validId(record.projectContextRevisionId) || !validId(record.sessionId)) return null;
  if (typeof record.savedAt !== "string") return null;
  return Object.freeze({
    schemaVersion: BINDING_SCHEMA_VERSION,
    projectId: record.projectId,
    projectContextRevisionId: record.projectContextRevisionId,
    sessionId: record.sessionId,
    savedAt: record.savedAt
  });
}

export class ProductBindingStore {
  private cached: PersistedProductBinding | null = null;
  private readonly bindingPath: string;

  constructor(bindingPath: string) {
    this.bindingPath = bindingPath;
  }

  get path(): string { return this.bindingPath; }

  get current(): PersistedProductBinding | null { return this.cached; }

  async load(): Promise<PersistedProductBinding | null> {
    try {
      const parsed: unknown = JSON.parse(await readFile(this.bindingPath, "utf8"));
      this.cached = parsePersistedBinding(parsed);
    } catch {
      this.cached = null;
    }
    return this.cached;
  }

  /** Persist only after the backend has validated the refs (openProject OK). */
  async persist(refs: ProductBindingRefs): Promise<PersistedProductBinding> {
    if (!validId(refs.projectId) || !validId(refs.projectContextRevisionId) || !validId(refs.sessionId)) {
      throw new TypeError("product binding refs must be bounded canonical identifiers");
    }
    const record: PersistedProductBinding = Object.freeze({
      schemaVersion: BINDING_SCHEMA_VERSION,
      projectId: refs.projectId,
      projectContextRevisionId: refs.projectContextRevisionId,
      sessionId: refs.sessionId,
      savedAt: new Date().toISOString()
    });
    await mkdir(dirname(this.bindingPath), { recursive: true });
    const temporary = `${this.bindingPath}.${process.pid}.tmp`;
    await writeFile(temporary, JSON.stringify(record, null, 2), "utf8");
    await rename(temporary, this.bindingPath);
    this.cached = record;
    return record;
  }

  clear(): void { this.cached = null; }
}

export function productBindingPath(userDataPath: string): string {
  return join(userDataPath, "v3-product-binding.json");
}
