import { createHash, randomBytes } from "node:crypto";
import { constants, type BigIntStats } from "node:fs";
import { lstat, open, realpath, type FileHandle } from "node:fs/promises";
import { basename, extname, resolve } from "node:path";
import { ProductAdapterError } from "./adapters";

export const LOCAL_DATA_TRANSFER_PROTOCOL = "v3.local-data-transfer/1.0.0";
export const MAX_LOCAL_DATA_SOURCE_BYTES = 256 * 1024 * 1024;
export const MAX_LOCAL_DATA_CHUNK_BYTES = 256 * 1024;
const MAX_OPEN_CAPABILITIES = 8;
const CAPABILITY_TTL_MS = 5 * 60 * 1000;
const ARTIFACT_ID_PATTERN = /^art_sha256_[0-9a-f]{64}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const TRANSFER_ID_PATTERN = /^ldt_[0-9A-HJKMNP-TV-Z]{26}$/;

export type LocalDataMediaType = "text/csv" | "application/vnd.apache.parquet";

export interface LocalDataSourceSelection {
  readonly displayName: string;
  readonly byteSize: number;
  readonly mediaType: LocalDataMediaType;
  readonly capabilityToken: string;
}

export interface LocalDataTransferScope {
  readonly capabilityToken: string;
  readonly projectId: string;
  readonly projectContextRevisionId: string;
}

export interface LocalDataRawArtifactRef {
  readonly artifactId: string;
  readonly sha256: string;
  readonly byteSize: number;
  readonly mediaType: LocalDataMediaType;
  readonly displayName: string;
}

export type LocalDataControlPort = (
  frame: Readonly<Record<string, unknown>>,
  timeoutMs?: number
) => Promise<Readonly<Record<string, unknown>>>;

interface OpenCapability {
  readonly token: string;
  readonly path: string;
  readonly displayName: string;
  readonly mediaType: LocalDataMediaType;
  readonly byteSize: number;
  readonly identity: string;
  readonly contentSha256: string;
  readonly handle: FileHandle;
  readonly expiresAt: number;
}

export interface LocalDataSourceBrokerOptions {
  readonly chooseFile: () => Promise<string | null>;
  readonly tokenFactory?: () => string;
  readonly now?: () => number;
  readonly isReparsePoint?: (path: string, stat: BigIntStats) => Promise<boolean>;
}

function sourceError(code: string, message: string, cause?: unknown): ProductAdapterError {
  return new ProductAdapterError(code, message, cause);
}

function fileIdentity(value: BigIntStats): string {
  return [value.dev, value.ino, value.size, value.mtimeNs, value.ctimeNs]
    .map((part) => part.toString())
    .join(":");
}

async function hashOpenFile(handle: FileHandle, byteSize: number): Promise<string> {
  const digest = createHash("sha256");
  const buffer = Buffer.allocUnsafe(Math.min(MAX_LOCAL_DATA_CHUNK_BYTES, byteSize));
  let offset = 0;
  while (offset < byteSize) {
    const read = await handle.read(
      buffer,
      0,
      Math.min(buffer.length, byteSize - offset),
      offset
    );
    if (read.bytesRead < 1) {
      throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在内容校验期间提前结束");
    }
    digest.update(buffer.subarray(0, read.bytesRead));
    offset += read.bytesRead;
  }
  const trailing = await handle.read(Buffer.alloc(1), 0, 1, offset);
  if (trailing.bytesRead !== 0) {
    throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在内容校验期间增长");
  }
  return digest.digest("hex");
}

function mediaTypeForPath(path: string): LocalDataMediaType {
  const extension = extname(path).toLowerCase();
  if (extension === ".csv") return "text/csv";
  if (extension === ".parquet") return "application/vnd.apache.parquet";
  throw sourceError("LOCAL_DATA_SOURCE_TYPE_NOT_ADMITTED", "本地数据仅支持 CSV 或 Parquet");
}

async function defaultIsReparsePoint(path: string, stat: BigIntStats): Promise<boolean> {
  if (stat.isSymbolicLink()) return true;
  const actual = resolve(await realpath(path));
  const requested = resolve(path);
  return process.platform === "win32"
    ? actual.toLowerCase() !== requested.toLowerCase()
    : actual !== requested;
}

function requiredRecord(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", `${label} is not an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function exactKeys(value: Readonly<Record<string, unknown>>, keys: readonly string[], label: string): void {
  const observed = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (observed.length !== expected.length || observed.some((key, index) => key !== expected[index])) {
    throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", `${label} fields do not match the closed shape`);
  }
}

function safeInteger(value: unknown, name: string, minimum: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum || Number(value) > maximum) {
    throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", `${name} is outside the admitted integer bound`);
  }
  return Number(value);
}

function token(): string {
  return `ldc_${randomBytes(24).toString("base64url")}`;
}

