"""Prepare one project-reachable large Artifact for the real stream smoke."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))
sys.path.insert(0, str(ROOT))

from apps.backend.tests.product_runtime.helpers import (  # noqa: E402
    build_product_golden_project,
)
from v3_backend.runtime.product_facades import ArtifactFacade  # noqa: E402
from v3_backend.runtime.product_runtime import mint_uuid7  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: artifact-stream-smoke-python.py <storage-root>")
    storage_root = Path(sys.argv[1]).resolve()
    setup = build_product_golden_project(storage_root)
    payload = b'{"payload":"' + (b"x" * (600 * 1024)) + b'"}'
    staged = setup.product.artifact_store.stage_bytes(payload)
    published = ArtifactFacade(setup.product).publish_artifact(
        {
            "request_id": mint_uuid7(),
            "project_id": setup.project_id,
            "project_context_revision_id": setup.product.current_revision(
                setup.project_id
            )["project_context_revision_id"],
            "staging_token": staged.staging_token,
            "declared_media_type": "application/json",
            "declared_role": "PRODUCT_RESEARCH_BACKTEST_READ_MODEL",
            "expected_sha256": staged.sha256,
            "idempotency_key": "artifact-stream-cross-language-large",
        }
    )["read_model"]
    print(
        json.dumps(
            {
                "project_id": setup.project_id,
                "project_context_revision_id": setup.product.current_revision(
                    setup.project_id
                )["project_context_revision_id"],
                "artifact_id": published["artifact_id"],
                "sha256": published["sha256"],
                "byte_size": published["byte_size"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
