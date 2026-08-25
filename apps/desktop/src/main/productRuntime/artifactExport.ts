import { createHash, randomBytes } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, realpath, rename, unlink, type FileHandle } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import { ProductAdapterError } from "./adapters";

const MAX_EXPORT_CAPABILITIES = 8;
const EXPORT_CAPABILITY_TTL_MS = 5 * 60 * 1000;
const MAX_EXPORT_CHUNK_BYTES = 256 * 1024;
const ARTIFACT_ID_PATTERN = /^art_sha256_[0-9a-f]{64}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export interface ArtifactExportSelection {
  readonly displayName: string;
  readonly capabilityToken: string;
}

export interface ArtifactExportScope {
  readonly capabilityToken: string;
  readonly artifactId: string;
  readonly expectedSha256: string;
  readonly expectedByteSize: number;
}

export interface ArtifactExportStreamReceipt {
  readonly artifactId: string;
  readonly sha256: string;
  readonly byteSize: number;
}

export interface ArtifactExportReceipt extends ArtifactExportStreamReceipt {
  readonly destinationToken: string;
  readonly displayName: string;
  readonly completedAt: string;
}

export type ArtifactExportSink = (chunk: Uint8Array, offset: number) => Promise<void>;
export type ArtifactExportProducer = (
  sink: ArtifactExportSink
) => Promise<ArtifactExportStreamReceipt>;

export interface ArtifactExportBrokerOptions {
  readonly chooseDestination: (suggestedName: string) => Promise<string | null>;
  readonly tokenFactory?: () => string;
  readonly temporaryNameFactory?: () => string;
  readonly now?: () => number;
}

interface DestinationCapability {
  readonly token: string;
  readonly destinationPath: string;
  readonly parentPath: string;
  readonly parentRealPath: string;
  readonly displayName: string;
  readonly expiresAt: number;
}

function exportError(code: string, message: string, cause?: unknown): ProductAdapterError {
  return new ProductAdapterError(code, message, cause);
}

function capabilityToken(): string {
  return `edc_${randomBytes(24).toString("base64url")}`;
}

function temporarySuffix(): string {
  return randomBytes(12).toString("hex");
}

function requireSuggestedName(value: string): string {
  if (
    typeof value !== "string"
    || value.length < 1
    || value.length > 255
    || basename(value) !== value
    || value === "."
    || value === ".."
  ) {
    throw exportError("ARTIFACT_EXPORT_NAME_INVALID", "导出文件名无效");
  }
  return value;
}

function requireScope(scope: ArtifactExportScope): void {
  if (!ARTIFACT_ID_PATTERN.test(scope.artifactId)) {
    throw exportError("ARTIFACT_EXPORT_IDENTITY_INVALID", "Artifact ID 无效");
  }
  if (
    !SHA256_PATTERN.test(scope.expectedSha256)
    || scope.artifactId !== `art_sha256_${scope.expectedSha256}`
  ) {
    throw exportError("ARTIFACT_EXPORT_IDENTITY_INVALID", "Artifact ID 与 SHA-256 不一致");
  }
  if (!Number.isSafeInteger(scope.expectedByteSize) || scope.expectedByteSize < 0) {
    throw exportError("ARTIFACT_EXPORT_SIZE_INVALID", "Artifact 字节大小无效");
  }
}

async function writeAll(handle: FileHandle, chunk: Uint8Array): Promise<void> {
  let written = 0;
  while (written < chunk.byteLength) {
    const result = await handle.write(chunk, written, chunk.byteLength - written, null);
    if (result.bytesWritten < 1) {
      throw exportError("ARTIFACT_EXPORT_WRITE_FAILED", "导出临时文件未能继续写入");
    }
    written += result.bytesWritten;
  }
}

export class ArtifactExportBroker {
  private readonly chooseNativeDestination: (suggestedName: string) => Promise<string | null>;
  private readonly tokenFactory: () => string;
  private readonly temporaryNameFactory: () => string;
  private readonly now: () => number;
  private readonly capabilities = new Map<string, DestinationCapability>();

  constructor(options: ArtifactExportBrokerOptions) {
    this.chooseNativeDestination = options.chooseDestination;
    this.tokenFactory = options.tokenFactory ?? capabilityToken;
    this.temporaryNameFactory = options.temporaryNameFactory ?? temporarySuffix;
    this.now = options.now ?? Date.now;
  }

  get retainedCapabilityCount(): number {
    return this.capabilities.size;
  }

  private sweepExpired(now: number): void {
    for (const [token, capability] of this.capabilities) {
      if (capability.expiresAt <= now) this.capabilities.delete(token);
    }
  }

