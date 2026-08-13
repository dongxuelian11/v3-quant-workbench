from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.strategy_payload import (
    StrategyPayloadBindingResolver,
    StrategyPayloadOwnerRecord,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.artifacts.identity import artifact_id_for_bytes
from v3_backend.domain.artifacts.policy import ADMITTED, FormatRule, SafeFormatPolicy
from v3_backend.domain.payload_authority import (
    CanonicalPayloadResolver,
    PayloadBindingUnavailable,
    PayloadContentMismatch,
)
from v3_backend.domain.strategies import (
    BoundInputReference,
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
    StrategyEvaluationBindingVersion,
    encode_score_payload,
    strategy_payload_context_identity,
)

from apps.backend.tests.track_f_strategy_runtime.helpers import build_runtime_fixture


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
        owner_namespace: str = "FACTOR",
        payload_role: str = SCORE_PAYLOAD_ROLE,
        decision_time: datetime = DECISION_TIME,
        byte_reader=None,
    ) -> None:
        self.case = case
        self.base = build_runtime_fixture()
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
        self.source_id = "canonical-score-owner-1"
        generic = GenericAdmittedArtifactReference(
            artifact_type="FEATURE_MATERIALIZATION",
            source_id=self.source_id,
            artifact_id=self.artifact_id,
            content_sha256=self.sha256,
            truth_admission=PRE_ALPHA_CEILING,
        )
        input_reference = BoundInputReference.from_generic("scores", generic)
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
            generic_artifact_references=(generic,),
        )
        self.context_identity = strategy_payload_context_identity(
            definition=self.base.definition,
            binding=self.binding,
            input_reference=input_reference,
            decision_time=decision_time,
        )
        self.record = StrategyPayloadOwnerRecord(
            binding_key="scores",
            owner_namespace=owner_namespace,
            owner_id=self.source_id,
            owner_version="1",
            payload_role=payload_role,
            artifact_id=self.artifact_id,
            expected_sha256=self.sha256,
            expected_byte_size=len(payload),
            context_identity=self.context_identity,
            binding_version="strategy-score-owner-binding/1.0.0",
            schema_fingerprint=schema_fingerprint,
            semantic_fingerprint="semantic_sha256_strategy_score_vector_v1",
            provenance_reference_id="prv_strategy_score_1",
        )
        self.owner = StrategyPayloadBindingResolver(
            binding=self.binding,
            records=(self.record,),
        )
        self.byte_reader = byte_reader or StaticByteReader(payload)
        self.payload_resolver = CanonicalPayloadResolver(
            binding_resolver=self.owner,
            byte_reader=self.byte_reader,
        )
        self.service = FormalStrategyEvaluationService(
            payload_resolver=self.payload_resolver
        )
        self.input_request = FormalStrategyInputRequest(
            binding_key="scores",
            owner_namespace=owner_namespace,
            owner_id=self.source_id,
            owner_version="1",
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


def mutate_json(payload: bytes, **changes):
    value = json.loads(payload)
    value.update(changes)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SystemicA2FormalPayloadTests(unittest.TestCase):
    def test_a2_01_canonical_artifact_store_happy_path_binds_p1_receipt(self) -> None:
        base = build_runtime_fixture()
        payload = encode_score_payload(
            definition=base.definition,
            binding=base.binding,
            binding_key="scores",
            decision_time=DECISION_TIME,
            values=SCORES,
        )
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
            fixture = FormalFixture(self, byte_reader=store)
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
        with self.assertRaisesRegex(Exception, "exactly match|canonical exact source"):
            SelectionArtifact._create_formal(
                definition=first_fixture.base.definition,
                binding=first_fixture.binding,
                entries=first.selection_artifact.entries,
                excluded_instrument_ids=first.selection_artifact.excluded_instrument_ids,
                input_artifacts=first.selection_artifact.input_artifacts,
                signal_artifact=second.signal_artifact,
                formal_execution_contract_version="v3.strategy-formal-evaluation/1.0.0",
            )
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
