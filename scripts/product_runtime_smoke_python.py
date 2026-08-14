"""B3 product-runtime smoke helpers (setup + verification).

Test-setup boundary: the setup command prepares canonical source data and
owners inside a product storage root through the accepted canonical owners.
The verify command re-reads canonical evidence through the product runtime's
hash-verified read path after backend restarts.  The framed-stdio business
path itself runs exclusively through the normal production bootstrap.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _setup(storage_root: str) -> None:
    from apps.backend.tests.product_runtime.helpers import build_product_golden_project

    setup = build_product_golden_project(Path(storage_root))
    print(
        json.dumps(
            {
                "project_id": setup.project_id,
                "project_context_revision_id": setup.project_context_revision_id,
                "run_spec_id": setup.run_spec_id,
                "session_hint": setup.session_id,
                "expected_backtest_result_id": setup.pipeline_result.backtest_result_id,
                "pipeline_result_artifact_sha256": (
                    setup.pipeline_result.result_artifact_sha256
                ),
            },
            separators=(",", ":"),
        )
    )


def _verify(storage_root: str, artifact_id: str, declared_sha: str, run_spec_id: str, expected_result_id: str) -> None:
    from v3_backend.runtime.product_runtime import build_product_runtime

    product = build_product_runtime(storage_root)
    payload = product.read_verified_bytes(artifact_id)
    observed = hashlib.sha256(payload).hexdigest()
    if observed != declared_sha:
        raise SystemExit(f"artifact SHA mismatch: declared={declared_sha} observed={observed}")
    wire = json.loads(payload.decode("utf-8"))
    if wire.get("run_spec_id") != run_spec_id:
        raise SystemExit("artifact run_spec_id mismatch")
    if wire.get("result_id") != expected_result_id:
        raise SystemExit("runtime result diverges from the canonical setup pipeline result")
    print(
        json.dumps(
            {
                "sha256": observed,
                "byte_size": len(payload),
                "result_id": wire.get("result_id"),
                "run_spec_id": wire.get("run_spec_id"),
                "verified": True,
            },
            separators=(",", ":"),
        )
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: product_runtime_smoke_python.py setup <root> | verify <root> <artifact> <sha> <spec> <result>")
    command = sys.argv[1]
    if command == "setup":
        _setup(sys.argv[2])
    elif command == "verify":
        _verify(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
