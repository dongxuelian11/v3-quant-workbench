"""Product Entry clean-start tests.

Covers the V1 Product Entry surface end-to-end at the runtime level:
projectless project bootstrap through closed control frames, verified
canonical research-package import, durable run-spec discovery, submit through
the existing canonical execution path, restart recovery, and the required
negative paths (tamper, traversal-free closed file sets, unknown manifest
fields, idempotency conflicts, cross-project submit).

The golden source storage is prepared ONLY as test setup (accepted canonical
owners); the imported package passes through exactly the same verification
path as a real user package.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
for entry in (str(SRC), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.errors.exceptions import (
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
)
from v3_backend.runtime.product_entry import (
    PACKAGE_SCHEMA_VERSION,
    PRODUCT_ENTRY_PROTOCOL_VERSION,
    build_research_package,
    create_project,
    handle_product_entry_control,
    import_research_package,
    list_backtest_run_specs,
    list_projects,
)
from v3_backend.runtime.product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    ProductRuntime,
)

from apps.backend.tests.product_runtime.helpers import build_product_golden_project


def _build_source_package(source_root: Path) -> tuple[dict, list[dict], str]:
    setup = build_product_golden_project(source_root)
    manifest, files = build_research_package(
        setup.product, source_project_id=setup.project_id, run_spec_id=setup.run_spec_id
    )
    return manifest, files, setup.run_spec_id


class _CleanStorageCase(unittest.TestCase):
    def setUp(self) -> None:
        self._source_tmp = tempfile.TemporaryDirectory()
        self._target_tmp = tempfile.TemporaryDirectory()
        self.source_root = Path(self._source_tmp.name)
        self.target_root = Path(self._target_tmp.name)
        self.manifest, self.files, self.run_spec_id = _build_source_package(self.source_root)
        self.product = ProductRuntime(self.target_root)
        created = create_project(
            self.product, display_name="导入研究", idempotency_key="case-setup"
        )
        self.project_id = created["project_id"]
        self.pcr = created["project_context_revision_id"]

    def tearDown(self) -> None:
        self._source_tmp.cleanup()
        self._target_tmp.cleanup()

    def _import(self, manifest=None, files=None, key="import-key"):
        return import_research_package(
            self.product,
            project_id=self.project_id,
            project_context_revision_id=self.pcr,
            manifest_wire=self.manifest if manifest is None else manifest,
            files_wire=self.files if files is None else files,
            idempotency_key=key,
        )

    def _active_spec_refs(self) -> list[tuple[str, str]]:
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            rows = connection.execute(
                "SELECT owner_id, artifact_id FROM artifact_reference "
                "WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE'",
                (self.project_id,),
            ).fetchall()
        finally:
            connection.close()
        return [(str(row["owner_id"]), str(row["artifact_id"])) for row in rows]


class CleanStartFlowTests(_CleanStorageCase):
    def test_fresh_storage_invents_no_projects_or_specs(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            virgin = ProductRuntime(Path(fresh))
            self.assertEqual(list_projects(virgin)["projects"], [])
            created = create_project(virgin, display_name="唯一项目", idempotency_key="fresh")
            listing = list_backtest_run_specs(
                virgin,
                project_id=created["project_id"],
                project_context_revision_id=created["project_context_revision_id"],
            )
            self.assertEqual(listing["specs"], [])
            self.assertFalse(listing["has_more"])

    def test_import_discover_submit_restart_recovery(self) -> None:
        outcome = self._import()
        self.assertFalse(outcome["already_imported"])
        self.assertEqual(outcome["run_spec_id"], self.run_spec_id)

        listing = list_backtest_run_specs(
            self.product, project_id=self.project_id, project_context_revision_id=self.pcr
        )
        self.assertEqual(len(listing["specs"]), 1)
        entry = listing["specs"][0]
        self.assertEqual(entry["status"], "EXECUTABLE")
        self.assertNotIn("diagnostic", entry)
        self.assertEqual(entry["project_context_revision_id"], self.pcr)

        execution = self.product.execution.submit_backtest(
            project_id=self.project_id,
            project_context_revision_id=self.pcr,
            run_spec_id=self.run_spec_id,
            execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
            idempotency_key="submit-1",
        )
        task = self.product.task_persistence.read_task(execution.task_id)
        self.assertEqual(task.state.value, "SUCCEEDED")
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            result_row = connection.execute(
                "SELECT * FROM result WHERE backtest_run_id=?", (execution.run_id,)
            ).fetchone()
            manifest_row = connection.execute(
                "SELECT artifact_id FROM artifact_reference WHERE owner_id=? AND role='LEDGER_MANIFEST' AND state='ACTIVE'",
                (execution.run_id,),
            ).fetchone()
            result_row2 = connection.execute(
                "SELECT artifact_id FROM artifact_reference WHERE owner_id=? AND role='BACKTEST_RUN_RESULT' AND state='ACTIVE'",
                (execution.run_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(manifest_row)
        self.assertIsNotNone(result_row2)
        # Actual artifact bytes hash matches the content-addressed identity.
        for row in (manifest_row, result_row2):
            payload = self.product.read_verified_bytes(str(row["artifact_id"]))
            self.assertTrue(row["artifact_id"].endswith(
                __import__("hashlib").sha256(payload).hexdigest()
            ))

        # Restart: every canonical state recovers from the same storage root.
        restarted = ProductRuntime(self.target_root)
        projects_after = list_projects(restarted)["projects"]
        listed_ids = {item["project_id"] for item in projects_after}
        self.assertIn(self.project_id, listed_ids)
        # The package's source project is explicit provenance (visible, not hidden).
        self.assertIn(self.manifest["source_project"]["project_id"], listed_ids)
        listing_after = list_backtest_run_specs(
            restarted, project_id=self.project_id, project_context_revision_id=self.pcr
        )
        self.assertEqual(listing_after, listing)
        task_after = restarted.task_persistence.read_task(execution.task_id)
        self.assertEqual(task_after.state.value, "SUCCEEDED")

    def test_reimport_same_package_is_idempotent(self) -> None:
        first = self._import(key="same")
        second = self._import(key="same")
        self.assertTrue(second["already_imported"])
        self.assertEqual(second["run_spec_id"], first["run_spec_id"])
        self.assertEqual(second["context_artifact_id"], first["context_artifact_id"])
        self.assertEqual(len(self._active_spec_refs()), 1)

    def test_import_under_second_project_keeps_stable_identity(self) -> None:
        self._import(key="p1")
        second = create_project(self.product, display_name="第二个项目", idempotency_key="p2")
        outcome = import_research_package(
            self.product,
            project_id=second["project_id"],
            project_context_revision_id=second["project_context_revision_id"],
            manifest_wire=self.manifest,
            files_wire=self.files,
            idempotency_key="p2-import",
        )
        self.assertEqual(outcome["run_spec_id"], self.run_spec_id)
        self.assertEqual(outcome["run_spec_artifact_id"], self._import(key="p1")["run_spec_artifact_id"])


class ProjectBootstrapTests(_CleanStorageCase):
    def test_create_project_mints_backend_identities_atomically(self) -> None:
        created = create_project(
            self.product, display_name="另一个项目", notes="备注", idempotency_key="fresh"
        )
        self.assertTrue(created["project_id"].startswith("prj_"))
        self.assertTrue(created["project_context_revision_id"].startswith("pcr_"))
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            revision = connection.execute(
                "SELECT * FROM project_context_revision WHERE project_context_revision_id=?",
                (created["project_context_revision_id"],),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(dict(revision)["revision_no"], 1)
        context = json.loads(dict(revision)["context_json"])
        self.assertEqual(context, {"context_fields": {"notes": "备注"}})

    def test_create_project_idempotency_and_conflict(self) -> None:
        first = create_project(self.product, display_name="A", idempotency_key="k")
        replay = create_project(self.product, display_name="A", idempotency_key="k")
        self.assertEqual(first, replay)
        with self.assertRaises(IdempotencyConflictError):
            create_project(self.product, display_name="B", idempotency_key="k")

    def test_list_projects_is_stable_and_bounded(self) -> None:
        created = create_project(self.product, display_name="B2", idempotency_key="b2")
        listing = list_projects(self.product, limit=1)
        self.assertEqual(len(listing["projects"]), 1)
        self.assertTrue(listing["has_more"])
        listing_all = list_projects(self.product, limit=10)
        self.assertEqual(
            [item["project_id"] for item in listing_all["projects"]],
            sorted(item["project_id"] for item in listing_all["projects"]),
        )
        self.assertIn(created["project_id"], [item["project_id"] for item in listing_all["projects"]])

    def test_control_frames_are_closed(self) -> None:
        response = handle_product_entry_control(
            self.product,
            "productEntry.createProject",
            {
                "kind": "productEntry.createProject",
                "protocol_version": PRODUCT_ENTRY_PROTOCOL_VERSION,
                "display_name": "通过控制帧",
                "idempotency_key": "cf1",
                "notes": None,
            },
        )
        self.assertEqual(response["kind"], "productEntry.projectCreated")
        with self.assertRaises(InvalidArgumentError):
            handle_product_entry_control(
                self.product,
                "productEntry.createProject",
                {
                    "kind": "productEntry.createProject",
                    "protocol_version": PRODUCT_ENTRY_PROTOCOL_VERSION,
                    "display_name": "x",
                    "idempotency_key": "cf2",
                    "notes": None,
                    "project_id": "prj_FORGED",
                },
            )
        with self.assertRaises(InvalidArgumentError):
            handle_product_entry_control(
                self.product,
                "productEntry.listProjects",
                {"kind": "productEntry.listProjects", "protocol_version": "v3.product-entry/0.9"},
            )


class ImportNegativeTests(_CleanStorageCase):
    def test_tampered_payload_byte_fails_and_registers_nothing(self) -> None:
        files = copy.deepcopy(self.files)
        spec_file = next(item for item in files if item["name"] == "spec.json")
        payload = bytearray(__import__("base64").b64decode(spec_file["payload_base64"]))
        payload[10] = payload[10] ^ 0x01
        spec_file["payload_base64"] = __import__("base64").b64encode(bytes(payload)).decode("ascii")
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files, key="tamper")
        self.assertEqual(self._active_spec_refs(), [])

    def test_declared_hash_lie_fails(self) -> None:
        files = copy.deepcopy(self.files)
        target = next(item for item in files if item["name"] == "adjusted.json")
        target["sha256"] = "0" * 64
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files, key="lie")
        self.assertEqual(self._active_spec_refs(), [])

    def test_path_traversal_and_unknown_file_names_fail(self) -> None:
        files = copy.deepcopy(self.files)
        files[0] = {**files[0], "name": "../escape.json"}
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files, key="traversal")
        files2 = copy.deepcopy(self.files)
        files2[0] = {**files2[0], "name": "sub/dir/file.json"}
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files2, key="subdir")

    def test_unknown_manifest_field_or_version_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["extra_field"] = "no"
        with self.assertRaises(InvalidArgumentError):
            self._import(manifest=manifest, key="unknown-field")
        manifest2 = copy.deepcopy(self.manifest)
        manifest2["schema_version"] = "v3.research-package/9.9.9"
        with self.assertRaises(InvalidArgumentError):
            self._import(manifest=manifest2, key="bad-version")

    def test_missing_required_file_fails(self) -> None:
        files = [item for item in self.files if item["name"] != "policy.json"]
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files, key="missing")
        self.assertEqual(self._active_spec_refs(), [])

    def test_extra_file_fails(self) -> None:
        files = self.files + [{
            "name": "extra.json",
            "sha256": "0" * 64,
            "byte_size": 1,
            "payload_base64": "eA==",
        }]
        with self.assertRaises(InvalidArgumentError):
            self._import(files=files, key="extra")

    def test_manifest_owner_binding_tamper_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["owner_publications"]["risk_adjusted_weight_vector_publication"][
            "context_identity"
        ] = "1" * 64
        with self.assertRaises(InvalidArgumentError):
            self._import(manifest=manifest, key="ctx-tamper")
        manifest2 = copy.deepcopy(self.manifest)
        manifest2["owner_publications"]["risk_application_receipt_publication"][
            "source_target_weight_vector_id"
        ] = "twv_sha256_" + "0" * 64
        with self.assertRaises(InvalidArgumentError):
            self._import(manifest=manifest2, key="receipt-tamper")

    def test_import_rejects_stale_or_foreign_project_context(self) -> None:
        with self.assertRaises(NotFoundError):
            import_research_package(
                self.product,
                project_id=self.project_id,
                project_context_revision_id="pcr_" + "A" * 26,
                manifest_wire=self.manifest,
                files_wire=self.files,
                idempotency_key="stale",
            )

    def test_import_into_source_project_identity_fails(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["source_project"]["project_id"] = self.project_id
        with self.assertRaises(InvalidArgumentError):
            self._import(manifest=manifest, key="self-import")

    def test_same_key_different_package_conflicts(self) -> None:
        self._import(key="dup")
        manifest = copy.deepcopy(self.manifest)
        manifest["source_project"]["display_name"] = "被替换的名称"
        with self.assertRaises(IdempotencyConflictError):
            self._import(manifest=manifest, key="dup")

    def test_caller_numeric_arrays_are_absent_from_request_surface(self) -> None:
        # The import request surface carries manifest + payload files only;
        # there is no prices/returns/weights/NAV field anywhere in the schema.
        manifest_keys = set(self.manifest)
        forbidden = {"prices", "returns", "observations", "weights", "nav", "metrics"}
        self.assertEqual(manifest_keys & forbidden, set())
        for item in self.files:
            self.assertEqual(
                set(item), {"name", "sha256", "byte_size", "payload_base64"}
            )


class DiscoveryNegativeTests(_CleanStorageCase):
    def test_tampered_spec_artifact_is_listed_unavailable_not_executable(self) -> None:
        self._import()
        connection = connect_catalog(self.product.database_path)
        try:
            row = connection.execute(
                "SELECT artifact_id FROM artifact_reference WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE'",
                (self.project_id,),
            ).fetchone()
            artifact_id = str(row["artifact_id"])
            sha = artifact_id.removeprefix("art_sha256_")
        finally:
            connection.close()
        # Corrupt the stored bytes on disk (simulate tampering after import).
        target_file = (
            self.target_root
            / "artifacts"
            / "sha256"
            / sha[:2]
            / sha[2:4]
            / sha
        )
        self.assertTrue(target_file.exists())
        original = target_file.read_bytes()
        try:
            target_file.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
            listing = list_backtest_run_specs(
                self.product, project_id=self.project_id, project_context_revision_id=self.pcr
            )
            self.assertEqual(listing["specs"][0]["status"], "UNAVAILABLE")
            self.assertTrue(listing["specs"][0]["diagnostic"])
        finally:
            target_file.write_bytes(original)

    def test_submit_run_spec_of_other_project_fails_closed(self) -> None:
        self._import()
        other = create_project(self.product, display_name="其他项目", idempotency_key="other")
        with self.assertRaises(Exception):
            self.product.execution.submit_backtest(
                project_id=other["project_id"],
                project_context_revision_id=other["project_context_revision_id"],
                run_spec_id=self.run_spec_id,
                execution_adapter_version_id=ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
                idempotency_key="cross",
            )


class PackageSchemaSanityTests(unittest.TestCase):
    def test_exported_manifest_is_the_frozen_schema_version(self) -> None:
        self.assertEqual(PACKAGE_SCHEMA_VERSION, "v3.research-package/1.0.0")


if __name__ == "__main__":
    unittest.main()
