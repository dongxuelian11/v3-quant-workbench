"""V1.1 local Data Truth application service.

This service orchestrates existing Artifact, Data Snapshot, Universe and Project
Context owners.  User bytes are streamed into the Artifact Store before parsing;
the renderer never supplies canonical bars or owner identities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping
from zoneinfo import ZoneInfo

from v3_backend.adapters.local_data import (
    LocalDataImportError,
    LocalDataImportIntentV1,
    LocalDataImportLimits,
    LocalDataNormalizationResult,
    import_csv_stream,
    import_parquet_stream,
)
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

from .product_runtime import (
    ProductRuntime,
    _accept_outcome_json,
    _canonical_request_hash,
    classify_execution_error,
    mint_v3_id,
    wire_time,
)


LOCAL_CONNECTOR_ID = "con_local_data_import_v1"
LOCAL_CONNECTOR_VERSION_ID = "cov_local_data_import_v1"
LOCAL_PROVIDER_ID = "pvd_local_user_supplied_v1"
LOCAL_DATASET = "LOCAL_A_SHARE_EOD"
LOCAL_TRUTH_PROFILE = "PRE_ALPHA_LOCAL_USER_SUPPLIED"
LOCAL_VALIDATION_PROFILE = "svp_local_user_supplied_v1"
LOCAL_NORMALIZATION_VERSION = "v3.local-a-share-eod/1.0.0"

RAW_ROLE = "LOCAL_DATA_RAW_FILE"
CONNECTOR_MANIFEST_ROLE = "LOCAL_DATA_CONNECTOR_MANIFEST"
MAPPING_ROLE = "LOCAL_DATA_SCHEMA_MAPPING"
NORMALIZATION_ROLE = "LOCAL_DATA_NORMALIZATION_RECEIPT"
PARTITION_ROLE = "DATA_TRUTH_SNAPSHOT_PARTITION"
PARTITION_MANIFEST_ROLE = "DATA_TRUTH_SNAPSHOT_MANIFEST"
CALENDAR_ROLE = "DATA_TRUTH_CALENDAR"
MEMBERSHIP_ROLE = "UNIVERSE_MEMBERSHIP"
UNIVERSE_AUDIT_ROLE = "LOCAL_DATA_UNIVERSE_AUDIT"
READ_MODEL_ROLE = "LOCAL_DATA_IMPORT_READ_MODEL"
PRODUCT_LOCAL_DATA_OPERATION = "ProductEntryService.v1.importLocalDataset"
LOCAL_DATA_CONTEXT_SCHEMA_VERSION = "v3.product-local-data-context/1.1.0"
LOCAL_VALIDATION_CHECKS = (
    "CLOSED_SCHEMA",
    "UNIT_NORMALIZATION",
    "UNIQUE_SYMBOL_DATE",
    "OHLC_INVARIANTS",
    "RESOURCE_BOUNDS",
    "DATE_ORDERING",
    "INSTRUMENT_RESOLUTION",
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")


def _json_text(value: Mapping[str, Any]) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _schema_fingerprint(name: str) -> str:
    return canonical_sha256({"schema": name})


def _discard_stage(product: ProductRuntime, token: str) -> None:
    product.artifact_store.discard_staging(
        token,
        not_newer_than=datetime.now(timezone.utc),
    )


def _normalize_staged(
    product: ProductRuntime,
    staging_token: str,
    *,
    intent: LocalDataImportIntentV1,
    limits: LocalDataImportLimits,
) -> LocalDataNormalizationResult:
    with product.artifact_store.open_staged(staging_token) as staged:
        return _normalize_source(staged, intent=intent, limits=limits)


def _normalize_source(
    source: BinaryIO,
    *,
    intent: LocalDataImportIntentV1,
    limits: LocalDataImportLimits,
) -> LocalDataNormalizationResult:
    if intent.media_type == "text/csv":
        return import_csv_stream(source, intent=intent, limits=limits)
    return import_parquet_stream(source, intent=intent, limits=limits)


def _observed_session_time(session_date, at: time) -> str:
    return wire_time(datetime.combine(session_date, at, tzinfo=_SHANGHAI))


def _ensure_exact_row(
    connection,
    table: str,
    identity_column: str,
    row: Mapping[str, Any],
    *,
    stable_fields: tuple[str, ...] | None = None,
) -> None:
    existing = connection.execute(
        f'SELECT * FROM "{table}" WHERE "{identity_column}"=?',
        (row[identity_column],),
    ).fetchone()
    if existing is None:
        columns = tuple(row)
        connection.execute(
            f'INSERT INTO "{table}" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
            tuple(row[column] for column in columns),
        )
        return
    fields = stable_fields or tuple(row)
    if any(existing[field] != row[field] for field in fields):
        raise ConflictError(f"canonical {table} identity conflicts with persisted truth")


def _connector_manifest_payload() -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.local-data-connector/1.0.0",
            "connector_version_id": LOCAL_CONNECTOR_VERSION_ID,
            "entrypoint": "v3.product-data.local-import",
            "network_policy": "DENY",
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }
    )


def _mapping_payload(intent: LocalDataImportIntentV1) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.local-data-schema-mapping/1.0.0",
            "required_columns": _REQUIRED_COLUMNS,
            "source": {
                "adjustment": intent.adjustment,
                "amount_unit": intent.amount_unit,
                "media_type": intent.media_type,
                "timezone": intent.timezone,
                "volume_unit": intent.volume_unit,
            },
            "canonical": {
                "adjustment": "UNADJUSTED",
                "amount_unit": "CNY",
                "timezone": "Asia/Shanghai",
                "volume_unit": "SHARES",
            },
        }
    )


def _normalization_payload(result: LocalDataNormalizationResult) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.local-data-normalization-receipt/1.0.0",
            "raw_content_hash": result.raw_content_hash,
            "normalized_payload_hash": result.normalized_payload_hash,
            "row_count": result.row_count,
            "instrument_count": result.instrument_count,
            "sort_order": ("session_date", "instrument_id"),
            "source_volume_unit": result.source_volume_unit,
            "canonical_volume_unit": "SHARES",
            "pit_state": "PIT_UNPROVABLE",
            "available_time": "UNKNOWN_WHEN_SOURCE_NULL",
            "revision": "UNKNOWN",
        }
    )


def _calendar_payload(result: LocalDataNormalizationResult) -> bytes:
    dates = sorted({row.session_date.isoformat() for row in result.rows})
    return canonical_json_bytes(
        {
            "schema_version": "v3.observed-local-calendar/1.0.0",
            "session_dates": dates,
            "timezone": "Asia/Shanghai",
            "semantics": "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR",
        }
    )


def _membership_payload(result: LocalDataNormalizationResult) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.user-defined-static-universe/1.0.0",
            "snapshot_id": result.snapshot_semantic_id,
            "role": "USER_DEFINED_STATIC",
            "instrument_ids": sorted({row.instrument_id for row in result.rows}),
        }
    )


def _universe_audit_payload(
    result: LocalDataNormalizationResult,
    membership_artifact_id: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "v3.user-defined-static-universe-audit/1.0.0",
            "snapshot_id": result.snapshot_semantic_id,
            "membership_artifact_id": membership_artifact_id,
            "missing_requested_symbols": (),
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }
    )


def _artifact_payloads(
    result: LocalDataNormalizationResult,
    intent: LocalDataImportIntentV1,
    project_id: str,
) -> tuple[dict[str, tuple[str, bytes]], str, str, str]:
    membership = _membership_payload(result)
    membership_id = artifact_id_for_bytes(membership)
    universe_definition = {
        "snapshot_id": result.snapshot_semantic_id,
        "role": "USER_DEFINED_STATIC",
        "instrument_ids": sorted({row.instrument_id for row in result.rows}),
    }
    universe_hash = canonical_sha256(
        {
            "project_id": project_id,
            "definition": universe_definition,
            "membership_artifact_id": membership_id,
        }
    )
    universe_id = "unv_sha256_" + universe_hash
    payloads: dict[str, tuple[str, bytes]] = {
        CONNECTOR_MANIFEST_ROLE: (CONNECTOR_MANIFEST_ROLE, _connector_manifest_payload()),
        MAPPING_ROLE: (MAPPING_ROLE, _mapping_payload(intent)),
        NORMALIZATION_ROLE: (NORMALIZATION_ROLE, _normalization_payload(result)),
        PARTITION_MANIFEST_ROLE: (PARTITION_MANIFEST_ROLE, result.normalized_payload),
        CALENDAR_ROLE: (CALENDAR_ROLE, _calendar_payload(result)),
        MEMBERSHIP_ROLE: (MEMBERSHIP_ROLE, membership),
        UNIVERSE_AUDIT_ROLE: (UNIVERSE_AUDIT_ROLE, _universe_audit_payload(result, membership_id)),
    }
    for partition in result.partitions:
        key = f"{PARTITION_ROLE}:{partition.partition_key}"
        payloads[key] = (PARTITION_ROLE, partition.payload)
    return payloads, membership_id, universe_id, universe_hash


def _validate_active_context(
    product: ProductRuntime,
    project_id: str,
    project_context_revision_id: str,
) -> Mapping[str, Any]:
    supplied = product.require_project_context_ownership(project_id, project_context_revision_id)
    current = product.current_revision(project_id)
    if current["project_context_revision_id"] != supplied["project_context_revision_id"]:
        raise ConflictError("local import requires the current project context revision")
    return supplied


def _publish_generated_artifacts(
    product: ProductRuntime,
    project_id: str,
    payloads: Mapping[str, tuple[str, bytes]],
) -> dict[str, str]:
    ordered = tuple(payloads.items())
    published = product.execution._publish_artifact_batch(
        payloads=tuple(
            (
                "prv_product_data_" + role.lower(),
                value[1],
                value[0],
                _schema_fingerprint(role.lower()),
            )
            for role, value in ordered
        ),
        references=tuple((project_id, role, index) for index, (role, _) in enumerate(ordered)),
    )
    return {
        role: published[index].descriptor.artifact_id
        for index, (role, _) in enumerate(ordered)
    }


def _register_connector_and_provider(
    connection,
    *,
    now: str,
    connector_manifest_artifact_id: str,
) -> None:
    _ensure_exact_row(
        connection,
        "connector",
        "connector_id",
        {
            "connector_id": LOCAL_CONNECTOR_ID,
            "stable_name": "v3-local-user-supplied-eod",
            "publisher": "V3",
            "state": "REGISTERED",
            "created_at": now,
        },
        stable_fields=("connector_id", "stable_name", "publisher", "state"),
    )
    _ensure_exact_row(
        connection,
        "connector_version",
        "connector_version_id",
        {
            "connector_version_id": LOCAL_CONNECTOR_VERSION_ID,
            "connector_id": LOCAL_CONNECTOR_ID,
            "semantic_version": "1.0.0",
            "bundle_artifact_id": connector_manifest_artifact_id,
            "bundle_sha256": connector_manifest_artifact_id.removeprefix("art_sha256_"),
            "entrypoint": "v3.product-data.local-import",
            "declared_manifest_json": _json_text(
                {
                    "logical_dataset": LOCAL_DATASET,
                    "provider_id": LOCAL_PROVIDER_ID,
                    "truth": "NOT_FORMAL",
                    "admission": "PRE_ALPHA",
                }
            ),
            "network_policy": "DENY",
            "state": "ADMITTED",
            "created_at": now,
        },
        stable_fields=(
            "connector_version_id",
            "connector_id",
            "semantic_version",
            "bundle_artifact_id",
            "bundle_sha256",
            "entrypoint",
            "declared_manifest_json",
            "network_policy",
            "state",
        ),
    )
    provider_metadata = {
        "source_type": "LOCAL_USER_SUPPLIED",
        "available_time": "UNKNOWN",
        "revision": "UNKNOWN",
    }
    provider_hash = canonical_sha256(provider_metadata)
    _ensure_exact_row(
        connection,
        "provider_descriptor",
        "provider_id",
        {
            "provider_id": LOCAL_PROVIDER_ID,
            "stable_name": "local-user-supplied",
            "display_name": "本地用户数据",
            "source_authority": "USER_SUPPLIED_UNVERIFIED",
            "metadata_json": _json_text(provider_metadata),
            "descriptor_hash": provider_hash,
            "state": "REGISTERED",
            "created_at": now,
        },
        stable_fields=(
            "provider_id",
            "stable_name",
            "display_name",
            "source_authority",
            "metadata_json",
            "descriptor_hash",
            "state",
        ),
    )


def _persist_raw_capture(
    connection,
    *,
    result: LocalDataNormalizationResult,
    raw_artifact_id: str,
    now: str,
) -> str:
    raw_capture_id = "raw_sha256_" + result.raw_content_hash
    request_fingerprint = canonical_sha256(
        {
            "connector_version_id": LOCAL_CONNECTOR_VERSION_ID,
            "raw_content_hash": result.raw_content_hash,
        }
    )
    first_date = min(row.session_date for row in result.rows).isoformat()
    last_date = max(row.session_date for row in result.rows).isoformat()
    row = {
        "raw_capture_id": raw_capture_id,
        "connector_version_id": LOCAL_CONNECTOR_VERSION_ID,
        "provider_dataset": LOCAL_DATASET,
        "request_fingerprint": request_fingerprint,
        "effective_range_start": first_date,
        "effective_range_end": last_date,
        "available_time": None,
        "provider_revision_id": None,
        "captured_at": now,
        "ingested_at": now,
        "artifact_id": raw_artifact_id,
        "content_hash": result.raw_content_hash,
        "state": "ACCEPTED",
    }
    _ensure_exact_row(
        connection,
        "raw_capture",
        "raw_capture_id",
        row,
        stable_fields=(
            "raw_capture_id",
            "connector_version_id",
            "provider_dataset",
            "request_fingerprint",
            "effective_range_start",
            "effective_range_end",
            "available_time",
            "provider_revision_id",
            "artifact_id",
            "content_hash",
            "state",
        ),
    )
    truth_metadata = {
        "media_type": result.source_media_type,
        "raw_content_hash": result.raw_content_hash,
        "source_type": "LOCAL_USER_SUPPLIED",
    }
    _ensure_exact_row(
        connection,
        "raw_capture_truth_descriptor",
        "raw_capture_id",
        {
            "raw_capture_id": raw_capture_id,
            "provider_id": LOCAL_PROVIDER_ID,
            "source_metadata_json": _json_text(truth_metadata),
            "provider_available_time": None,
            "provenance_complete": 0,
        },
    )
    return raw_capture_id


def _persist_snapshot(
    connection,
    *,
    result: LocalDataNormalizationResult,
    raw_capture_id: str,
    artifacts: Mapping[str, str],
    now: str,
) -> None:
    snapshot_id = result.snapshot_semantic_id
    first_date = min(row.session_date for row in result.rows)
    last_date = max(row.session_date for row in result.rows)
    existing = connection.execute(
        "SELECT * FROM data_snapshot WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()
    snapshot_is_new = existing is None
    if snapshot_is_new:
        connection.execute(
            """
            INSERT INTO data_snapshot(
                snapshot_id,connector_version_id,parent_snapshot_id,manifest_artifact_id,
                content_hash,normalization_spec_version,truth_profile_id,min_effective_time,
                max_effective_time,max_available_time,state,created_at,validated_at,published_at
            ) VALUES(?,?,NULL,?,?,?,?,?,?,NULL,'CANDIDATE',?,NULL,NULL)
            """,
            (
                snapshot_id,
                LOCAL_CONNECTOR_VERSION_ID,
                artifacts[PARTITION_MANIFEST_ROLE],
                result.normalized_payload_hash,
                LOCAL_NORMALIZATION_VERSION,
                LOCAL_TRUTH_PROFILE,
                _observed_session_time(first_date, time(15, 0)),
                _observed_session_time(last_date, time(15, 0)),
                now,
            ),
        )
    else:
        expected = (
            LOCAL_CONNECTOR_VERSION_ID,
            artifacts[PARTITION_MANIFEST_ROLE],
            result.normalized_payload_hash,
            LOCAL_NORMALIZATION_VERSION,
            LOCAL_TRUTH_PROFILE,
        )
        observed = tuple(
            existing[name]
            for name in (
                "connector_version_id",
                "manifest_artifact_id",
                "content_hash",
                "normalization_spec_version",
                "truth_profile_id",
            )
        )
        if observed != expected:
            raise ConflictError("local Snapshot identity conflicts with persisted truth")
    # A published Snapshot is immutable, including its admitted raw-source set.
    # Equivalent later encodings retain their own RawCapture + normalization
    # receipt, but do not mutate the already-published semantic Snapshot.
    if snapshot_is_new:
        connection.execute(
            """
            INSERT INTO snapshot_raw_capture(snapshot_id,raw_capture_id,logical_dataset,linked_at)
            VALUES(?,?,?,?)
            """,
            (snapshot_id, raw_capture_id, LOCAL_DATASET, now),
        )
    calendar_hash = artifacts[CALENDAR_ROLE].removeprefix("art_sha256_")
    calendar_id = "tcv_sha256_" + calendar_hash
    _ensure_exact_row(
        connection,
        "trading_calendar_version",
        "calendar_version_id",
        {
            "calendar_version_id": calendar_id,
            "market": "CN_A_SHARE",
            "timezone": "Asia/Shanghai",
            "source_artifact_id": artifacts[CALENDAR_ROLE],
            "content_hash": calendar_hash,
            "state": "PUBLISHED",
            "published_at": now,
        },
        stable_fields=(
            "calendar_version_id",
            "market",
            "timezone",
            "source_artifact_id",
            "content_hash",
            "state",
        ),
    )
    for ordinal, session_date in enumerate(sorted({row.session_date for row in result.rows})):
        session_id = "trs_sha256_" + canonical_sha256(
            {"calendar_version_id": calendar_id, "session_date": session_date.isoformat()}
        )
        _ensure_exact_row(
            connection,
            "trading_session",
            "trading_session_id",
            {
                "trading_session_id": session_id,
                "calendar_version_id": calendar_id,
                "session_date": session_date.isoformat(),
                "is_trading_day": 1,
                "session_ordinal": ordinal,
                "open_time": _observed_session_time(session_date, time(9, 30)),
                "close_time": _observed_session_time(session_date, time(15, 0)),
                "available_time": None,
                "evidence_artifact_id": artifacts[CALENDAR_ROLE],
            },
            stable_fields=(
                "trading_session_id",
                "calendar_version_id",
                "session_date",
                "is_trading_day",
                "session_ordinal",
                "open_time",
                "close_time",
                "available_time",
                "evidence_artifact_id",
            ),
        )
    _ensure_exact_row(
        connection,
        "snapshot_calendar",
        "snapshot_id",
        {"snapshot_id": snapshot_id, "calendar_version_id": calendar_id, "linked_at": now},
        stable_fields=("snapshot_id", "calendar_version_id"),
    )
    for partition in result.partitions:
        row = {
            "snapshot_id": snapshot_id,
            "logical_dataset": LOCAL_DATASET,
            "partition_key": partition.partition_key,
            "parquet_artifact_id": artifacts[f"{PARTITION_ROLE}:{partition.partition_key}"],
            "row_count": partition.row_count,
            "schema_fingerprint": _schema_fingerprint(LOCAL_NORMALIZATION_VERSION),
            "min_effective_time": _observed_session_time(partition.min_session_date, time(15, 0)),
            "max_effective_time": _observed_session_time(partition.max_session_date, time(15, 0)),
            "max_available_time": None,
        }
        existing_partition = connection.execute(
            """
            SELECT * FROM snapshot_partition
            WHERE snapshot_id=? AND logical_dataset=? AND partition_key=?
            """,
            (snapshot_id, LOCAL_DATASET, partition.partition_key),
        ).fetchone()
        if existing_partition is None:
            columns = tuple(row)
            connection.execute(
                f'INSERT INTO "snapshot_partition" ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                tuple(row[column] for column in columns),
            )
        elif any(existing_partition[field] != value for field, value in row.items()):
            raise ConflictError("local Snapshot partition conflicts with persisted truth")
    _ensure_exact_row(
        connection,
        "snapshot_validation_profile",
        "validation_profile_id",
        {
            "validation_profile_id": LOCAL_VALIDATION_PROFILE,
            "admission_state": "PRE_ALPHA",
            "description": "Local user data with explicit units; PIT, revision and formal calendar remain unavailable",
            "created_at": now,
        },
        stable_fields=("validation_profile_id", "admission_state", "description"),
    )
    for check_code in LOCAL_VALIDATION_CHECKS:
        existing_requirement = connection.execute(
            """
            SELECT * FROM snapshot_validation_requirement
            WHERE validation_profile_id=? AND check_code=?
            """,
            (LOCAL_VALIDATION_PROFILE, check_code),
        ).fetchone()
        requirement = {
            "validation_profile_id": LOCAL_VALIDATION_PROFILE,
            "check_code": check_code,
            "required_state": "PASS",
            "severity": "BLOCKING",
        }
        if existing_requirement is None:
            connection.execute(
                """
                INSERT INTO snapshot_validation_requirement(
                    validation_profile_id,check_code,required_state,severity
                ) VALUES(?,?,?,?)
                """,
                tuple(requirement.values()),
            )
        elif any(existing_requirement[field] != value for field, value in requirement.items()):
            raise ConflictError("local Snapshot validation requirement conflicts")
        validation_id = "snv_sha256_" + canonical_sha256(
            {
                "snapshot_id": snapshot_id,
                "validation_profile_id": LOCAL_VALIDATION_PROFILE,
                "check_code": check_code,
            }
        )
        _ensure_exact_row(
            connection,
            "snapshot_validation",
            "snapshot_validation_id",
            {
                "snapshot_validation_id": validation_id,
                "snapshot_id": snapshot_id,
                "validation_profile_id": LOCAL_VALIDATION_PROFILE,
                "check_code": check_code,
                "state": "PASS",
                "severity": "BLOCKING",
                "report_artifact_id": artifacts[PARTITION_MANIFEST_ROLE],
                "validated_at": now,
            },
            stable_fields=(
                "snapshot_validation_id",
                "snapshot_id",
                "validation_profile_id",
                "check_code",
                "state",
                "severity",
                "report_artifact_id",
            ),
        )
    _ensure_exact_row(
        connection,
        "snapshot_validation_binding",
        "snapshot_id",
        {
            "snapshot_id": snapshot_id,
            "validation_profile_id": LOCAL_VALIDATION_PROFILE,
            "bound_at": now,
        },
        stable_fields=("snapshot_id", "validation_profile_id"),
    )
    state = connection.execute(
        "SELECT state FROM data_snapshot WHERE snapshot_id=?", (snapshot_id,)
    ).fetchone()[0]
    if state == "CANDIDATE":
        connection.execute(
            """
            UPDATE data_snapshot SET state='VALIDATED',validated_at=?
            WHERE snapshot_id=? AND state='CANDIDATE'
            """,
            (now, snapshot_id),
        )
        state = "VALIDATED"
    if state == "VALIDATED":
        connection.execute(
            "UPDATE data_snapshot SET state='PUBLISHED',published_at=? WHERE snapshot_id=? AND state='VALIDATED'",
            (now, snapshot_id),
        )
    elif state != "PUBLISHED":
        raise ConflictError("local Snapshot is not publishable")


def _persist_universe(
    connection,
    *,
    project_id: str,
    result: LocalDataNormalizationResult,
    artifacts: Mapping[str, str],
    universe_id: str,
    universe_hash: str,
    now: str,
) -> str:
    definition = {
        "snapshot_id": result.snapshot_semantic_id,
        "role": "USER_DEFINED_STATIC",
        "instrument_ids": sorted({row.instrument_id for row in result.rows}),
    }
    definition_hash = canonical_sha256({"project_id": project_id, "definition": definition})
    definition_id = "und_sha256_" + definition_hash
    _ensure_exact_row(
        connection,
        "universe_definition",
        "universe_definition_id",
        {
            "universe_definition_id": definition_id,
            "project_id": project_id,
            "constructor_kind": "WATCHLIST",
            "definition_json": _json_text(definition),
            "canonical_hash": definition_hash,
            "state": "PUBLISHED",
            "created_at": now,
        },
        stable_fields=(
            "universe_definition_id",
            "project_id",
            "constructor_kind",
            "definition_json",
            "canonical_hash",
            "state",
        ),
    )
    _ensure_exact_row(
        connection,
        "universe_version",
        "universe_version_id",
        {
            "universe_version_id": universe_id,
            "universe_definition_id": definition_id,
            "snapshot_id": result.snapshot_semantic_id,
            "industry_taxonomy_version_id": None,
            "knowledge_cutoff": now,
            "membership_artifact_id": artifacts[MEMBERSHIP_ROLE],
            "audit_artifact_id": artifacts[UNIVERSE_AUDIT_ROLE],
            "content_hash": universe_hash,
            "state": "PUBLISHED",
            "published_at": now,
        },
        stable_fields=(
            "universe_version_id",
            "universe_definition_id",
            "snapshot_id",
            "industry_taxonomy_version_id",
            "membership_artifact_id",
            "audit_artifact_id",
            "content_hash",
            "state",
        ),
    )
    return definition_id


def _new_context(
    connection,
    *,
    project_id: str,
    prior: Mapping[str, Any],
    snapshot_id: str,
    universe_id: str,
    source_type: str,
    now: str,
) -> str:
    context = {
        "context_fields": {
            "data_source": source_type,
            "pit_state": "PIT_UNPROVABLE",
            "truth": "NOT_FORMAL",
        },
        "snapshot_id": snapshot_id,
        "universe_version_id": universe_id,
    }
    context_json = _json_text(context)
    context_hash = canonical_sha256(context_json)
    existing = connection.execute(
        "SELECT project_context_revision_id FROM project_context_revision WHERE project_id=? AND canonical_hash=?",
        (project_id, context_hash),
    ).fetchone()
    if existing is not None:
        return str(existing[0])
    revision_id = mint_v3_id("pcr_")
    connection.execute(
        """
        INSERT INTO project_context_revision(
            project_context_revision_id,project_id,revision_no,parent_revision_id,
            connector_version_id,snapshot_id,universe_version_id,environment_profile_id,
            context_json,canonical_hash,created_by,created_at
        ) VALUES(?,?,?,?,?,?,?,NULL,?,?,?,?)
        """,
        (
            revision_id,
            project_id,
            int(prior["revision_no"]) + 1,
            prior["project_context_revision_id"],
            LOCAL_CONNECTOR_VERSION_ID,
            snapshot_id,
            universe_id,
            context_json,
            context_hash,
            "v3.product-data/1.1.0",
            now,
        ),
    )
    return revision_id


@dataclass(frozen=True, slots=True)
class ProductLocalDataSubmission:
    project_id: str
    project_context_revision_id: str
    source: Mapping[str, Any]
    idempotency_key: str
    execution_deadline_at: str | None = None


@dataclass(frozen=True, slots=True)
class _PreparedLocalDataRequest:
    project_id: str
    project_context_revision_id: str
    source_ref: dict[str, Any]
    semantic: dict[str, Any]
    request_hash: str
    scope: str
    execution_deadline_at: str | None


@dataclass(frozen=True, slots=True)
class _LocalDataTaskHandles:
    task: Any
    run: Any
    attempt: Any


def _local_data_accept_outcome(
    task_id: str,
    run_id: str,
    source_artifact_id: str,
    *,
    event_cursor: int | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "task_id": task_id,
        "run_id": run_id,
        "accepted_state": "QUEUED",
        "maturity": "PRODUCT_CONNECTED",
        "truth": "NOT_FORMAL",
        "admission": "PRE_ALPHA",
        "checkpoint_resume": "UNAVAILABLE",
        "retry": "NEW_ATTEMPT_SAME_RUN_FROM_START",
        "source_artifact_id": source_artifact_id,
    }
    if event_cursor is not None:
        outcome["event_cursor"] = event_cursor
    return outcome


class ProductDataService:
    """Additive PRE_ALPHA local-data path; never reinterprets legacy DEMO operations."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    @staticmethod
    def _bounded_display_name(display_name: object) -> str:
        name = display_name.strip() if isinstance(display_name, str) else ""
        if not name or len(name) > 255 or Path(name).name != name:
            raise LocalDataImportError("display_name must be a bounded flat filename")
        return name

    def _require_source_ref(
        self,
        *,
        project_id: str,
        source: Mapping[str, Any],
        limits: LocalDataImportLimits,
    ) -> dict[str, Any]:
        required = {
            "artifact_id",
            "sha256",
            "byte_size",
            "media_type",
            "display_name",
            "volume_unit",
            "amount_unit",
            "timezone",
            "adjustment",
        }
        if set(source) != required:
            raise InvalidArgumentError("local source ref does not match the closed shape")
        artifact_id = source["artifact_id"]
        sha256 = source["sha256"]
        byte_size = source["byte_size"]
        if not isinstance(artifact_id, str) or not isinstance(sha256, str):
            raise InvalidArgumentError("local source Artifact identity is invalid")
        if artifact_id != "art_sha256_" + sha256:
            raise TruthPreconditionFailedError(
                "local source Artifact ID and SHA-256 do not identify the same bytes"
            )
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or not 1 <= byte_size <= limits.max_bytes
        ):
            raise InvalidArgumentError("local source byte_size exceeds the admitted bound")
        intent = LocalDataImportIntentV1(
            media_type=str(source["media_type"]),
            volume_unit=str(source["volume_unit"]),
            amount_unit=str(source["amount_unit"]),
            timezone=str(source["timezone"]),
            adjustment=str(source["adjustment"]),
        )
        name = self._bounded_display_name(source["display_name"])
        descriptor = self.product.require_published_artifact(artifact_id)
        expected_descriptor = {
            "sha256": sha256,
            "byte_size": byte_size,
            "media_type": intent.media_type,
            "semantic_role": RAW_ROLE,
            "schema_fingerprint": _schema_fingerprint("local-user-source-v1"),
        }
        if any(descriptor.get(field) != value for field, value in expected_descriptor.items()):
            raise TruthPreconditionFailedError(
                "local source ref does not match the published Artifact descriptor"
            )
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            reachable = connection.execute(
                """
                SELECT 1 FROM artifact_reference
                WHERE owner_type='Project' AND owner_id=? AND role=?
                  AND artifact_id=? AND state='ACTIVE'
                """,
                (project_id, RAW_ROLE, artifact_id),
            ).fetchone()
        finally:
            connection.close()
        if reachable is None:
            raise TruthPreconditionFailedError(
                "local source Artifact is not reachable from the request project"
            )
        return {
            "artifact_id": artifact_id,
            "sha256": sha256,
            "byte_size": byte_size,
            "media_type": intent.media_type,
            "display_name": name,
            "volume_unit": intent.volume_unit,
            "amount_unit": intent.amount_unit,
            "timezone": intent.timezone,
            "adjustment": intent.adjustment,
        }

    def _persist_normalized_import(
        self,
        *,
        project_id: str,
        prior: Mapping[str, Any],
        name: str,
        intent: LocalDataImportIntentV1,
        result: LocalDataNormalizationResult,
        raw_artifact_id: str,
    ) -> dict[str, Any]:
        payloads, membership_id, universe_id, universe_hash = _artifact_payloads(
            result, intent, project_id
        )
        artifacts = _publish_generated_artifacts(self.product, project_id, payloads)
        if artifacts[MEMBERSHIP_ROLE] != membership_id:
            raise ConflictError("Universe membership Artifact identity drifted")

        now = wire_time(datetime.now(timezone.utc))
        raw_capture_id = "raw_sha256_" + result.raw_content_hash
        connection = connect_catalog(self.product.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _register_connector_and_provider(
                connection,
                now=now,
                connector_manifest_artifact_id=artifacts[CONNECTOR_MANIFEST_ROLE],
            )
            persisted_raw_id = _persist_raw_capture(
                connection,
                result=result,
                raw_artifact_id=raw_artifact_id,
                now=now,
            )
            if persisted_raw_id != raw_capture_id:
                raise ConflictError("RawCapture identity drifted")
            _persist_snapshot(
                connection,
                result=result,
                raw_capture_id=raw_capture_id,
                artifacts=artifacts,
                now=now,
            )
            _persist_universe(
                connection,
                project_id=project_id,
                result=result,
                artifacts=artifacts,
                universe_id=universe_id,
                universe_hash=universe_hash,
                now=now,
            )
            context_id = _new_context(
                connection,
                project_id=project_id,
                prior=prior,
                snapshot_id=result.snapshot_semantic_id,
                universe_id=universe_id,
                source_type="LOCAL_USER_SUPPLIED",
                now=now,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        read_model = {
            "schema_version": "v3.product-data-read-model/1.0.0",
            "project_id": project_id,
            "project_context_revision_id": context_id,
            "display_name": name,
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
            "source_type": "LOCAL_USER_SUPPLIED",
            "pit_state": "PIT_UNPROVABLE",
            "media_type": intent.media_type,
            "row_count": result.row_count,
            "instrument_count": result.instrument_count,
            "date_coverage_start": min(row.session_date for row in result.rows).isoformat(),
            "date_coverage_end": max(row.session_date for row in result.rows).isoformat(),
            "partition_count": len(result.partitions),
            "universe_role": "USER_DEFINED_STATIC",
            "quality_status": "PASS",
            "validation_profile_id": LOCAL_VALIDATION_PROFILE,
            "capability_reasons": {
                "pit": "PIT_UNPROVABLE",
                "revision": "PROVIDER_REVISION_UNKNOWN",
                "calendar": "OBSERVED_LOCAL_ROWS_NOT_FORMAL_TRADING_CALENDAR",
                "status": "SOURCE_COLUMN_ABSENT_OR_NULL_WHEN_NOT_PROVIDED",
            },
            "volume_unit": "SHARES",
            "amount_unit": "CNY",
            "adjustment": "UNADJUSTED",
            "raw_capture_id": raw_capture_id,
            "raw_content_hash": result.raw_content_hash,
            "snapshot_id": result.snapshot_semantic_id,
            "normalized_payload_hash": result.normalized_payload_hash,
            "universe_version_id": universe_id,
            "imported_at": now,
            "artifact_ids": {RAW_ROLE: raw_artifact_id, **artifacts},
        }
        self.product.execution._publish_artifact_batch(
            payloads=((
                "prv_product_data_read_model_" + result.snapshot_semantic_id,
                canonical_json_bytes(read_model),
                READ_MODEL_ROLE,
                _schema_fingerprint("v3.product-data-read-model/1.0.0"),
            ),),
            references=((project_id, READ_MODEL_ROLE, 0),),
        )
        return read_model

    def import_local_dataset(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        display_name: str,
        source: BinaryIO,
        intent: LocalDataImportIntentV1,
        limits: LocalDataImportLimits = LocalDataImportLimits(),
    ) -> dict[str, Any]:
        name = self._bounded_display_name(display_name)
        prior = _validate_active_context(
            self.product, project_id, project_context_revision_id
        )
        staging = self.product.artifact_store.stage_stream(source, max_bytes=limits.max_bytes)
        try:
            result = _normalize_staged(
                self.product,
                staging.staging_token,
                intent=intent,
                limits=limits,
            )
            if (
                result.raw_content_hash != staging.sha256
                or result.raw_byte_size != staging.byte_size
            ):
                raise LocalDataImportError("parsed local bytes differ from staged source identity")
            raw_publication = self.product.execution._publish_staged_artifact(
                staging=staging,
                provenance_entity_id="prv_product_data_raw_" + result.raw_content_hash,
                role=RAW_ROLE,
                media_type=intent.media_type,
                schema_fingerprint=_schema_fingerprint("local-user-source-v1"),
                references=((project_id, RAW_ROLE),),
            )
        except Exception:
            _discard_stage(self.product, staging.staging_token)
            raise
        return self._persist_normalized_import(
            project_id=project_id,
            prior=prior,
            name=name,
            intent=intent,
            result=result,
            raw_artifact_id=raw_publication.descriptor.artifact_id,
        )

    def import_local_artifact(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        source_ref: Mapping[str, Any],
        limits: LocalDataImportLimits = LocalDataImportLimits(),
    ) -> dict[str, Any]:
        prior = _validate_active_context(
            self.product, project_id, project_context_revision_id
        )
        source = self._require_source_ref(
            project_id=project_id,
            source=source_ref,
            limits=limits,
        )
        intent = LocalDataImportIntentV1(
            media_type=source["media_type"],
            volume_unit=source["volume_unit"],
            amount_unit=source["amount_unit"],
            timezone=source["timezone"],
            adjustment=source["adjustment"],
        )
        with self.product.artifact_store.open_verified(
            source["artifact_id"],
            expected_sha256=source["sha256"],
            expected_byte_size=source["byte_size"],
            max_bytes=limits.max_bytes,
        ) as handle:
            result = _normalize_source(handle, intent=intent, limits=limits)
        if (
            result.raw_content_hash != source["sha256"]
            or result.raw_byte_size != source["byte_size"]
        ):
            raise TruthPreconditionFailedError(
                "normalized source bytes do not match the immutable Artifact ref"
            )
        return self._persist_normalized_import(
            project_id=project_id,
            prior=prior,
            name=source["display_name"],
            intent=intent,
            result=result,
            raw_artifact_id=source["artifact_id"],
        )

    def _prepare_submission(
        self,
        submission: ProductLocalDataSubmission,
    ) -> _PreparedLocalDataRequest:
        self.product.require_project_context_ownership(
            submission.project_id, submission.project_context_revision_id
        )
        if not isinstance(submission.idempotency_key, str) or not submission.idempotency_key.strip():
            raise InvalidArgumentError("idempotency_key is required")
        source_ref = self._require_source_ref(
            project_id=submission.project_id,
            source=submission.source,
            limits=LocalDataImportLimits(),
        )
        semantic = {
            "project_id": submission.project_id,
            "project_context_revision_id": submission.project_context_revision_id,
            "source": source_ref,
        }
        request_hash = _canonical_request_hash(PRODUCT_LOCAL_DATA_OPERATION, semantic)
        return _PreparedLocalDataRequest(
            project_id=submission.project_id,
            project_context_revision_id=submission.project_context_revision_id,
            source_ref=source_ref,
            semantic=semantic,
            request_hash=request_hash,
            scope=self.product.idempotency.scope_key(
                PRODUCT_LOCAL_DATA_OPERATION,
                submission.project_id,
                submission.idempotency_key,
            ),
            execution_deadline_at=submission.execution_deadline_at,
        )

    def _accept_request(self, request: _PreparedLocalDataRequest) -> _LocalDataTaskHandles:
        context_artifact_id = self.product.execution._persist_context_artifact(
            {
                "schema_version": LOCAL_DATA_CONTEXT_SCHEMA_VERSION,
                "context_kind": "PRODUCT_LOCAL_DATA_IMPORT",
                "project_id": request.project_id,
                "project_context_revision_id": request.project_context_revision_id,
                "source_ref": request.source_ref,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "execution_state": "QUEUED_BEFORE_IMPORT",
            },
            provenance="prv_product_local_data_intent_" + request.request_hash,
        )
        return _LocalDataTaskHandles(
            *self.product.execution._create_task(
                operation_id=PRODUCT_LOCAL_DATA_OPERATION,
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                normalized_input_hash=canonical_sha256(request.semantic),
                context_artifact_id=context_artifact_id,
                idempotency=(request.scope, request.request_hash, _accept_outcome_json),
                execution_deadline_at=request.execution_deadline_at,
                inline_worker=False,
                service_contract_version="1.1.0",
            )
        )

    def submit(self, submission: ProductLocalDataSubmission) -> dict[str, Any]:
        request = self._prepare_submission(submission)
        existing = self.product.idempotency.lookup(
            self.product, request.scope, request.request_hash
        )
        if existing is not None:
            return _local_data_accept_outcome(
                str(existing["task_id"]),
                str(existing["run_id"]),
                request.source_ref["artifact_id"],
            )
        _validate_active_context(
            self.product, request.project_id, request.project_context_revision_id
        )
        workers = getattr(self.product, "product_workers", None)
        if workers is None:
            raise CapabilityUnavailableError(
                "isolated Product worker is unavailable for local import",
                details={"reason_code": "PRODUCT_WORKER_NOT_AVAILABLE"},
            )
        reservation = workers.reserve_capacity()
        handles: _LocalDataTaskHandles | None = None
        try:
            handles = self._accept_request(request)
            workers.start(
                request,
                handles,
                reservation_token=reservation,
                operation_id=PRODUCT_LOCAL_DATA_OPERATION,
                work_kind="LOCAL_DATA_IMPORT",
                resource_class="PRODUCT_DATA_CPU",
            )
        except Exception as error:
            workers.release_capacity(reservation)
            if handles is not None:
                self.product.execution._finish_failure(
                    handles.task,
                    handles.run,
                    handles.attempt,
                    error=error,
                    category=classify_execution_error(error),
                )
            raise
        return _local_data_accept_outcome(
            handles.task.task_id,
            handles.run.run_id,
            request.source_ref["artifact_id"],
            event_cursor=self.product.latest_event_sequence(request.project_id),
        )

    def execute_accepted(
        self,
        request: _PreparedLocalDataRequest,
        handles: _LocalDataTaskHandles,
    ) -> dict[str, Any]:
        try:
            imported = self.import_local_artifact(
                project_id=request.project_id,
                project_context_revision_id=request.project_context_revision_id,
                source_ref=request.source_ref,
            )
            self.product.execution._finish_success(
                handles.task,
                handles.run,
                handles.attempt,
                outputs={
                    "snapshot_id": imported["snapshot_id"],
                    "universe_version_id": imported["universe_version_id"],
                    "project_context_revision_id": imported[
                        "project_context_revision_id"
                    ],
                    "raw_artifact_id": request.source_ref["artifact_id"],
                },
            )
            return imported
        except Exception as error:
            self.product.execution._finish_failure(
                handles.task,
                handles.run,
                handles.attempt,
                error=error,
                category=classify_execution_error(error),
            )
            raise

    def get_local_dataset(
        self,
        *,
        project_id: str,
        project_context_revision_id: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        self.product.require_project(project_id)
        context = self.product.require_project_context_ownership(
            project_id, project_context_revision_id
        )
        if context.get("snapshot_id") != snapshot_id:
            raise NotFoundError("local Snapshot is not bound to the requested project context")
        connection = connect_catalog(self.product.database_path, read_only=True)
        try:
            owner = connection.execute(
                """
                SELECT 1
                FROM universe_version AS u
                JOIN universe_definition AS d
                  ON d.universe_definition_id=u.universe_definition_id
                WHERE d.project_id=? AND u.snapshot_id=? AND u.state='PUBLISHED'
                """,
                (project_id, snapshot_id),
            ).fetchone()
            if owner is None:
                raise NotFoundError("local Snapshot is not reachable from the project")
            rows = connection.execute(
                """
                SELECT a.artifact_id
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=? AND r.role=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                ORDER BY r.created_at DESC
                """,
                (project_id, READ_MODEL_ROLE),
            ).fetchall()
            reachable_rows = connection.execute(
                """
                SELECT a.artifact_id,a.sha256,a.semantic_role,a.state,r.role
                FROM artifact AS a
                JOIN artifact_reference AS r ON r.artifact_id=a.artifact_id
                WHERE r.owner_type='Project' AND r.owner_id=?
                  AND r.state='ACTIVE' AND a.state='PUBLISHED'
                """,
                (project_id,),
            ).fetchall()
        finally:
            connection.close()
        reachable = {
            (str(artifact_id), str(reference_role)): (
                str(sha256), str(semantic_role), str(state)
            )
            for artifact_id, sha256, semantic_role, state, reference_role in reachable_rows
        }
        for row in rows:
            try:
                payload = json.loads(
                    self.product.read_verified_bytes(str(row[0])).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
                raise TruthPreconditionFailedError(
                    "local data read-model bytes are invalid"
                ) from error
            if (
                isinstance(payload, dict)
                and payload.get("project_id") == project_id
                and payload.get("project_context_revision_id")
                == project_context_revision_id
                and payload.get("snapshot_id") == snapshot_id
            ):
                artifacts = payload.get("artifact_ids")
                if not isinstance(artifacts, dict) or not artifacts:
                    raise TruthPreconditionFailedError(
                        "local data read model has no closed Artifact identities"
                    )
                for role, artifact_id in artifacts.items():
                    if not isinstance(role, str) or not isinstance(artifact_id, str):
                        raise TruthPreconditionFailedError(
                            "local data read model Artifact identity is malformed"
                        )
                    descriptor = reachable.get((artifact_id, role))
                    expected_semantic_role = (
                        PARTITION_ROLE
                        if role.startswith(PARTITION_ROLE + ":")
                        else role
                    )
                    if (
                        descriptor is None
                        or artifact_id != "art_sha256_" + descriptor[0]
                        or descriptor[1] != expected_semantic_role
                        or descriptor[2] != "PUBLISHED"
                    ):
                        raise TruthPreconditionFailedError(
                            f"local data Artifact {role} is not exactly project-reachable"
                        )
                if artifacts.get(RAW_ROLE) != "art_sha256_" + str(
                    payload.get("raw_content_hash")
                ):
                    raise TruthPreconditionFailedError(
                        "local data raw Artifact identity drifted"
                    )
                if artifacts.get(PARTITION_MANIFEST_ROLE) != "art_sha256_" + str(
                    payload.get("normalized_payload_hash")
                ):
                    raise TruthPreconditionFailedError(
                        "local data manifest Artifact identity drifted"
                    )
                return payload
        raise NotFoundError("local data read model is unavailable")


__all__ = (
    "PRODUCT_LOCAL_DATA_OPERATION",
    "ProductDataService",
    "ProductLocalDataSubmission",
)
