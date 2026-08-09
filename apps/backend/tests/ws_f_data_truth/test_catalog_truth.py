from __future__ import annotations

import hashlib
import sqlite3
import unittest

from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
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
            r.data_truth.declare_capability(
                {
                    "provider_id": "pvd_test",
                    "capability_code": "CN_EOD",
                    "frequency": "1D",
                    "supplies_available_time": 1,
                    "supplies_revisions": 1,
                    "declaration_hash": digest("c"),
                    "declared_at": NOW,
                }
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
            r.data_truth.classify_instrument(
                {
                    "instrument_id": "ins_old",
                    "board": "MAIN",
                    "security_category": "EQUITY",
                    "effective_from": "2010-01-01",
                    "available_time": "2010-01-01T00:00:00Z",
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
    ) -> None:
        r.snapshot.create_candidate(
            {
                "snapshot_id": snapshot_id,
                "connector_version_id": "cov_truth",
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
        r.snapshot.record_validation(
            {
                "snapshot_validation_id": "snv_" + snapshot_id,
                "snapshot_id": snapshot_id,
                "validation_profile_id": "financial-invariants-v1",
                "check_code": "PIT_NO_FUTURE_DATA",
                "state": "PASS",
                "severity": "BLOCKING",
                "report_artifact_id": artifacts["validation"],
                "validated_at": NOW,
            }
        )
        r.snapshot.mark_validated(snapshot_id, validated_at=NOW)
        if publish:
            r.snapshot.publish_validated(
                snapshot_id,
                manifest_artifact_id=artifacts["manifest"],
                content_hash=digest("3"),
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
        with self.assertRaises(sqlite3.IntegrityError):
            with SQLiteUnitOfWork(self.connection) as unit:
                self.registry(unit).snapshot.publish_validated(
                    "snp_missing_time",
                    manifest_artifact_id=artifacts["manifest"],
                    content_hash=digest("3"),
                    published_at=NOW,
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
                    "instrument_id": "ins_old",
                    "effective_from": "2010-01-01",
                    "effective_to": "2021-01-01",
                    "available_time": "2010-01-01T00:00:00Z",
                    "revision_id": "old-v1",
                },
                {
                    "membership_interval_id": "umi_new",
                    "instrument_id": "ins_new",
                    "effective_from": "2021-01-01",
                    "effective_to": None,
                    "available_time": "2021-01-01T00:00:00Z",
                    "revision_id": "new-v1",
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
                    "truth_state": "FORMAL",
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
            self.assertIn(artifacts["manifest"], r.artifact.reachable_set())


if __name__ == "__main__":
    unittest.main()
