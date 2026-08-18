"""smoke:product-entry package builder (test setup boundary).

Prepares target-owned canonical source state in the smoke's exact storage,
exports one package, then adds enough canonical RunSpecs to prove Desktop page
2 discovery. The package can execute only because the backend later resolves
the exact source rows and bytes from this target state; package rows cannot
bootstrap authority.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "backend" / "src"))
sys.path.insert(0, str(ROOT))

from apps.backend.tests.product_runtime.helpers import build_product_golden_project  # noqa: E402
from v3_backend.domain.backtest_runtime.model import BacktestRunSpec  # noqa: E402
from v3_backend.runtime.product_entry import build_research_package  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: product_entry_smoke_python.py <target-storage-root>")
    source_root = Path(sys.argv[1]).resolve()
    package_root = Path(tempfile.mkdtemp(prefix="v3-product-entry-package-"))
    try:
        setup = build_product_golden_project(source_root)
        manifest, files = build_research_package(
            setup.product,
            source_project_id=setup.project_id,
            run_spec_id=setup.run_spec_id,
        )
        source_pcr = str(
            setup.product.current_revision(setup.project_id)["project_context_revision_id"]
        )
        (package_root / "manifest.v3.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        written = {}
        for item in files:
            payload = base64.b64decode(item["payload_base64"])
            (package_root / item["name"]).write_bytes(payload)
            written[item["name"]] = item["sha256"]

        base, _ = setup.product.spec_codec.reconstruct(
            project_id=setup.project_id,
            run_spec_id=setup.run_spec_id,
        )
        published_at = datetime(2026, 1, 5, 15, 31, tzinfo=timezone.utc)
        for ordinal in range(1, 51):
            variant = BacktestRunSpec.create(
                initial_cash=str(100_000 + ordinal),
                initial_holdings=base.initial_holdings,
                instruments=base.instruments,
                sessions=base.sessions,
                schedule=base.schedule,
                rule_profile=base.rule_profile,
                cost_policy=base.cost_policy,
                execution_timing_profile=base.execution_timing_profile,
                exact_references=base.exact_references,
                runtime_identity=base.runtime_identity,
                engine_version=base.engine_version,
            )
            setup.product.spec_codec.persist(
                spec=variant,
                rule_profile=variant.rule_profile,
                cost_policy=variant.cost_policy,
                timing_profile=variant.execution_timing_profile,
                project_id=setup.project_id,
                project_context_revision_id=source_pcr,
                published_at=published_at,
            )
        print(json.dumps({
            "package_dir": str(package_root),
            "run_spec_id": setup.run_spec_id,
            "source_project_id": setup.project_id,
            "source_project_context_revision_id": source_pcr,
            "source_run_spec_count": 51,
            "files": written,
        }))
        return 0
    except Exception:
        import shutil
        shutil.rmtree(package_root, ignore_errors=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
