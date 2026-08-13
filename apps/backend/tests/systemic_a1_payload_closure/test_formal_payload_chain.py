from __future__ import annotations

import inspect
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store.filesystem import FileSystemArtifactStore
from v3_backend.adapters.systemic_a1_payload import (
    A1CanonicalPayloadBindingResolver,
    FileSystemCanonicalJsonArtifactPublisher,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.data_truth import CanonicalSnapshotVersion, CanonicalUniverseVersion
from v3_backend.domain.datasets import (
    DATASET_ARTIFACT_ROLE,
    LABEL_PAYLOAD_ROLE,
    LABEL_SCHEMA_FINGERPRINT,
    LABEL_SCHEMA_VERSION,
    CanonicalLabelPayloadVersion,
    FormalDatasetBuildRequest,
    FormalDatasetService,
    LabelSpec,
    SplitSpec,
    label_payload_context_identity,
)
from v3_backend.domain.factors import (
    FACTOR_INPUT_PAYLOAD_ROLE,
    FACTOR_INPUT_SCHEMA_FINGERPRINT,
    FACTOR_INPUT_SCHEMA_VERSION,
    FACTOR_OUTPUT_ARTIFACT_ROLE,
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FeatureNode,
    FormalFactorEvaluationRequest,
    FormalFactorEvaluationService,
    default_operator_registry,
    factor_payload_context_identity,
)
from v3_backend.domain.payload_authority import CanonicalPayloadResolver
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256


class MemoryRepository:
    def __init__(self, values):
        self._values = dict(values)

    def get_snapshot(self, identity):
        return self._values.get(identity)

    def get_universe(self, identity):
        return self._values.get(identity)

    def get_definition(self, identity):
        return self._values.get(identity)

    def get_materialization(self, identity):
        return self._values.get(identity)

    def get_label_spec(self, identity):
        return self._values.get(identity)

    def get_split_spec(self, identity):
        return self._values.get(identity)

    def get_label_payload(self, identity, context_identity=None):
        direct = self._values.get(identity)
        if direct is not None:
            return direct
        matches = [value for value in self._values.values() if getattr(value, "label_spec_id", None) == identity and (context_identity is None or value.context_identity == context_identity)]
        return matches[0] if len(matches) == 1 else None

    def find_definitions_for_field(self, field_name):
        return tuple(value for value in self._values.values() if getattr(getattr(value, "root", None), "feature_name", None) == field_name)

    def publish_materialization(self, value):
        self._values[value.feature_materialization_id] = value
        return value

    def publish_label_payload(self, value):
        self._values[value.label_payload_id] = value
        return value

    def publish_dataset(self, value):
        self._values[value.dataset_version_id] = value
        return value


class MemoryFactorContexts:
    def __init__(self, values):
        self._values = dict(values)

    def get_factor_context(self, context_identity):
        return self._values.get(context_identity)


class FormalPayloadChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FileSystemArtifactStore(Path(self.tmp.name))
        self.publisher = FileSystemCanonicalJsonArtifactPublisher(self.store)
        self.registry = default_operator_registry()
        self.definition = FactorDefinitionVersion.create("close", FeatureNode("close", "a-share-eod/1"), self.registry)
        self.knowledge = datetime(2024, 1, 9, 16, tzinfo=timezone.utc)
        self.universe = CanonicalUniverseVersion.create(
            universe_version_id="universe-csi-test-v1",
            snapshot_id="snapshot-eod-v1",
            as_of=date(2024, 1, 9),
            knowledge_cutoff=self.knowledge,
            instrument_ids=("CN.000001", "CN.600000"),
            truth_admission=FORMAL_ADMITTED_CEILING,
        )
        self.input_payload = self._input_payload(values=["1", "2", "3", "4", "5", None])
        input_descriptor = self.publisher.publish_canonical_json(
            self.input_payload,
            semantic_role=FACTOR_INPUT_PAYLOAD_ROLE,
            provenance_entity_id="data-truth-eod-v1",
            schema_fingerprint=FACTOR_INPUT_SCHEMA_FINGERPRINT,
        )
        self.snapshot = CanonicalSnapshotVersion(
            "snapshot-eod-v1",
            "data-truth-eod-v1",
            date(2024, 1, 9),
            self.knowledge,
            "calendar-sse-v1",
            input_descriptor.artifact_id,
            input_descriptor.sha256,
            input_descriptor.byte_size,
            FACTOR_INPUT_SCHEMA_FINGERPRINT,
            FORMAL_ADMITTED_CEILING,
        )
        self.snapshots = MemoryRepository({self.snapshot.snapshot_id: self.snapshot})
        self.universes = MemoryRepository({self.universe.universe_version_id: self.universe})
        self.definitions = MemoryRepository({self.definition.factor_definition_version_id: self.definition})
        self.materializations = MemoryRepository({})
        self.label_payloads = MemoryRepository({})
        self.datasets = MemoryRepository({})
        self.factor_contexts = MemoryFactorContexts({
            factor_payload_context_identity(snapshot=self.snapshot, universe=self.universe, definition=self.definition): (self.snapshot, self.universe, self.definition)
        })
        self.binding = A1CanonicalPayloadBindingResolver(
            snapshots=self.snapshots,
            factor_contexts=self.factor_contexts,
            materializations=self.materializations,
            label_payloads=self.label_payloads,
        )
        self.resolver = CanonicalPayloadResolver(binding_resolver=self.binding, byte_reader=self.store)
        self.factor_service = FormalFactorEvaluationService(
            snapshots=self.snapshots,
            universes=self.universes,
            definitions=self.definitions,
            payload_resolver=self.resolver,
            evaluator=DeterministicReferenceEvaluator(self.registry),
            artifact_publisher=self.publisher,
            materialization_publisher=self.materializations,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _input_payload(self, *, values, membership_identity=None, snapshot_id="snapshot-eod-v1"):
        universe_identity = membership_identity or self.universe.membership_identity
        return {
            "schema_version": FACTOR_INPUT_SCHEMA_VERSION,
            "schema_fingerprint": FACTOR_INPUT_SCHEMA_FINGERPRINT,
            "context": {
                "snapshot_id": snapshot_id,
                "universe_version_id": self.universe.universe_version_id,
                "membership_identity": universe_identity,
                "source_data_truth_id": "data-truth-eod-v1",
                "as_of": "2024-01-09",
                "knowledge_cutoff": "2024-01-09T16:00:00Z",
            },
            "instrument_ids": list(self.universe.instrument_ids),
            "observation_ids": ["s0", "s1", "s2"],
            "fields": [{"name": "close", "value_type": "FLOAT_SERIES", "shape": [2, 3], "values": values}],
        }

    def _factor_request(self):
        return FormalFactorEvaluationRequest(
            self.definition.factor_definition_version_id,
            self.snapshot.snapshot_id,
            self.universe.universe_version_id,
            100_000,
            FORMAL_ADMITTED_CEILING,
        )

    def _materialize(self):
        materialization = self.factor_service.evaluate(self._factor_request())
        self.materializations._values[materialization.feature_materialization_id] = materialization
        return materialization

    def _dataset_fixture(self, materialization, *, label_values=None, horizon=1):
        label = LabelSpec.create("forward-return", "close", horizon, 0)
        split = SplitSpec.create(
            train_start=0, train_end=0,
            validation_start=2, validation_end=2,
            test_start=4, test_end=4,
            purge_observations=0, embargo_observations=0,
        )
        context = label_payload_context_identity(
            snapshot_id=self.snapshot.snapshot_id,
            universe_version_id=self.universe.universe_version_id,
            membership_identity=self.universe.membership_identity,
            calendar_version_id=self.snapshot.calendar_version_id,
            knowledge_cutoff="2024-01-09T16:00:00Z",
            label_spec=label,
        )
        payload = {
            "schema_version": LABEL_SCHEMA_VERSION,
            "schema_fingerprint": LABEL_SCHEMA_FINGERPRINT,
            "context_identity": context,
            "label_spec_id": label.label_spec_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "universe_version_id": self.universe.universe_version_id,
            "calendar_version_id": self.snapshot.calendar_version_id,
            "knowledge_cutoff": "2024-01-09T16:00:00Z",
            "horizon_observations": label.horizon_observations,
            "instrument_ids": list(self.universe.instrument_ids),
            "observation_ids": ["s0", "s1", "s2"],
            "shape": [2, 3],
            "values": label_values or ["0.1", "0.2", "0.3", "0.4", None, "0.6"],
        }
        descriptor = self.publisher.publish_canonical_json(
            payload,
            semantic_role=LABEL_PAYLOAD_ROLE,
            provenance_entity_id=label.label_spec_id,
            schema_fingerprint=LABEL_SCHEMA_FINGERPRINT,
        )
        label_identity = {
            "label_spec_id": label.label_spec_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "universe_version_id": self.universe.universe_version_id,
            "calendar_version_id": self.snapshot.calendar_version_id,
            "context_identity": context,
            "source_receipt_id": materialization.input_receipt.receipt_identity,
            "engine_version": "test-label-engine/1",
            "artifact_id": descriptor.artifact_id,
            "sha256": descriptor.sha256,
            "byte_size": descriptor.byte_size,
            "schema_fingerprint": LABEL_SCHEMA_FINGERPRINT,
            "truth_admission": FORMAL_ADMITTED_CEILING.to_wire(),
        }
        label_owner = CanonicalLabelPayloadVersion(
            "clp_sha256_" + canonical_sha256(label_identity), label.label_spec_id,
            self.snapshot.snapshot_id, self.universe.universe_version_id,
            self.snapshot.calendar_version_id, context,
            materialization.input_receipt, "test-label-engine/1",
            descriptor.artifact_id, descriptor.sha256,
            descriptor.byte_size, LABEL_SCHEMA_FINGERPRINT, FORMAL_ADMITTED_CEILING,
        )
        self.label_payloads._values[label_owner.label_payload_id] = label_owner
        service = FormalDatasetService(
            snapshots=self.snapshots,
            universes=self.universes,
            materializations=self.materializations,
            label_specs=MemoryRepository({label.label_spec_id: label}),
            split_specs=MemoryRepository({split.split_spec_id: split}),
            label_payloads=self.label_payloads,
            payload_resolver=self.resolver,
            artifact_publisher=self.publisher,
            dataset_publisher=self.datasets,
        )
        request = FormalDatasetBuildRequest(
            (materialization.feature_materialization_id,), label.label_spec_id, split.split_spec_id,
            self.snapshot.snapshot_id, self.universe.universe_version_id, 100_000,
            FORMAL_ADMITTED_CEILING,
        )
        return service, request, label_owner

    def test_exact_canonical_happy_path_resolves_receipts_and_publishes_bytes(self):
        materialization = self._materialize()
        self.assertEqual(self.store.read_bytes(materialization.output_descriptor.artifact_id), canonical_json_bytes({
            "schema_version": "v3.feature-materialization-payload/1.0.0",
            "schema_fingerprint": materialization.output_schema_fingerprint,
            "factor_definition_version_id": self.definition.factor_definition_version_id,
            "input_receipt_id": materialization.input_receipt.receipt_identity,
            "context_identity": factor_payload_context_identity(snapshot=self.snapshot, universe=self.universe, definition=self.definition),
            "instrument_ids": list(self.universe.instrument_ids), "observation_ids": ["s0", "s1", "s2"],
            "value_type": "FLOAT_SERIES", "shape": [2, 3], "values": ["1", "2", "3", "4", "5", None],
        }))
        service, request, _ = self._dataset_fixture(materialization)
        dataset = service.build(request)
        self.assertEqual(dataset.truth_admission, FORMAL_ADMITTED_CEILING)
        self.assertEqual(len(dataset.feature_receipts), 1)
        self.assertEqual(dataset.sample_count, 4)
        self.assertEqual(dataset.dataset_descriptor.artifact_id, "art_sha256_" + dataset.dataset_descriptor.sha256)
        dataset_bytes = self.store.read_bytes(dataset.dataset_descriptor.artifact_id)
        self.assertIn(b'"split":"TRAIN"', dataset_bytes)
        self.assertIn(b'"split":"VALIDATION"', dataset_bytes)

    def test_valid_refs_with_altered_factor_values_cannot_enter_formal_request(self):
        self.assertNotIn("features", inspect.signature(FormalFactorEvaluationRequest).parameters)
        altered = self._input_payload(values=["9", "9", "9", "9", "9", "9"])
        self.assertNotEqual(canonical_json_bytes(altered), canonical_json_bytes(self.input_payload))
        materialization = self.factor_service.evaluate(self._factor_request())
        self.assertEqual(materialization.input_receipt.artifact_id, self.snapshot.payload_artifact_id)

    def test_valid_artifact_id_with_modified_bytes_is_rejected(self):
        class ModifiedReader:
            def read_bytes(_self, artifact_id, *, max_bytes):
                return self.store.read_bytes(artifact_id, max_bytes=max_bytes) + b" "
        service = FormalFactorEvaluationService(
            snapshots=self.snapshots, universes=self.universes, definitions=self.definitions,
            payload_resolver=CanonicalPayloadResolver(binding_resolver=self.binding, byte_reader=ModifiedReader()),
            evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher,
            materialization_publisher=self.materializations,
        )
        with self.assertRaisesRegex(Exception, "SHA-256|byte size|identity"):
            service.evaluate(self._factor_request())

    def test_wrong_input_context_membership_snapshot_and_as_of_reject(self):
        for changed in (
            self._input_payload(values=["1","2","3","4","5","6"], membership_identity="unv_sha256_" + "0"*64),
            self._input_payload(values=["1","2","3","4","5","6"], snapshot_id="other-snapshot"),
        ):
            descriptor = self.publisher.publish_canonical_json(changed, semantic_role=FACTOR_INPUT_PAYLOAD_ROLE, provenance_entity_id="data-truth-eod-v1", schema_fingerprint=FACTOR_INPUT_SCHEMA_FINGERPRINT)
            bad_snapshot = replace(self.snapshot, payload_artifact_id=descriptor.artifact_id, payload_sha256=descriptor.sha256, payload_byte_size=descriptor.byte_size)
            snapshots = MemoryRepository({bad_snapshot.snapshot_id: bad_snapshot})
            contexts = MemoryFactorContexts({factor_payload_context_identity(snapshot=bad_snapshot, universe=self.universe, definition=self.definition): (bad_snapshot, self.universe, self.definition)})
            binding = A1CanonicalPayloadBindingResolver(snapshots=snapshots, factor_contexts=contexts, materializations=self.materializations, label_payloads=self.label_payloads)
            service = FormalFactorEvaluationService(snapshots=snapshots, universes=self.universes, definitions=self.definitions, payload_resolver=CanonicalPayloadResolver(binding_resolver=binding, byte_reader=self.store), evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher, materialization_publisher=self.materializations)
            with self.assertRaisesRegex(ValueError, "context"):
                service.evaluate(self._factor_request())
        wrong_asof = CanonicalUniverseVersion.create(universe_version_id=self.universe.universe_version_id, snapshot_id=self.universe.snapshot_id, as_of=date(2024, 1, 8), knowledge_cutoff=self.knowledge, instrument_ids=self.universe.instrument_ids, truth_admission=FORMAL_ADMITTED_CEILING)
        with self.assertRaisesRegex(ValueError, "as-of"):
            FormalFactorEvaluationService(snapshots=self.snapshots, universes=MemoryRepository({wrong_asof.universe_version_id: wrong_asof}), definitions=self.definitions, payload_resolver=self.resolver, evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher, materialization_publisher=self.materializations).evaluate(self._factor_request())

    def test_unresolved_raw_snapshot_or_universe_cannot_be_formal(self):
        empty = MemoryRepository({})
        for snapshots, universes in ((empty, self.universes), (self.snapshots, empty)):
            with self.assertRaisesRegex(ValueError, "canonical (Snapshot|Universe)"):
                FormalFactorEvaluationService(snapshots=snapshots, universes=universes, definitions=self.definitions, payload_resolver=self.resolver, evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher, materialization_publisher=self.materializations).evaluate(self._factor_request())

    def test_pure_engine_result_cannot_mint_formal_materialization(self):
        result = DeterministicReferenceEvaluator(self.registry).evaluate(self.definition, {"close": [99, 99]})
        self.assertEqual(result.values, (99.0, 99.0))
        self.assertNotIn("result", inspect.signature(FormalFactorEvaluationRequest).parameters)

    def test_wrong_input_receipt_or_output_corruption_rejects_dataset(self):
        materialization = self._materialize()
        service, request, _ = self._dataset_fixture(materialization)
        fake = replace(materialization.input_receipt, request_identity="prq_sha256_fake")
        with self.assertRaisesRegex(ValueError, "identity"):
            replace(materialization, input_receipt=fake)
        path = self.store._final_path(materialization.output_descriptor.sha256)
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(Exception, "integrity|match|rejected"):
            service.build(request)

    def test_dataset_request_has_no_detached_features_or_labels(self):
        parameters = inspect.signature(FormalDatasetBuildRequest).parameters
        self.assertNotIn("features", parameters)
        self.assertNotIn("labels", parameters)

    def test_label_horizon_and_split_context_mismatch_reject(self):
        materialization = self._materialize()
        service, request, label_owner = self._dataset_fixture(materialization)
        with self.assertRaisesRegex(ValueError, "identity"):
            replace(label_owner, context_identity="lblctx_sha256_wrong")
        unsafe = SplitSpec.create(train_start=0, train_end=1, validation_start=2, validation_end=2, test_start=3, test_end=3, purge_observations=0, embargo_observations=0)
        service._split_specs = MemoryRepository({unsafe.split_spec_id: unsafe})
        with self.assertRaises(ValueError):
            service.build(replace(request, split_spec_id=unsafe.split_spec_id))

    def test_downstream_truth_cannot_exceed_weakest_upstream(self):
        weak = replace(self.universe, truth_admission=PRE_ALPHA_CEILING)
        service = FormalFactorEvaluationService(
            snapshots=self.snapshots,
            universes=MemoryRepository({weak.universe_version_id: weak}),
            definitions=self.definitions,
            payload_resolver=self.resolver,
            evaluator=DeterministicReferenceEvaluator(self.registry),
            artifact_publisher=self.publisher,
            materialization_publisher=self.materializations,
        )
        result = service.evaluate(self._factor_request())
        self.assertEqual(result.truth_admission, PRE_ALPHA_CEILING)

    def test_non_finite_label_is_rejected(self):
        materialization = self._materialize()
        with self.assertRaises(ValueError):
            self._dataset_fixture(materialization, label_values=[math.inf, "0.2", "0.3", "0.4", "0.5", "0.6"])

    def test_numeric_wire_is_unique_and_multi_digit_values_are_preserved(self):
        invalid = self._input_payload(values=["1.0", "2", "3", "4", "5", "6"])
        descriptor = self.publisher.publish_canonical_json(invalid, semantic_role=FACTOR_INPUT_PAYLOAD_ROLE, provenance_entity_id="data-truth-eod-v1", schema_fingerprint=FACTOR_INPUT_SCHEMA_FINGERPRINT)
        snapshot = replace(self.snapshot, payload_artifact_id=descriptor.artifact_id, payload_sha256=descriptor.sha256, payload_byte_size=descriptor.byte_size)
        snapshots = MemoryRepository({snapshot.snapshot_id: snapshot})
        contexts = MemoryFactorContexts({factor_payload_context_identity(snapshot=snapshot, universe=self.universe, definition=self.definition): (snapshot, self.universe, self.definition)})
        binding = A1CanonicalPayloadBindingResolver(snapshots=snapshots, factor_contexts=contexts, materializations=self.materializations, label_payloads=self.label_payloads)
        service = FormalFactorEvaluationService(snapshots=snapshots, universes=self.universes, definitions=self.definitions, payload_resolver=CanonicalPayloadResolver(binding_resolver=binding, byte_reader=self.store), evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher, materialization_publisher=self.materializations)
        with self.assertRaisesRegex(ValueError, "non-canonical"):
            service.evaluate(self._factor_request())

        valid = self._input_payload(values=["10", "20", "30", "40", "50", "60"])
        descriptor = self.publisher.publish_canonical_json(valid, semantic_role=FACTOR_INPUT_PAYLOAD_ROLE, provenance_entity_id="data-truth-eod-v1", schema_fingerprint=FACTOR_INPUT_SCHEMA_FINGERPRINT)
        snapshot = replace(self.snapshot, payload_artifact_id=descriptor.artifact_id, payload_sha256=descriptor.sha256, payload_byte_size=descriptor.byte_size)
        snapshots = MemoryRepository({snapshot.snapshot_id: snapshot})
        contexts = MemoryFactorContexts({factor_payload_context_identity(snapshot=snapshot, universe=self.universe, definition=self.definition): (snapshot, self.universe, self.definition)})
        binding = A1CanonicalPayloadBindingResolver(snapshots=snapshots, factor_contexts=contexts, materializations=self.materializations, label_payloads=self.label_payloads)
        service = FormalFactorEvaluationService(snapshots=snapshots, universes=self.universes, definitions=self.definitions, payload_resolver=CanonicalPayloadResolver(binding_resolver=binding, byte_reader=self.store), evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=self.publisher, materialization_publisher=self.materializations)
        output = service.evaluate(self._factor_request())
        self.assertIn(b'"values":["10","20","30","40","50","60"]', self.store.read_bytes(output.output_descriptor.artifact_id))


if __name__ == "__main__":
    unittest.main()
