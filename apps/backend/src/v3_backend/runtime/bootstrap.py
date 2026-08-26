"""Only executable composition entry for the canonical Python backend runtime."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from v3_backend.errors.exceptions import CatalogStartupError

from .composition_root import RuntimePorts, build_runtime, default_capabilities
from .build_manifest import BUILD_MANIFEST
from .framed_stdio import ProtocolViolation
from .handshake import read_supervisor_token
from .product_runtime import build_product_ports, resolve_product_storage_root

BACKEND_VERSION = BUILD_MANIFEST.code_version
TRANSPORT = "stdio-framed-v1"


def _diagnostic(level: str, code: str, message: str) -> None:
    record: dict[str, Any] = {"level": level, "code": code, "message": message}
    sys.stderr.write(json.dumps(record, separators=(",", ":")) + "\n")
    sys.stderr.flush()


def _build_ports(args: argparse.Namespace) -> RuntimePorts:
    """Normal production bootstrap binds the product runtime composition.

    The transport-only development shell (every service UNAVAILABLE with
    ASL_FACADE_NOT_BOUND) remains available exclusively through the explicit
    --development-shell opt-in; it is never the normal path.
    """
    if args.development_shell:
        return RuntimePorts(capabilities=default_capabilities())
    storage_root = resolve_product_storage_root(args.storage_root)
    provider_factory = None
    acceptance_provider = getattr(args, "product_release_acceptance_provider", None)
    if acceptance_provider is not None:
        from .product_release_acceptance import (
            product_release_acceptance_provider_factory,
        )

        provider_factory = product_release_acceptance_provider_factory(
            acceptance_provider
        )
    return build_product_ports(
        storage_root,
        research_provider_factory=provider_factory,
        research_provider_mode=acceptance_provider,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v3_backend.runtime.bootstrap")
    parser.add_argument("--transport", required=True, choices=[TRANSPORT])
    parser.add_argument(
        "--storage-root",
        default=None,
        help="product storage root (default: $V3_PRODUCT_STORAGE_ROOT or the local app-data product root)",
    )
    parser.add_argument(
        "--development-shell",
        action="store_true",
        help="explicit opt-in transport-only development shell (no product facades)",
    )
    parser.add_argument(
        "--product-release-acceptance-provider",
        choices=["DETERMINISTIC_SUCCESS", "DETERMINISTIC_UNAVAILABLE"],
        default=None,
        help="explicit packaged V1 acceptance-only provider boundary; never normal product startup",
    )
    args = parser.parse_args(argv)
    try:
        token = read_supervisor_token()
        runtime = build_runtime(token, BACKEND_VERSION, _build_ports(args))
        runtime.run(sys.stdin.buffer, sys.stdout.buffer)
        return 0
    except ProtocolViolation as exc:
        _diagnostic("ERROR", "RUNTIME_PROTOCOL_VIOLATION", str(exc))
        return 2
    except CatalogStartupError as exc:
        _diagnostic("ERROR", exc.code.value, exc.public_message)
        return 3
    except Exception:
        _diagnostic("ERROR", "RUNTIME_INTERNAL_ERROR", "runtime terminated unexpectedly")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
