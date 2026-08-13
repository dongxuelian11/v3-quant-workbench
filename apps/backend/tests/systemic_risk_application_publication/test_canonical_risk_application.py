from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor
import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from round3_track_i_risk_runtime.test_risk_runtime import RiskRuntimeFixture
from v3_backend.adapters.sqlite.risk_application import (
    ADJUSTED_NAMESPACE,
    ADJUSTED_ROLE,
    SQLiteRiskApplicationRepository,
)
from v3_backend.domain.artifacts.identity import storage_key_for_artifact_id
from v3_backend.domain.payload_authority import PayloadContentMismatch
from v3_backend.domain.risk_runtime import (
    CanonicalRiskApplicationRequest,
    CanonicalRiskApplicationService,
    RiskApplicationAuthorityError,
    RiskPolicySetVersion,
    RiskStateRequirement,
    apply_risk,
)
from v3_backend.domain.weights import ReferenceKind, RuntimeIdentity
from v3_backend.domain.weights.codec import canonical_weight_bytes
from v3_backend.migrations import apply_migrations


class CanonicalRiskApplicationTests(RiskRuntimeFixture):
    def setUp(self) -> None:
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = root / "catalog.sqlite3"
        self.artifact_root = root / "artifacts"
        apply_migrations(self.database, application_version="risk-publication-test")
        self.repository = SQLiteRiskApplicationRepository(
            self.database, self.artifact_root
        )
        self.service = CanonicalRiskApplicationService(self.repository)
        self.now = datetime(2026, 8, 13, 1, 2, 3, tzinfo=timezone.utc)
        self.target_value = self.target()
        self.policy_set = RiskPolicySetVersion.create((self.max_policy(),))

    def request(self, **changes: object) -> CanonicalRiskApplicationRequest:
        values = {
            "source_target_weight_vector_id": self.target_value.target_weight_vector_id,
            "risk_policy_set_version_id": self.policy_set.risk_policy_set_version_id,
            "runtime_identity": self.risk_runtime,
            "context_identity": self.target_value.source.source_reference_sha256,
        }
        values.update(changes)
        return CanonicalRiskApplicationRequest(**values)

    def publish_upstream(self) -> None:
        self.repository.publish_target_weight(
            self.target_value, published_at=self.now
        )
        self.repository.publish_risk_policy_set(
            self.policy_set,
            runtime_identity=self.risk_runtime,
            published_at=self.now,
        )

    def publish_application(self):
        self.publish_upstream()
        return self.service.apply_and_publish(self.request(), published_at=self.now)

    def owner_counts(self) -> tuple[int, int, int, int]:
        connection = sqlite3.connect(self.database)
        try:
            return tuple(
                int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "target_weight_vector_publication",
                    "risk_policy_set_publication",
                    "risk_application_receipt_publication",
                    "risk_adjusted_weight_vector_publication",
                )
            )
        finally:
            connection.close()

    # RISK-P01/P02
    def test_unreachable_target_or_policy_cannot_drive_publication(self) -> None:
        self.repository.publish_risk_policy_set(
            self.policy_set,
            runtime_identity=self.risk_runtime,
            published_at=self.now,
        )
        with self.assertRaises(Exception):
            self.service.apply_and_publish(self.request(), published_at=self.now)
        self.assertEqual(self.owner_counts(), (0, 1, 0, 0))

        self.repository.publish_target_weight(self.target_value, published_at=self.now)
        unknown_policy = RiskPolicySetVersion.create((self.pass_policy(),))
        with self.assertRaises(RiskApplicationAuthorityError):
            self.service.apply_and_publish(
                self.request(
                    risk_policy_set_version_id=unknown_policy.risk_policy_set_version_id
                ),
                published_at=self.now,
            )
        self.assertEqual(self.owner_counts(), (1, 1, 0, 0))

    # RISK-P03/P04/P05
    def test_formal_service_rejects_caller_result_receipt_and_vector_inputs(self) -> None:
        result = apply_risk(
            source_target=self.target_value,
            policy_set=self.policy_set,
            runtime_identity=self.risk_runtime,
        )
        for forged in (
            result,
            result.application_receipt,
            result.adjusted_weights,
        ):
            with self.subTest(value=type(forged).__name__), self.assertRaises(TypeError):
                self.service.apply_and_publish(forged, published_at=self.now)
        self.assertEqual(self.owner_counts(), (0, 0, 0, 0))

    # RISK-P06
    def test_direct_apply_risk_is_deterministic_and_non_persisting(self) -> None:
        first = apply_risk(
            source_target=self.target_value,
            policy_set=self.policy_set,
            runtime_identity=self.risk_runtime,
        )
        second = apply_risk(
            source_target=self.target_value,
            policy_set=self.policy_set,
            runtime_identity=self.risk_runtime,
        )
        self.assertEqual(first, second)
        self.assertEqual(self.owner_counts(), (0, 0, 0, 0))

    # RISK-P07 / RISK-A01/A02 / RISK-R03/R04/R05
    def test_formal_service_publishes_exact_bytes_and_lineage(self) -> None:
        publication = self.publish_application()
        receipt = self.repository.require_risk_application_receipt(
            publication.risk_application_receipt_id
        )
        adjusted = self.repository.require_adjusted_weight_vector(
            publication.risk_adjusted_weight_vector_id
        )
        self.assertEqual(receipt.source_target, self.target_value)
        self.assertEqual(receipt.risk_policy_set.source_id, self.policy_set.risk_policy_set_version_id)
        self.assertEqual(adjusted.risk_application, receipt)
        self.assertEqual(self.owner_counts(), (1, 1, 1, 1))

    def _artifact_path(self, artifact_id: str) -> Path:
        return self.artifact_root.joinpath(*storage_key_for_artifact_id(artifact_id).split("/"))

    # RISK-A03/A04
    def test_tampered_receipt_or_adjusted_backing_bytes_reject(self) -> None:
        for kind in ("receipt", "adjusted"):
            with self.subTest(kind=kind):
                # Each subtest needs an independent durable store.
                if kind == "receipt":
                    publication = self.publish_application()
                    artifact_id = publication.receipt_artifact_id
                    resolver = lambda: self.repository.require_risk_application_receipt(
                        publication.risk_application_receipt_id
                    )
                else:
                    publication = self.publish_application()
                    artifact_id = publication.adjusted_artifact_id
                    resolver = lambda: self.repository.require_adjusted_weight_vector(
                        publication.risk_adjusted_weight_vector_id
                    )
                path = self._artifact_path(artifact_id)
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                with self.assertRaises(Exception):
                    resolver()
                path.write_bytes(original)

    # RISK-A05/A06/A07
    def test_corrupt_owner_pointer_metadata_or_content_identity_rejects(self) -> None:
        publication = self.publish_application()
        self._corrupt_adjusted(
            publication.risk_adjusted_weight_vector_id,
            "artifact_id",
            self._target_artifact_id(),
        )
        with self.assertRaises(Exception):
            self.repository.require_adjusted_weight_vector(
                publication.risk_adjusted_weight_vector_id
            )

    def test_corrupt_owner_size_rejects(self) -> None:
        publication = self.publish_application()
        self._corrupt_adjusted(
            publication.risk_adjusted_weight_vector_id, "byte_size", 1
        )
        with self.assertRaises(Exception):
            self.repository.require_adjusted_weight_vector(
                publication.risk_adjusted_weight_vector_id
            )

    def test_corrupt_owner_content_hash_rejects(self) -> None:
        publication = self.publish_application()
        self._corrupt_adjusted(
            publication.risk_adjusted_weight_vector_id,
            "content_sha256",
            "f" * 64,
        )
        with self.assertRaises(Exception):
            self.repository.require_adjusted_weight_vector(
                publication.risk_adjusted_weight_vector_id
            )

    def _corrupt_adjusted(self, identity: str, column: str, value: object) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_risk_adjusted_vector_append_only_u"
            )
            connection.execute(
                f"UPDATE risk_adjusted_weight_vector_publication SET {column}=? WHERE risk_adjusted_weight_vector_id=?",
                (value, identity),
            )
            connection.commit()
        finally:
            connection.close()

    def _target_artifact_id(self) -> str:
        connection = sqlite3.connect(self.database)
        try:
            return str(
                connection.execute(
                    "SELECT artifact_id FROM target_weight_vector_publication"
                ).fetchone()[0]
            )
        finally:
            connection.close()

    # RISK-R01/R02/R03/R04/R05 and A3 readiness
    def test_restart_reopen_resolves_exact_downstream_binding_and_bytes(self) -> None:
        publication = self.publish_application()
        reopened = SQLiteRiskApplicationRepository(self.database, self.artifact_root)
        receipt = reopened.require_risk_application_receipt(
            publication.risk_application_receipt_id
        )
        resolved = reopened.resolve_adjusted_weight_for_downstream(
            publication.risk_adjusted_weight_vector_id
        )
        self.assertEqual(resolved.vector.risk_application, receipt)
        self.assertEqual(
            resolved.source_target_weight_vector_id,
            self.target_value.target_weight_vector_id,
        )
        self.assertEqual(
            resolved.binding.owner_namespace, ADJUSTED_NAMESPACE
        )
        self.assertEqual(resolved.binding.payload_role, ADJUSTED_ROLE)
        self.assertEqual(resolved.binding.artifact_id, publication.adjusted_artifact_id)

    # RISK-R06/R07 and concurrency/idempotency contract (sequential retry)
    def test_exact_retry_is_idempotent_and_conflicting_object_rejects(self) -> None:
        first = self.publish_application()
        second = self.service.apply_and_publish(self.request(), published_at=self.now)
        self.assertEqual(first, second)
        self.assertEqual(self.owner_counts(), (1, 1, 1, 1))
        forged = dataclasses.replace(self.target_value, cash_weight="0")
        with self.assertRaises(Exception):
            self.repository.publish_target_weight(forged, published_at=self.now)

    def test_two_concurrent_exact_publications_converge_to_one_owner_chain(self) -> None:
        self.publish_upstream()

        def publish_once():
            repository = SQLiteRiskApplicationRepository(
                self.database, self.artifact_root
            )
            return CanonicalRiskApplicationService(repository).apply_and_publish(
                self.request(), published_at=self.now
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: publish_once(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.owner_counts(), (1, 1, 1, 1))

    def test_sqlite_failure_compensates_new_unreferenced_output_bytes(self) -> None:
        self.publish_upstream()
        expected = apply_risk(
            source_target=self.target_value,
            policy_set=self.policy_set,
            runtime_identity=self.risk_runtime,
        )
        receipt_artifact = "art_sha256_" + hashlib.sha256(
            canonical_weight_bytes(expected.application_receipt)
        ).hexdigest()
        adjusted_artifact = "art_sha256_" + hashlib.sha256(
            canonical_weight_bytes(expected.adjusted_weights)
        ).hexdigest()
        connection = sqlite3.connect(self.database)
        try:
            connection.execute(
                """
                CREATE TRIGGER force_risk_publication_failure
                BEFORE INSERT ON risk_application_receipt_publication
                BEGIN SELECT RAISE(ABORT,'injected commit boundary failure'); END
                """
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(Exception):
            self.service.apply_and_publish(self.request(), published_at=self.now)
        self.assertEqual(self.owner_counts(), (1, 1, 0, 0))
        self.assertFalse(self._artifact_path(receipt_artifact).exists())
        self.assertFalse(self._artifact_path(adjusted_artifact).exists())

    # RISK-R08/R09/R10
    def test_missing_upstream_and_receipt_lineage_fail_closed(self) -> None:
        with self.assertRaises(Exception):
            self.repository.require_target_weight(
                self.target_value.target_weight_vector_id,
                context_identity=self.target_value.source.source_reference_sha256,
            )
        with self.assertRaises(RiskApplicationAuthorityError):
            self.repository.require_risk_policy_set(
                self.policy_set.risk_policy_set_version_id,
                runtime_identity=self.risk_runtime,
            )
        with self.assertRaises(RiskApplicationAuthorityError):
            self.repository.require_risk_application_receipt("rar_sha256_" + "0" * 64)

    # RISK-T01/T02/T06
    def test_truth_ceiling_is_from_resolved_upstream_and_request_has_no_promotion_field(self) -> None:
        publication = self.publish_application()
        adjusted = self.repository.require_adjusted_weight_vector(
            publication.risk_adjusted_weight_vector_id
        )
        self.assertEqual(adjusted.truth_admission, self.target_value.truth_admission)
        self.assertEqual(adjusted.truth_admission, self.policy_set.truth_admission)
        with self.assertRaises(TypeError):
            CanonicalRiskApplicationRequest(
                source_target_weight_vector_id=self.target_value.target_weight_vector_id,
                risk_policy_set_version_id=self.policy_set.risk_policy_set_version_id,
                runtime_identity=self.risk_runtime,
                context_identity=self.target_value.source.source_reference_sha256,
                truth_admission="FORMAL",  # type: ignore[call-arg]
            )

    # RISK-T03/T04/T05
    def test_required_state_context_and_runtime_mismatch_fail_closed(self) -> None:
        required = RiskStateRequirement("risk-model", ReferenceKind.RISK_MODEL)
        state_policy = RiskPolicySetVersion.create(
            (self.max_policy(required_state_inputs=(required,)),)
        )
        self.repository.publish_target_weight(self.target_value, published_at=self.now)
        self.repository.publish_risk_policy_set(
            state_policy,
            runtime_identity=self.risk_runtime,
            published_at=self.now,
        )
        with self.assertRaises(RiskApplicationAuthorityError):
            self.service.apply_and_publish(
                self.request(risk_policy_set_version_id=state_policy.risk_policy_set_version_id),
                published_at=self.now,
            )

        self.repository.publish_risk_policy_set(
            self.policy_set,
            runtime_identity=self.risk_runtime,
            published_at=self.now,
        )
        with self.assertRaises(Exception):
            self.service.apply_and_publish(
                self.request(context_identity="0" * 64), published_at=self.now
            )
        mismatched_runtime = RuntimeIdentity(
            code_version="git:other",
            runtime_profile_id=self.risk_runtime.runtime_profile_id,
            environment_fingerprint=self.risk_runtime.environment_fingerprint,
        )
        with self.assertRaises(RiskApplicationAuthorityError):
            self.service.apply_and_publish(
                self.request(runtime_identity=mismatched_runtime), published_at=self.now
            )
        mismatched_environment = RuntimeIdentity(
            code_version=self.risk_runtime.code_version,
            runtime_profile_id=self.risk_runtime.runtime_profile_id,
            environment_fingerprint="different-environment-fingerprint",
        )
        with self.assertRaises(RiskApplicationAuthorityError):
            self.service.apply_and_publish(
                self.request(runtime_identity=mismatched_environment),
                published_at=self.now,
            )


if __name__ == "__main__":
    unittest.main()
