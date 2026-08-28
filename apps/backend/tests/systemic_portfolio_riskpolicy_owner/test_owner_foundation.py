from __future__ import annotations

import dataclasses
import inspect
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from track_f_strategy_runtime.helpers import build_runtime_fixture
from v3_backend.adapters.sqlite.portfolio_risk_owner import (
    SQLitePortfolioRiskPolicyOwner,
)
from v3_backend.adapters.sqlite.connection import connect_catalog
from v3_backend.domain.artifacts.identity import storage_key_for_artifact_id
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
    PayloadResolutionRequest,
)
from v3_backend.domain.portfolio_construction import (
    CanonicalPortfolioOwnerService,
    ConstructionMethod,
    PortfolioConstructionSpecVersion,
    TargetWeightOwnerAuthorityError,
)
from v3_backend.domain.portfolio_construction.owner import (
    TARGET_WEIGHT_OWNER_NAMESPACE,
    TARGET_WEIGHT_PAYLOAD_ROLE,
)
from v3_backend.domain.risk_runtime import (
    CanonicalRiskPolicyAuthoringService,
    GrossNetExposureValidatePolicyInput,
    MaxSingleNamePolicyInput,
    PassThroughPolicyInput,
    RiskPolicyDefinition,
    RiskPolicyOwnerAuthorityError,
    RiskPolicySetVersion,
    RiskRuntimeError,
)
from v3_backend.domain.risk_runtime.authoring import (
    RISK_POLICY_OWNER_NAMESPACE,
    RISK_POLICY_PAYLOAD_ROLE,
)
from v3_backend.domain.strategies import DeterministicStrategyEvaluator
from v3_backend.domain.weights import RuntimeIdentity
from v3_backend.migrations import apply_migrations, discover_migrations
from v3_backend.migrations.runner import _apply_one


NOW = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)


class OwnerFoundationFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "catalog.sqlite3"
        self.artifact_root = self.root / "artifacts"
        apply_migrations(self.database, application_version="owner-foundation-test")
        self._insert_project_context("prj_owner", "pcr_owner", "1" * 64)
        self._insert_project_context("prj_other", "pcr_other", "2" * 64)
        self.owner = SQLitePortfolioRiskPolicyOwner(self.database, self.artifact_root)

        self.fixture = build_runtime_fixture()
        evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            inputs=(self.fixture.runtime_input,),
        )
        assert evaluation.portfolio_intent is not None
        self.intent = evaluation.portfolio_intent
        self.runtime = RuntimeIdentity(
            code_version="git:owner-foundation-test",
            runtime_profile_id="v3.portfolio-risk-owner-test/1.0.0",
            environment_fingerprint="cpython-3.14-test",
        )
        self.spec = PortfolioConstructionSpecVersion.create(
            method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
            method_version="1.0.0",
            target_cash_weight="0.1",
            max_instrument_weight="1",
            runtime_identity=self.runtime,
        )
        self.as_of = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        self.decision_time = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
        self.rebalance_time = datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)
        self.valid_until = datetime(2026, 1, 6, 7, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _insert_project_context(
        self, project_id: str, revision_id: str, canonical_hash: str
    ) -> None:
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                """
                INSERT INTO project(project_id,display_name,created_at,state)
                VALUES(?,?,?,'ACTIVE')
                """,
                (project_id, project_id, NOW.isoformat()),
            )
            connection.execute(
                """
                INSERT INTO project_context_revision(
                  project_context_revision_id,project_id,revision_no,context_json,
                  canonical_hash,created_by,created_at
                ) VALUES(?,?,1,'{}',?,'owner-test',?)
                """,
                (revision_id, project_id, canonical_hash, NOW.isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def publish_target(self, *, project="prj_owner", context="pcr_owner", at=NOW):
        return CanonicalPortfolioOwnerService(self.owner).construct_and_publish(
            project_id=project,
            project_context_revision_id=context,
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            construction_spec=self.spec,
            runtime_identity=self.runtime,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
            published_at=at,
        )

    def publish_policy(self, *, project="prj_owner", context="pcr_owner", at=NOW):
        return CanonicalRiskPolicyAuthoringService(self.owner).author_and_publish(
            project_id=project,
            project_context_revision_id=context,
            definitions=(
                MaxSingleNamePolicyInput("0.4"),
                GrossNetExposureValidatePolicyInput("1", "0", "1"),
            ),
            runtime_identity=self.runtime,
            published_at=at,
        )

    def resolve(self, publication, namespace, role):
        resolver = CanonicalPayloadResolver(
            binding_resolver=SQLitePortfolioRiskPolicyOwner(
                self.database, self.artifact_root
            ),
            byte_reader=SQLitePortfolioRiskPolicyOwner(
                self.database, self.artifact_root
            ).store,
        )
        owner_id = (
            publication.target_weight_vector_id
            if hasattr(publication, "target_weight_vector_id")
            else publication.risk_policy_set_version_id
        )
        return resolver.resolve(
            PayloadResolutionRequest(
                owner_namespace=namespace,
                owner_id=owner_id,
                owner_version=publication.content_sha256,
                payload_role=role,
                context_identity=publication.context_identity,
                max_bytes=1_000_000,
            )
        )


class MigrationOwnerFoundationTests(OwnerFoundationFixture):
    def test_0003_and_0004_owner_boundaries_remain_scoped_after_current_migrations(self) -> None:
        connection = connect_catalog(self.database)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 8)
            migrations = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT migration_id FROM schema_migration ORDER BY migration_id"
                )
            )
            self.assertEqual(
                migrations,
                (
                    "0001_control_catalog",
                    "0002_data_truth",
                    "0003_portfolio_riskpolicy_owner",
                    "0004_risk_application_publication",
                    "0005_task_execution_deadline",
                    "0006_catalog_upgrade_session_integrity",
                    "0007_artifact_promotion_gc",
                    "0008_runtime_execution_truth",
                ),
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("target_weight_vector_publication", tables)
            self.assertIn("risk_policy_set_publication", tables)
            self.assertIn("risk_application_receipt_publication", tables)
            self.assertIn("risk_adjusted_weight_vector_publication", tables)
            self.assertEqual(tuple(connection.execute("PRAGMA foreign_key_check")), ())
        finally:
            connection.close()
        self.assertEqual(
            apply_migrations(
                self.database, application_version="owner-foundation-reopen"
            ).applied,
            (),
        )
        versions = (
            Path(__file__).parents[2]
            / "src"
            / "v3_backend"
            / "migrations"
            / "versions"
        )
        owner_sql = (versions / "0003_portfolio_riskpolicy_owner.sql").read_text(
            encoding="utf-8"
        )
        application_sql = (
            versions / "0004_risk_application_publication.sql"
        ).read_text(encoding="utf-8")
        deadline_sql = (versions / "0005_task_execution_deadline.sql").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("CREATE TABLE risk_application_receipt_publication", owner_sql)
        self.assertNotIn("CREATE TABLE risk_adjusted_weight_vector_publication", owner_sql)
        self.assertNotIn("CREATE TABLE target_weight_vector_publication", application_sql)
        self.assertNotIn("CREATE TABLE risk_policy_set_publication", application_sql)
        for owner_table in (
            "target_weight_vector_publication",
            "risk_policy_set_publication",
            "risk_application_receipt_publication",
            "risk_adjusted_weight_vector_publication",
        ):
            self.assertNotIn(f"CREATE TABLE {owner_table}", deadline_sql)

    def test_0003_applies_after_exact_0001_0002_prefix(self) -> None:
        root = self.root / "prefix-upgrade"
        versions = root / "versions"
        versions.mkdir(parents=True)
        source = (
            Path(__file__).parents[2]
            / "src"
            / "v3_backend"
            / "migrations"
            / "versions"
        )
        for name in ("0001_control_catalog.sql", "0002_data_truth.sql"):
            (versions / name).write_bytes((source / name).read_bytes())
        path = root / "catalog.sqlite3"
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            for migration in discover_migrations(versions):
                _apply_one(
                    connection,
                    migration,
                    application_version="v2-prefix",
                    backup=None,
                )
        finally:
            connection.close()
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            owner_migration = discover_migrations(source)[2]
            self.assertEqual(
                owner_migration.migration_id, "0003_portfolio_riskpolicy_owner"
            )
            _apply_one(
                connection,
                owner_migration,
                application_version="v3-owner-upgrade",
                backup=None,
            )
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("target_weight_vector_publication", tables)
            self.assertIn("risk_policy_set_publication", tables)
            self.assertNotIn("risk_application_receipt_publication", tables)
            self.assertNotIn("risk_adjusted_weight_vector_publication", tables)
        finally:
            connection.close()


class TargetWeightOwnerTests(OwnerFoundationFixture):
    def test_trusted_service_publishes_and_restart_resolves_exact_bytes(self) -> None:
        result = self.publish_target()
        publication = result.publication
        resolved = self.resolve(
            publication, TARGET_WEIGHT_OWNER_NAMESPACE, TARGET_WEIGHT_PAYLOAD_ROLE
        )
        self.assertEqual(
            resolved.verified_payload.artifact_id, publication.artifact_id
        )
        self.assertEqual(
            resolved.verified_payload.actual_sha256, publication.artifact_sha256
        )
        self.assertEqual(resolved.receipt.context_identity, publication.context_identity)
        self.assertIn(result.construction.target.target_weight_vector_id.encode(), resolved.verified_payload.payload)
        self.assertEqual(publication.canonical_truth_state, "NOT_FORMAL")
        self.assertEqual(publication.canonical_admission_state, "PRE_ALPHA")
        self.assertEqual(
            result.construction.target.source.owner_receipt_resolution,
            "UNRESOLVED_CALLER_ASSERTED",
        )

    def test_service_has_no_prebuilt_target_publication_api(self) -> None:
        service = CanonicalPortfolioOwnerService(self.owner)
        self.assertFalse(hasattr(service, "publish_target_weight"))
        parameters = inspect.signature(service.construct_and_publish).parameters
        self.assertNotIn("target", parameters)
        self.assertNotIn("weights", parameters)

    def test_unpersisted_and_wrong_context_fail_closed(self) -> None:
        publication = self.publish_target().publication
        resolver = CanonicalPayloadResolver(
            binding_resolver=self.owner, byte_reader=self.owner.store
        )
        base = dict(
            owner_namespace=TARGET_WEIGHT_OWNER_NAMESPACE,
            owner_version=publication.content_sha256,
            payload_role=TARGET_WEIGHT_PAYLOAD_ROLE,
            context_identity=publication.context_identity,
            max_bytes=1_000_000,
        )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id="twv_sha256_" + "0" * 64, **base
                )
            )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id=publication.target_weight_vector_id,
                    **{**base, "owner_version": "e" * 64},
                )
            )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id=publication.target_weight_vector_id,
                    **{**base, "context_identity": "f" * 64},
                )
            )

    def test_idempotent_replay_and_context_conflict(self) -> None:
        first = self.publish_target()
        second = self.publish_target(at=datetime(2026, 8, 14, 1, tzinfo=timezone.utc))
        self.assertEqual(first.publication, second.publication)
        with self.assertRaises(TargetWeightOwnerAuthorityError):
            self.publish_target(project="prj_other", context="pcr_other")

    def test_altered_numeric_artifact_bytes_fail_p1(self) -> None:
        publication = self.publish_target().publication
        artifact_path = self.artifact_root.joinpath(
            *storage_key_for_artifact_id(publication.artifact_id).split("/")
        )
        artifact_path.write_bytes(b'{"rows":[{"target_weight":"1"}]}')
        with self.assertRaises(PayloadContentMismatch):
            self.resolve(
                publication, TARGET_WEIGHT_OWNER_NAMESPACE, TARGET_WEIGHT_PAYLOAD_ROLE
            )

    def test_wrong_catalog_artifact_size_fails_closed(self) -> None:
        publication = self.publish_target().publication
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET byte_size=byte_size+1 WHERE artifact_id=?",
                (publication.artifact_id,),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(PayloadBindingUnavailable):
            self.resolve(
                publication, TARGET_WEIGHT_OWNER_NAMESPACE, TARGET_WEIGHT_PAYLOAD_ROLE
            )

    def test_db_conflict_after_artifact_publication_is_compensated(self) -> None:
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                """
                CREATE TRIGGER reject_target_owner_for_test
                BEFORE INSERT ON target_weight_vector_publication
                BEGIN SELECT RAISE(ABORT,'test conflict'); END
                """
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(TargetWeightOwnerAuthorityError):
            self.publish_target()
        connection = connect_catalog(self.database)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM target_weight_vector_publication"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM artifact WHERE semantic_role='TARGET_WEIGHT_VECTOR'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()
        published_files = tuple((self.artifact_root / "sha256").rglob("*"))
        self.assertFalse(any(path.is_file() for path in published_files))
        connection = connect_catalog(self.database)
        try:
            connection.execute("DROP TRIGGER reject_target_owner_for_test")
            connection.commit()
        finally:
            connection.close()
        retry = self.publish_target()
        self.assertTrue(retry.publication.artifact_id.startswith("art_sha256_"))