export class LocalDataSourceBroker {
  private readonly chooseFile: () => Promise<string | null>;
  private readonly tokenFactory: () => string;
  private readonly now: () => number;
  private readonly isReparsePoint: (path: string, stat: BigIntStats) => Promise<boolean>;
  private readonly capabilities = new Map<string, OpenCapability>();

  constructor(options: LocalDataSourceBrokerOptions) {
    this.chooseFile = options.chooseFile;
    this.tokenFactory = options.tokenFactory ?? token;
    this.now = options.now ?? Date.now;
    this.isReparsePoint = options.isReparsePoint ?? defaultIsReparsePoint;
  }

  private async sweepExpired(now: number): Promise<void> {
    const expired = [...this.capabilities.values()].filter((item) => item.expiresAt <= now);
    for (const item of expired) {
      this.capabilities.delete(item.token);
      await item.handle.close().catch(() => undefined);
    }
  }

  async chooseSource(): Promise<LocalDataSourceSelection | null> {
    const now = this.now();
    await this.sweepExpired(now);
    if (this.capabilities.size >= MAX_OPEN_CAPABILITIES) {
      throw sourceError("LOCAL_DATA_CAPABILITY_LIMIT", "待导入的本地数据文件过多，请完成或重新选择");
    }
    const selected = await this.chooseFile();
    if (selected === null) return null;
    if (typeof selected !== "string" || selected.length < 1) {
      throw sourceError("LOCAL_DATA_SOURCE_INVALID", "原生文件选择器返回了无效结果");
    }
    const mediaType = mediaTypeForPath(selected);
    let before: BigIntStats;
    try {
      before = await lstat(selected, { bigint: true });
    } catch (error) {
      throw sourceError("LOCAL_DATA_SOURCE_OPEN_FAILED", "无法检查所选本地数据文件", error);
    }
    if (await this.isReparsePoint(selected, before)) {
      throw sourceError("LOCAL_DATA_SOURCE_REPARSE_POINT", "拒绝符号链接或 reparse point 本地数据源");
    }
    if (!before.isFile()) {
      throw sourceError("LOCAL_DATA_SOURCE_NOT_REGULAR", "本地数据源必须是普通文件");
    }
    const byteSize = safeInteger(Number(before.size), "local source byte size", 1, MAX_LOCAL_DATA_SOURCE_BYTES);
    let handle: FileHandle | undefined;
    try {
      handle = await open(selected, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
      const opened = await handle.stat({ bigint: true });
      const after = await lstat(selected, { bigint: true });
      if (
        !opened.isFile()
        || await this.isReparsePoint(selected, after)
        || fileIdentity(before) !== fileIdentity(opened)
        || fileIdentity(before) !== fileIdentity(after)
      ) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在安全打开期间发生变化");
      }
      const contentSha256 = await hashOpenFile(handle, byteSize);
      const capabilityToken = this.tokenFactory();
      if (typeof capabilityToken !== "string" || capabilityToken.length < 16 || capabilityToken.length > 128 || this.capabilities.has(capabilityToken)) {
        throw sourceError("LOCAL_DATA_CAPABILITY_INVALID", "无法生成唯一的本地数据能力 token");
      }
      const displayName = basename(selected);
      this.capabilities.set(capabilityToken, {
        token: capabilityToken,
        path: selected,
        displayName,
        mediaType,
        byteSize,
        identity: fileIdentity(before),
        contentSha256,
        handle,
        expiresAt: now + CAPABILITY_TTL_MS
      });
      handle = undefined;
      return Object.freeze({ displayName, byteSize, mediaType, capabilityToken });
    } catch (error) {
      if (handle !== undefined) await handle.close().catch(() => undefined);
      if (error instanceof ProductAdapterError) throw error;
      throw sourceError("LOCAL_DATA_SOURCE_OPEN_FAILED", "无法安全打开所选本地数据文件", error);
    }
  }

