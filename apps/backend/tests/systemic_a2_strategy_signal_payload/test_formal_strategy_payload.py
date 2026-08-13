from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.sqlite.repositories import SQLiteRepositoryRegistry
from v3_backend.adapters.sqlite.unit_of_work import SQLiteUnitOfWork
from v3_backend.adapters.strategy_payload import StrategyPayloadBindingResolver
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.domain.artifacts.policy import ADMITTED, FormatRule, SafeFormatPolicy
from v3_backend.migrations import apply_migrations
from v3_backend.repositories.unit_of_work import TransactionMode
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
)
from v3_backend.domain.strategies import (
    BoundInputReference,
    BindingSlot,
    CanonicalOwnerArtifactReference,
    CrossSectionInputArtifact,
    DeterministicStrategyEvaluator,
    FormalStrategyEvaluationError,
    FormalStrategyEvaluationRequest,
    FormalStrategyEvaluationService,
    FormalStrategyInputRequest,
    GenericAdmittedArtifactReference,
    PortfolioIntent,
    SCORE_PAYLOAD_ROLE,
    SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
    SelectionArtifact,
    SignalArtifact,
    InputArtifactEvidence,
    StrategyEvaluationBindingVersion,
    StrategyCompiler,
    default_component_registry,
    encode_score_payload,
    strategy_payload_context_identity,
)
import v3_backend.adapters.strategy_payload as strategy_payload_adapter

from apps.backend.tests.track_f_strategy_runtime.helpers import (
    build_runtime_fixture,
    build_strategy_ir,
    score_port,
)


DECISION_TIME = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
SCORES = ("3", "3", "2", None)


class StaticByteReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read_bytes(self, artifact_id: str, *, max_bytes: int) -> bytes:
        return self.payload


