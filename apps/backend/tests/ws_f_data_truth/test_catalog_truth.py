from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.domain.data_truth import CapabilityTruthState, PitCapabilityUnavailable
from v3_backend.errors.exceptions import ConflictError

from ws_b_catalog.support import CatalogTestCase, NOW


def digest(symbol: str) -> str:
    return symbol * 64


class DataTruthCatalogTests(CatalogTestCase):
    def seed_truth(self) -> dict[str, str]:
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            self.add_project(r)
            artifacts = {
                key: self.publish_artifact(r, digest(value))["artifact_id"]
                for key, value in {
                    "bundle": "a",
                    "raw": "1",
                    "classification": "2",
                    "manifest": "3",
                    "partition": "4",
                    "validation": "5",
                    "membership": "6",
                    "audit": "7",
                    "calendar": "0",
                }.items()
            }
            r.connector.table("connector").add_new(
                {
                    "connector_id": "con_truth",
                    "stable_name": "truth-port",
                    "publisher": "V3",
                    "state": "REGISTERED",
                    "created_at": NOW,
                }
            )
            r.connector.table("connector_version").add_new(
                {
                    "connector_version_id": "cov_truth",
                    "connector_id": "con_truth",
                    "semantic_version": "1.0.0",
                    "bundle_artifact_id": artifacts["bundle"],
                    "bundle_sha256": digest("a"),
                    "entrypoint": "v3:raw-capture",
                    "declared_manifest_json": {"output": "RAW_CAPTURE_ONLY"},
                    "network_policy": "DENY",
                    "state": "ADMITTED",
                    "created_at": NOW,
                }
            )
            r.data_truth.register_provider(
                {
                    "provider_id": "pvd_test",
                    "stable_name": "TEST",
                    "display_name": "Test Provider",
                    "source_authority": "TEST_FIXTURE",
                    "metadata_json": {"formal": False},
                    "descriptor_hash": digest("b"),
                    "state": "REGISTERED",
                    "created_at": NOW,
                }
            )
            r.connector.set_capability_state(
                {
                    "connector_version_id": "cov_truth",
                    "capability_code": "CN_EOD",
                    "declared_state": "DECLARED",
                    "admitted_truth_state": "FORMAL",
                    "limitation_json": {"scope": "TEST_FIXTURE_ONLY"},
                    "evidence_artifact_id": artifacts["classification"],
                }
            )
            r.data_truth.declare_connector_capability_extension(
                {
                    "connector_version_id": "cov_truth",
                    "capability_code": "CN_EOD",
                    "provider_id": "pvd_test",
                    "logical_dataset": "CN_EOD",
                    "frequency": "1D",
                    "revision_semantics": "REVISION_AWARE",
                    "provenance_required": 1,
                    "policy_artifact_id": artifacts["classification"],
                    "declared_at": NOW,
                }
            )
            r.snapshot.table("snapshot_validation_profile").add_new(
                {
                    "validation_profile_id": "financial-invariants-v1",
                    "admission_state": "PRE_ALPHA",
                    "description": "Complete WS-F financial invariant gate; not external provider admission",
                    "created_at": NOW,
                },
                idempotent=True,
            )
            for check_code in ("PIT_NO_FUTURE_DATA", "SNAPSHOT_ARTIFACT_LINKAGE"):
                r.snapshot.table("snapshot_validation_requirement").add_new(
                    {
                        "validation_profile_id": "financial-invariants-v1",
                        "check_code": check_code,
                        "required_state": "PASS",
                        "severity": "BLOCKING",
                    },
                    idempotent=True,
                )
            r.data_truth.publish_calendar(
                {
                    "calendar_version_id": "tcv_test",
                    "market": "CN_A_SHARE",
                    "timezone": "Asia/Shanghai",
                    "source_artifact_id": artifacts["calendar"],
                    "content_hash": digest("0"),
                    "state": "PUBLISHED",
                    "published_at": NOW,
                }
            )
            r.data_truth.add_session(
                {
                    "trading_session_id": "trs_20200102",
                    "calendar_version_id": "tcv_test",
                    "session_date": "2020-01-02",
                    "is_trading_day": 1,
                    "session_ordinal": 1,
                    "open_time": "2020-01-02T01:30:00Z",
                    "close_time": "2020-01-02T07:00:00Z",
                    "available_time": "2019-12-31T00:00:00Z",
                    "evidence_artifact_id": artifacts["calendar"],
                }
            )
            r.instrument.table("instrument").add_new(
                {
                    "instrument_id": "ins_old",
                    "asset_class": "CN_A_SHARE",
                    "exchange": "SSE",
                    "listing_date": "2010-01-01",
                    "delisting_date": "2020-12-31",
                    "state": "DELISTED",
                    "created_at": NOW,
                }
            )
            r.instrument.table("instrument").add_new(
                {
                    "instrument_id": "ins_new",
                    "asset_class": "CN_A_SHARE",
                    "exchange": "SSE",
                    "listing_date": "2021-01-01",
                    "state": "ACTIVE",
                    "created_at": NOW,
                }
            )
            r.instrument.table("instrument_revision").add_new(
                {
                    "instrument_revision_id": "inr_old_v1",
                    "instrument_id": "ins_old",
                    "revision_no": 1,
                    "effective_from": "2010-01-01",
                    "available_time": "2010-01-01T00:00:00Z",
                    "revision_id": "old-classification-v1",
                    "name": "Old Test Instrument",
                    "lifecycle_json": {"board": "MAIN", "security_category": "EQUITY"},
                    "provider": "TEST",
                    "ingested_at": "2010-01-01T00:01:00Z",
                    "content_hash": digest("2"),
                    "evidence_artifact_id": artifacts["classification"],
                }
            )
            r.data_truth.submit_raw_capture(
                {
                    "raw_capture_id": "raw_truth",
                    "connector_version_id": "cov_truth",
                    "provider_id": "pvd_test",
                    "provider_dataset": "CN_EOD",
                    "source_metadata_json": {"request": "fixture"},
                    "provenance_complete": 1,
                    "request_fingerprint": digest("d"),
                    "effective_range_start": "2020-01-02T15:00:00Z",
                    "effective_range_end": "2020-01-02T15:00:00Z",
                    "available_time": "2020-01-03T08:00:00Z",
                    "captured_at": "2020-01-03T08:00:00Z",
                    "ingested_at": "2020-01-03T08:01:00Z",
                    "artifact_id": artifacts["raw"],
                    "content_hash": digest("1"),
                    "state": "CAPTURED",
                }
            )
            r.data_truth.accept_raw_capture("raw_truth")
            self.create_snapshot(r, "snp_truth", artifacts)
            r.artifact.bind_artifact(
                artifact_reference_id="arf_snapshot_manifest",
                owner_type="DataSnapshotVersion",
                owner_id="snp_truth",
                role="MANIFEST",
                artifact_id=artifacts["manifest"],
                created_at=NOW,
            )
        return artifacts

    def create_snapshot(
        self,
        r: SQLiteRepositoryRegistry,
        snapshot_id: str,
        artifacts: dict[str, str],
        *,
        publish: bool = True,
        raw_capture_id: str = "raw_truth",
        connector_version_id: str = "cov_truth",
    ) -> None:
        r.snapshot.create_candidate(
            {
                "snapshot_id": snapshot_id,
                "connector_version_id": connector_version_id,
                "normalization_spec_version": "canonical-eod-v1",
                "truth_profile_id": "STRICT_PIT",
                "state": "CANDIDATE",
                "created_at": NOW,
            }
        )
        r.data_truth.link_snapshot_source(
            {
                "snapshot_id": snapshot_id,
                "raw_capture_id": raw_capture_id,
                "logical_dataset": "CN_EOD",
                "linked_at": NOW,
            }
        )
        r.data_truth.link_snapshot_calendar(
            {
                "snapshot_id": snapshot_id,
                "calendar_version_id": "tcv_test",
                "linked_at": NOW,
            }
        )
        r.snapshot.table("snapshot_partition").add_new(
            {
                "snapshot_id": snapshot_id,
                "logical_dataset": "CN_EOD",
                "partition_key": "2020-01-02",
                "parquet_artifact_id": artifacts["partition"],
                "row_count": 1,
                "schema_fingerprint": digest("e"),
                "min_effective_time": "2020-01-02T15:00:00Z",
                "max_effective_time": "2020-01-02T15:00:00Z",
                "max_available_time": "2020-01-03T08:00:00Z",
            }
        )
        for suffix, check_code in (
            ("pit", "PIT_NO_FUTURE_DATA"),
            ("artifact", "SNAPSHOT_ARTIFACT_LINKAGE"),
        ):
            r.snapshot.record_validation(
                {
                    "snapshot_validation_id": f"snv_{suffix}_{snapshot_id}",
                    "snapshot_id": snapshot_id,
                    "validation_profile_id": "financial-invariants-v1",
                    "check_code": check_code,
                    "state": "PASS",
                    "severity": "BLOCKING",
                    "report_artifact_id": artifacts["validation"],
                    "validated_at": NOW,
                }
            )
        r.snapshot.mark_validated(
            snapshot_id,
            validation_profile_id="financial-invariants-v1",
            validated_at=NOW,
        )
        if publish:
            r.snapshot.publish_validated(
                snapshot_id,
                manifest_artifact_id=artifacts["manifest"],
                content_hash=digest("3"),
                published_at=NOW,
            )

    def add_connector_version(
        self,
        r: SQLiteRepositoryRegistry,
        connector_version_id: str,
        semantic_version: str,
        artifacts: dict[str, str],
        *,
        capability_code: str | None = "CN_EOD",
        admitted_truth_state: str = "FORMAL",
        revision_semantics: str = "REVISION_AWARE",
    ) -> None:
        r.connector.table("connector_version").add_new(
            {
                "connector_version_id": connector_version_id,
                "connector_id": "con_truth",
                "semantic_version": semantic_version,
                "bundle_artifact_id": artifacts["bundle"],
                "bundle_sha256": digest("a"),
                "entrypoint": "v3:raw-capture",
                "declared_manifest_json": {"output": "RAW_CAPTURE_ONLY"},
                "network_policy": "DENY",
                "state": "ADMITTED",
                "created_at": NOW,
            }
        )
        if capability_code is None:
            return
        r.connector.set_capability_state(
            {
                "connector_version_id": connector_version_id,
                "capability_code": capability_code,
                "declared_state": "DECLARED",
                "admitted_truth_state": admitted_truth_state,
                "limitation_json": {"scope": "TEST_FIXTURE_ONLY"},
                "evidence_artifact_id": artifacts["classification"],
            }
        )
        r.data_truth.declare_connector_capability_extension(
            {
                "connector_version_id": connector_version_id,
                "capability_code": capability_code,
                "provider_id": "pvd_test",
                "logical_dataset": capability_code,
                "frequency": "1D",
                "revision_semantics": revision_semantics,
                "provenance_required": 1,
                "policy_artifact_id": artifacts["classification"],
                "declared_at": NOW,
            }
        )

    def create_universe_version(
        self,
        r: SQLiteRepositoryRegistry,
        universe_version_id: str,
        *,
        knowledge_cutoff: str,
        artifacts: dict[str, str],
        memberships: tuple[dict[str, object], ...],
        snapshot_id: str = "snp_truth",
    ) -> None:
        definition_id = "und_" + universe_version_id.removeprefix("unv_")
        r.universe.publish_version(
            "universe_definition",
            {
                "universe_definition_id": definition_id,
                "project_id": "prj_test",
                "constructor_kind": "INDEX",
                "definition_json": {"fixture": universe_version_id},
                "canonical_hash": hashlib.sha256(universe_version_id.encode()).hexdigest(),
                "state": "PUBLISHED",
                "created_at": NOW,
            },
        )
        r.universe.table("universe_version").add_new(
            {
                "universe_version_id": universe_version_id,
                "universe_definition_id": definition_id,
                "snapshot_id": snapshot_id,
                "knowledge_cutoff": knowledge_cutoff,
                "state": "BUILDING",
            }
        )
        for membership in memberships:
            r.data_truth.add_membership_interval(
                {
                    **membership,
                    "universe_version_id": universe_version_id,
                    "provenance_artifact_id": artifacts["membership"],
                }
            )
        r.data_truth.publish_universe_version(
            universe_version_id,
            membership_artifact_id=artifacts["membership"],
            audit_artifact_id=artifacts["audit"],
            content_hash=digest("6"),
            published_at=NOW,
        )

    def test_snapshot_is_immutable_and_artifact_linkage_is_exact(self) -> None:
        artifacts = self.seed_truth()
        row = self.connection.execute(
            "SELECT state,manifest_artifact_id,content_hash FROM data_snapshot WHERE snapshot_id='snp_truth'"
        ).fetchone()
        self.assertEqual(tuple(row), ("PUBLISHED", artifacts["manifest"], digest("3")))
        partition = self.connection.execute(
            "SELECT parquet_artifact_id FROM snapshot_partition WHERE snapshot_id='snp_truth'"
        ).fetchone()
        self.assertEqual(partition[0], artifacts["partition"])
        self.assertEqual(
            self.connection.execute(
                "SELECT state FROM artifact WHERE artifact_id=?", (partition[0],)
            ).fetchone()[0],
            "PUBLISHED",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE data_snapshot SET content_hash=? WHERE snapshot_id='snp_truth'",
                (digest("f"),),
            )

    def test_snapshot_publication_is_atomic(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            self.create_snapshot(self.registry(unit), "snp_atomic", artifacts, publish=False)
        with self.assertRaises(RuntimeError):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.registry(unit).snapshot.publish_validated(
                    "snp_atomic",
                    manifest_artifact_id=artifacts["manifest"],
                    content_hash=digest("3"),
                    published_at=NOW,
                )
                raise RuntimeError("force rollback")
        self.assertEqual(
            self.connection.execute(
                "SELECT state FROM data_snapshot WHERE snapshot_id='snp_atomic'"
            ).fetchone()[0],
            "VALIDATED",
        )

    def test_snapshot_validation_requires_complete_registered_profile(self) -> None:
        artifacts = self.seed_truth()
        with self.assertRaises(ConflictError):
            with SQLiteUnitOfWork(self.connection) as unit:
                r = self.registry(unit)
                r.snapshot.create_candidate(
                    {
                        "snapshot_id": "snp_incomplete_validation",
                        "connector_version_id": "cov_truth",
                        "normalization_spec_version": "canonical-eod-v1",
                        "truth_profile_id": "STRICT_PIT",
                        "state": "CANDIDATE",
                        "created_at": NOW,
                    }
                )
                r.snapshot.record_validation(
                    {
                        "snapshot_validation_id": "snv_incomplete_pit",
                        "snapshot_id": "snp_incomplete_validation",
                        "validation_profile_id": "financial-invariants-v1",
                        "check_code": "PIT_NO_FUTURE_DATA",
                        "state": "PASS",
                        "severity": "BLOCKING",
                        "report_artifact_id": artifacts["validation"],
                        "validated_at": NOW,
                    }
                )
                r.snapshot.mark_validated(
                    "snp_incomplete_validation",
                    validation_profile_id="financial-invariants-v1",
                    validated_at=NOW,
                )
        profile_state = self.connection.execute(
            """
            SELECT admission_state FROM snapshot_validation_profile
            WHERE validation_profile_id='financial-invariants-v1'
            """
        ).fetchone()[0]
        self.assertEqual(profile_state, "PRE_ALPHA")

    def test_snapshot_validation_requires_matching_blocking_severity(self) -> None:
        artifacts = self.seed_truth()
        with self.assertRaises(ConflictError):
            with SQLiteUnitOfWork(self.connection) as unit:
                r = self.registry(unit)
                r.snapshot.create_candidate(
                    {
                        "snapshot_id": "snp_wrong_validation_severity",
                        "connector_version_id": "cov_truth",
                        "normalization_spec_version": "canonical-eod-v1",
                        "truth_profile_id": "STRICT_PIT",
                        "state": "CANDIDATE",
                        "created_at": NOW,
                    }
                )
                for suffix, check_code, severity in (
                    ("pit", "PIT_NO_FUTURE_DATA", "INFO"),
                    ("artifact", "SNAPSHOT_ARTIFACT_LINKAGE", "BLOCKING"),
                ):
                    r.snapshot.record_validation(
                        {
                            "snapshot_validation_id": (
                                f"snv_wrong_severity_{suffix}"
                            ),
                            "snapshot_id": "snp_wrong_validation_severity",
                            "validation_profile_id": "financial-invariants-v1",
                            "check_code": check_code,
                            "state": "PASS",
                            "severity": severity,
                            "report_artifact_id": artifacts["validation"],
                            "validated_at": NOW,
                        }
                    )
                r.snapshot.mark_validated(
                    "snp_wrong_validation_severity",
                    validation_profile_id="financial-invariants-v1",
                    validated_at=NOW,
                )

    def test_missing_provider_available_time_blocks_strict_snapshot(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            missing_artifact = self.publish_artifact(r, digest("8"))["artifact_id"]
            r.data_truth.submit_raw_capture(
                {
                    "raw_capture_id": "raw_missing_time",
                    "connector_version_id": "cov_truth",
                    "provider_id": "pvd_test",
                    "provider_dataset": "CN_EOD",
                    "source_metadata_json": {"missing": "provider_available_time"},
                    "provenance_complete": 1,
                    "request_fingerprint": digest("8"),
                    "effective_range_start": "2020-01-03T15:00:00Z",
                    "effective_range_end": "2020-01-03T15:00:00Z",
                    "available_time": None,
                    "captured_at": "2020-01-04T08:00:00Z",
                    "ingested_at": "2020-01-04T08:01:00Z",
                    "artifact_id": missing_artifact,
                    "content_hash": digest("8"),
                    "state": "CAPTURED",
                }
            )
            r.data_truth.accept_raw_capture("raw_missing_time")
            self.create_snapshot(
                r,
                "snp_missing_time",
                artifacts,
                publish=False,
                raw_capture_id="raw_missing_time",
            )
        with self.assertRaises(PitCapabilityUnavailable):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.registry(unit).snapshot.publish_validated(
                    "snp_missing_time",
                    manifest_artifact_id=artifacts["manifest"],
                    content_hash=digest("3"),
                    published_at=NOW,
                )

    def test_connector_version_capability_is_single_authority_and_fail_closed(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            self.add_connector_version(
                r, "cov_truth_v2", "2.0.0", artifacts, capability_code=None
            )
            v1 = r.data_truth.resolve_connector_capability("cov_truth", "CN_EOD")
            v2 = r.data_truth.resolve_connector_capability("cov_truth_v2", "CN_EOD")
            missing = r.data_truth.resolve_connector_capability(
                "cov_truth", "CN_CORPORATE_ACTION"
            )
            self.assertEqual(v1.truth_state, CapabilityTruthState.FORMAL)
            self.assertEqual(v1.reason_code, "EXACT_CONNECTOR_VERSION_ADMITTED")
            self.assertEqual(v2.truth_state, CapabilityTruthState.UNAVAILABLE)
            self.assertEqual(missing.truth_state, CapabilityTruthState.UNAVAILABLE)
        tables = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertNotIn("provider_capability", tables)
        self.assertIn("connector_capability", tables)

    def test_capability_extension_cannot_shadow_missing_authority(self) -> None:
        artifacts = self.seed_truth()
        with self.assertRaises(ConflictError):
            with SQLiteUnitOfWork(self.connection) as unit:
                r = self.registry(unit)
                self.add_connector_version(
                    r, "cov_no_authority", "3.0.0", artifacts, capability_code=None
                )
                r.data_truth.declare_connector_capability_extension(
                    {
                        "connector_version_id": "cov_no_authority",
                        "capability_code": "CN_EOD",
                        "provider_id": "pvd_test",
                        "logical_dataset": "CN_EOD",
                        "frequency": "1D",
                        "revision_semantics": "REVISION_AWARE",
                        "provenance_required": 1,
                        "policy_artifact_id": artifacts["classification"],
                        "declared_at": NOW,
                    }
                )

    def test_available_time_with_unknown_revision_semantics_is_not_strict_pit(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            self.add_connector_version(
                r,
                "cov_unknown_revision",
                "4.0.0",
                artifacts,
                revision_semantics="UNKNOWN",
            )
            unknown_raw = self.publish_artifact(r, digest("8"))["artifact_id"]
            r.data_truth.submit_raw_capture(
                {
                    "raw_capture_id": "raw_unknown_revision",
                    "connector_version_id": "cov_unknown_revision",
                    "provider_id": "pvd_test",
                    "provider_dataset": "CN_EOD",
                    "source_metadata_json": {"revision_semantics": "UNKNOWN"},
                    "provenance_complete": 1,
                    "request_fingerprint": digest("8"),
                    "effective_range_start": "2020-01-03T15:00:00Z",
                    "effective_range_end": "2020-01-03T15:00:00Z",
                    "available_time": "2020-01-04T08:00:00Z",
                    "captured_at": "2020-01-04T08:00:00Z",
                    "ingested_at": "2020-01-04T08:01:00Z",
                    "artifact_id": unknown_raw,
                    "content_hash": digest("8"),
                    "state": "CAPTURED",
                }
            )
            r.data_truth.accept_raw_capture("raw_unknown_revision")
            resolved = r.data_truth.resolve_connector_capability(
                "cov_unknown_revision", "CN_EOD"
            )
            self.assertEqual(resolved.truth_state, CapabilityTruthState.UNAVAILABLE)
            self.assertEqual(resolved.reason_code, "REVISION_SEMANTICS_UNKNOWN")
        with self.assertRaises(PitCapabilityUnavailable):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.create_snapshot(
                    self.registry(unit),
                    "snp_unknown_revision",
                    artifacts,
                    raw_capture_id="raw_unknown_revision",
                    connector_version_id="cov_unknown_revision",
                )

    def test_snapshot_rejects_raw_capture_from_wrong_connector_version(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            self.add_connector_version(
                self.registry(unit), "cov_other", "5.0.0", artifacts
            )
        with self.assertRaises(PitCapabilityUnavailable):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.create_snapshot(
                    self.registry(unit),
                    "snp_wrong_connector",
                    artifacts,
                    raw_capture_id="raw_truth",
                    connector_version_id="cov_other",
                )

    def test_raw_capture_missing_availability_is_null_not_sentinel(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            raw_artifact = self.publish_artifact(r, digest("f"))["artifact_id"]
            r.data_truth.submit_raw_capture(
                {
                    "raw_capture_id": "raw_null_availability",
                    "connector_version_id": "cov_truth",
                    "provider_id": "pvd_test",
                    "provider_dataset": "CN_EOD",
                    "source_metadata_json": {"available_time": None},
                    "provenance_complete": 1,
                    "request_fingerprint": digest("f"),
                    "available_time": None,
                    "captured_at": "2020-01-04T08:00:00Z",
                    "ingested_at": "2020-01-04T08:01:00Z",
                    "artifact_id": raw_artifact,
                    "content_hash": digest("f"),
                    "state": "CAPTURED",
                }
            )
        value = self.connection.execute(
            "SELECT available_time FROM raw_capture WHERE raw_capture_id='raw_null_availability'"
        ).fetchone()[0]
        self.assertIsNone(value)
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM raw_capture WHERE available_time='UNAVAILABLE'"
            ).fetchone()[0],
            0,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE raw_capture SET available_time='UNAVAILABLE' WHERE raw_capture_id='raw_null_availability'"
            )

    def test_instrument_classification_revisions_are_bitemporal_and_immutable(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            r.instrument.table("instrument").add_new(
                {
                    "instrument_id": "ins_revision",
                    "asset_class": "CN_A_SHARE",
                    "exchange": "SSE",
                    "listing_date": "2020-01-01",
                    "state": "ACTIVE",
                    "created_at": NOW,
                }
            )
            for revision_no, revision_id, available_time, board in (
                (1, "r1", "2020-01-02T00:00:00Z", "MAIN"),
                (2, "r2", "2020-02-01T00:00:00Z", "STAR"),
            ):
                r.instrument.table("instrument_revision").add_new(
                    {
                        "instrument_revision_id": f"inr_classification_{revision_id}",
                        "instrument_id": "ins_revision",
                        "revision_no": revision_no,
                        "effective_from": "2020-01-01",
                        "available_time": available_time,
                        "revision_id": revision_id,
                        "name": "Revision Test",
                        "lifecycle_json": {
                            "board": board,
                            "security_category": "EQUITY",
                        },
                        "provider": "TEST",
                        "ingested_at": available_time,
                        "content_hash": hashlib.sha256(revision_id.encode()).hexdigest(),
                        "evidence_artifact_id": artifacts["classification"],
                    }
                )
            early = r.data_truth.resolve_instrument_revision_as_of(
                "ins_revision",
                as_of="2020-01-10",
                decision_time="2020-01-15T00:00:00Z",
            )
            late = r.data_truth.resolve_instrument_revision_as_of(
                "ins_revision",
                as_of="2020-01-10",
                decision_time="2020-02-15T00:00:00Z",
            )
            self.assertEqual(early["revision_id"], "r1")
            self.assertEqual(late["revision_id"], "r2")
            self.assertEqual(json.loads(late["lifecycle_json"])["board"], "STAR")
            self.assertEqual(
                self.connection.execute(
                    "SELECT COUNT(*) FROM instrument_revision WHERE instrument_id='ins_revision'"
                ).fetchone()[0],
                2,
            )
            r.instrument.table("instrument_revision").add_new(
                {
                    "instrument_revision_id": "inr_classification_ambiguous",
                    "instrument_id": "ins_revision",
                    "revision_no": 3,
                    "effective_from": "2019-12-01",
                    "available_time": "2020-01-03T00:00:00Z",
                    "revision_id": "ambiguous",
                    "name": "Ambiguous Revision Test",
                    "lifecycle_json": {
                        "board": "MAIN",
                        "security_category": "EQUITY",
                    },
                    "provider": "TEST",
                    "ingested_at": "2020-01-03T00:00:00Z",
                    "content_hash": hashlib.sha256(b"ambiguous").hexdigest(),
                    "evidence_artifact_id": artifacts["classification"],
                }
            )
            with self.assertRaises(PitCapabilityUnavailable):
                r.data_truth.resolve_instrument_revision_as_of(
                    "ins_revision",
                    as_of="2020-01-10",
                    decision_time="2020-02-15T00:00:00Z",
                )

    def test_universe_revisions_and_knowledge_cutoff_fail_closed(self) -> None:
        artifacts = self.seed_truth()
        base_rows = (
            {
                "membership_interval_id": "umi_cutoff_r1",
                "membership_fact_id": "umf_cutoff",
                "instrument_id": "ins_old",
                "effective_from": "2020-01-01",
                "available_time": "2020-01-02T00:00:00Z",
                "revision_id": "r1",
                "membership_state": "INCLUDED",
            },
            {
                "membership_interval_id": "umi_cutoff_r2",
                "membership_fact_id": "umf_cutoff",
                "instrument_id": "ins_old",
                "effective_from": "2020-01-01",
                "available_time": "2020-02-01T00:00:00Z",
                "revision_id": "r2",
                "membership_state": "INCLUDED",
            },
        )
        new_rows = tuple(
            {**row, "membership_interval_id": str(row["membership_interval_id"]) + "_new"}
            for row in base_rows
        )
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            self.create_universe_version(
                r,
                "unv_cutoff_old",
                knowledge_cutoff="2020-01-31T23:59:59Z",
                artifacts=artifacts,
                memberships=base_rows,
            )
            self.create_universe_version(
                r,
                "unv_cutoff_new",
                knowledge_cutoff="2020-02-28T23:59:59Z",
                artifacts=artifacts,
                memberships=new_rows,
            )
            jan = r.data_truth.resolve_members_as_of(
                "unv_cutoff_old",
                as_of="2020-01-10",
                decision_time="2020-01-15T00:00:00Z",
            )
            old_at_cutoff = r.data_truth.resolve_members_as_of(
                "unv_cutoff_old",
                as_of="2020-01-10",
                decision_time="2020-01-31T00:00:00Z",
            )
            feb = r.data_truth.resolve_members_as_of(
                "unv_cutoff_new",
                as_of="2020-01-10",
                decision_time="2020-02-15T00:00:00Z",
            )
            self.assertEqual([row["revision_id"] for row in jan], ["r1"])
            self.assertEqual([row["revision_id"] for row in old_at_cutoff], ["r1"])
            self.assertEqual([row["revision_id"] for row in feb], ["r2"])
            self.assertEqual(jan.audit["knowledge_cutoff"], "2020-01-31T23:59:59Z")
            self.assertEqual(
                jan.audit["selected_revisions"],
                (
                    {
                        "membership_fact_id": "umf_cutoff",
                        "instrument_id": "ins_old",
                        "revision_id": "r1",
                        "available_time": "2020-01-02T00:00:00Z",
                        "provenance_artifact_id": artifacts["membership"],
                    },
                ),
            )
            with self.assertRaises(PitCapabilityUnavailable):
                r.data_truth.resolve_members_as_of(
                    "unv_cutoff_old",
                    as_of="2020-01-10",
                    decision_time="2020-02-15T00:00:00Z",
                )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM universe_membership_interval WHERE membership_fact_id='umf_cutoff'"
            ).fetchone()[0],
            4,
        )

    def test_universe_revision_ambiguity_fails_closed(self) -> None:
        artifacts = self.seed_truth()
        rows = tuple(
            {
                "membership_interval_id": f"umi_ambiguous_{revision}",
                "membership_fact_id": "umf_ambiguous",
                "instrument_id": "ins_old",
                "effective_from": "2020-01-01",
                "available_time": "2020-01-02T00:00:00Z",
                "revision_id": revision,
                "membership_state": "INCLUDED",
            }
            for revision in ("r1", "r2")
        )
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            self.create_universe_version(
                r,
                "unv_ambiguous",
                knowledge_cutoff="2020-12-31T23:59:59Z",
                artifacts=artifacts,
                memberships=rows,
            )
            with self.assertRaises(PitCapabilityUnavailable):
                r.data_truth.resolve_members_as_of(
                    "unv_ambiguous",
                    as_of="2020-01-10",
                    decision_time="2020-01-15T00:00:00Z",
                )

    def test_universe_resolution_requires_exact_published_bound_snapshot(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            r.snapshot.create_candidate(
                {
                    "snapshot_id": "snp_unpublished_bound",
                    "connector_version_id": "cov_truth",
                    "normalization_spec_version": "canonical-eod-v1",
                    "truth_profile_id": "STRICT_PIT",
                    "state": "CANDIDATE",
                    "created_at": NOW,
                }
            )
            self.create_universe_version(
                r,
                "unv_unpublished_bound",
                knowledge_cutoff="2020-12-31T23:59:59Z",
                artifacts=artifacts,
                snapshot_id="snp_unpublished_bound",
                memberships=(
                    {
                        "membership_interval_id": "umi_unpublished_bound",
                        "membership_fact_id": "umf_unpublished_bound",
                        "instrument_id": "ins_old",
                        "effective_from": "2020-01-01",
                        "available_time": "2020-01-02T00:00:00Z",
                        "revision_id": "r1",
                        "membership_state": "INCLUDED",
                    },
                ),
            )
            with self.assertRaises(PitCapabilityUnavailable):
                r.data_truth.resolve_members_as_of(
                    "unv_unpublished_bound",
                    as_of="2020-01-10",
                    decision_time="2020-01-15T00:00:00Z",
                )

    def test_project_pin_does_not_auto_upgrade(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            first = r.project.append_revision(
                {
                    "project_context_revision_id": "pcr_pin_1",
                    "project_id": "prj_test",
                    "connector_version_id": "cov_truth",
                    "snapshot_id": "snp_truth",
                    "context_json": {"snapshot_id": "snp_truth"},
                    "canonical_hash": hashlib.sha256(b"pin-1").hexdigest(),
                    "created_by": "test",
                    "created_at": NOW,
                },
                base_revision_id=None,
            )
            self.create_snapshot(r, "snp_upgrade", artifacts)
            self.assertEqual(
                r.project.get_current_revision("prj_test")["project_context_revision_id"],
                first["project_context_revision_id"],
            )
            self.assertEqual(r.project.get_current_revision("prj_test")["snapshot_id"], "snp_truth")

    def test_historical_universe_persists_across_restart(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            r.universe.publish_version(
                "universe_definition",
                {
                    "universe_definition_id": "und_history",
                    "project_id": "prj_test",
                    "constructor_kind": "INDEX",
                    "definition_json": {"index": "TEST"},
                    "canonical_hash": digest("9"),
                    "state": "PUBLISHED",
                    "created_at": NOW,
                },
            )
            r.universe.table("universe_version").add_new(
                {
                    "universe_version_id": "unv_history",
                    "universe_definition_id": "und_history",
                    "snapshot_id": "snp_truth",
                    "knowledge_cutoff": "2026-01-01T00:00:00Z",
                    "state": "BUILDING",
                }
            )
            for row in (
                {
                    "membership_interval_id": "umi_old",
                    "membership_fact_id": "umf_old",
                    "instrument_id": "ins_old",
                    "effective_from": "2010-01-01",
                    "effective_to": "2021-01-01",
                    "available_time": "2010-01-01T00:00:00Z",
                    "revision_id": "old-v1",
                    "membership_state": "INCLUDED",
                },
                {
                    "membership_interval_id": "umi_new",
                    "membership_fact_id": "umf_new",
                    "instrument_id": "ins_new",
                    "effective_from": "2021-01-01",
                    "effective_to": None,
                    "available_time": "2021-01-01T00:00:00Z",
                    "revision_id": "new-v1",
                    "membership_state": "INCLUDED",
                },
            ):
                r.data_truth.add_membership_interval(
                    {
                        **row,
                        "universe_version_id": "unv_history",
                        "provenance_artifact_id": artifacts["membership"],
                    }
                )
            r.data_truth.publish_universe_version(
                "unv_history",
                membership_artifact_id=artifacts["membership"],
                audit_artifact_id=artifacts["audit"],
                content_hash=digest("6"),
                published_at=NOW,
            )
            old = r.data_truth.resolve_members_as_of(
                "unv_history", as_of="2020-06-30", decision_time="2020-06-30T23:00:00Z"
            )
            new = r.data_truth.resolve_members_as_of(
                "unv_history", as_of="2022-06-30", decision_time="2022-06-30T23:00:00Z"
            )
            self.assertEqual([row["instrument_id"] for row in old], ["ins_old"])
            self.assertEqual([row["instrument_id"] for row in new], ["ins_new"])
            self.assertEqual(old.audit["snapshot_id"], "snp_truth")
        self.connection.close()
        self.connection = connect_catalog(self.database_path)
        with SQLiteUnitOfWork(self.connection) as unit:
            persisted = self.registry(unit).data_truth.resolve_members_as_of(
                "unv_history", as_of="2020-06-30", decision_time="2020-06-30T23:00:00Z"
            )
            self.assertEqual([row["instrument_id"] for row in persisted], ["ins_old"])

    def test_snapshot_task_run_and_artifact_provenance_are_linked(self) -> None:
        artifacts = self.seed_truth()
        with SQLiteUnitOfWork(self.connection) as unit:
            r = self.registry(unit)
            context = r.project.append_revision(
                {
                    "project_context_revision_id": "pcr_provenance",
                    "project_id": "prj_test",
                    "connector_version_id": "cov_truth",
                    "snapshot_id": "snp_truth",
                    "context_json": {"snapshot_id": "snp_truth"},
                    "canonical_hash": hashlib.sha256(b"provenance-context").hexdigest(),
                    "created_by": "test",
                    "created_at": NOW,
                },
                base_revision_id=None,
            )
            task, run = r.task.create_task_and_run(
                {
                    "task_id": "tsk_truth",
                    "project_id": "prj_test",
                    "service_name": "DataSnapshotService",
                    "operation_id": "DataSnapshotService.v1.createSnapshotCandidate",
                    "task_type": "DATA_TRUTH",
                    "display_name": "Normalize raw capture",
                    "truth_state": "DEMO",
                    "state": "SUCCEEDED",
                    "created_by": "test",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "terminal_at": NOW,
                },
                {
                    "run_id": "run_truth",
                    "task_id": "tsk_truth",
                    "run_no": 1,
                    "project_context_revision_id": context["project_context_revision_id"],
                    "canonical_input_json": {"raw_capture_ids": ["raw_truth"]},
                    "input_hash": digest("a"),
                    "code_version": "ws-f-v1",
                    "environment_profile_id": "core-stdlib",
                    "state": "TERMINAL",
                    "created_at": NOW,
                    "terminal_at": NOW,
                },
            )
            entities = (
                ("prv_raw", "RawCapture", "raw_truth", digest("1")),
                ("prv_task", "Task", task["task_id"], digest("b")),
                ("prv_run", "Run", run["run_id"], digest("a")),
                ("prv_snapshot", "DataSnapshotVersion", "snp_truth", digest("3")),
            )
            for entity_id, subject_type, subject_id, content_hash in entities:
                r.provenance.record_entity_once(
                    {
                        "provenance_entity_id": entity_id,
                        "subject_type": subject_type,
                        "subject_id": subject_id,
                        "canonical_hash": content_hash,
                        "code_version": "ws-f-v1",
                        "environment_profile_id": "core-stdlib",
                        "actor": "test",
                        "recorded_at": NOW,
                    }
                )
            for edge_id, source, relation in (
                ("pre_raw_snapshot", "prv_raw", "DERIVED_FROM"),
                ("pre_task_snapshot", "prv_task", "GENERATED_BY"),
                ("pre_run_snapshot", "prv_run", "EXECUTED_WITH"),
            ):
                r.provenance.record_edge_once(
                    {
                        "provenance_edge_id": edge_id,
                        "from_entity_id": source,
                        "relation": relation,
                        "to_entity_id": "prv_snapshot",
                        "recorded_at": NOW,
                    }
                )
            ancestors = r.provenance.walk_ancestors("prv_snapshot")
            self.assertEqual(
                {row["subject_id"] for row in ancestors},
                {"raw_truth", "tsk_truth", "run_truth"},
            )
            self.assertEqual(
                self.connection.execute(
                    "SELECT connector_version_id FROM raw_capture WHERE raw_capture_id='raw_truth'"
                ).fetchone()[0],
                context["connector_version_id"],
            )
            self.assertIn(artifacts["manifest"], r.artifact.reachable_set())


if __name__ == "__main__":
    unittest.main()
