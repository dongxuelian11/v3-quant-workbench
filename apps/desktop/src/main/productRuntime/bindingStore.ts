import { mkdir, open, readFile, rename, unlink } from "node:fs/promises";
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

export class ProductBindingStoreError extends Error {
  readonly code: string;
  override readonly cause?: unknown;

  constructor(code: string, message: string, cause?: unknown) {
    super(message);
    this.name = "ProductBindingStoreError";
    this.code = code;
    this.cause = cause;
  }
}

export interface ProductBindingFileOps {
  readFile(path: string): Promise<string>;
  writeFileDurable(path: string, content: string): Promise<void>;
  rename(from: string, to: string): Promise<void>;
  mkdir(path: string): Promise<void>;
  unlink(path: string): Promise<void>;
  syncCommitDirectory(directory: string, committedPath: string): Promise<void>;
}

const defaultFileOps: ProductBindingFileOps = {
  readFile: (path) => readFile(path, "utf8"),
  writeFileDurable: async (path, content) => {
    const handle = await open(path, "w");
    try {
      await handle.writeFile(content, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
  },
  rename,
  mkdir: async (path) => { await mkdir(path, { recursive: true }); },
  unlink,
  syncCommitDirectory: async (directory, committedPath) => {
    const directoryHandle = await open(directory, "r");
    try {
      await directoryHandle.sync();
      return;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (process.platform !== "win32" || code !== "EPERM") throw error;
    } finally {
      await directoryHandle.close();
    }
    // Node cannot fsync a directory handle on Windows. Flush the committed
    // file handle after the atomic rename so the product never reports a
    // binding committed while its actual bytes remain only in process cache.
    const committedHandle = await open(committedPath, "r+");
    try { await committedHandle.sync(); } finally { await committedHandle.close(); }
  }
};

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
  private readonly fileOps: ProductBindingFileOps;

  constructor(bindingPath: string, fileOps: ProductBindingFileOps = defaultFileOps) {
    this.bindingPath = bindingPath;
    this.fileOps = fileOps;
  }

  get path(): string { return this.bindingPath; }

  get pendingPath(): string { return `${this.bindingPath}.pending`; }

  get current(): PersistedProductBinding | null { return this.cached; }

  async load(): Promise<PersistedProductBinding | null> {
    try {
      const parsed: unknown = JSON.parse(await this.fileOps.readFile(this.bindingPath));
      const binding = parsePersistedBinding(parsed);
      if (binding === null) {
        throw new ProductBindingStoreError("BINDING_STORE_CORRUPT", "active product binding has an invalid closed shape");
      }
      this.cached = binding;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        this.cached = null;
      } else if (error instanceof ProductBindingStoreError) {
        throw error;
      } else if (error instanceof SyntaxError) {
        throw new ProductBindingStoreError("BINDING_STORE_CORRUPT", "active product binding is not valid JSON", error);
      } else {
        throw new ProductBindingStoreError("BINDING_STORE_IO_FAILED", "active product binding could not be read", error);
      }
    }
    await this.isolatePendingAfterCrash();
    return this.cached;
  }

  /** Write and fsync candidate bytes without changing the active commit marker. */
  async stage(refs: ProductBindingRefs): Promise<PersistedProductBinding> {
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
    await this.fileOps.mkdir(dirname(this.bindingPath));
    await this.fileOps.writeFileDurable(this.pendingPath, JSON.stringify(record, null, 2));
    return record;
  }

  /** Atomic activation commit: active is the only durable commit marker. */
  async commit(staged: PersistedProductBinding): Promise<PersistedProductBinding> {
    try {
      await this.fileOps.rename(this.pendingPath, this.bindingPath);
    } catch (error) {
      throw new ProductBindingStoreError("BINDING_COMMIT_RENAME_FAILED", "candidate binding could not replace the active commit marker", error);
    }
    this.cached = staged;
    try {
      await this.fileOps.syncCommitDirectory(dirname(this.bindingPath), this.bindingPath);
    } catch (error) {
      // rename already crossed the commit boundary. The caller must keep the
      // candidate generation fenced in place; rolling runtime back to prior
      // would split the active file from the running project.
      throw new ProductBindingStoreError(
        "BINDING_COMMIT_DURABILITY_UNCERTAIN",
        "candidate binding is active but commit durability could not be confirmed",
        error
      );
    }
    return staged;
  }

  /** Normal activation failure cleanup; active/cache are deliberately untouched. */
  async abortStaged(): Promise<void> {
    try {
      await this.fileOps.unlink(this.pendingPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw new ProductBindingStoreError("BINDING_PENDING_CLEANUP_FAILED", "candidate binding could not be removed after failed activation", error);
      }
    }
  }

  /** Compatibility helper for already-validated callers. */
  async persist(refs: ProductBindingRefs): Promise<PersistedProductBinding> {
    const staged = await this.stage(refs);
    return this.commit(staged);
  }

  /**
   * Remove a canonically rejected active binding from the restart path while
   * retaining its exact bytes for bounded diagnosis.
   */
  async isolateActive(reasonCode: string): Promise<string | null> {
    if (this.cached === null) return null;
    if (!validId(reasonCode)) {
      throw new TypeError("binding isolation reason must be a bounded stable code");
    }
    const isolated = `${this.bindingPath}.isolated.${reasonCode}.${Date.now()}.${process.pid}`;
    try {
      await this.fileOps.rename(this.bindingPath, isolated);
    } catch (error) {
      throw new ProductBindingStoreError(
        "BINDING_ACTIVE_ISOLATION_FAILED",
        "canonically rejected active binding could not be isolated",
        error
      );
    }
    this.cached = null;
    try {
      await this.fileOps.syncCommitDirectory(dirname(this.bindingPath), isolated);
    } catch (error) {
      throw new ProductBindingStoreError(
        "BINDING_ACTIVE_ISOLATION_DURABILITY_UNCERTAIN",
        "active binding was isolated but directory durability could not be confirmed",
        error
      );
    }
    return isolated;
  }

  private async isolatePendingAfterCrash(): Promise<void> {
    try {
      await this.fileOps.readFile(this.pendingPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw new ProductBindingStoreError("BINDING_PENDING_IO_FAILED", "pending product binding could not be inspected", error);
    }
    const isolated = `${this.pendingPath}.orphaned.${Date.now()}.${process.pid}`;
    try {
      await this.fileOps.rename(this.pendingPath, isolated);
      await this.fileOps.syncCommitDirectory(dirname(this.bindingPath), isolated);
    } catch (error) {
      throw new ProductBindingStoreError("BINDING_PENDING_ISOLATION_FAILED", "crash-left pending binding could not be isolated", error);
    }
  }

  clear(): void { this.cached = null; }
}

export function productBindingPath(userDataPath: string): string {
  return join(userDataPath, "v3-product-binding.json");
}