class FormalFixture:
    def __init__(
        self,
        case: unittest.TestCase,
        *,
        payload_mutator=None,
        schema_fingerprint: str = SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
        owner_namespace: str = "PREDICTION_SIGNAL_VERSION",
        payload_role: str = SCORE_PAYLOAD_ROLE,
        decision_time: datetime = DECISION_TIME,
        byte_reader=None,
    ) -> None:
        self.case = case
        base = build_runtime_fixture(snapshot_id="snp_a2", universe_id="unv_a2")
        prediction_definition = StrategyCompiler(default_component_registry()).compile(
            dataclasses.replace(
                build_strategy_ir(),
                required_bindings=(
                    BindingSlot("scores", "PREDICTION_SIGNAL", score_port()),
                ),
            )
        )
        self.base = dataclasses.replace(base, definition=prediction_definition)
        payload = encode_score_payload(
            definition=self.base.definition,
            binding=self.base.binding,
            binding_key="scores",
            decision_time=decision_time,
            values=SCORES,
        )
        if payload_mutator is not None:
            payload = payload_mutator(payload)
        self.payload = payload
        self.sha256 = hashlib.sha256(payload).hexdigest()
        self.artifact_id = artifact_id_for_bytes(payload)
        self.source_id = "sgv_strategy_score_1"
        self.owner_version = self.sha256
        self.owner_reference = CanonicalOwnerArtifactReference(
            artifact_type="PREDICTION_SIGNAL",
            owner_namespace=owner_namespace,
            owner_id=self.source_id,
            owner_version=self.owner_version,
            payload_role=payload_role,
            artifact_id=self.artifact_id,
            content_sha256=self.sha256,
        )
        input_reference = BoundInputReference.from_canonical_owner(
            "scores", self.owner_reference
        )
        self.binding = StrategyEvaluationBindingVersion.create(
            definition=self.base.definition,
            dataset=self.base.dataset,
            factor_evaluations=(self.base.factor_evaluation,),
            feature_materializations=(self.base.materialization,),
            snapshot=self.base.binding.snapshot,
            universe=self.base.binding.universe,
            period=self.base.binding.period,
            knowledge_cutoff=self.base.binding.knowledge_cutoff,
            calendar=self.base.binding.calendar,
            compiler_version=self.base.binding.compiler_version,
            runtime_profile_id=self.base.binding.runtime_profile_id,
            environment_fingerprint=self.base.binding.environment_fingerprint,
            input_references=(input_reference,),
            canonical_owner_references=(self.owner_reference,),
        )
        self.context_identity = strategy_payload_context_identity(
            definition=self.base.definition,
            binding=self.binding,
            input_reference=input_reference,
            decision_time=decision_time,
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "catalog.sqlite3"
        apply_migrations(self.database_path, application_version="a2-owner-tests")
        self.connection = sqlite3.connect(self.database_path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self._seed_catalog(schema_fingerprint=schema_fingerprint)
        self.uow = SQLiteUnitOfWork(self.connection, TransactionMode.READ_ONLY)
        self.uow.begin()
        self.repositories = SQLiteRepositoryRegistry(self.uow)
        self.owner = StrategyPayloadBindingResolver(
            binding=self.binding, repositories=self.repositories
        )
        self.byte_reader = byte_reader or StaticByteReader(payload)
        self.service = FormalStrategyEvaluationService(
            repositories=self.repositories,
            byte_reader=self.byte_reader,
        )
        self.input_request = FormalStrategyInputRequest(
            binding_key="scores",
            owner_namespace=owner_namespace,
            owner_id=self.source_id,
            owner_version=self.owner_version,
            payload_role=payload_role,
            decision_time=decision_time,
            max_bytes=64 * 1024,
        )
        self.request = FormalStrategyEvaluationRequest(
            definition=self.base.definition,
            binding=self.binding,
            inputs=(self.input_request,),
        )

    def evaluate(self):
        return self.service.evaluate(self.request)

    def close(self) -> None:
        self.uow.rollback()
        self.connection.close()
        self.temporary.cleanup()

    def _seed_catalog(self, *, schema_fingerprint: str) -> None:
        now = "2026-01-05T15:00:00Z"
        with SQLiteUnitOfWork(self.connection) as unit:
            repositories = SQLiteRepositoryRegistry(unit)
            artifact = {
                "artifact_id": self.artifact_id,
                "sha256": self.sha256,
                "byte_size": len(self.payload),
                "media_type": "application/json",
                "semantic_role": SCORE_PAYLOAD_ROLE,
                "storage_key": self.sha256,
                "schema_fingerprint": schema_fingerprint,
                "state": "STAGED",
                "created_at": now,
            }
            repositories.artifact.declare_staged(artifact)
            repositories.artifact.publish_verified(
                self.artifact_id, sha256=self.sha256, published_at=now
            )
            membership_artifact_id = self.binding.universe.membership_artifact_id
            membership_sha256 = self.binding.universe.membership_sha256
            repositories.artifact.declare_staged(
                {
                    "artifact_id": membership_artifact_id,
                    "sha256": membership_sha256,
                    "byte_size": 0,
                    "media_type": "application/json",
                    "semantic_role": "UNIVERSE_MEMBERSHIP",
                    "storage_key": membership_sha256,
                    "schema_fingerprint": None,
                    "state": "STAGED",
                    "created_at": now,
                }
            )
            repositories.artifact.publish_verified(
                membership_artifact_id,
                sha256=membership_sha256,
                published_at=now,
            )
            repositories.project.add_new(
                {"project_id": "prj_a2", "display_name": "A2", "created_at": now, "state": "ACTIVE"}
            )
            repositories.connector.table("connector").add_new(
                {
                    "connector_id": "con_a2",
                    "stable_name": "a2",
                    "publisher": "V3",
                    "state": "REGISTERED",
                    "created_at": now,
                }
            )
            repositories.connector.table("connector_version").add_new(
                {
                    "connector_version_id": "cov_a2",
                    "connector_id": "con_a2",
                    "semantic_version": "1.0.0",
                    "bundle_artifact_id": self.artifact_id,
                    "bundle_sha256": self.sha256,
                    "entrypoint": "a2:owner",
                    "declared_manifest_json": {},
                    "network_policy": "DENY",
                    "state": "ADMITTED",
                    "created_at": now,
                }
            )
            repositories.snapshot.table("data_snapshot").add_new(
                {
                    "snapshot_id": self.base.dataset.binding.snapshot_id,
                    "connector_version_id": "cov_a2",
                    "manifest_artifact_id": self.artifact_id,
                    "content_hash": self.binding.snapshot.content_sha256,
                    "normalization_spec_version": "1.0.0",
                    "truth_profile_id": "formal-a2",
                    "state": "PUBLISHED",
                    "created_at": now,
                    "published_at": now,
                }
            )
            repositories.universe.table("universe_definition").add_new(
                {
                    "universe_definition_id": "und_a2",
                    "project_id": "prj_a2",
                    "constructor_kind": "WATCHLIST",
                    "definition_json": {},
                    "canonical_hash": "1" * 64,
                    "state": "PUBLISHED",
                    "created_at": now,
                }
            )
            repositories.universe.table("universe_version").add_new(
                {
                    "universe_version_id": self.base.dataset.binding.universe_version_id,
                    "universe_definition_id": "und_a2",
                    "snapshot_id": self.base.dataset.binding.snapshot_id,
                    "knowledge_cutoff": now,
                    "membership_artifact_id": membership_artifact_id,
                    "audit_artifact_id": membership_artifact_id,
                    "content_hash": "2" * 64,
                    "state": "PUBLISHED",
                    "published_at": now,
                }
            )
            repositories.dataset.table("dataset_spec").add_new(
                {
                    "dataset_spec_id": "dss_a2",
                    "project_id": "prj_a2",
                    "spec_json": {},
                    "canonical_hash": "3" * 64,
                    "split_kind": "CHRONOLOGICAL",
                    "preprocessing_fit_scope": "TRAIN_ONLY",
                    "state": "VALIDATED",
                    "created_at": now,
                }
            )
            repositories.dataset.table("dataset_version").add_new(
                {
                    "dataset_version_id": self.base.dataset.dataset_version_id,
                    "dataset_spec_id": "dss_a2",
                    "snapshot_id": self.base.dataset.binding.snapshot_id,
                    "universe_version_id": self.base.dataset.binding.universe_version_id,
                    "manifest_artifact_id": self.artifact_id,
                    "leakage_audit_artifact_id": self.artifact_id,
                    "content_hash": "4" * 64,
                    "state": "PUBLISHED",
                    "published_at": now,
                }
            )
            repositories.model.table("model_spec").add_new(
                {
                    "model_spec_id": "mds_a2",
                    "project_id": "prj_a2",
                    "model_family": "LINEAR",
                    "spec_json": {},
                    "environment_profile_id": "env_a2",
                    "canonical_hash": "5" * 64,
                    "state": "VALIDATED",
                    "created_at": now,
                }
            )
            repositories.model.table("model_version").add_new(
                {
                    "model_version_id": "mdv_a2",
                    "model_spec_id": "mds_a2",
                    "dataset_version_id": self.base.dataset.dataset_version_id,
                    "run_id": "run_a2",
                    "model_artifact_id": self.artifact_id,
                    "metrics_artifact_id": self.artifact_id,
                    "content_hash": "6" * 64,
                    "safe_format_id": "canonical-json-v1",
                    "state": "PUBLISHED",
                    "published_at": now,
                }
            )
            repositories.model.table("prediction_signal_version").add_new(
                {
                    "prediction_signal_version_id": self.source_id,
                    "model_version_id": "mdv_a2",
                    "dataset_version_id": self.base.dataset.dataset_version_id,
                    "signal_artifact_id": self.artifact_id,
                    "content_hash": self.sha256,
                    "state": "PUBLISHED",
                    "published_at": now,
                }
            )

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def mutate_json(payload: bytes, **changes):
    value = json.loads(payload)
    value.update(changes)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SystemicA2FormalPayloadTests(unittest.TestCase):
    def test_a2_o01_caller_owner_record_type_is_not_an_authority_api(self) -> None:
        self.assertFalse(hasattr(strategy_payload_adapter, "StrategyPayloadOwnerRecord"))
        self.assertNotIn(
            "records", inspect.signature(StrategyPayloadBindingResolver).parameters
        )

    def test_a2_o02_matching_generic_reference_cannot_drive_formal_evaluation(self) -> None:
        fixture = FormalFixture(self)
        generic = GenericAdmittedArtifactReference(
            artifact_type="PREDICTION_SIGNAL",
            source_id=fixture.source_id,
            artifact_id=fixture.artifact_id,
            content_sha256=fixture.sha256,
            truth_admission=PRE_ALPHA_CEILING,
        )
        unresolved_binding = dataclasses.replace(
            fixture.binding,
            input_references=(BoundInputReference.from_generic("scores", generic),),
            generic_artifact_references=(generic,),
            canonical_owner_references=(),
        )
        unresolved_request = dataclasses.replace(
            fixture.request, binding=unresolved_binding
        )
        with self.assertRaisesRegex(FormalStrategyEvaluationError, "UNRESOLVED"):
            fixture.service.evaluate(unresolved_request)

    def test_a2_o03_unresolved_caller_asserted_reference_cannot_produce_signal(self) -> None:
        self.test_a2_o02_matching_generic_reference_cannot_drive_formal_evaluation()

    def test_a2_o04_caller_published_bytes_not_selected_by_owner_are_rejected(self) -> None:
        fixture = FormalFixture(self)
        other_payload = mutate_json(fixture.payload, values=["9", "8", "7", None])
        other_sha = hashlib.sha256(other_payload).hexdigest()
        other_artifact = artifact_id_for_bytes(other_payload)
        wrong_owner_intent = dataclasses.replace(
            fixture.owner_reference,
            artifact_id=other_artifact,
            content_sha256=other_sha,
            owner_version=other_sha,
        )
        wrong_bound = dataclasses.replace(
            fixture.binding.input_references[0],
            artifact_id=other_artifact,
            content_sha256=other_sha,
        )
        wrong_binding = dataclasses.replace(
            fixture.binding,
            input_references=(wrong_bound,),
            canonical_owner_references=(wrong_owner_intent,),
        )
        wrong_input = dataclasses.replace(
            fixture.input_request, owner_version=other_sha
        )
        with self.assertRaisesRegex(Exception, "publication|binding"):
            fixture.service.evaluate(
                dataclasses.replace(
                    fixture.request, binding=wrong_binding, inputs=(wrong_input,)
                )
            )

    def test_a2_o05_catalog_owner_to_exact_artifact_to_p1_happy_path(self) -> None:
        fixture = FormalFixture(self)
        result = fixture.evaluate()
        assert result.signal_artifact is not None
        self.assertTrue(result.signal_artifact.input_artifacts[0].is_p1_verified)
        self.assertEqual(
            result.signal_artifact.input_artifacts[0].artifact_id,
            fixture.artifact_id,
        )
        evidence = result.signal_artifact.input_artifacts[0]
        self.assertEqual(evidence.canonical_owner_namespace, "PREDICTION_SIGNAL_VERSION")
        self.assertEqual(evidence.canonical_owner_id, fixture.source_id)
        self.assertEqual(evidence.canonical_owner_version, fixture.owner_version)
        self.assertEqual(evidence.payload_role, SCORE_PAYLOAD_ROLE)

    def test_a2_o06_owner_artifact_a_caller_artifact_b_rejected(self) -> None:
        self.test_a2_o04_caller_published_bytes_not_selected_by_owner_are_rejected()

    def test_a2_o07_canonical_owner_dataset_context_mismatch_rejected(self) -> None:
        fixture = FormalFixture(self)
        wrong_universe = dataclasses.replace(
            fixture.binding.universe,
            universe_version_id="unv_wrong_context",
        )
        wrong_binding = dataclasses.replace(
            fixture.binding,
            universe=wrong_universe,
        )
        with self.assertRaisesRegex(Exception, "context|publication"):
            fixture.service.evaluate(
                dataclasses.replace(fixture.request, binding=wrong_binding)
            )

    def test_a2_o08_missing_canonical_owner_fails_closed(self) -> None:
        fixture = FormalFixture(self)
        missing = dataclasses.replace(
            fixture.owner_reference, owner_id="sgv_missing_owner"
        )
        missing_bound = dataclasses.replace(
            fixture.binding.input_references[0], source_id=missing.owner_id
        )
        missing_binding = dataclasses.replace(
            fixture.binding,
            input_references=(missing_bound,),
            canonical_owner_references=(missing,),
        )
        missing_input = dataclasses.replace(
            fixture.input_request, owner_id=missing.owner_id
        )
        with self.assertRaises(PayloadBindingUnavailable):
            fixture.service.evaluate(
                dataclasses.replace(
                    fixture.request,
                    binding=missing_binding,
                    inputs=(missing_input,),
                )
            )

    def test_a2_m01_fake_p1_evidence_cannot_mint_signal(self) -> None:
        fixture = FormalFixture(self)
        fake = InputArtifactEvidence(
            binding_key="scores",
            artifact_id=fixture.artifact_id,
            content_sha256=fixture.sha256,
            payload_verification="P1_VERIFIED",
            payload_request_identity="prq_sha256_fake",
            payload_binding_identity="cpb_sha256_fake",
            payload_resolution_receipt_identity="prr_sha256_fake",
            canonical_owner_namespace="PREDICTION_SIGNAL_VERSION",
            canonical_owner_id=fixture.source_id,
            canonical_owner_version=fixture.owner_version,
            payload_role=SCORE_PAYLOAD_ROLE,
            actual_byte_size=len(fixture.payload),
            context_identity=fixture.context_identity,
            schema_fingerprint=SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
            resolver_contract_version="v3.payload-resolution-resolver/fake",
        )
        pure = DeterministicStrategyEvaluator().evaluate(
            definition=fixture.base.definition,
            binding=fixture.binding,
            inputs=(
                CrossSectionInputArtifact(
                    binding_key="scores",
                    artifact_id=fixture.artifact_id,
                    content_sha256=fixture.sha256,
                    decision_time=DECISION_TIME,
                    values=dict(zip(fixture.binding.universe.instrument_ids, SCORES, strict=True)),
                ),
            ),
        )
        assert pure.signal_artifact is not None
        with self.assertRaisesRegex(Exception, "only be minted"):
            SignalArtifact.create(
                definition=fixture.base.definition,
                binding=fixture.binding,
                input_artifacts=(fake,),
                decision_time=pure.signal_artifact.decision_time,
                rows=pure.signal_artifact.rows,
                missing_instrument_ids=pure.signal_artifact.missing_instrument_ids,
            )

    def test_a2_m02_former_private_formal_factories_are_absent(self) -> None:
        for artifact_type in (SignalArtifact, SelectionArtifact, PortfolioIntent):
            self.assertFalse(hasattr(artifact_type, "_create_formal"))

    def test_a2_m03_fake_receipt_id_does_not_confer_authority(self) -> None:
        self.test_a2_m01_fake_p1_evidence_cannot_mint_signal()

    def test_a2_m04_caller_cannot_construct_formal_signal_or_selection(self) -> None:
        formal = FormalFixture(self).evaluate()
        assert formal.signal_artifact is not None
        assert formal.selection_artifact is not None
        signal_fields = {
            field.name: getattr(formal.signal_artifact, field.name)
            for field in dataclasses.fields(SignalArtifact)
        }
        selection_fields = {
            field.name: getattr(formal.selection_artifact, field.name)
            for field in dataclasses.fields(SelectionArtifact)
        }
        with self.assertRaisesRegex(Exception, "construction is closed"):
            SignalArtifact(**signal_fields)
        with self.assertRaisesRegex(Exception, "construction is closed"):
            SelectionArtifact(**selection_fields)

    def test_a2_m05_caller_cannot_construct_formal_portfolio_intent(self) -> None:
        formal = FormalFixture(self).evaluate()
        assert formal.portfolio_intent is not None
        intent_fields = {
            field.name: getattr(formal.portfolio_intent, field.name)
            for field in dataclasses.fields(PortfolioIntent)
        }
        with self.assertRaisesRegex(Exception, "construction is closed"):
            PortfolioIntent(**intent_fields)

    def test_a2_m06_live_owner_and_p1_service_mints_exact_signal(self) -> None:
        fixture = FormalFixture(self)
        result = fixture.evaluate()
        assert result.signal_artifact is not None
        self.assertEqual(
            result.signal_artifact.formal_execution_contract_version,
            "v3.strategy-formal-evaluation/1.0.0",
        )

    def test_a2_m07_formal_selection_binds_exact_live_signal(self) -> None:
        fixture = FormalFixture(self)
        result = fixture.evaluate()
        assert result.signal_artifact is not None and result.selection_artifact is not None
        self.assertEqual(
            result.selection_artifact.source_signal_artifact_id,
            result.signal_artifact.signal_artifact_id,
        )

    def test_a2_m08_formal_intent_binds_exact_live_selection_and_signal(self) -> None:
        fixture = FormalFixture(self)
        result = fixture.evaluate()
        assert result.signal_artifact is not None
        assert result.selection_artifact is not None
        assert result.portfolio_intent is not None
        self.assertEqual(
            result.portfolio_intent.source_selection_artifact_id,
            result.selection_artifact.selection_artifact_id,
        )
        self.assertEqual(
            result.portfolio_intent.source_signal_artifact_id,
            result.signal_artifact.signal_artifact_id,
        )

    def test_a2_m09_evidence_is_immutable_and_replacement_cannot_redirect_mint(self) -> None:
        fixture = FormalFixture(self)
        result = fixture.evaluate()
        assert result.signal_artifact is not None
        evidence = result.signal_artifact.input_artifacts[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            evidence.artifact_id = "art_sha256_" + "9" * 64  # type: ignore[misc]
        redirected = dataclasses.replace(
            evidence,
            artifact_id="art_sha256_" + "9" * 64,
            content_sha256="9" * 64,
        )
        with self.assertRaisesRegex(Exception, "only be minted|exactly match"):
            SignalArtifact.create(
                definition=fixture.base.definition,
                binding=fixture.binding,
                input_artifacts=(redirected,),
                decision_time=result.signal_artifact.decision_time,
                rows=result.signal_artifact.rows,
                missing_instrument_ids=result.signal_artifact.missing_instrument_ids,
            )

    def test_a2_m10_pure_evaluator_cannot_mint_formal_artifacts(self) -> None:
        fixture = build_runtime_fixture()
        result = DeterministicStrategyEvaluator().evaluate(
            definition=fixture.definition,
            binding=fixture.binding,
            inputs=(fixture.runtime_input,),
        )
        assert result.signal_artifact is not None
        self.assertIsNone(result.signal_artifact.formal_execution_contract_version)
        self.assertEqual(result.signal_artifact.truth_admission, PRE_ALPHA_CEILING)

    def test_a2_01_canonical_artifact_store_happy_path_binds_p1_receipt(self) -> None:
        fixture = FormalFixture(self)
        payload = fixture.payload
        policy = SafeFormatPolicy(
            (
                FormatRule(
                    SCORE_PAYLOAD_ROLE,
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "bounded canonical Strategy score vector",
                ),
            )
        )
        with tempfile.TemporaryDirectory() as temp:
            store = FileSystemArtifactStore(Path(temp), policy=policy)
            stage = store.stage_bytes(payload)
            publication = store.publish(
                stage.staging_token,
                expected_sha256=stage.sha256,
                expected_byte_size=stage.byte_size,
                media_type="application/json",
                role=SCORE_PAYLOAD_ROLE,
                provenance_entity_id="prv_strategy_score_1",
                schema_fingerprint=SCORE_PAYLOAD_SCHEMA_FINGERPRINT,
                semantic_fingerprint="semantic_sha256_strategy_score_vector_v1",
            )
            fixture.byte_reader = store
            fixture.service = FormalStrategyEvaluationService(
                repositories=fixture.repositories, byte_reader=store
            )
            self.assertEqual(fixture.artifact_id, publication.descriptor.artifact_id)
            result = fixture.evaluate()
        signal = result.signal_artifact
        selection = result.selection_artifact
        intent = result.portfolio_intent
        assert signal is not None and selection is not None and intent is not None
        evidence = signal.input_artifacts[0]
        self.assertTrue(evidence.is_p1_verified)
        self.assertTrue(evidence.payload_resolution_receipt_identity.startswith("prr_sha256_"))
        self.assertEqual(evidence.artifact_id, publication.descriptor.artifact_id)
        self.assertEqual(selection.source_signal_artifact_id, signal.signal_artifact_id)
        self.assertEqual(intent.source_selection_artifact_id, selection.selection_artifact_id)
        self.assertEqual(intent.source_signal_artifact_id, signal.signal_artifact_id)

    def test_a2_02_formal_request_has_no_values_or_raw_payload_field(self) -> None:
        fields = set(inspect.signature(FormalStrategyInputRequest).parameters)
        self.assertFalse({"values", "scores", "payload", "bytes"}.intersection(fields))

    def test_a2_03_correct_ref_with_altered_caller_values_cannot_mint_formal_signal(self) -> None:
        fixture = FormalFixture(self)
        poisoned = CrossSectionInputArtifact(
            binding_key="scores",
            artifact_id=fixture.artifact_id,
            content_sha256=fixture.sha256,
            decision_time=DECISION_TIME,
            values={instrument: "999" for instrument in fixture.binding.universe.instrument_ids},
        )
        legacy = DeterministicStrategyEvaluator().evaluate(
            definition=fixture.base.definition,
            binding=fixture.binding,
            inputs=(poisoned,),
        )
        assert legacy.signal_artifact is not None
        self.assertEqual(legacy.signal_artifact.truth_admission, PRE_ALPHA_CEILING)
        self.assertIsNone(legacy.signal_artifact.formal_execution_contract_version)
        self.assertFalse(legacy.signal_artifact.input_artifacts[0].is_p1_verified)
        formal = fixture.evaluate()
        self.assertNotEqual(
            tuple(row.value for row in legacy.signal_artifact.rows),
            tuple(row.value for row in formal.signal_artifact.rows),  # type: ignore[union-attr]
        )

    def test_a2_04_wrong_actual_bytes_rejected_by_p1(self) -> None:
        fixture = FormalFixture(self, byte_reader=StaticByteReader(b"wrong bytes"))
        with self.assertRaises(PayloadContentMismatch):
            fixture.evaluate()

    def test_a2_05_wrong_owner_is_rejected_before_signal(self) -> None:
        fixture = FormalFixture(self)
        wrong = dataclasses.replace(fixture.input_request, owner_namespace="MODEL")
        with self.assertRaises(PayloadBindingUnavailable):
            fixture.service.evaluate(dataclasses.replace(fixture.request, inputs=(wrong,)))

    def test_a2_06_wrong_payload_role_is_rejected_before_p1(self) -> None:
        fixture = FormalFixture(self)
        wrong = dataclasses.replace(fixture.input_request, payload_role="TEXT_REPORT")
        with self.assertRaisesRegex(FormalStrategyEvaluationError, "role"):
            fixture.service.evaluate(dataclasses.replace(fixture.request, inputs=(wrong,)))

    def test_a2_07_wrong_context_or_as_of_is_rejected(self) -> None:
        fixture = FormalFixture(self)
        wrong = dataclasses.replace(
            fixture.input_request,
            decision_time=datetime(2026, 1, 6, 15, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(FormalStrategyEvaluationError, "period"):
            fixture.service.evaluate(dataclasses.replace(fixture.request, inputs=(wrong,)))

    def test_a2_08_wrong_universe_or_instrument_order_is_rejected(self) -> None:
        fixture = FormalFixture(
            self,
            payload_mutator=lambda payload: mutate_json(
                payload,
                instrument_ids=list(reversed(json.loads(payload)["instrument_ids"])),
            ),
        )
        with self.assertRaisesRegex(FormalStrategyEvaluationError, "order"):
            fixture.evaluate()

    def test_a2_09_wrong_schema_fingerprint_is_rejected(self) -> None:
        fixture = FormalFixture(self, schema_fingerprint="schema_sha256_wrong")
        with self.assertRaisesRegex(FormalStrategyEvaluationError, "schema fingerprint"):
            fixture.evaluate()

    def test_a2_10_signal_factory_rejects_incomplete_receipt_evidence(self) -> None:
        fixture = FormalFixture(self)
        formal = fixture.evaluate()
        assert formal.signal_artifact is not None
        with self.assertRaisesRegex(Exception, "only be minted"):
            type(formal.signal_artifact).create(
                definition=fixture.base.definition,
                binding=fixture.binding,
                input_artifacts=formal.signal_artifact.input_artifacts,
                decision_time=formal.signal_artifact.decision_time,
                rows=formal.signal_artifact.rows,
                missing_instrument_ids=formal.signal_artifact.missing_instrument_ids,
            )

    def test_a2_11_selection_and_intent_reject_unrelated_sources(self) -> None:
        first_fixture = FormalFixture(self)
        first = first_fixture.evaluate()
        second_fixture = FormalFixture(
            self,
            payload_mutator=lambda payload: mutate_json(payload, values=["4", "3", "2", None]),
        )
        second = second_fixture.evaluate()
        assert first.selection_artifact is not None
        assert first.signal_artifact is not None
        assert first.portfolio_intent is not None
        assert second.signal_artifact is not None
        self.assertFalse(hasattr(SelectionArtifact, "_create_formal"))
        with self.assertRaisesRegex(Exception, "only be minted"):
            PortfolioIntent.create(
                definition=second_fixture.base.definition,
                binding=second_fixture.binding,
                selection_artifact=first.selection_artifact,
                signal_artifact=second.signal_artifact,
                exposure_mode=first.portfolio_intent.exposure_mode,
                cash_policy=first.portfolio_intent.cash_policy,
                rebalance_intent=first.portfolio_intent.rebalance_intent,
                items=first.portfolio_intent.items,
                constraints=first.portfolio_intent.constraints,
            )

    def test_a2_12_formal_happy_path_is_deterministic(self) -> None:
        fixture = FormalFixture(self)
        first = fixture.evaluate()
        second = fixture.evaluate()
        self.assertEqual(first, second)
        self.assertEqual(first.to_wire(), second.to_wire())

    def test_a2_13_pure_evaluator_remains_deterministic_and_non_formal(self) -> None:
        fixture = build_runtime_fixture()
        evaluator = DeterministicStrategyEvaluator()
        first = evaluator.evaluate(
            definition=fixture.definition,
            binding=fixture.binding,
            inputs=(fixture.runtime_input,),
        )
        second = evaluator.evaluate(
            definition=fixture.definition,
            binding=fixture.binding,
            inputs=(fixture.runtime_input,),
        )
        self.assertEqual(first, second)
        self.assertIsNone(first.signal_artifact.formal_execution_contract_version)  # type: ignore[union-attr]
        self.assertEqual(first.signal_artifact.truth_admission, PRE_ALPHA_CEILING)  # type: ignore[union-attr]

    def test_a2_14_pure_evaluator_has_no_formal_bypass_parameters(self) -> None:
        parameters = set(inspect.signature(DeterministicStrategyEvaluator.evaluate).parameters)
        self.assertEqual(parameters, {"self", "definition", "binding", "inputs"})
        service_parameters = set(inspect.signature(FormalStrategyEvaluationService.evaluate).parameters)
        self.assertEqual(service_parameters, {"self", "request"})


if __name__ == "__main__":
    unittest.main()
