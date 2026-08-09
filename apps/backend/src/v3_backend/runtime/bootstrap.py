"""Only executable composition entry for the canonical Python backend runtime."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .composition_root import build_runtime
from .framed_stdio import ProtocolViolation
from .handshake import read_supervisor_token

BACKEND_VERSION = "0.1.0-recovery.1"
TRANSPORT = "stdio-framed-v1"


def _diagnostic(level: str, code: str, message: str) -> None:
    record: dict[str, Any] = {"level": level, "code": code, "message": message}
    sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v3_backend.runtime.bootstrap")
    parser.add_argument("--transport", required=True, choices=[TRANSPORT])
    parser.parse_args(argv)
    try:
        token = read_supervisor_token()
        runtime = build_runtime(token, BACKEND_VERSION)
        runtime.run(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    except ProtocolViolation as exc:
        _diagnostic("ERROR", "RUNTIME_PROTOCOL_VIOLATION", str(exc))
        return 2
    except Exception:
        _diagnostic("ERROR", "RUNTIME_INTERNAL_ERROR", "runtime terminated unexpectedly")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
