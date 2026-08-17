"""Canonical Product Entry: clean-start projects + verified research packages.

This module owns the V1 Product Entry surface:

* projectless bootstrap (createProject / listProjects) as a narrow, versioned
  runtime control protocol - the backend canonical project owner mints every
  project/context identity in one atomic transaction; callers supply bounded
  display intent only;
* verified import of ``v3.research-package/1.0.0`` research packages: closed
  manifest parsing, actual-byte hashing, canonical identity and owner-binding
  verification, atomic all-or-nothing registration, and post-import
  reconstruction proof through the existing ``ResearchRunSpecCodec``;
* durable run-spec discovery from project-owned canonical artifact references.

Numeric financial truth is never authored here: imported owner rows keep their
immutable content-addressed identities and original project provenance, and
the only new artifacts minted by import are product binding records (the new
project's execution context) over already-verified bytes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v3_backend.adapters.artifact_store.filesystem import FileSystemArtifactStore
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.errors.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
    V3ContractError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode

from .product_runtime import (
    ADMITTED_EXECUTION_ADAPTER_VERSION_ID,
    BACKTEST_RUN_SPEC_ROLE,
    EXECUTION_CONTEXT_SCHEMA_VERSION,
    PRODUCT_EXECUTION_CONTEXT_ROLE,
    PRODUCT_RUNTIME_VERSION,
    PROJECT_SPEC_CONTEXT_REFERENCE_ROLE,
    PROJECT_SPEC_REFERENCE_ROLE,
    RESEARCH_RUN_CONTEXT_KIND,
    ProductArtifactBatch,
    ProductRuntime,
    _canonical_request_hash,
    mint_v3_id,
    wire_time,
)

PRODUCT_ENTRY_PROTOCOL_VERSION = "v3.product-entry/1.0.0"
PACKAGE_SCHEMA_VERSION = "v3.research-package/1.0.0"
CREATE_PROJECT_OPERATION = "ProductEntry.createProject"
IMPORT_OPERATION = "ProductEntryService.v1.importResearchPackage"

MAX_DISPLAY_NAME_LENGTH = 200
MAX_NOTES_LENGTH = 2048
MAX_PROJECT_PAGE_SIZE = 100
MAX_PACKAGE_TOTAL_BYTES = 786_432

# Closed set of durable owner tables carried by a research package.  The rows
# are transferred verbatim and re-verified against the actual payload bytes
# before registration; identities are immutable and stay bound to their
# original source project (numeric truth provenance is never rewritten).
PACKAGE_OWNER_TABLES = (
    "target_weight_vector_publication",
    "risk_policy_set_publication",
    "risk_application_receipt_publication",
    "risk_adjusted_weight_vector_publication",
)
_OWNER_ID_COLUMN = {
    "target_weight_vector_publication": "target_weight_vector_id",
    "risk_policy_set_publication": "risk_policy_set_version_id",
    "risk_application_receipt_publication": "risk_application_receipt_id",
    "risk_adjusted_weight_vector_publication": "risk_adjusted_weight_vector_id",
}
_OWNER_ID_PREFIX = {
    "target_weight_vector_publication": ("target_weight_vector_id", "twv_sha256_"),
    "risk_policy_set_publication": ("risk_policy_set_version_id", "rpsv_sha256_"),
    "risk_application_receipt_publication": ("risk_application_receipt_id", "rar_sha256_"),
    "risk_adjusted_weight_vector_publication": ("risk_adjusted_weight_vector_id", "rawv_sha256_"),
}
_PAYLOAD_ROLES = {
    "target_weight_vector_publication": "TARGET_WEIGHT_VECTOR",
    "risk_policy_set_publication": "RISK_POLICY_SET",
    "risk_application_receipt_publication": "RISK_APPLICATION_RECEIPT",
    "risk_adjusted_weight_vector_publication": "RISK_ADJUSTED_WEIGHT_VECTOR",
}
_PACKAGE_FILE_PATTERN_PREFIXES = ("spec", "context", "target", "policy", "receipt", "adjusted")

_MANIFEST_KEYS = {
    "schema_version",
    "source_product_runtime_version",
    "source_project",
    "source_project_context_revision",
    "run_spec_id",
    "run_spec_artifact",
    "execution_context_artifact",
    "artifacts",
    "artifact_references",
    "owner_publications",
}
_DESCRIPTOR_KEYS = {"name", "artifact_id", "sha256", "byte_size"}
_OWNER_PUBLICATIONS_KEYS = set(PACKAGE_OWNER_TABLES)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_text(value: Any, name: str, *, max_length: int = 400) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise InvalidArgumentError(f"{name} must be a bounded non-empty string")
    return value


def _require_hex64(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise InvalidArgumentError(f"{name} must be a lowercase 64-hex digest")
    return value


def _require_package_path(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or not value.isascii():
        raise InvalidArgumentError(f"{name} must be a bounded ASCII package file name")
    if "/" in value or "\\" in value or value.startswith("."):
        raise InvalidArgumentError(f"{name} must be a relative single-segment package file name")
    if not any(value.startswith(prefix + ".") for prefix in _PACKAGE_FILE_PATTERN_PREFIXES):
        raise InvalidArgumentError(f"{name} is not an admitted package payload name")
    return value


def _owner_context_identity(project_id: str, pcr: str, canonical_hash: str) -> str:
    return canonical_sha256(
        {
            "project_id": project_id,
            "project_context_revision_id": pcr,
            "project_context_canonical_hash": canonical_hash,
        }
    )


# ---------------------------------------------------------------------------
# Project bootstrap (projectless control protocol handlers)
# ---------------------------------------------------------------------------


def create_project(
    product: ProductRuntime,
    *,
    display_name: Any,
    notes: Any = None,
    idempotency_key: Any,
) -> dict[str, Any]:
    """Create the first canonical project through the durable project owner.

    All canonical identities (project + first ProjectContextRevision) are
    minted by the backend in one atomic transaction; the caller supplies only
    bounded non-financial display intent.
    """
    name = _require_text(display_name, "display_name", max_length=MAX_DISPLAY_NAME_LENGTH)
    if notes is not None:
        if not isinstance(notes, str) or len(notes) > MAX_NOTES_LENGTH:
            raise InvalidArgumentError("notes must be a bounded string")
    key = _require_text(idempotency_key, "idempotency_key", max_length=200)
    intent = {"display_name": name, "notes": notes}
    request_hash = _canonical_request_hash(CREATE_PROJECT_OPERATION, intent)
    scope_key = f"{CREATE_PROJECT_OPERATION}|__product_entry__|{key}"

    context: dict[str, Any] = {}
    if notes:
        context["context_fields"] = {"notes": notes}
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    connection = connect_catalog(product.database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT canonical_request_hash, outcome_json FROM idempotency_record WHERE scope_key=?",
            (scope_key,),
        ).fetchone()
        if existing is not None:
            if str(existing["canonical_request_hash"]) != request_hash:
                raise IdempotencyConflictError(
                    "idempotency_key reuse with a different canonical create intent"
                )
            connection.execute("ROLLBACK")
            return json.loads(str(existing["outcome_json"]))
        now = wire_time(_utcnow())
        project_id = mint_v3_id("prj_")
        project_context_revision_id = mint_v3_id("pcr_")
        connection.execute(
            "INSERT INTO project(project_id, display_name, created_at, state) VALUES(?,?,?,'ACTIVE')",
            (project_id, name, now),
        )
        connection.execute(
            """
            INSERT INTO project_context_revision(
                project_context_revision_id, project_id, revision_no, parent_revision_id,
                context_json, canonical_hash, created_by, created_at
            ) VALUES(?,?,1,NULL,?,?,?,?)
            """,
            (
                project_context_revision_id,
                project_id,
                context_json,
                canonical_sha256(context_json),
                "product-entry",
                now,
            ),
        )
        outcome = {
            "project_id": project_id,
            "project_context_revision_id": project_context_revision_id,
            "display_name": name,
            "created_at": now,
        }
        connection.execute(
            """
            INSERT INTO idempotency_record(
                scope_key, operation_id, project_id, canonical_request_hash,
                outcome_kind, outcome_json, created_at, expires_at
            ) VALUES(?,?,?,?,?,?,?,NULL)
            """,
            (
                scope_key,
                CREATE_PROJECT_OPERATION,
                project_id,
                request_hash,
                "RESPONSE",
                json.dumps(outcome, separators=(",", ":"), sort_keys=True),
                now,
            ),
        )
        connection.execute("COMMIT")
        return outcome
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        connection.close()


def list_projects(
    product: ProductRuntime,
    *,
    limit: Any = 50,
    after_project_id: Any = None,
) -> dict[str, Any]:
    """Durable, stable-ordered project discovery over the canonical catalog."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_PROJECT_PAGE_SIZE:
        raise InvalidArgumentError(f"limit must be an integer in [1, {MAX_PROJECT_PAGE_SIZE}]")
    if after_project_id is not None and (
        not isinstance(after_project_id, str) or not after_project_id
    ):
        raise InvalidArgumentError("after_project_id must be a non-empty string when present")
    connection = connect_catalog(product.database_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT project.project_id AS project_id,
                   project.display_name AS display_name,
                   project.created_at AS created_at,
                   (SELECT project_context_revision_id FROM project_context_revision r
                     WHERE r.project_id = project.project_id
                     ORDER BY revision_no DESC LIMIT 1) AS project_context_revision_id
            FROM project
            WHERE project.state='ACTIVE'
              AND (? IS NULL OR project.project_id > ?)
            ORDER BY project.project_id
            LIMIT ?
            """,
            (after_project_id, after_project_id, limit + 1),
        ).fetchall()
    finally:
        connection.close()
    has_more = len(rows) > limit
    projects = [
        {
            "project_id": str(row["project_id"]),
            "project_context_revision_id": str(row["project_context_revision_id"]),
            "display_name": str(row["display_name"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows[:limit]
        if row["project_context_revision_id"] is not None
    ]
    return {"projects": projects, "has_more": has_more}


# ---------------------------------------------------------------------------
# Research package manifest codec
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PackageFile:
    path: str
    sha256: str
    byte_size: int
    payload: bytes


def _parse_descriptor(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DESCRIPTOR_KEYS:
        raise InvalidArgumentError(f"{name} must be a closed artifact descriptor")
    path = _require_package_path(value["name"], f"{name}.name")
    artifact_id = _require_text(value["artifact_id"], f"{name}.artifact_id", max_length=100)
    if not artifact_id.startswith("art_sha256_"):
        raise InvalidArgumentError(f"{name}.artifact_id must be content-addressed")
    sha256 = _require_hex64(value["sha256"], f"{name}.sha256")
    if artifact_id != "art_sha256_" + sha256:
        raise InvalidArgumentError(f"{name}.artifact_id does not match its declared digest")
    byte_size = value["byte_size"]
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 1 or byte_size > 262_144:
        raise InvalidArgumentError(f"{name}.byte_size must be an integer in [1, 262144]")
    return {
        "name": path,
        "artifact_id": artifact_id,
        "sha256": sha256,
        "byte_size": byte_size,
    }


def parse_package_manifest(wire: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly parse and shape-check the closed research package manifest."""
    if not isinstance(wire, Mapping):
        raise InvalidArgumentError("package manifest must be an object")
    if set(wire) != _MANIFEST_KEYS:
        unknown = sorted(set(wire) - _MANIFEST_KEYS)
        missing = sorted(_MANIFEST_KEYS - set(wire))
        raise InvalidArgumentError(
            f"package manifest shape mismatch (unknown={unknown}, missing={missing})"
        )
    if wire["schema_version"] != PACKAGE_SCHEMA_VERSION:
        raise InvalidArgumentError(
            f"unsupported research package schema version: {wire['schema_version']!r}"
        )
    _require_text(wire["source_product_runtime_version"], "source_product_runtime_version")
    source_project = wire["source_project"]
    if not isinstance(source_project, Mapping) or not {
        "project_id",
        "display_name",
        "created_at",
        "state",
    } <= set(source_project):
        raise InvalidArgumentError("source_project must carry the canonical project record fields")
    if not str(source_project["project_id"]).startswith("prj_"):
        raise InvalidArgumentError("source project identity is not canonical")
    if source_project["state"] != "ACTIVE":
        raise InvalidArgumentError("source project must be ACTIVE at export time")
    revision = wire["source_project_context_revision"]
    if not isinstance(revision, Mapping) or not {
        "project_context_revision_id",
        "project_id",
        "revision_no",
        "parent_revision_id",
        "context_json",
        "canonical_hash",
        "created_by",
        "created_at",
    } <= set(revision):
        raise InvalidArgumentError(
            "source_project_context_revision must carry the canonical revision record fields"
        )
    if revision["project_id"] != source_project["project_id"]:
        raise InvalidArgumentError("source revision does not belong to the source project")
    _require_hex64(revision["canonical_hash"], "source_project_context_revision.canonical_hash")
    run_spec_id = _require_text(wire["run_spec_id"], "run_spec_id", max_length=100)
    if not run_spec_id.startswith("btrs_sha256_"):
        raise InvalidArgumentError("run_spec_id must be a canonical btrs_sha256_ identity")

    artifacts = wire["artifacts"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64:
        raise InvalidArgumentError("artifacts must be a bounded non-empty array")
    parsed_artifacts: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, Mapping) or set(item) != {"row", "name"}:
            raise InvalidArgumentError("each artifact entry must be {row, path}")
        if not isinstance(item["row"], Mapping):
            raise InvalidArgumentError("artifact row must be an object")
        row = dict(item["row"])
        byte_size = row.get("byte_size")
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0 or byte_size > 262_144:
            raise InvalidArgumentError("artifact row byte_size must be bounded")
        if byte_size > 0:
            path = _require_package_path(item["name"], "artifacts.name")
        else:
            # Catalog-only record (e.g. an external-boundary membership stub):
            # the source storage itself carries no payload bytes for it.
            if item["name"] is not None:
                raise InvalidArgumentError(
                    "catalog-only artifact entries must not declare a payload path"
                )
            path = None
        parsed_artifacts.append({"row": row, "name": path})
    references = wire["artifact_references"]
    if not isinstance(references, list):
        raise InvalidArgumentError("artifact_references must be an array")
    parsed_references: list[dict[str, Any]] = []
    for item in references:
        if not isinstance(item, Mapping):
            raise InvalidArgumentError("artifact reference row must be an object")
        parsed_references.append(dict(item))
    publications = wire["owner_publications"]
    if not isinstance(publications, Mapping) or set(publications) != _OWNER_PUBLICATIONS_KEYS:
        raise InvalidArgumentError("owner_publications must carry exactly the four canonical owner rows")
    parsed_publications = {table: dict(publications[table]) for table in PACKAGE_OWNER_TABLES}
    return {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "source_product_runtime_version": wire["source_product_runtime_version"],
        "source_project": dict(source_project),
        "source_project_context_revision": dict(revision),
        "run_spec_id": run_spec_id,
        "run_spec_artifact": _parse_descriptor(wire["run_spec_artifact"], "run_spec_artifact"),
        "execution_context_artifact": _parse_descriptor(
            wire["execution_context_artifact"], "execution_context_artifact"
        ),
        "artifacts": parsed_artifacts,
        "artifact_references": parsed_references,
        "owner_publications": parsed_publications,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _decode_files(files_wire: Any) -> dict[str, PackageFile]:
    if not isinstance(files_wire, list) or not 1 <= len(files_wire) <= 64:
        raise InvalidArgumentError("files must be a bounded non-empty array")
    decoded: dict[str, PackageFile] = {}
    total = 0
    for item in files_wire:
        if not isinstance(item, Mapping) or set(item) != {"name", "sha256", "byte_size", "payload_base64"}:
            raise InvalidArgumentError("each package file must be a closed {path, sha256, byte_size, payload_base64}")
        path = _require_package_path(item["name"], "files.name")
        if path in decoded:
            raise InvalidArgumentError(f"duplicate package file: {path}")
        declared_sha = _require_hex64(item["sha256"], "files.sha256")
        byte_size = item["byte_size"]
        if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 1 or byte_size > 262_144:
            raise InvalidArgumentError("files.byte_size must be an integer in [1, 262144]")
        encoded = item["payload_base64"]
        if not isinstance(encoded, str) or len(encoded) > 349_526:
            raise InvalidArgumentError("files.payload_base64 exceeds the bounded transfer size")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidArgumentError(f"package file {path} is not valid base64") from exc
        if len(payload) != byte_size:
            raise InvalidArgumentError(f"package file {path} byte_size does not match its payload")
        actual_sha = hashlib.sha256(payload).hexdigest()
        if actual_sha != declared_sha:
            raise InvalidArgumentError(f"package file {path} declared hash does not match actual bytes")
        total += byte_size
        if total > MAX_PACKAGE_TOTAL_BYTES:
            raise InvalidArgumentError("research package exceeds the bounded total transfer size")
        decoded[path] = PackageFile(path, actual_sha, byte_size, payload)
    return decoded


def _require_table_columns(connection: sqlite3.Connection, table: str, row: Mapping[str, Any]) -> None:
    columns = {
        str(item[1])
        for item in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    if not columns:
        raise V3ContractError(f"unknown catalog table for import: {table}")
    if set(row) != columns:
        raise InvalidArgumentError(
            f"imported {table} row does not match the catalog schema shape"
        )


def _insert_verbatim_row(
    connection: sqlite3.Connection, *, table: str, row: Mapping[str, Any], id_column: str
) -> None:
    _require_table_columns(connection, table, row)
    identity = row[id_column]
    existing = connection.execute(
        f'SELECT * FROM "{table}" WHERE "{id_column}"=?', (identity,)
    ).fetchone()
    if existing is not None:
        existing_row = {key: existing[key] for key in existing.keys()}
        if existing_row != dict(row):
            raise ConflictError(f"imported {table} row conflicts with an existing record: {identity}")
        return
    names = ", ".join(f'"{name}"' for name in row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f'INSERT INTO "{table}"({names}) VALUES({placeholders})', tuple(row.values())
    )


def import_research_package(
    product: ProductRuntime,
    *,
    project_id: str,
    project_context_revision_id: str,
    manifest_wire: Mapping[str, Any],
    files_wire: Any,
    idempotency_key: str,
) -> dict[str, Any]:
    """Verify and atomically import a canonical research package.

    Whole-package verification precedes any registration: every payload byte is
    hashed, every canonical identity is recomputed, and every owner binding is
    re-derived.  Registration is a single all-or-nothing transaction; a failed
    import leaves no active run-spec reference behind.
    """
    _require_text(idempotency_key, "idempotency_key", max_length=200)
    manifest = parse_package_manifest(manifest_wire)
    files = _decode_files(files_wire)
    _verify_closed_file_set(manifest, files)

    # Target project must own this exact context revision.
    product.require_project_context_ownership(project_id, project_context_revision_id)
    source_project_id = str(manifest["source_project"]["project_id"])
    if source_project_id == project_id:
        raise InvalidArgumentError(
            "a research package cannot be imported into its own source project identity"
        )

    # --- actual-byte verification of every declared payload -----------------
    spec_file = files[manifest["run_spec_artifact"]["name"]]
    context_file = files[manifest["execution_context_artifact"]["name"]]
    _require_descriptor_matches(manifest["run_spec_artifact"], spec_file, "run_spec_artifact")
    _require_descriptor_matches(
        manifest["execution_context_artifact"], context_file, "execution_context_artifact"
    )
    spec_wire = _parse_canonical_json(spec_file.payload, "run spec")
    context_wire = _parse_canonical_json(context_file.payload, "execution context")
    _verify_spec_wire(spec_wire, manifest)
    _verify_context_wire(context_wire, manifest, spec_wire)

    owner_payloads: dict[str, PackageFile] = {}
    for table in PACKAGE_OWNER_TABLES:
        row = manifest["owner_publications"][table]
        artifact_id = str(row["artifact_id"])
        descriptor = _find_artifact_entry(manifest, artifact_id, table)
        payload_file = files[descriptor["name"]]
        _require_descriptor_matches(descriptor, payload_file, table)
        owner_payloads[table] = payload_file

    _verify_owner_rows(manifest, files)

    semantic_request = {
        "manifest_sha256": canonical_sha256(_manifest_freeze(manifest_wire)),
        "file_sha256s": sorted(file.sha256 for file in files.values()),
        "project_id": project_id,
        "project_context_revision_id": project_context_revision_id,
    }
    scope_key = f"{IMPORT_OPERATION}|{project_id}|{idempotency_key}"
    request_hash = _canonical_request_hash(IMPORT_OPERATION, semantic_request)

    existing = _lookup_idempotency(product, scope_key, request_hash)
    if existing is not None:
        replay = dict(existing)
        replay["already_imported"] = True
        return replay

    # Package-level idempotency (task section 7B): re-importing the SAME
    # verified package into the same project must be idempotent and return a
    # stable RunSpec identity even with a fresh transport idempotency key.
    spec_artifact_id = artifact_id_for_bytes(spec_file.payload)
    already = _lookup_existing_import(
        product, project_id, str(manifest["run_spec_id"]), spec_artifact_id
    )
    if already is not None:
        return {
            "run_spec_id": str(manifest["run_spec_id"]),
            "run_spec_artifact_id": spec_artifact_id,
            "context_artifact_id": already,
            "already_imported": True,
            "source_project_id": source_project_id,
            "imported_at": wire_time(_utcnow()),
        }

    # --- atomic registration ------------------------------------------------
    imported_at = _utcnow()
    new_context_payload = _build_bound_context_payload(
        context_wire, project_id, project_context_revision_id, imported_at
    )
    source_project = manifest["source_project"]
    source_revision = manifest["source_project_context_revision"]

    # Stage all bytes up front: weight payloads through the baseline-policy
    # store (their owner roles), spec/context through the product store.
    weight_store = FileSystemArtifactStore(product.artifact_root)
    weight_plans = tuple(
        (
            "prv_imported_owner_payload_" + owner_payloads[table].sha256,
            owner_payloads[table].payload,
            _PAYLOAD_ROLES[table],
            str(manifest["owner_publications"][table]["schema_version"]),
        )
        for table in PACKAGE_OWNER_TABLES
    )
    spec_plan = (
        "prv_imported_run_spec_" + spec_file.sha256,
        spec_file.payload,
        BACKTEST_RUN_SPEC_ROLE,
        str(spec_wire["schema_version"]),
    )
    new_context_plan = (
        "prv_product_execution_context_" + manifest["run_spec_id"],
        new_context_payload,
        PRODUCT_EXECUTION_CONTEXT_ROLE,
        EXECUTION_CONTEXT_SCHEMA_VERSION,
    )
    batch = _SplitStoreBatch(
        product_store=product.artifact_store,
        weight_store=weight_store,
        product_payloads=(spec_plan, new_context_plan),
        weight_payloads=weight_plans,
        published_at=imported_at,
    )

    connection = connect_catalog(product.database_path)
    uow = SQLiteUnitOfWork(connection, TransactionMode.PUBLISH, publish_callbacks=batch)
    try:
        uow.begin()
        _insert_verbatim_row(
            connection,
            table="project",
            row=source_project,
            id_column="project_id",
        )
        _insert_verbatim_row(
            connection,
            table="project_context_revision",
            row=_revision_row_with_append_fields(source_revision),
            id_column="project_context_revision_id",
        )
        for entry in manifest["artifacts"]:
            _insert_verbatim_row(
                connection, table="artifact", row=entry["row"], id_column="artifact_id"
            )
        for reference in manifest["artifact_references"]:
            _insert_verbatim_row(
                connection,
                table="artifact_reference",
                row=reference,
                id_column="artifact_reference_id",
            )
        for table in (
            "target_weight_vector_publication",
            "risk_policy_set_publication",
            "risk_application_receipt_publication",
            "risk_adjusted_weight_vector_publication",
        ):
            _insert_verbatim_row(
                connection,
                table=table,
                row=manifest["owner_publications"][table],
                id_column=_OWNER_ID_COLUMN[table],
            )
        # New project-owned canonical references: immutable spec bytes plus a
        # freshly bound execution context for THIS project's current revision.
        # Catalog registration goes through the canonical publication port so
        # the new context artifact receives its descriptor row and both
        # references are bound by the standard publication path.
        from v3_backend.adapters.sqlite.artifact_publication import SQLiteArtifactPublicationPort
        from v3_backend.domain.artifacts.model import ArtifactReference
        from v3_backend.domain.artifacts.publication import ArtifactPublication

        port = SQLiteArtifactPublicationPort(uow)
        now = wire_time(imported_at)
        port.publish(
            ArtifactPublication(
                descriptor=batch.spec_result.descriptor,
                active_references=(
                    ArtifactReference(
                        reference_id=mint_v3_id("arf_"),
                        owner_id=project_id,
                        artifact_id=batch.spec_result.descriptor.artifact_id,
                        role=PROJECT_SPEC_REFERENCE_ROLE,
                        created_at=imported_at,
                        state="ACTIVE",
                    ),
                ),
            )
        )
        port.publish(
            ArtifactPublication(
                descriptor=batch.context_result.descriptor,
                active_references=(
                    ArtifactReference(
                        reference_id=mint_v3_id("arf_"),
                        owner_id=project_id,
                        artifact_id=batch.context_result.descriptor.artifact_id,
                        role=PROJECT_SPEC_CONTEXT_REFERENCE_ROLE,
                        created_at=imported_at,
                        state="ACTIVE",
                    ),
                ),
            )
        )
        _verify_imported_closure(connection, manifest, project_id)
        outcome = {
            "run_spec_id": manifest["run_spec_id"],
            "run_spec_artifact_id": batch.spec_result.descriptor.artifact_id,
            "context_artifact_id": batch.context_result.descriptor.artifact_id,
            "already_imported": False,
            "source_project_id": source_project_id,
            "imported_at": now,
        }
        connection.execute(
            """
            INSERT INTO idempotency_record(
                scope_key, operation_id, project_id, canonical_request_hash,
                outcome_kind, outcome_json, created_at, expires_at
            ) VALUES(?,?,?,?,?,?,?,NULL)
            """,
            (
                scope_key,
                IMPORT_OPERATION,
                project_id,
                request_hash,
                "RESPONSE",
                json.dumps(outcome, separators=(",", ":"), sort_keys=True),
                now,
            ),
        )
        uow.commit()
    finally:
        if uow.active:
            uow.rollback()
        connection.close()

    # Post-commit canonical proof: the imported spec must reconstruct through
    # the exact same codec used by submission, with exact identity equality.
    spec, context_artifact_id = product.spec_codec.reconstruct(
        project_id=project_id, run_spec_id=manifest["run_spec_id"]
    )
    if spec.run_spec_id != manifest["run_spec_id"] or context_artifact_id != outcome["context_artifact_id"]:
        raise TruthPreconditionFailedError("imported run spec failed the post-commit reconstruction proof")
    return outcome


class _SplitStoreBatch:
    """PUBLISH UoW callbacks that stage one batch across two stores.

    Owner weight payloads are admitted by the baseline artifact policy; the
    product spec/context artifacts by the product publication policy.  Both
    stores share the same content-addressed artifact root, so registration is
    still one logical batch with one compensating cleanup.
    """

    def __init__(
        self,
        *,
        product_store: FileSystemArtifactStore,
        weight_store: FileSystemArtifactStore,
        product_payloads: tuple[tuple[str, bytes, str, str], ...],
        weight_payloads: tuple[tuple[str, bytes, str, str], ...],
        published_at: datetime,
    ) -> None:
        self._batches = (
            ProductArtifactBatch(store=product_store, payloads=product_payloads, published_at=published_at),
            ProductArtifactBatch(store=weight_store, payloads=weight_payloads, published_at=published_at),
        )
        self.spec_result: Any = None
        self.context_result: Any = None

    def verify_staged(self) -> None:
        for batch in self._batches:
            batch.verify_staged()

    def publish_staged(self) -> None:
        product_batch = self._batches[0]
        product_batch.publish_staged()
        self.spec_result = product_batch.results[0]
        self.context_result = product_batch.results[1]
        self._batches[1].publish_staged()

    def compensate_unreferenced_staging(self) -> None:
        for batch in self._batches:
            batch.compensate_unreferenced_staging()

    def notify_committed(self) -> None:
        for batch in self._batches:
            batch.notify_committed()


def _revision_row_with_append_fields(revision: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(revision)
    if "revision_no" not in row or "parent_revision_id" not in row:
        raise InvalidArgumentError("source revision record is missing append-only fields")
    return row


def _lookup_existing_import(
    product: ProductRuntime, project_id: str, run_spec_id: str, spec_artifact_id: str
) -> str | None:
    """Return the bound context artifact id when this project already owns the
    exact spec artifact (same content-addressed identity) - i.e. the package
    was imported before.  The spec reference alone is not proof: discovery and
    submit both require the matching execution-context reference.
    """
    connection = connect_catalog(product.database_path, read_only=True)
    try:
        row = connection.execute(
            """
            SELECT 1 FROM artifact_reference
            WHERE owner_id=? AND role=? AND artifact_id=? AND state='ACTIVE'
            """,
            (project_id, PROJECT_SPEC_REFERENCE_ROLE, spec_artifact_id),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    try:
        _, context_artifact_id = product.spec_codec.reconstruct(
            project_id=project_id, run_spec_id=run_spec_id
        )
    except Exception:
        return None
    return context_artifact_id


def _lookup_idempotency(
    product: ProductRuntime, scope_key: str, request_hash: str
) -> dict[str, Any] | None:
    connection = connect_catalog(product.database_path, read_only=True)
    try:
        row = connection.execute(
            "SELECT canonical_request_hash, outcome_json FROM idempotency_record WHERE scope_key=?",
            (scope_key,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    if str(row["canonical_request_hash"]) != request_hash:
        raise IdempotencyConflictError(
            "idempotency_key reuse with a different canonical import request"
        )
    return json.loads(str(row["outcome_json"]))


def _verify_closed_file_set(manifest: Mapping[str, Any], files: Mapping[str, PackageFile]) -> None:
    expected: set[str] = {
        manifest["run_spec_artifact"]["name"],
        manifest["execution_context_artifact"]["name"],
    }
    for entry in manifest["artifacts"]:
        if entry["name"] is not None:
            expected.add(str(entry["name"]))
    if set(files) != expected:
        missing = sorted(expected - set(files))
        extra = sorted(set(files) - expected)
        raise InvalidArgumentError(
            f"package file set does not match the manifest (missing={missing}, extra={extra})"
        )


def _find_artifact_entry(manifest: Mapping[str, Any], artifact_id: str, table: str) -> dict[str, Any]:
    for entry in manifest["artifacts"]:
        if str(entry["row"].get("artifact_id")) == artifact_id:
            if entry["name"] is None:
                raise InvalidArgumentError(
                    f"{table} payload artifact has no package payload file: {artifact_id}"
                )
            return {
                "name": str(entry["name"]),
                "artifact_id": artifact_id,
                "sha256": str(entry["row"]["sha256"]),
                "byte_size": int(entry["row"]["byte_size"]),
            }
    raise InvalidArgumentError(f"package manifest lacks the artifact row required by {table}: {artifact_id}")


def _require_descriptor_matches(descriptor: Mapping[str, Any], file: PackageFile, name: str) -> None:
    if descriptor["sha256"] != file.sha256 or descriptor["byte_size"] != file.byte_size:
        raise InvalidArgumentError(f"{name} descriptor does not match the actual payload bytes")
    if descriptor["artifact_id"] != artifact_id_for_bytes(file.payload):
        raise InvalidArgumentError(f"{name} artifact identity does not match the actual payload bytes")


def _parse_canonical_json(payload: bytes, name: str) -> dict[str, Any]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidArgumentError(f"{name} payload is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidArgumentError(f"{name} payload must be a JSON object")
    if canonical_json_bytes(parsed) != payload:
        raise InvalidArgumentError(f"{name} payload bytes are not canonical JSON")
    return parsed


def _verify_spec_wire(spec_wire: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    run_spec_id = str(spec_wire.get("run_spec_id", ""))
    if run_spec_id != manifest["run_spec_id"]:
        raise InvalidArgumentError("run spec payload identity does not match the manifest")
    if not run_spec_id.startswith("btrs_sha256_"):
        raise InvalidArgumentError("run spec identity is not canonical")
    if run_spec_id.removeprefix("btrs_sha256_") != str(spec_wire.get("content_sha256")):
        raise InvalidArgumentError("run spec content digest does not match its identity")
    schedule = spec_wire.get("schedule")
    if not isinstance(schedule, list) or not schedule:
        raise InvalidArgumentError("run spec carries no weight schedule")
    adjusted_id = str(schedule[0].get("risk_adjusted_weight_vector_id"))
    if adjusted_id != str(
        manifest["owner_publications"]["risk_adjusted_weight_vector_publication"]["risk_adjusted_weight_vector_id"]
    ):
        raise InvalidArgumentError("run spec schedule does not reference the packaged weight owner")


def _verify_context_wire(
    context_wire: Mapping[str, Any], manifest: Mapping[str, Any], spec_wire: Mapping[str, Any]
) -> None:
    if context_wire.get("context_kind") != RESEARCH_RUN_CONTEXT_KIND:
        raise InvalidArgumentError("execution context payload is not a research run context")
    if str(context_wire.get("run_spec_id")) != manifest["run_spec_id"]:
        raise InvalidArgumentError("execution context does not bind the packaged run spec")
    if str(context_wire.get("run_spec_content_sha256")) != str(spec_wire.get("content_sha256")):
        raise InvalidArgumentError("execution context and run spec content identity diverge")
    if str(context_wire.get("project_id")) != str(manifest["source_project"]["project_id"]):
        raise InvalidArgumentError("execution context provenance does not match the source project")
    for section in ("rule_profile", "cost_policy", "execution_timing_profile"):
        if not isinstance(context_wire.get(section), Mapping):
            raise InvalidArgumentError(f"execution context lacks the {section} section")


def _verify_owner_rows(manifest: Mapping[str, Any], files: Mapping[str, PackageFile]) -> None:
    source_project_id = str(manifest["source_project"]["project_id"])
    source_revision = manifest["source_project_context_revision"]
    for pinned in ("connector_version_id", "snapshot_id", "universe_version_id"):
        if source_revision.get(pinned) is not None:
            raise InvalidArgumentError(
                "research packages carrying pinned connector/snapshot/universe revisions are "
                "outside the V1 import closure"
            )
    source_pcr = str(source_revision["project_context_revision_id"])
    expected_context_identity = _owner_context_identity(
        source_project_id, source_pcr, str(source_revision["canonical_hash"])
    )
    artifact_ids = {str(entry["row"].get("artifact_id")) for entry in manifest["artifacts"]}
    reference_ids = {
        str(row.get("artifact_reference_id")) for row in manifest["artifact_references"]
    }
    for table in PACKAGE_OWNER_TABLES:
        row = manifest["owner_publications"][table]
        id_column, id_prefix = _OWNER_ID_PREFIX[table]
        identity = str(row.get(id_column, ""))
        if not identity.startswith(id_prefix):
            raise InvalidArgumentError(f"{table} identity is not canonical")
        content_sha = str(row.get("content_sha256", ""))
        _require_hex64(content_sha, f"{table}.content_sha256")
        if identity[len(id_prefix):] != content_sha:
            raise InvalidArgumentError(f"{table} identity does not embed its content digest")
        if str(row.get("project_id")) != source_project_id or str(
            row.get("project_context_revision_id")
        ) != source_pcr:
            raise InvalidArgumentError(f"{table} provenance does not match the source project context")
        if str(row.get("context_identity")) != expected_context_identity:
            raise InvalidArgumentError(f"{table} context identity cannot be re-derived from the package")
        if str(row.get("artifact_id")) not in artifact_ids:
            raise InvalidArgumentError(f"{table} references an artifact absent from the package")
        if str(row.get("artifact_reference_id")) not in reference_ids:
            raise InvalidArgumentError(f"{table} references an artifact reference absent from the package")
    receipt = manifest["owner_publications"]["risk_application_receipt_publication"]
    adjusted = manifest["owner_publications"]["risk_adjusted_weight_vector_publication"]
    target = manifest["owner_publications"]["target_weight_vector_publication"]
    policy = manifest["owner_publications"]["risk_policy_set_publication"]
    target_id = str(target[_OWNER_ID_COLUMN["target_weight_vector_publication"]])
    policy_id = str(policy[_OWNER_ID_COLUMN["risk_policy_set_publication"]])
    receipt_id = str(receipt[_OWNER_ID_COLUMN["risk_application_receipt_publication"]])
    if str(receipt["source_target_weight_vector_id"]) != target_id:
        raise InvalidArgumentError("receipt does not bind the packaged target weight owner")
    if str(receipt["risk_policy_set_version_id"]) != policy_id:
        raise InvalidArgumentError("receipt does not bind the packaged risk policy owner")
    if str(adjusted["source_target_weight_vector_id"]) != target_id:
        raise InvalidArgumentError("adjusted vector does not bind the packaged target weight owner")
    if str(adjusted["risk_application_receipt_id"]) != receipt_id:
        raise InvalidArgumentError("adjusted vector does not bind the packaged receipt owner")
    for reference in manifest["artifact_references"]:
        if str(reference.get("state")) != "ACTIVE":
            raise InvalidArgumentError("imported artifact references must be ACTIVE")
        if str(reference.get("artifact_id")) not in artifact_ids:
            raise InvalidArgumentError("artifact reference points outside the package closure")
    for entry in manifest["artifacts"]:
        row = entry["row"]
        if str(row.get("state")) != "PUBLISHED":
            raise InvalidArgumentError("imported artifacts must be PUBLISHED")
        if str(row.get("artifact_id")) != "art_sha256_" + str(row.get("sha256")):
            raise InvalidArgumentError("imported artifact identity does not match its digest")
        if entry["name"] is None:
            continue  # catalog-only record: no payload bytes exist at the source
        file = files[str(entry["name"])]
        if str(row.get("sha256")) != file.sha256 or int(row.get("byte_size", -1)) != file.byte_size:
            raise InvalidArgumentError("imported artifact row does not match the actual payload bytes")


def _verify_imported_closure(
    connection: sqlite3.Connection, manifest: Mapping[str, Any], target_project_id: str
) -> None:
    """Re-verify the imported owner chain against the just-inserted rows."""
    adjusted_id = _OWNER_ID_COLUMN["risk_adjusted_weight_vector_publication"]
    identity = str(manifest["owner_publications"]["risk_adjusted_weight_vector_publication"][adjusted_id])
    row = connection.execute(
        "SELECT * FROM risk_adjusted_weight_vector_publication WHERE risk_adjusted_weight_vector_id=?",
        (identity,),
    ).fetchone()
    if row is None or str(row["project_id"]) == target_project_id:
        raise V3ContractError("imported adjusted weight vector is missing or misbound")
    receipt = connection.execute(
        "SELECT risk_policy_set_version_id FROM risk_application_receipt_publication WHERE risk_application_receipt_id=?",
        (str(row["risk_application_receipt_id"]),),
    ).fetchone()
    target = connection.execute(
        "SELECT 1 FROM target_weight_vector_publication WHERE target_weight_vector_id=?",
        (str(row["source_target_weight_vector_id"]),),
    ).fetchone()
    policy = connection.execute(
        "SELECT 1 FROM risk_policy_set_publication WHERE risk_policy_set_version_id=?",
        (str(receipt["risk_policy_set_version_id"]) if receipt is not None else "",),
    ).fetchone()
    if receipt is None or target is None or policy is None:
        raise V3ContractError("imported owner chain is incomplete")


def _build_bound_context_payload(
    original_context: Mapping[str, Any],
    project_id: str,
    project_context_revision_id: str,
    imported_at: datetime,
) -> bytes:
    """Bind the verified execution parameters to THIS project's revision.

    Only the product binding fields change; the rule/cost/timing parameters are
    copied verbatim from the verified original context and the run-spec
    identity fields must keep matching the immutable spec artifact.
    """
    context = {
        "schema_version": EXECUTION_CONTEXT_SCHEMA_VERSION,
        "context_kind": RESEARCH_RUN_CONTEXT_KIND,
        "project_id": project_id,
        "project_context_revision_id": project_context_revision_id,
        "run_spec_id": str(original_context["run_spec_id"]),
        "run_spec_content_sha256": str(original_context["run_spec_content_sha256"]),
        "engine_version": str(original_context["engine_version"]),
        "rule_profile": dict(original_context["rule_profile"]),
        "cost_policy": dict(original_context["cost_policy"]),
        "execution_timing_profile": dict(original_context["execution_timing_profile"]),
        "published_at": wire_time(imported_at),
    }
    return canonical_json_bytes(context)


def _manifest_freeze(manifest_wire: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(dict(manifest_wire), sort_keys=True, separators=(",", ":")))


# ---------------------------------------------------------------------------
# Run-spec discovery
# ---------------------------------------------------------------------------


def list_backtest_run_specs(
    product: ProductRuntime,
    *,
    project_id: str,
    project_context_revision_id: str,
    limit: int = 50,
    after_run_spec_id: str | None = None,
) -> dict[str, Any]:
    """Discover project-owned canonical run specs through verified artifacts."""
    product.require_project_context_ownership(project_id, project_context_revision_id)
    connection = connect_catalog(product.database_path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT artifact_id FROM artifact_reference
            WHERE owner_id=? AND role=? AND state='ACTIVE'
              AND (? IS NULL OR artifact_id > ?)
            ORDER BY artifact_id LIMIT ?
            """,
            (project_id, PROJECT_SPEC_REFERENCE_ROLE, after_run_spec_id, after_run_spec_id, limit + 1),
        ).fetchall()
    finally:
        connection.close()
    has_more = len(rows) > limit
    specs: list[dict[str, Any]] = []
    for row in rows[:limit]:
        artifact_id = str(row["artifact_id"])
        entry = _discover_single_spec(product, project_id, artifact_id)
        specs.append(entry)
    return {"specs": specs, "has_more": has_more}


def _discover_single_spec(
    product: ProductRuntime, project_id: str, artifact_id: str
) -> dict[str, Any]:
    try:
        payload = product.read_verified_bytes(artifact_id)
        wire = json.loads(payload.decode("utf-8"))
        run_spec_id = str(wire["run_spec_id"])
        context_rows = product.references(project_id, PROJECT_SPEC_CONTEXT_REFERENCE_ROLE)
        context_wire = None
        for context_row in context_rows:
            candidate = json.loads(
                product.read_verified_bytes(str(context_row["artifact_id"])).decode("utf-8")
            )
            if (
                candidate.get("context_kind") == RESEARCH_RUN_CONTEXT_KIND
                and candidate.get("run_spec_id") == run_spec_id
            ):
                context_wire = candidate
                break
        if context_wire is None:
            raise NotFoundError("no durable execution context for run spec")
        spec, _ = product.spec_codec.reconstruct(project_id=project_id, run_spec_id=run_spec_id)
        if spec.run_spec_id != run_spec_id:
            raise TruthPreconditionFailedError("reconstructed run spec identity mismatch")
        return {
            "run_spec_id": run_spec_id,
            "artifact_id": artifact_id,
            "content_sha256": str(spec.content_sha256),
            "project_context_revision_id": str(context_wire["project_context_revision_id"]),
            "engine_version": str(context_wire["engine_version"]),
            "created_at": str(context_wire["published_at"]),
            "execution_adapter_version_id": str(context_wire["engine_version"]),
            "status": "EXECUTABLE",
        }
    except Exception as error:  # honest degradation: never list unverifiable specs
        diagnostic = f"{type(error).__name__}: {error}"[:500]
        try:
            payload = product.read_verified_bytes(artifact_id)
            wire = json.loads(payload.decode("utf-8"))
            run_spec_id = str(wire.get("run_spec_id", "btrs_sha256_unknown"))
            content_sha256 = str(wire.get("content_sha256", ""))
        except Exception:
            run_spec_id = "btrs_sha256_unknown"
            content_sha256 = ""
        return {
            "run_spec_id": run_spec_id,
            "artifact_id": artifact_id,
            "content_sha256": content_sha256,
            "project_context_revision_id": "",
            "engine_version": "",
            "created_at": "",
            "execution_adapter_version_id": "",
            "status": "UNAVAILABLE",
            "diagnostic": diagnostic,
        }


# ---------------------------------------------------------------------------
# Export (test-setup / future export operation support)
# ---------------------------------------------------------------------------


def build_research_package(
    product: ProductRuntime, *, source_project_id: str, run_spec_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a v3.research-package/1.0.0 manifest + file list from a source storage.

    This is a bounded reader over durable canonical records; it never authors
    numeric truth.  The produced package must pass the exact same verification
    path as a user-authored one when imported.
    """
    connection = connect_catalog(product.database_path, read_only=True)

    def one(sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = connection.execute(sql, params).fetchone()
        return None if row is None else {key: row[key] for key in row.keys()}

    try:
        project = one("SELECT * FROM project WHERE project_id=?", (source_project_id,))
        if project is None:
            raise NotFoundError(f"unknown source project: {source_project_id}")
        spec_ref = one(
            "SELECT artifact_id FROM artifact_reference WHERE owner_id=? AND role=? AND state='ACTIVE' LIMIT 1",
            (source_project_id, PROJECT_SPEC_REFERENCE_ROLE),
        )
        if spec_ref is None:
            raise NotFoundError("source project owns no run spec reference")
        spec_artifact_id = str(spec_ref["artifact_id"])
        spec_wire = json.loads(product.read_verified_bytes(spec_artifact_id).decode("utf-8"))
        if str(spec_wire.get("run_spec_id")) != run_spec_id:
            raise NotFoundError("source project run spec reference does not match the requested identity")
        adjusted_id = str(spec_wire["schedule"][0]["risk_adjusted_weight_vector_id"])
        owner_rows: dict[str, dict[str, Any]] = {}
        for table in (
            "risk_adjusted_weight_vector_publication",
            "risk_application_receipt_publication",
            "target_weight_vector_publication",
            "risk_policy_set_publication",
        ):
            row = one(f'SELECT * FROM "{table}" WHERE "{_OWNER_ID_COLUMN[table]}"=?', (_owner_key(table, owner_rows, adjusted_id),))
            if row is None:
                raise NotFoundError(f"source storage lacks the canonical owner row: {table}")
            owner_rows[table] = row
        source_pcr = str(owner_rows["risk_adjusted_weight_vector_publication"]["project_context_revision_id"])
        revision = one(
            "SELECT * FROM project_context_revision WHERE project_context_revision_id=?",
            (source_pcr,),
        )
        if revision is None:
            raise NotFoundError("source storage lacks the owner-bound context revision")
        artifact_rows: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        paths: dict[str, str] = {}
        payload_plans: list[tuple[str, str]] = []
        _ROLE_PATH = {
            "target_weight_vector_publication": "target.json",
            "risk_policy_set_publication": "policy.json",
            "risk_application_receipt_publication": "receipt.json",
            "risk_adjusted_weight_vector_publication": "adjusted.json",
        }
        for table in PACKAGE_OWNER_TABLES:
            row = owner_rows[table]
            artifact_id = str(row["artifact_id"])
            reference = one(
                "SELECT * FROM artifact_reference WHERE artifact_reference_id=?",
                (str(row["artifact_reference_id"]),),
            )
            if reference is None:
                raise NotFoundError("owner artifact reference is missing in source storage")
            references.append(reference)
            artifact = one("SELECT * FROM artifact WHERE artifact_id=?", (artifact_id,))
            if artifact is None:
                raise NotFoundError("owner artifact row is missing in source storage")
            path = _ROLE_PATH[table]
            paths[artifact_id] = path
            artifact_rows.append({"row": artifact, "name": path})
            payload_plans.append((path, artifact_id))
        spec_artifact = one("SELECT * FROM artifact WHERE artifact_id=?", (spec_artifact_id,))
        if spec_artifact is None:
            raise NotFoundError("run spec artifact row is missing in source storage")
        artifact_rows.append({"row": spec_artifact, "name": "spec.json"})
        paths[spec_artifact_id] = "spec.json"
        payload_plans.append(("spec.json", spec_artifact_id))
        context_ref = one(
            "SELECT artifact_id FROM artifact_reference WHERE owner_id=? AND role=? AND state='ACTIVE' LIMIT 1",
            (source_project_id, PROJECT_SPEC_CONTEXT_REFERENCE_ROLE),
        )
        if context_ref is None:
            raise NotFoundError("source project owns no execution context reference")
        context_artifact_id = str(context_ref["artifact_id"])
        context_wire = json.loads(product.read_verified_bytes(context_artifact_id).decode("utf-8"))
        if context_wire.get("run_spec_id") != run_spec_id:
            raise NotFoundError("source execution context does not match the run spec")
        context_artifact = one("SELECT * FROM artifact WHERE artifact_id=?", (context_artifact_id,))
        if context_artifact is None:
            raise NotFoundError("execution context artifact row is missing in source storage")
        artifact_rows.append({"row": context_artifact, "name": "context.json"})
        payload_plans.append(("context.json", context_artifact_id))

        # Generic closure walk: every *_artifact_id column reachable from the
        # carried rows must ship its artifact record so the imported catalog
        # keeps satisfying the schema invariants (e.g. the universe membership
        # stub referenced by the target weight owner row).
        carried_rows = [revision] + [owner_rows[table] for table in PACKAGE_OWNER_TABLES]
        for carried in carried_rows:
            for column, value in carried.items():
                if not column.endswith("_artifact_id") or value is None:
                    continue
                reached_id = str(value)
                if reached_id in paths:
                    continue
                reached = one("SELECT * FROM artifact WHERE artifact_id=?", (reached_id,))
                if reached is None:
                    raise NotFoundError(
                        f"carried row references an artifact missing in source storage: {reached_id}"
                    )
                if int(reached["byte_size"]) > 0:
                    reached_path = f"ref{len(paths)}.json"
                    paths[reached_id] = reached_path
                    artifact_rows.append({"row": reached, "name": reached_path})
                    payload_plans.append((reached_path, reached_id))
                else:
                    paths[reached_id] = ""
                    artifact_rows.append({"row": reached, "name": None})

        manifest = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "source_product_runtime_version": PRODUCT_RUNTIME_VERSION,
            "source_project": project,
            "source_project_context_revision": revision,
            "run_spec_id": run_spec_id,
            "run_spec_artifact": {
                "name": "spec.json",
                "artifact_id": spec_artifact_id,
                "sha256": str(spec_artifact["sha256"]),
                "byte_size": int(spec_artifact["byte_size"]),
            },
            "execution_context_artifact": {
                "name": "context.json",
                "artifact_id": context_artifact_id,
                "sha256": str(context_artifact["sha256"]),
                "byte_size": int(context_artifact["byte_size"]),
            },
            "artifacts": artifact_rows,
            "artifact_references": references,
            "owner_publications": {table: owner_rows[table] for table in PACKAGE_OWNER_TABLES},
        }
        files = []
        for path, artifact_id in payload_plans:
            payload = product.read_verified_bytes(artifact_id)
            files.append(
                {
                    "name": path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                    "payload_base64": base64.b64encode(payload).decode("ascii"),
                }
            )
        return manifest, files
    finally:
        connection.close()


def _owner_key(table: str, owner_rows: Mapping[str, Mapping[str, Any]], adjusted_id: str) -> str:
    """Resolve the owner row identity for the closure walk order."""
    if table == "risk_adjusted_weight_vector_publication":
        return adjusted_id
    if table == "risk_application_receipt_publication":
        return str(owner_rows["risk_adjusted_weight_vector_publication"]["risk_application_receipt_id"])
    if table == "target_weight_vector_publication":
        return str(owner_rows["risk_application_receipt_publication"]["source_target_weight_vector_id"])
    return str(owner_rows["risk_application_receipt_publication"]["risk_policy_set_version_id"])


# ---------------------------------------------------------------------------
# Projectless control-protocol frames (productEntry.*)
# ---------------------------------------------------------------------------

_CREATE_FRAME_KEYS = {
    "kind",
    "protocol_version",
    "display_name",
    "idempotency_key",
    "notes",
}
_LIST_FRAME_KEYS = {"kind", "protocol_version", "limit", "after_project_id"}


def handle_product_entry_control(
    product: ProductRuntime, kind: str, message: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate and execute one closed productEntry.* control frame."""
    if not isinstance(message, Mapping):
        raise InvalidArgumentError("product entry control frame must be an object")
    if message.get("protocol_version") != PRODUCT_ENTRY_PROTOCOL_VERSION:
        raise InvalidArgumentError(
            f"unsupported product entry control protocol: {message.get('protocol_version')!r}"
        )
    if kind == "productEntry.createProject":
        if set(message) != _CREATE_FRAME_KEYS:
            raise InvalidArgumentError(
                "productEntry.createProject fields do not match the closed wire shape"
            )
        outcome = create_project(
            product,
            display_name=message["display_name"],
            notes=message["notes"],
            idempotency_key=message["idempotency_key"],
        )
        return {"kind": "productEntry.projectCreated", **outcome}
    if kind == "productEntry.listProjects":
        if set(message) != _LIST_FRAME_KEYS:
            raise InvalidArgumentError(
                "productEntry.listProjects fields do not match the closed wire shape"
            )
        outcome = list_projects(
            product,
            limit=message["limit"] if message["limit"] is not None else 50,
            after_project_id=message["after_project_id"],
        )
        return {"kind": "productEntry.projectsListed", **outcome}
    raise InvalidArgumentError(f"unknown product entry control frame: {kind}")


__all__ = [
    "PRODUCT_ENTRY_PROTOCOL_VERSION",
    "PACKAGE_SCHEMA_VERSION",
    "CREATE_PROJECT_OPERATION",
    "IMPORT_OPERATION",
    "create_project",
    "list_projects",
    "import_research_package",
    "list_backtest_run_specs",
    "build_research_package",
    "parse_package_manifest",
    "handle_product_entry_control",
]
