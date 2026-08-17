"""smoke:product-entry package builder (test setup boundary).

Prepares a canonical V3 research package from a TEMP source storage through
the accepted canonical owners (golden test setup) and writes it to a plain
directory (manifest.v3.json + actual payload files).  The LIVE Product Entry
import inside the smoke consumes this directory through the exact same
verification path as a real user package.  The helper exits immediately; the
parent smoke cleans up the printed temp directories.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))
sys.path.insert(0, str(ROOT))

from apps.backend.tests.product_runtime.helpers import build_product_golden_project  # noqa: E402
from v3_backend.runtime.product_entry import build_research_package  # noqa: E402


def main() -> int:
    source_root = Path(tempfile.mkdtemp(prefix="v3-product-entry-source-"))
    package_root = Path(tempfile.mkdtemp(prefix="v3-product-entry-package-"))
    try:
        setup = build_product_golden_project(source_root)
        manifest, files = build_research_package(
            setup.product,
            source_project_id=setup.project_id,
            run_spec_id=setup.run_spec_id,
        )
        (package_root / "manifest.v3.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        written = {}
        for item in files:
            payload = base64.b64decode(item["payload_base64"])
            (package_root / item["name"]).write_bytes(payload)
            written[item["name"]] = item["sha256"]
        print(json.dumps({
            "source_root": str(source_root),
            "package_dir": str(package_root),
            "run_spec_id": setup.run_spec_id,
            "files": written,
        }))
        return 0
    finally:
        import shutil

        shutil.rmtree(source_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