  async transferSource(
    scope: LocalDataTransferScope,
    control: LocalDataControlPort
  ): Promise<LocalDataRawArtifactRef> {
    const now = this.now();
    await this.sweepExpired(now);
    const capability = this.capabilities.get(scope.capabilityToken);
    if (capability === undefined) {
      throw sourceError("LOCAL_DATA_CAPABILITY_NOT_AVAILABLE", "本地数据能力已使用、过期或不存在");
    }
    this.capabilities.delete(scope.capabilityToken);
    let transferId: string | null = null;
    try {
      let current: BigIntStats;
      try {
        current = await lstat(capability.path, { bigint: true });
      } catch (error) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在传输前不可再验证", error);
      }
      if (
        await this.isReparsePoint(capability.path, current)
        || !current.isFile()
        || fileIdentity(current) !== capability.identity
      ) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在传输前发生变化");
      }
      let opened: BigIntStats;
      try {
        opened = await capability.handle.stat({ bigint: true });
      } catch (error) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "已打开的本地数据源不可再验证", error);
      }
      if (!opened.isFile() || fileIdentity(opened) !== capability.identity) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "已打开的本地数据源身份发生变化");
      }
      if (await hashOpenFile(capability.handle, capability.byteSize) !== capability.contentSha256) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源内容在传输前发生变化");
      }
      const ready = requiredRecord(await control({
        kind: "localData.beginTransfer",
        protocol_version: LOCAL_DATA_TRANSFER_PROTOCOL,
        project_id: scope.projectId,
        project_context_revision_id: scope.projectContextRevisionId,
        display_name: capability.displayName,
        media_type: capability.mediaType,
        expected_byte_size: capability.byteSize
      }), "localData.transferReady");
      exactKeys(ready, ["kind", "transfer_id", "next_offset", "max_chunk_bytes"], "localData.transferReady");
      if (ready.kind !== "localData.transferReady" || typeof ready.transfer_id !== "string" || !TRANSFER_ID_PATTERN.test(ready.transfer_id)) {
        throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", "backend returned an invalid transfer identity");
      }
      transferId = ready.transfer_id;
      if (safeInteger(ready.next_offset, "next_offset", 0, 0) !== 0) {
        throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", "backend transfer must start at offset zero");
      }
      const chunkBytes = safeInteger(
        ready.max_chunk_bytes,
        "max_chunk_bytes",
        1,
        MAX_LOCAL_DATA_CHUNK_BYTES
      );
      const digest = createHash("sha256");
      let offset = 0;
      const buffer = Buffer.allocUnsafe(chunkBytes);
      while (offset < capability.byteSize) {
        const remaining = capability.byteSize - offset;
        const read = await capability.handle.read(buffer, 0, Math.min(chunkBytes, remaining), null);
        if (read.bytesRead < 1) {
          throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源在声明大小之前结束");
        }
        const chunk = Buffer.from(buffer.subarray(0, read.bytesRead));
        digest.update(chunk);
        const accepted = requiredRecord(await control({
          kind: "localData.appendChunk",
          protocol_version: LOCAL_DATA_TRANSFER_PROTOCOL,
          transfer_id: transferId,
          offset,
          payload_base64: chunk.toString("base64"),
          chunk_sha256: createHash("sha256").update(chunk).digest("hex")
        }), "localData.chunkAccepted");
        exactKeys(accepted, ["kind", "transfer_id", "next_offset"], "localData.chunkAccepted");
        const next = offset + read.bytesRead;
        if (accepted.kind !== "localData.chunkAccepted" || accepted.transfer_id !== transferId || accepted.next_offset !== next) {
          throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", "backend did not acknowledge the exact next chunk offset");
        }
        offset = next;
      }
      const trailing = await capability.handle.read(Buffer.alloc(1), 0, 1, null);
      if (trailing.bytesRead !== 0) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源超过选择时声明的大小");
      }
      const expectedSha256 = digest.digest("hex");
      if (expectedSha256 !== capability.contentSha256) {
        throw sourceError("LOCAL_DATA_SOURCE_CHANGED", "本地数据源内容在传输期间发生变化");
      }
      const published = requiredRecord(await control({
        kind: "localData.finishTransfer",
        protocol_version: LOCAL_DATA_TRANSFER_PROTOCOL,
        transfer_id: transferId,
        expected_sha256: expectedSha256,
        expected_byte_size: offset
      }, 120_000), "localData.sourcePublished");
      exactKeys(published, ["kind", "transfer_id", "source"], "localData.sourcePublished");
      if (published.kind !== "localData.sourcePublished" || published.transfer_id !== transferId) {
        throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", "backend returned a mismatched publication receipt");
      }
      const source = requiredRecord(published.source, "localData.sourcePublished.source");
      exactKeys(source, ["artifact_id", "sha256", "byte_size", "media_type", "display_name"], "localData.sourcePublished.source");
      if (
        typeof source.artifact_id !== "string"
        || !ARTIFACT_ID_PATTERN.test(source.artifact_id)
        || typeof source.sha256 !== "string"
        || !SHA256_PATTERN.test(source.sha256)
        || source.artifact_id !== `art_sha256_${source.sha256}`
        || source.sha256 !== expectedSha256
        || source.byte_size !== offset
        || source.media_type !== capability.mediaType
        || source.display_name !== capability.displayName
      ) {
        throw sourceError("LOCAL_DATA_TRANSFER_PROTOCOL_ERROR", "backend publication receipt does not match the transferred source");
      }
      transferId = null;
      return Object.freeze({
        artifactId: source.artifact_id,
        sha256: source.sha256,
        byteSize: offset,
        mediaType: capability.mediaType,
        displayName: capability.displayName
      });
    } catch (error) {
      if (transferId !== null) {
        await control({
          kind: "localData.abortTransfer",
          protocol_version: LOCAL_DATA_TRANSFER_PROTOCOL,
          transfer_id: transferId
        }).catch(() => undefined);
      }
      throw error;
    } finally {
      await capability.handle.close().catch(() => undefined);
    }
  }

  async close(): Promise<void> {
    const active = [...this.capabilities.values()];
    this.capabilities.clear();
    await Promise.all(active.map((item) => item.handle.close().catch(() => undefined)));
  }
}