class RiskPolicyOwnerTests(OwnerFoundationFixture):
    def test_definition_input_authors_publishes_and_restart_resolves(self) -> None:
        result = self.publish_policy()
        publication = result.publication
        self.assertTrue(
            all(
                policy.risk_model_requirement.value == "NOT_REQUIRED"
                for policy in result.policy_set.policies
            )
        )
        resolved = self.resolve(
            publication, RISK_POLICY_OWNER_NAMESPACE, RISK_POLICY_PAYLOAD_ROLE
        )
        self.assertIn(publication.risk_policy_set_version_id.encode(), resolved.verified_payload.payload)
        self.assertEqual(publication.risk_model_requirement, "NOT_REQUIRED")
        self.assertEqual(publication.canonical_admission_state, "PRE_ALPHA")

    def test_prebuilt_policy_set_has_no_canonical_publication_api(self) -> None:
        service = CanonicalRiskPolicyAuthoringService(self.owner)
        self.assertFalse(hasattr(service, "publish_risk_policy_set"))
        parameters = inspect.signature(service.author_and_publish).parameters
        self.assertNotIn("policy_set", parameters)
        prebuilt = RiskPolicySetVersion.create(
            (
                RiskPolicyDefinition.pass_through(
                    code_version=self.runtime.code_version,
                    runtime_profile_id=self.runtime.runtime_profile_id,
                ),
            )
        )
        with self.assertRaises(TypeError):
            service.author_and_publish(
                project_id="prj_owner",
                project_context_revision_id="pcr_owner",
                definitions=(prebuilt,),  # type: ignore[arg-type]
                runtime_identity=self.runtime,
                published_at=NOW,
            )

    def test_invalid_definition_fails_before_publication(self) -> None:
        with self.assertRaises(RiskRuntimeError):
            CanonicalRiskPolicyAuthoringService(self.owner).author_and_publish(
                project_id="prj_owner",
                project_context_revision_id="pcr_owner",
                definitions=(MaxSingleNamePolicyInput("2"),),
                runtime_identity=self.runtime,
                published_at=NOW,
            )
        connection = connect_catalog(self.database)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM risk_policy_set_publication"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_unpersisted_wrong_context_tamper_idempotency_and_conflict(self) -> None:
        publication = self.publish_policy().publication
        resolver = CanonicalPayloadResolver(
            binding_resolver=self.owner, byte_reader=self.owner.store
        )
        base = dict(
            owner_namespace=RISK_POLICY_OWNER_NAMESPACE,
            owner_version=publication.content_sha256,
            payload_role=RISK_POLICY_PAYLOAD_ROLE,
            context_identity=publication.context_identity,
            max_bytes=1_000_000,
        )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id="rpsv_sha256_" + "0" * 64, **base
                )
            )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id=publication.risk_policy_set_version_id,
                    **{**base, "owner_version": "e" * 64},
                )
            )
        with self.assertRaises(PayloadBindingUnavailable):
            resolver.resolve(
                PayloadResolutionRequest(
                    owner_id=publication.risk_policy_set_version_id,
                    **{**base, "context_identity": "f" * 64},
                )
            )
        replay = self.publish_policy(
            at=datetime(2026, 8, 14, 1, tzinfo=timezone.utc)
        ).publication
        self.assertEqual(publication, replay)
        with self.assertRaises(RiskPolicyOwnerAuthorityError):
            self.publish_policy(project="prj_other", context="pcr_other")

        artifact_path = self.artifact_root.joinpath(
            *storage_key_for_artifact_id(publication.artifact_id).split("/")
        )
        artifact_path.write_bytes(b'{"ordered_policies":[]}')
        with self.assertRaises(PayloadContentMismatch):
            self.resolve(
                publication, RISK_POLICY_OWNER_NAMESPACE, RISK_POLICY_PAYLOAD_ROLE
            )

    def test_wrong_catalog_artifact_sha_fails_closed(self) -> None:
        publication = self.publish_policy().publication
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                "UPDATE artifact SET sha256=? WHERE artifact_id=?",
                ("e" * 64, publication.artifact_id),
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(PayloadBindingUnavailable):
            self.resolve(
                publication, RISK_POLICY_OWNER_NAMESPACE, RISK_POLICY_PAYLOAD_ROLE
            )

    def test_policy_db_conflict_compensates_then_retry_is_safe(self) -> None:
        connection = connect_catalog(self.database)
        try:
            connection.execute(
                """
                CREATE TRIGGER reject_policy_owner_for_test
                BEFORE INSERT ON risk_policy_set_publication
                BEGIN SELECT RAISE(ABORT,'test conflict'); END
                """
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(RiskPolicyOwnerAuthorityError):
            self.publish_policy()
        connection = connect_catalog(self.database)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM risk_policy_set_publication"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM artifact WHERE semantic_role='RISK_POLICY_SET'"
                ).fetchone()[0],
                0,
            )
            connection.execute("DROP TRIGGER reject_policy_owner_for_test")
            connection.commit()
        finally:
            connection.close()
        published_files = tuple((self.artifact_root / "sha256").rglob("*"))
        self.assertFalse(any(path.is_file() for path in published_files))
        retry = self.publish_policy()
        self.assertTrue(retry.publication.artifact_id.startswith("art_sha256_"))

    def test_pass_through_also_remains_riskmodel_not_required(self) -> None:
        result = CanonicalRiskPolicyAuthoringService(self.owner).author_and_publish(
            project_id="prj_owner",
            project_context_revision_id="pcr_owner",
            definitions=(PassThroughPolicyInput(),),
            runtime_identity=self.runtime,
            published_at=NOW,
        )
        self.assertEqual(
            {policy.risk_model_requirement.value for policy in result.policy_set.policies},
            {"NOT_REQUIRED"},
        )


if __name__ == "__main__":
    unittest.main()
