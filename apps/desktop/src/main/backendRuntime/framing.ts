const HEADER_SEPARATOR = Buffer.from("\r\n\r\n", "ascii");
const CONTENT_TYPE = "application/json; charset=utf-8";
export const MAX_FRAME_BYTES = 1024 * 1024;
const MAX_HEADER_BYTES = 4096;

export class TransportProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransportProtocolError";
  }
}

function strictJsonStringify(value: unknown): string {
  const encoded = JSON.stringify(value, (_key, item: unknown) => {
    if (typeof item === "number" && !Number.isFinite(item)) throw new TransportProtocolError("non-finite JSON number is forbidden");
    if (typeof item === "bigint" || typeof item === "function" || typeof item === "undefined") {
      throw new TransportProtocolError("frame contains a non-JSON value");
    }
    return item;
  });
  if (encoded === undefined || encoded.startsWith("[") || !encoded.startsWith("{")) {
    throw new TransportProtocolError("frame payload must be a JSON object");
  }
  return encoded;
}

export function encodeFrame(value: Readonly<Record<string, unknown>>, maximum = MAX_FRAME_BYTES): Buffer {
  const body = Buffer.from(strictJsonStringify(value), "utf8");
  if (body.byteLength === 0 || body.byteLength > maximum) throw new TransportProtocolError("frame exceeds negotiated maximum");
  const header = Buffer.from(
    `Content-Length: ${body.byteLength}\r\nContent-Type: ${CONTENT_TYPE}\r\n\r\n`,
    "ascii"
  );
  return Buffer.concat([header, body]);
}

export class FrameDecoder {
  private buffer = Buffer.alloc(0);
  private expectedLength: number | undefined;

  constructor(private readonly maximum = MAX_FRAME_BYTES) {
    if (!Number.isInteger(maximum) || maximum < 1 || maximum > MAX_FRAME_BYTES) {
      throw new RangeError("maximum frame size must be between 1 and 1 MiB");
    }
  }

  feed(chunk: Uint8Array): Array<Record<string, unknown>> {
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    const frames: Array<Record<string, unknown>> = [];
    for (;;) {
      if (this.expectedLength === undefined) {
        const boundary = this.buffer.indexOf(HEADER_SEPARATOR);
        if (boundary < 0) {
          if (this.buffer.byteLength > MAX_HEADER_BYTES) throw new TransportProtocolError("frame header exceeds maximum");
          break;
        }
        const header = this.buffer.subarray(0, boundary).toString("ascii");
        this.buffer = this.buffer.subarray(boundary + HEADER_SEPARATOR.byteLength);
        this.expectedLength = this.parseHeader(header);
      }
      if (this.buffer.byteLength < this.expectedLength) break;
      const body = this.buffer.subarray(0, this.expectedLength);
      this.buffer = this.buffer.subarray(this.expectedLength);
      this.expectedLength = undefined;
      let value: unknown;
      try {
        value = JSON.parse(body.toString("utf8"));
      } catch (error) {
        throw new TransportProtocolError(`frame body is not strict UTF-8 JSON: ${String(error)}`);
      }
      if (value === null || Array.isArray(value) || typeof value !== "object") {
        throw new TransportProtocolError("frame body must be a JSON object");
      }
      frames.push(value as Record<string, unknown>);
    }
    return frames;
  }

  finish(): void {
    if (this.buffer.byteLength > 0 || this.expectedLength !== undefined) {
      throw new TransportProtocolError("transport closed with a partial frame");
    }
  }

  private parseHeader(header: string): number {
    const lines = header.split("\r\n");
    if (lines.length !== 2 || !lines[0]?.startsWith("Content-Length: ") || lines[1] !== `Content-Type: ${CONTENT_TYPE}`) {
      throw new TransportProtocolError("invalid or reordered frame headers");
    }
    const text = lines[0].slice("Content-Length: ".length);
    if (!/^(0|[1-9][0-9]*)$/.test(text)) throw new TransportProtocolError("Content-Length must use canonical decimal form");
    const length = Number(text);
    if (!Number.isSafeInteger(length) || length < 1 || length > this.maximum) {
      throw new TransportProtocolError("Content-Length is outside negotiated bounds");
    }
    return length;
  }
}
