"""Product Entry foundation tests.

Covers the V1 Product Entry surface end-to-end at the runtime level:
projectless project bootstrap through closed control frames, verified
canonical research-package import, durable run-spec discovery, submit through
the existing canonical execution path, restart recovery, and the required
negative paths (tamper, traversal-free closed file sets, unknown manifest
fields, idempotency conflicts, cross-project submit).

Positive import cases explicitly pre-establish accepted canonical owners in
the target and therefore prove TARGET_CANONICAL_REUSE only. Separate empty-
target negatives prove that a package cannot bootstrap first source authority.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "apps" / "backend" / "src"
for entry in (str(SRC), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.contracts.common.dto import ContractValidationError
from v3_backend.contracts.product_entry import ListBacktestRunSpecsResponseV1
from v3_backend.domain.backtest_runtime.model import BacktestRunSpec
from v3_backend.errors.exceptions import (
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.runtime.product_entry import (
    PACKAGE_SCHEMA_VERSION,
    PRODUCT_ENTRY_PROTOCOL_VERSION,
    _decode_files,
    _find_artifact_entry,
    _parse_canonical_json,
    _require_descriptor_matches,
    _verify_closed_file_set,
    _verify_context_wire,
    _verify_owner_rows,
    _verify_spec_wire,
    build_research_package,
    create_project,
    handle_product_entry_control,
    import_research_package,
    list_backtest_run_specs,
    list_projects,
    parse_package_manifest,
)
from v3_backend.runtime.product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    ProductRuntime,
    build_product_ports,
    mint_v3_id,
    mint_uuid7,
)
from v3_backend.runtime.request_router import RequestRouter

from apps.backend.tests.product_runtime.helpers import build_product_golden_project


def _build_source_package(source_root: Path) -> tuple[dict, list[dict], str]:
    setup = build_product_golden_project(source_root)
    manifest, files = build_research_package(
        setup.product, source_project_id=setup.project_id, run_spec_id=setup.run_spec_id
    )
    return manifest, files, setup.run_spec_id


def _decode_file(files: list[dict], name: str) -> dict:
    item = next(entry for entry in files if entry["name"] == name)
    return json.loads(base64.b64decode(item["payload_base64"]).decode("utf-8"))


def _replace_file(manifest: dict, files: list[dict], name: str, wire: dict) -> tuple[str, str]:
    payload = canonical_json_bytes(wire)
    digest = hashlib.sha256(payload).hexdigest()
    artifact_id = "art_sha256_" + digest
    item = next(entry for entry in files if entry["name"] == name)
    item.update(
        sha256=digest,
        byte_size=len(payload),
        payload_base64=base64.b64encode(payload).decode("ascii"),
    )
    artifact = next(entry for entry in manifest["artifacts"] if entry["name"] == name)
    artifact["row"].update(
        artifact_id=artifact_id,
        sha256=digest,
        byte_size=len(payload),
        storage_key=f"sha256/{digest[:2]}/{digest[2:4]}/{digest}",
    )
    for descriptor_name in ("run_spec_artifact", "execution_context_artifact"):
        descriptor = manifest[descriptor_name]
        if descriptor["name"] == name:
            descriptor.update(
                artifact_id=artifact_id,
                sha256=digest,
                byte_size=len(payload),
            )
    return artifact_id, digest


def _recompute_run_spec(manifest: dict, files: list[dict], spec: dict) -> None:
    payload = {
        key: value
        for key, value in spec.items()
        if key not in {"artifact_type", "run_spec_id", "content_sha256"}
    }
    content_sha = canonical_sha256(payload)
    run_spec_id = "btrs_sha256_" + content_sha
    spec["content_sha256"] = content_sha
    spec["run_spec_id"] = run_spec_id
    manifest["run_spec_id"] = run_spec_id
    _replace_file(manifest, files, "spec.json", spec)
    context = _decode_file(files, "context.json")
    context["run_spec_id"] = run_spec_id
    context["run_spec_content_sha256"] = content_sha
    _replace_file(manifest, files, "context.json", context)


def _assert_package_internal_integrity(manifest_wire: dict, files_wire: list[dict]) -> None:
    manifest = parse_package_manifest(manifest_wire)
    files = _decode_files(files_wire)
    _verify_closed_file_set(manifest, files)
    spec_file = files[manifest["run_spec_artifact"]["name"]]
    context_file = files[manifest["execution_context_artifact"]["name"]]
    _require_descriptor_matches(manifest["run_spec_artifact"], spec_file, "run_spec_artifact")
    _require_descriptor_matches(
        manifest["execution_context_artifact"], context_file, "execution_context_artifact"
    )
    spec = _parse_canonical_json(spec_file.payload, "run spec")
    context = _parse_canonical_json(context_file.payload, "execution context")
    _verify_spec_wire(spec, manifest)
    _verify_context_wire(context, manifest, spec)
    for table, row in manifest["owner_publications"].items():
        descriptor = _find_artifact_entry(manifest, str(row["artifact_id"]), table)
        _require_descriptor_matches(descriptor, files[descriptor["name"]], table)
    _verify_owner_rows(manifest, files)


def _fully_consistent_market_forgery(manifest: dict, files: list[dict]) -> tuple[dict, list[dict]]:
    forged_manifest = copy.deepcopy(manifest)
    forged_files = copy.deepcopy(files)
    spec = _decode_file(forged_files, "spec.json")
    spec["sessions"][0]["states"][0]["raw_open"] = "99.25"
    market_digest = canonical_sha256(spec["sessions"])
    for reference in spec["exact_references"]:
        if reference["reference_kind"] in {"MARKET_DATA", "SNAPSHOT"}:
            prefix = "research_market_sha256_" if reference["reference_kind"] == "MARKET_DATA" else "research_snapshot_sha256_"
            reference["content_sha256"] = market_digest
            reference["source_id"] = prefix + market_digest
    _recompute_run_spec(forged_manifest, forged_files, spec)
    _assert_package_internal_integrity(forged_manifest, forged_files)
    return forged_manifest, forged_files


def _rebind_owner_artifact(
    manifest: dict,
    *,
    table: str,
    identity_column: str,
    identity: str,
    content_sha: str,
    file_name: str,
    artifact_id: str,
    artifact_sha: str,
    byte_size: int,
) -> None:
    row = manifest["owner_publications"][table]
    old_reference_id = row["artifact_reference_id"]
    new_reference_id = mint_v3_id("arf_")
    row.update(
        {
            identity_column: identity,
            "content_sha256": content_sha,
            "artifact_id": artifact_id,
            "artifact_reference_id": new_reference_id,
            "artifact_sha256": artifact_sha,
            "byte_size": byte_size,
        }
    )
    reference = next(
        item for item in manifest["artifact_references"]
        if item["artifact_reference_id"] == old_reference_id
    )
    reference.update(
        artifact_reference_id=new_reference_id,
        owner_id=identity,
        artifact_id=artifact_id,
    )
    assert next(entry for entry in manifest["artifacts"] if entry["name"] == file_name)


def _fully_consistent_weight_forgery(manifest: dict, files: list[dict]) -> tuple[dict, list[dict]]:
    forged_manifest = copy.deepcopy(manifest)
    forged_files = copy.deepcopy(files)

    target = _decode_file(forged_files, "target.json")
    target["rows"][0]["target_weight"] = "0.44"
    target["rows"][1]["target_weight"] = "0.44"
    target["cash_weight"] = "0.12"
    target_payload = {
        key: value for key, value in target.items()
        if key not in {"artifact_type", "target_weight_vector_id", "content_sha256"}
    }
    target_sha = canonical_sha256(target_payload)
    target_id = "twv_sha256_" + target_sha
    target.update(target_weight_vector_id=target_id, content_sha256=target_sha)
    target_artifact_id, target_artifact_sha = _replace_file(
        forged_manifest, forged_files, "target.json", target
    )
    _rebind_owner_artifact(
        forged_manifest,
        table="target_weight_vector_publication",
        identity_column="target_weight_vector_id",
        identity=target_id,
        content_sha=target_sha,
        file_name="target.json",
        artifact_id=target_artifact_id,
        artifact_sha=target_artifact_sha,
        byte_size=len(canonical_json_bytes(target)),
    )

    receipt = _decode_file(forged_files, "receipt.json")
    receipt.update(
        source_target_weight_vector_id=target_id,
        source_target_content_sha256=target_sha,
    )
    receipt_payload = {
        key: value for key, value in receipt.items()
        if key not in {"artifact_type", "risk_application_receipt_id", "content_sha256"}
    }
    receipt_sha = canonical_sha256(receipt_payload)
    receipt_id = "rar_sha256_" + receipt_sha
    receipt.update(risk_application_receipt_id=receipt_id, content_sha256=receipt_sha)
    receipt_artifact_id, receipt_artifact_sha = _replace_file(
        forged_manifest, forged_files, "receipt.json", receipt
    )
    _rebind_owner_artifact(
        forged_manifest,
        table="risk_application_receipt_publication",
        identity_column="risk_application_receipt_id",
        identity=receipt_id,
        content_sha=receipt_sha,
        file_name="receipt.json",
        artifact_id=receipt_artifact_id,
        artifact_sha=receipt_artifact_sha,
        byte_size=len(canonical_json_bytes(receipt)),
    )
    receipt_row = forged_manifest["owner_publications"]["risk_application_receipt_publication"]
    receipt_row.update(
        source_target_weight_vector_id=target_id,
        source_target_content_sha256=target_sha,
    )

    adjusted = _decode_file(forged_files, "adjusted.json")
    adjusted.update(
        source_target_weight_vector_id=target_id,
        source_target_content_sha256=target_sha,
        risk_application_receipt_id=receipt_id,
        risk_application_content_sha256=receipt_sha,
        rows=copy.deepcopy(target["rows"]),
        cash_weight=target["cash_weight"],
    )
    adjusted_payload = {
        key: value for key, value in adjusted.items()
        if key not in {"artifact_type", "risk_adjusted_weight_vector_id", "content_sha256"}
    }
    adjusted_sha = canonical_sha256(adjusted_payload)
    adjusted_id = "rawv_sha256_" + adjusted_sha
    adjusted.update(risk_adjusted_weight_vector_id=adjusted_id, content_sha256=adjusted_sha)
    adjusted_artifact_id, adjusted_artifact_sha = _replace_file(
        forged_manifest, forged_files, "adjusted.json", adjusted
    )
    _rebind_owner_artifact(
        forged_manifest,
        table="risk_adjusted_weight_vector_publication",
        identity_column="risk_adjusted_weight_vector_id",
        identity=adjusted_id,
        content_sha=adjusted_sha,
        file_name="adjusted.json",
        artifact_id=adjusted_artifact_id,
        artifact_sha=adjusted_artifact_sha,
        byte_size=len(canonical_json_bytes(adjusted)),
    )
    adjusted_row = forged_manifest["owner_publications"]["risk_adjusted_weight_vector_publication"]
    adjusted_row.update(
        source_target_weight_vector_id=target_id,
        source_target_content_sha256=target_sha,
        risk_application_receipt_id=receipt_id,
        risk_application_content_sha256=receipt_sha,
    )

    spec = _decode_file(forged_files, "spec.json")
    spec["schedule"][0].update(
        risk_adjusted_weight_vector_id=adjusted_id,
        content_sha256=adjusted_sha,
    )
    _recompute_run_spec(forged_manifest, forged_files, spec)
    _assert_package_internal_integrity(forged_manifest, forged_files)
    return forged_manifest, forged_files


class _TargetCanonicalReuseCase(unittest.TestCase):
    def setUp(self) -> None:
        self._target_tmp = tempfile.TemporaryDirectory()
        self.target_root = Path(self._target_tmp.name)
        source = build_product_golden_project(self.target_root)
        self.product = source.product
        self.manifest, self.files = build_research_package(
            self.product,
            source_project_id=source.project_id,
            run_spec_id=source.run_spec_id,
        )
        self.run_spec_id = source.run_spec_id
        created = create_project(
            self.product, display_name="导入研究", idempotency_key="case-setup"
        )
        self.project_id = created["project_id"]
        self.pcr = created["project_context_revision_id"]

    def tearDown(self) -> None:
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


class TargetCanonicalReuseFlowTests(_TargetCanonicalReuseCase):
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

    def test_target_canonical_reuse_import_submit_restart_recovery(self) -> None:
        outcome = self._import()
        self.assertFalse(outcome["already_imported"])
        self.assertEqual(outcome["run_spec_id"], self.run_spec_id)

        listing = list_backtest_run_specs(
            self.product, project_id=self.project_id, project_context_revision_id=self.pcr
        )
        self.assertEqual(len(listing["specs"]), 1)
        entry = listing["specs"][0]
        self.assertEqual(entry["status"], "EXECUTABLE")
        self.assertIsNone(entry["diagnostic"])
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

    def test_response_lost_reimport_with_new_transport_key_is_idempotent(self) -> None:
        first = self._import(key="transport-response-lost-1")
        second = self._import(key="transport-response-lost-2")
        self.assertTrue(second["already_imported"])
        self.assertEqual(second["run_spec_id"], first["run_spec_id"])
        self.assertEqual(second["context_artifact_id"], first["context_artifact_id"])
        self.assertEqual(len(self._active_spec_refs()), 1)
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            for table in (
                "target_weight_vector_publication",
                "risk_policy_set_publication",
                "risk_application_receipt_publication",
                "risk_adjusted_weight_vector_publication",
            ):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1)
        finally:
            connection.close()

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


class ProjectBootstrapTests(_TargetCanonicalReuseCase):
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


class ImportNegativeTests(_TargetCanonicalReuseCase):
    def test_target_owner_absent_rejects_before_any_authority_registration(self) -> None:
        with tempfile.TemporaryDirectory() as external_source, tempfile.TemporaryDirectory() as empty_target:
            manifest, files, _ = _build_source_package(Path(external_source))
            target = ProductRuntime(Path(empty_target))
            created = create_project(target, display_name="无来源权威", idempotency_key="target")
            with self.assertRaisesRegex(
                TruthPreconditionFailedError, "SOURCE_AUTHORITY_NOT_VERIFIED"
            ):
                import_research_package(
                    target,
                    project_id=created["project_id"],
                    project_context_revision_id=created["project_context_revision_id"],
                    manifest_wire=manifest,
                    files_wire=files,
                    idempotency_key="absent-anchor",
                )
            connection = connect_catalog(target.database_path, read_only=True)
            try:
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM project WHERE project_id=?",
                        (manifest["source_project"]["project_id"],),
                    ).fetchone()
                )
                for table, id_column in (
                    ("target_weight_vector_publication", "target_weight_vector_id"),
                    ("risk_policy_set_publication", "risk_policy_set_version_id"),
                    ("risk_application_receipt_publication", "risk_application_receipt_id"),
                    ("risk_adjusted_weight_vector_publication", "risk_adjusted_weight_vector_id"),
                ):
                    identity = manifest["owner_publications"][table][id_column]
                    self.assertIsNone(
                        connection.execute(
                            f"SELECT 1 FROM {table} WHERE {id_column}=?", (identity,)
                        ).fetchone()
                    )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM artifact_reference WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE'",
                        (created["project_id"],),
                    ).fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_exact_target_owner_and_actual_bytes_match_accepts(self) -> None:
        outcome = self._import(key="target-owner-match")
        self.assertEqual(outcome["run_spec_id"], self.run_spec_id)
        self.assertFalse(outcome["already_imported"])

    def test_fully_self_consistent_forged_market_payload_is_rejected(self) -> None:
        manifest, files = _fully_consistent_market_forgery(self.manifest, self.files)
        with self.assertRaisesRegex(
            TruthPreconditionFailedError, "SOURCE_AUTHORITY_NOT_VERIFIED"
        ):
            self._import(manifest=manifest, files=files, key="forged-market")
        self.assertEqual(self._active_spec_refs(), [])

    def test_fully_self_consistent_forged_weight_chain_is_rejected(self) -> None:
        manifest, files = _fully_consistent_weight_forgery(self.manifest, self.files)
        with self.assertRaisesRegex(
            TruthPreconditionFailedError, "SOURCE_AUTHORITY_NOT_VERIFIED"
        ):
            self._import(manifest=manifest, files=files, key="forged-weights")
        self.assertEqual(self._active_spec_refs(), [])

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
        manifest["source_project"]["display_name"] = "合法更新后的来源项目"
        connection = connect_catalog(self.product.database_path)
        try:
            connection.execute(
                "UPDATE project SET display_name=? WHERE project_id=?",
                (
                    manifest["source_project"]["display_name"],
                    manifest["source_project"]["project_id"],
                ),
            )
            connection.commit()
        finally:
            connection.close()
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


class DiscoveryNegativeTests(_TargetCanonicalReuseCase):
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
            for field in (
                "run_spec_id",
                "content_sha256",
                "project_context_revision_id",
                "engine_version",
                "created_at",
                "execution_adapter_version_id",
            ):
                self.assertIsNone(listing["specs"][0][field], field)
            self.assertNotIn("btrs_sha256_unknown", json.dumps(listing))
        finally:
            target_file.write_bytes(original)

    def test_tampered_spec_degrades_through_request_router_as_valid_response(self) -> None:
        self._import()
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            artifact_id = str(connection.execute(
                "SELECT artifact_id FROM artifact_reference "
                "WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE'",
                (self.project_id,),
            ).fetchone()["artifact_id"])
        finally:
            connection.close()
        sha = artifact_id.removeprefix("art_sha256_")
        target_file = self.target_root / "artifacts" / "sha256" / sha[:2] / sha[2:4] / sha
        original = target_file.read_bytes()
        try:
            target_file.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))
            router = RequestRouter(build_product_ports(self.target_root).operation_handlers)
            request_id = mint_uuid7()
            body = {
                "request_id": request_id,
                "project_id": self.project_id,
                "project_context_revision_id": self.pcr,
                "expected_api_version": "1.0",
                "page": {"limit": 50},
            }
            response = router.route({
                "kind": "request",
                "request_id": request_id,
                "operation_id": "ProductEntryService.v1.listBacktestRunSpecs",
                "contract_version": "1.0",
                "project_id": self.project_id,
                "project_context_revision_id": self.pcr,
                "body": body,
            })
            self.assertEqual(response["status"], "OK", response)
            item = response["body"]["read_model"]["specs"][0]
            self.assertEqual(item["status"], "UNAVAILABLE")
            self.assertEqual(item["artifact_id"], artifact_id)
            self.assertTrue(item["diagnostic"])
            self.assertIsNone(item["run_spec_id"])
            self.assertIsNone(item["content_sha256"])
        finally:
            target_file.write_bytes(original)

    def test_executable_response_rejects_null_identity_metadata(self) -> None:
        request_id = mint_uuid7()
        invalid_item = {
            "run_spec_id": None,
            "artifact_id": "art_sha256_" + "a" * 64,
            "content_sha256": "b" * 64,
            "project_context_revision_id": "pcr_" + "A" * 26,
            "engine_version": "engine/1",
            "created_at": "2026-08-18T00:00:00Z",
            "execution_adapter_version_id": "adapter/1",
            "status": "EXECUTABLE",
            "diagnostic": None,
        }
        with self.assertRaises(ContractValidationError):
            ListBacktestRunSpecsResponseV1.from_mapping({
                "request_id": request_id,
                "truth_state": "FORMAL",
                "read_model": {
                    "read_model_version": "v3.product-entry/1.0",
                    "specs": [invalid_item],
                    "has_more": False,
                    "next_after_artifact_id": None,
                },
            })

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


class RunSpecPaginationTests(unittest.TestCase):
    @staticmethod
    def _collect_all(
        product: ProductRuntime, project_id: str, pcr: str
    ) -> tuple[list[str], list[str]]:
        artifact_ids: list[str] = []
        cursors: list[str] = []
        cursor = None
        while True:
            page = list_backtest_run_specs(
                product,
                project_id=project_id,
                project_context_revision_id=pcr,
                limit=50,
                after_artifact_id=cursor,
            )
            page_ids = [item["artifact_id"] for item in page["specs"]]
            artifact_ids.extend(page_ids)
            if not page["has_more"]:
                self_next = page["next_after_artifact_id"]
                if self_next is not None:
                    raise AssertionError("terminal page must not return a cursor")
                break
            next_cursor = page["next_after_artifact_id"]
            if next_cursor is None or next_cursor == cursor:
                raise AssertionError("pagination cursor did not advance")
            if not page_ids or next_cursor != page_ids[-1]:
                raise AssertionError("cursor must be the last returned artifact identity")
            cursors.append(next_cursor)
            cursor = next_cursor
        return artifact_ids, cursors

    @staticmethod
    def _release_to_count(
        product: ProductRuntime, project_id: str, count: int
    ) -> None:
        connection = connect_catalog(product.database_path)
        try:
            active_specs = connection.execute(
                "SELECT artifact_reference_id, artifact_id FROM artifact_reference "
                "WHERE owner_id=? AND role='RESEARCH_RUN_SPEC' AND state='ACTIVE' "
                "ORDER BY artifact_id",
                (project_id,),
            ).fetchall()
            for spec_ref in active_specs[count:]:
                spec_wire = json.loads(
                    product.read_verified_bytes(str(spec_ref["artifact_id"])).decode("utf-8")
                )
                run_spec_id = str(spec_wire["run_spec_id"])
                context_refs = connection.execute(
                    "SELECT artifact_reference_id, artifact_id FROM artifact_reference "
                    "WHERE owner_id=? AND role='RESEARCH_RUN_CONTEXT' AND state='ACTIVE'",
                    (project_id,),
                ).fetchall()
                for context_ref in context_refs:
                    context_wire = json.loads(
                        product.read_verified_bytes(str(context_ref["artifact_id"])).decode("utf-8")
                    )
                    if str(context_wire.get("run_spec_id")) == run_spec_id:
                        connection.execute(
                            "UPDATE artifact_reference SET state='RELEASED', released_at=? "
                            "WHERE artifact_reference_id=? AND state='ACTIVE'",
                            (
                                "2026-01-08T00:00:00Z",
                                str(context_ref["artifact_reference_id"]),
                            ),
                        )
                connection.execute(
                    "UPDATE artifact_reference SET state='RELEASED', released_at=? "
                    "WHERE artifact_reference_id=? AND state='ACTIVE'",
                    (
                        "2026-01-08T00:00:00Z",
                        str(spec_ref["artifact_reference_id"]),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def test_zero_one_fifty_fifty_one_101_and_251_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as storage:
            root = Path(storage)
            setup = build_product_golden_project(root)
            product = setup.product
            pcr = str(product.current_revision(setup.project_id)["project_context_revision_id"])
            base, _ = product.spec_codec.reconstruct(
                project_id=setup.project_id, run_spec_id=setup.run_spec_id
            )
            published_at = datetime(2026, 1, 5, 15, 31, tzinfo=timezone.utc)
            for ordinal in range(1, 251):
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
                product.spec_codec.persist(
                    spec=variant,
                    rule_profile=variant.rule_profile,
                    cost_policy=variant.cost_policy,
                    timing_profile=variant.execution_timing_profile,
                    project_id=setup.project_id,
                    project_context_revision_id=pcr,
                    published_at=published_at,
                )

            for expected_count in (251, 101, 51, 50, 1, 0):
                with self.subTest(run_specs=expected_count):
                    self._release_to_count(product, setup.project_id, expected_count)
                    artifact_ids, cursors = self._collect_all(
                        product, setup.project_id, pcr
                    )
                    self.assertEqual(len(artifact_ids), expected_count)
                    self.assertEqual(len(artifact_ids), len(set(artifact_ids)))
                    self.assertEqual(artifact_ids, sorted(artifact_ids))
                    self.assertEqual(len(cursors), max(0, (expected_count - 1) // 50))
                    restarted = ProductRuntime(root)
                    restarted_ids, restarted_cursors = self._collect_all(
                        restarted, setup.project_id, pcr
                    )
                    self.assertEqual(restarted_ids, artifact_ids)
                    self.assertEqual(restarted_cursors, cursors)
                    product = restarted

            with self.assertRaises(InvalidArgumentError):
                list_backtest_run_specs(
                    product,
                    project_id=setup.project_id,
                    project_context_revision_id=pcr,
                    after_artifact_id="btrs_sha256_" + "0" * 64,
                )


class PackageSchemaSanityTests(unittest.TestCase):
    def test_exported_manifest_is_the_frozen_schema_version(self) -> None:
        self.assertEqual(PACKAGE_SCHEMA_VERSION, "v3.research-package/1.0.0")


if __name__ == "__main__":
    unittest.main()