  async chooseDestination(suggestedName: string): Promise<ArtifactExportSelection | null> {
    const admittedName = requireSuggestedName(suggestedName);
    const now = this.now();
    this.sweepExpired(now);
    if (this.capabilities.size >= MAX_EXPORT_CAPABILITIES) {
      throw exportError("ARTIFACT_EXPORT_CAPABILITY_LIMIT", "待导出的目标文件过多，请完成或重新选择");
    }
    const selected = await this.chooseNativeDestination(admittedName);
    if (selected === null) return null;
    if (typeof selected !== "string" || !isAbsolute(selected)) {
      throw exportError("ARTIFACT_EXPORT_DESTINATION_INVALID", "原生保存对话框返回了无效目标");
    }
    const destinationPath = resolve(selected);
    const parentPath = dirname(destinationPath);
    let parentRealPath: string;
    try {
      const parent = await lstat(parentPath, { bigint: true });
      if (!parent.isDirectory() || parent.isSymbolicLink()) {
        throw exportError("ARTIFACT_EXPORT_DESTINATION_INVALID", "导出目标目录必须是普通目录");
      }
      parentRealPath = resolve(await realpath(parentPath));
    } catch (error) {
      if (error instanceof ProductAdapterError) throw error;
      throw exportError("ARTIFACT_EXPORT_DESTINATION_INVALID", "无法验证导出目标目录", error);
    }
    const token = this.tokenFactory();
    if (
      typeof token !== "string"
      || token.length < 16
      || token.length > 128
      || this.capabilities.has(token)
    ) {
      throw exportError("ARTIFACT_EXPORT_CAPABILITY_INVALID", "无法生成唯一的导出能力 token");
    }
    const displayName = basename(destinationPath);
    this.capabilities.set(token, {
      token,
      destinationPath,
      parentPath,
      parentRealPath,
      displayName,
      expiresAt: now + EXPORT_CAPABILITY_TTL_MS
    });
    return Object.freeze({ displayName, capabilityToken: token });
  }

  discardDestination(capabilityToken: string): void {
    this.capabilities.delete(capabilityToken);
  }

  async writeDestination(
    scope: ArtifactExportScope,
    produce: ArtifactExportProducer
  ): Promise<ArtifactExportReceipt> {
    requireScope(scope);
    if (typeof produce !== "function") {
      throw exportError("ARTIFACT_EXPORT_PRODUCER_INVALID", "Artifact 导出生产器无效");
    }
    const now = this.now();
    this.sweepExpired(now);
    const capability = this.capabilities.get(scope.capabilityToken);
    if (capability === undefined) {
      throw exportError(
        "ARTIFACT_EXPORT_CAPABILITY_NOT_AVAILABLE",
        "导出目标能力已使用、过期或不存在"
      );
    }
    this.capabilities.delete(scope.capabilityToken);

    const suffix = this.temporaryNameFactory();
    if (!/^[0-9a-f]{8,64}$/.test(suffix)) {
      throw exportError("ARTIFACT_EXPORT_TEMPORARY_NAME_INVALID", "无法生成安全的导出临时文件名");
    }
    const temporaryPath = join(
      capability.parentPath,
      `.${capability.displayName}.v3-${suffix}.tmp`
    );
    let handle: FileHandle | undefined;
    try {
      if (resolve(await realpath(capability.parentPath)) !== capability.parentRealPath) {
        throw exportError("ARTIFACT_EXPORT_DESTINATION_CHANGED", "导出目标目录在写入前发生变化");
      }
      handle = await open(
        temporaryPath,
        constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY,
        0o600
      );
      const digest = createHash("sha256");
      let nextOffset = 0;
      const streamReceipt = await produce(async (value, offset) => {
        const chunk = Buffer.from(value);
        if (
          !Number.isSafeInteger(offset)
          || offset !== nextOffset
          || chunk.byteLength < 1
          || chunk.byteLength > MAX_EXPORT_CHUNK_BYTES
          || nextOffset + chunk.byteLength > scope.expectedByteSize
        ) {
          throw exportError("ARTIFACT_EXPORT_STREAM_INVALID", "Artifact 导出数据块不连续或超出边界");
        }
        await writeAll(handle!, chunk);
        digest.update(chunk);
        nextOffset += chunk.byteLength;
      });
      const sha256 = digest.digest("hex");
      if (
        nextOffset !== scope.expectedByteSize
        || sha256 !== scope.expectedSha256
        || streamReceipt.artifactId !== scope.artifactId
        || streamReceipt.sha256 !== scope.expectedSha256
        || streamReceipt.byteSize !== scope.expectedByteSize
      ) {
        throw exportError("ARTIFACT_EXPORT_STREAM_INVALID", "导出字节与已验证 Artifact 描述不一致");
      }
      await handle.sync();
      await handle.close();
      handle = undefined;
      if (resolve(await realpath(capability.parentPath)) !== capability.parentRealPath) {
        throw exportError("ARTIFACT_EXPORT_DESTINATION_CHANGED", "导出目标目录在提交前发生变化");
      }
      try {
        const existing = await lstat(capability.destinationPath, { bigint: true });
        if (!existing.isFile() || existing.isSymbolicLink()) {
          throw exportError("ARTIFACT_EXPORT_DESTINATION_INVALID", "导出目标不是普通文件");
        }
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        if (code !== "ENOENT") throw error;
      }
      await rename(temporaryPath, capability.destinationPath);
      return Object.freeze({
        destinationToken: capability.token,
        displayName: capability.displayName,
        artifactId: scope.artifactId,
        sha256,
        byteSize: nextOffset,
        completedAt: new Date(this.now()).toISOString()
      });
    } catch (error) {
      await handle?.close().catch(() => undefined);
      // The capability is one-use and there is no supported resume path. A
      // failed stream must therefore remove only the unique temporary file it
      // created instead of leaving research bytes behind indefinitely.
      await unlink(temporaryPath).catch(() => undefined);
      throw error;
    }
  }
}
