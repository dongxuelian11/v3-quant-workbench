"""smoke:product-entry setup/inspection helper (test boundary).

``build`` prepares target-owned canonical source state, exports one package,
then adds enough canonical RunSpecs to prove Desktop page-2 discovery.
``inspect-empty`` performs a read-only post-failure pollution audit against an
external package. Package rows can never bootstrap target authority.
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
from v3_backend.adapters.sqlite.connection import connect_catalog  # noqa: E402


def build(source_root: Path) -> int:
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


def inspect_empty(storage_root: Path, target_project_id: str, package_root: Path) -> int:
    manifest = json.loads((package_root / "manifest.v3.json").read_text(encoding="utf-8"))
    connection = connect_catalog(storage_root / "catalog.sqlite3", read_only=True)
    try:
        project_ids = [
            str(row["project_id"])
            for row in connection.execute("SELECT project_id FROM project ORDER BY project_id")
        ]
        source_project_id = str(manifest["source_project"]["project_id"])
        owner_matches = {}
        for table, identity_column in (
            ("target_weight_vector_publication", "target_weight_vector_id"),
            ("risk_policy_set_publication", "risk_policy_set_version_id"),
            ("risk_application_receipt_publication", "risk_application_receipt_id"),
            ("risk_adjusted_weight_vector_publication", "risk_adjusted_weight_vector_id"),
        ):
            identity = manifest["owner_publications"][table][identity_column]
            owner_matches[table] = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {identity_column}=?", (identity,)
            ).fetchone()[0]
        target_spec_refs = connection.execute(
            "SELECT COUNT(*) FROM artifact_reference "
            "WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE'",
            (target_project_id,),
        ).fetchone()[0]
        all_spec_refs = connection.execute(
            "SELECT COUNT(*) FROM artifact_reference "
            "WHERE role='RESEARCH_RUN_SPEC' AND state='ACTIVE'"
        ).fetchone()[0]
    finally:
        connection.close()
    print(json.dumps({
        "project_ids": project_ids,
        "source_project_id": source_project_id,
        "source_project_present": source_project_id in project_ids,
        "owner_row_matches": owner_matches,
        "target_research_run_spec_refs": target_spec_refs,
        "all_research_run_spec_refs": all_spec_refs,
    }))
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "build" and len(sys.argv) == 3:
        return build(Path(sys.argv[2]).resolve())
    if len(sys.argv) == 2:
        return build(Path(sys.argv[1]).resolve())
    if len(sys.argv) == 5 and sys.argv[1] == "inspect-empty":
        return inspect_empty(
            Path(sys.argv[2]).resolve(), sys.argv[3], Path(sys.argv[4]).resolve()
        )
    raise SystemExit(
        "usage: product_entry_smoke_python.py build <storage-root> | "
        "inspect-empty <storage-root> <target-project-id> <package-root>"
    )


if __name__ == "__main__":
    raise SystemExit(main())
