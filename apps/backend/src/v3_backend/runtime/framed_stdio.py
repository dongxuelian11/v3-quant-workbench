"""Strict Content-Length framed JSON transport for stdin/stdout."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, BinaryIO

MAX_FRAME_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 4096
_SEPARATOR = b"\r\n\r\n"
_CONTENT_TYPE = "application/json; charset=utf-8"


class ProtocolViolation(RuntimeError):
    """The peer violated the local runtime wire protocol."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def encode_frame(message: Mapping[str, Any], max_frame_bytes: int = MAX_FRAME_BYTES) -> bytes:
    if not isinstance(message, Mapping):
        raise ProtocolViolation("frame payload must be a JSON object")
    try:
        payload = json.dumps(
            dict(message),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation("frame payload is not strict JSON") from exc
    if len(payload) > max_frame_bytes:
        raise ProtocolViolation("frame exceeds negotiated maximum")
    header = (
        f"Content-Length: {len(payload)}\r\n"
        f"Content-Type: {_CONTENT_TYPE}\r\n\r\n"
    ).encode("ascii")
    return header + payload


class FrameDecoder:
    """Incrementally decodes fragmented or coalesced strict JSON frames."""

    def __init__(self, max_frame_bytes: int = MAX_FRAME_BYTES) -> None:
        if not 1 <= max_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError("max_frame_bytes must be between 1 and 1 MiB")
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self._expected_length: int | None = None

    def feed(self, chunk: bytes | bytearray | memoryview) -> list[dict[str, Any]]:
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TypeError("frame chunk must be bytes-like")
        self._buffer.extend(chunk)
        frames: list[dict[str, Any]] = []
        while True:
            if self._expected_length is None:
                boundary = self._buffer.find(_SEPARATOR)
                if boundary < 0:
                    if len(self._buffer) > MAX_HEADER_BYTES:
                        raise ProtocolViolation("frame header exceeds maximum")
                    break
                header_bytes = bytes(self._buffer[:boundary])
                del self._buffer[: boundary + len(_SEPARATOR)]
                self._expected_length = self._parse_header(header_bytes)
            if len(self._buffer) < self._expected_length:
                break
            payload = bytes(self._buffer[: self._expected_length])
            del self._buffer[: self._expected_length]
            self._expected_length = None
            frames.append(self._parse_payload(payload))
        return frames

    def finish(self) -> None:
        if self._buffer or self._expected_length is not None:
            raise ProtocolViolation("transport closed with a partial frame")

    def _parse_header(self, raw: bytes) -> int:
        try:
            lines = raw.decode("ascii").split("\r\n")
        except UnicodeDecodeError as exc:
            raise ProtocolViolation("frame header must be ASCII") from exc
        if len(lines) != 2:
            raise ProtocolViolation("frame header must contain exactly two fields")
        expected_type = f"Content-Type: {_CONTENT_TYPE}"
        if not lines[0].startswith("Content-Length: ") or lines[1] != expected_type:
            raise ProtocolViolation("invalid or reordered frame headers")
        length_text = lines[0][len("Content-Length: ") :]
        if not length_text or not length_text.isascii() or not length_text.isdecimal():
            raise ProtocolViolation("Content-Length must be an unsigned decimal")
        if len(length_text) > 1 and length_text.startswith("0"):
            raise ProtocolViolation("Content-Length must use canonical decimal form")
        length = int(length_text)
        if length <= 0 or length > self.max_frame_bytes:
            raise ProtocolViolation("Content-Length is outside negotiated bounds")
        return length

    @staticmethod
    def _parse_payload(payload: bytes) -> dict[str, Any]:
        try:
            decoded = payload.decode("utf-8")
            value = json.loads(decoded, parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProtocolViolation("frame body must be strict UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ProtocolViolation("frame body must be a JSON object")
        return value


def read_frames(stream: BinaryIO, chunk_size: int = 65536) -> Iterator[dict[str, Any]]:
    decoder = FrameDecoder()
    read_available = getattr(stream, "read1", stream.read)
    while True:
        chunk = read_available(chunk_size)
        if not chunk:
            decoder.finish()
            return
        yield from decoder.feed(chunk)


def write_frame(stream: BinaryIO, message: Mapping[str, Any]) -> None:
    stream.write(encode_frame(message))
    stream.flush()
