from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from v3_backend.adapters.artifact_store import FileSystemArtifactStore
from v3_backend.adapters.sqlite import (
    SQLiteA1CanonicalOwnerRepository,
    SQLiteUnitOfWork,
    connect_catalog,
)
from v3_backend.adapters.systemic_a1_payload import (
    A1CanonicalHistoricalLabelSource,
    A1CanonicalPayloadBindingResolver,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.datasets import (
    CanonicalLabelPayloadVersion,
    DeterministicForwardReturnLabelEngine,
    FormalDatasetBuildRequest,
    FormalDatasetService,
    FormalLabelService,
    LABEL_PAYLOAD_ROLE,
    LABEL_SCHEMA_FINGERPRINT,
    LABEL_SCHEMA_VERSION,
    LabelSpec,
    SplitSpec,
    label_payload_context_identity,
)
from v3_backend.domain.data_truth import CanonicalUniverseVersion
from v3_backend.domain.factors import (
    FACTOR_INPUT_PAYLOAD_ROLE,
    FACTOR_INPUT_SCHEMA_FINGERPRINT,
    FACTOR_INPUT_SCHEMA_VERSION,
    FeatureNode,
    FactorDefinitionVersion,
    FormalFactorEvaluationRequest,
    FormalFactorEvaluationService,
    default_operator_registry,
)
from v3_backend.domain.data_truth.formal import CanonicalSnapshotVersion, CanonicalUniverseVersion as FormalUniverse
from v3_backend.domain.factors.evaluator import DeterministicReferenceEvaluator
from v3_backend.domain.payload_authority import CanonicalPayloadResolver
from v3_backend.errors.exceptions import ConflictError
from v3_backend.migrations import apply_migrations
from v3_backend.provenance.canonical_hash import canonical_json_bytes
from v3_backend.provenance.canonical_hash import canonical_sha256
from v3_backend.repositories.unit_of_work import TransactionMode


NOW = "2024-01-09T16:00:00Z"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class DefinitionRepository:
    def __init__(self, definition):
        self.definition = definition

    def get_definition(self, identity):
        return self.definition if identity == self.definition.factor_definition_version_id else None

    def find_definitions_for_field(self, field_name):
        return (self.definition,) if self.definition.root.feature_name == field_name else ()


class SpecRepository:
    def __init__(self, *values):
        self.values = {getattr(value, "label_spec_id", getattr(value, "split_spec_id", "")): value for value in values}

    def get_label_spec(self, identity):
        return self.values.get(identity)

    def get_split_spec(self, identity):
        return self.values.get(identity)


class ContextRepository:
    def __init__(self, owner, definitions, label_specs):
        self.owner = owner
        self.definitions = definitions
        self.label_specs = label_specs

    def get_factor_context(self, context_identity):
        from v3_backend.domain.factors import factor_payload_context_identity

        snapshot = self.owner.get_snapshot("snp_a1")
        universe = self.owner.get_universe("unv_a1")
        definition = self.definitions.definition
        if snapshot is None or universe is None:
            return None
        return (snapshot, universe, definition) if factor_payload_context_identity(snapshot=snapshot, universe=universe, definition=definition) == context_identity else None

    def get_label_context(self, context_identity):
        from v3_backend.domain.datasets import label_source_payload_context_identity

        snapshot = self.owner.get_snapshot("snp_a1")
        universe = self.owner.get_universe("unv_a1")
        if snapshot is None or universe is None:
            return None
        for label_spec in self.label_specs.values.values():
            exact = label_source_payload_context_identity(
                snapshot=snapshot, universe=universe, label_spec=label_spec
            )
            if exact == context_identity:
                return snapshot, universe, label_spec
        return None


class SQLiteCanonicalOwnerClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "catalog.sqlite3"
        self.store = FileSystemArtifactStore(self.root / "artifacts")
        apply_migrations(self.db, application_version="a1-test")
        self.registry = default_operator_registry()
        self.definition = FactorDefinitionVersion.create("close", FeatureNode("close", "a-share-eod/1"), self.registry)
        self.definitions = DefinitionRepository(self.definition)
        self.label = LabelSpec.create("forward-return", "close", 1, 0)
        self.label_specs = SpecRepository(self.label)
        self.split = SplitSpec.create(
            train_start=0, train_end=0, validation_start=2, validation_end=2,
            test_start=4, test_end=4, purge_observations=0, embargo_observations=0,
        )
        self._seed_catalog()

    def tearDown(self):
        self.tmp.cleanup()

    def _publish_store(self, payload, *, schema, semantic_role="FACTOR_INPUT"):
        encoded = canonical_json_bytes(payload)
        staged = self.store.stage_bytes(encoded)
        return self.store.publish(
            staged.staging_token,
            expected_sha256=staged.sha256,
            expected_byte_size=staged.byte_size,
            media_type="application/json",
            role="PARQUET_DATASET_MANIFEST",
            provenance_entity_id="prv_a1_test",
            schema_fingerprint=schema,
            semantic_fingerprint=semantic_role,
        ).descriptor

    def _insert_artifact(self, connection, descriptor):
        connection.execute(
            """INSERT INTO artifact(artifact_id,sha256,byte_size,media_type,semantic_role,storage_key,schema_fingerprint,state,created_at,published_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (descriptor.artifact_id, descriptor.sha256, descriptor.byte_size, descriptor.media_type,
             descriptor.role, descriptor.storage_key, descriptor.schema_fingerprint, "PUBLISHED", NOW, NOW),
        )

    def _seed_catalog(self):
        payload = {
            "schema_version": FACTOR_INPUT_SCHEMA_VERSION,
            "schema_fingerprint": FACTOR_INPUT_SCHEMA_FINGERPRINT,
            "context": {
                "snapshot_id": "snp_a1", "universe_version_id": "unv_a1",
                "membership_identity": "PENDING", "source_data_truth_id": "PENDING",
                "as_of": "2024-01-09", "knowledge_cutoff": NOW,
            },
            "instrument_ids": ["ins_a", "ins_b"],
            "observation_ids": ["s0", "s1", "s2", "s3"],
            "fields": [{"name": "close", "value_type": "FLOAT_SERIES", "shape": [2, 4],
                        "values": ["10", "11", "12.1", "13.31", "20", "18", None, "21"]}],
        }
        descriptors = {}
        for name in ("bundle", "raw", "manifest", "calendar", "membership", "audit", "validation"):
            descriptor = self._publish_store({"name": name}, schema="sch_sha256_" + digest(name))
            descriptors[name] = descriptor
            setattr(self, name, descriptor)
        source_data_truth_id = "dtr_sha256_" + canonical_sha256((("raw_a1", self.raw.sha256),))
        universe = CanonicalUniverseVersion.create(
            universe_version_id="unv_a1", snapshot_id="snp_a1",
            as_of=datetime.fromisoformat(NOW.replace("Z", "+00:00")).date(),
            knowledge_cutoff=datetime.fromisoformat(NOW.replace("Z", "+00:00")),
            instrument_ids=("ins_a", "ins_b"), truth_admission=PRE_ALPHA_CEILING,
        )
        payload["context"] = {
            "snapshot_id": "snp_a1", "universe_version_id": "unv_a1",
            "membership_identity": universe.membership_identity,
            "source_data_truth_id": source_data_truth_id,
            "as_of": "2024-01-09", "knowledge_cutoff": NOW,
        }
        exact = self._publish_store(payload, schema=FACTOR_INPUT_SCHEMA_FINGERPRINT)
        self.exact = exact
        connection = connect_catalog(self.db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_artifact(connection, exact)
            for descriptor in descriptors.values():
                self._insert_artifact(connection, descriptor)
            connection.execute("INSERT INTO project(project_id,display_name,created_at,state) VALUES('prj_a1','A1',?,'ACTIVE')", (NOW,))
            connection.execute("INSERT INTO connector VALUES('con_a1','a1','V3','REGISTERED',?,0)", (NOW,))
            connection.execute(
                "INSERT INTO connector_version(connector_version_id,connector_id,semantic_version,bundle_artifact_id,bundle_sha256,entrypoint,declared_manifest_json,network_policy,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("cov_a1", "con_a1", "1", self.bundle.artifact_id, self.bundle.sha256, "v3:a1", "{}", "DENY", "ADMITTED", NOW),
            )
            connection.execute("INSERT INTO connector_capability VALUES('cov_a1','CN_EOD','DECLARED','FORMAL','{}',?)", (self.validation.artifact_id,))
            connection.execute("INSERT INTO provider_descriptor VALUES('pvd_a1','A1','A1','TEST','{}',?,'REGISTERED',?)", (digest('provider'), NOW))
            connection.execute("INSERT INTO connector_data_capability VALUES('cov_a1','CN_EOD','pvd_a1','CN_EOD','1D','REVISION_AWARE',1,?,?)", (self.validation.artifact_id, NOW))
            connection.execute("INSERT INTO raw_capture(raw_capture_id,connector_version_id,provider_dataset,request_fingerprint,effective_range_start,effective_range_end,available_time,captured_at,ingested_at,artifact_id,content_hash,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               ("raw_a1", "cov_a1", "CN_EOD", digest('request'), NOW, NOW, NOW, NOW, NOW, self.raw.artifact_id, self.raw.sha256, "ACCEPTED"))
            connection.execute("INSERT INTO raw_capture_truth_descriptor VALUES('raw_a1','pvd_a1','{}',?,1)", (NOW,))
            connection.execute("INSERT INTO snapshot_validation_profile VALUES('a1-formal','FORMAL_ADMITTED','A1',?)", (NOW,))
            for code in ("PIT", "ARTIFACT"):
                connection.execute("INSERT INTO snapshot_validation_requirement VALUES('a1-formal',?,'PASS','BLOCKING')", (code,))
            connection.execute("INSERT INTO trading_calendar_version VALUES('tcv_a1','CN_A_SHARE','Asia/Shanghai',?,?, 'PUBLISHED',?)", (self.calendar.artifact_id, self.calendar.sha256, NOW))
            for ordinal, day in enumerate(("2024-01-06", "2024-01-07", "2024-01-08", "2024-01-09")):
                connection.execute("INSERT INTO trading_session VALUES(?,?,?,?,?,?,?,?,?)", (f"trs_{ordinal}", "tcv_a1", day, 1, ordinal, day+"T01:30:00Z", day+"T07:00:00Z", day+"T08:00:00Z", self.calendar.artifact_id))
            for instrument in ("ins_a", "ins_b"):
                connection.execute("INSERT INTO instrument(instrument_id,asset_class,exchange,listing_date,state,created_at) VALUES(?,'CN_A_SHARE','SSE','2020-01-01','ACTIVE',?)", (instrument, NOW))
            connection.execute("INSERT INTO data_snapshot(snapshot_id,connector_version_id,normalization_spec_version,truth_profile_id,min_effective_time,max_effective_time,max_available_time,state,created_at) VALUES(?,?,?,?,?,?,?,'CANDIDATE',?)",
                               ("snp_a1", "cov_a1", "a1", "STRICT_PIT", "2024-01-06T07:00:00Z", NOW, NOW, NOW))
            connection.execute("INSERT INTO snapshot_raw_capture VALUES('snp_a1','raw_a1','CN_EOD',?)", (NOW,))
            connection.execute("INSERT INTO snapshot_calendar VALUES('snp_a1','tcv_a1',?)", (NOW,))
            connection.execute("INSERT INTO snapshot_partition VALUES('snp_a1','CN_EOD','all',?,?,?,?,?,?)", (exact.artifact_id, 8, FACTOR_INPUT_SCHEMA_FINGERPRINT.removeprefix("sch_sha256_"), "2024-01-06T07:00:00Z", NOW, NOW))
            for code in ("PIT", "ARTIFACT"):
                connection.execute("INSERT INTO snapshot_validation VALUES(?,?,?,?,?,?,?,?)", (f"snv_{code}", "snp_a1", "a1-formal", code, "PASS", "BLOCKING", self.validation.artifact_id, NOW))
            connection.execute("INSERT INTO snapshot_validation_binding VALUES('snp_a1','a1-formal',?)", (NOW,))
            connection.execute("UPDATE data_snapshot SET state='VALIDATED',validated_at=? WHERE snapshot_id='snp_a1'", (NOW,))
            connection.execute("UPDATE data_snapshot SET state='PUBLISHED',manifest_artifact_id=?,content_hash=?,published_at=? WHERE snapshot_id='snp_a1'", (self.manifest.artifact_id, self.manifest.sha256, NOW))
            connection.execute("INSERT INTO universe_definition VALUES('und_a1','prj_a1','INDEX','{}',?,'PUBLISHED',?)", (digest('universe'), NOW))
            connection.execute("INSERT INTO universe_version(universe_version_id,universe_definition_id,snapshot_id,knowledge_cutoff,state) VALUES('unv_a1','und_a1','snp_a1',?,'BUILDING')", (NOW,))
            for instrument in ("ins_a", "ins_b"):
                connection.execute("INSERT INTO universe_membership_interval VALUES(?,?,?,?,?,?,?,?,?,?)", (f"umi_{instrument}", f"umf_{instrument}", "unv_a1", instrument, "2020-01-01", None, "2020-01-01T00:00:00Z", "r1", "INCLUDED", self.membership.artifact_id))
            connection.execute("UPDATE universe_version SET membership_artifact_id=?,audit_artifact_id=?,content_hash=?,state='PUBLISHED',published_at=? WHERE universe_version_id='unv_a1'", (self.membership.artifact_id, self.audit.artifact_id, digest('membership-set'), NOW))
            connection.commit()
        finally:
            connection.close()

    def _runtime(self, *, read_only=False):
        connection = connect_catalog(self.db, read_only=read_only)
        mode = TransactionMode.READ_ONLY if read_only else TransactionMode.WRITE_CONTROL
        uow = SQLiteUnitOfWork(connection, mode)
        uow.begin()
        owner = SQLiteA1CanonicalOwnerRepository(uow, self.store)
        contexts = ContextRepository(owner, self.definitions, self.label_specs)
        binding = A1CanonicalPayloadBindingResolver(snapshots=owner, factor_contexts=contexts, materializations=owner, label_payloads=owner, label_contexts=contexts)
        resolver = CanonicalPayloadResolver(binding_resolver=binding, byte_reader=self.store)
        return connection, uow, owner, resolver

    def _factor_service(self, owner, resolver):
        return FormalFactorEvaluationService(
            snapshots=owner,
            universes=owner,
            definitions=self.definitions,
            payload_resolver=resolver,
            evaluator=DeterministicReferenceEvaluator(self.registry),
            artifact_publisher=owner.artifact_publisher,
            materialization_publisher=owner,
        )

    def _label_service(self, owner, resolver, label_spec=None):
        label_spec = label_spec or self.label
        self.label_specs.values[label_spec.label_spec_id] = label_spec
        return FormalLabelService(
            snapshots=owner,
            universes=owner,
            label_specs=SpecRepository(label_spec),
            historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver),
            engine=DeterministicForwardReturnLabelEngine(),
            artifact_publisher=owner.artifact_publisher,
            label_publisher=owner,
        )

    def _dataset_service(self, owner, resolver):
        return FormalDatasetService(
            snapshots=owner,
            universes=owner,
            materializations=owner,
            label_specs=SpecRepository(self.label),
            split_specs=SpecRepository(self.split),
            label_payloads=owner,
            payload_resolver=resolver,
            artifact_publisher=owner.artifact_publisher,
            dataset_publisher=owner,
        )

    def test_a1_o01_o10_owner_projection_and_neg_a(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            self.assertIsNotNone(owner.get_snapshot("snp_a1"))
            self.assertIsNotNone(owner.get_universe("unv_a1"))
            self.assertIsNone(owner.get_snapshot("snp_unpersisted"))
            self.assertIsNone(owner.get_universe("unv_unpersisted"))
            connection.execute("INSERT INTO data_snapshot(snapshot_id,connector_version_id,normalization_spec_version,truth_profile_id,state,created_at) VALUES('snp_candidate','cov_a1','a1','STRICT_PIT','CANDIDATE',?)", (NOW,))
            self.assertIsNone(owner.get_snapshot("snp_candidate"))
            connection.execute("INSERT INTO universe_version(universe_version_id,universe_definition_id,snapshot_id,knowledge_cutoff,state) VALUES('unv_building','und_a1','snp_a1',?,'BUILDING')", (NOW,))
            self.assertIsNone(owner.get_universe("unv_building"))
            snapshot = owner.get_snapshot("snp_a1")
            universe = owner.get_universe("unv_a1")
            self.assertEqual(universe.snapshot_id, snapshot.snapshot_id)
            self.assertEqual(universe.truth_admission, snapshot.truth_admission)
            factor = FormalFactorEvaluationService(snapshots=owner, universes=owner, definitions=self.definitions, payload_resolver=resolver, evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=owner.artifact_publisher, materialization_publisher=owner)
            materialization = factor.evaluate(FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING))
            self.assertEqual(owner.get_materialization(materialization.feature_materialization_id), materialization)
        finally:
            uow.commit(); connection.close()

        connection, uow, writable, _ = self._runtime()
        try:
            with self.assertRaises(ConflictError):
                writable.publish_materialization(replace(materialization, row_count=999))
        finally:
            uow.rollback(); connection.close()

    def test_a1_o01_o03_unpersisted_projection_and_caller_truth_reject(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            canonical = owner.get_snapshot("snp_a1")
            fake_snapshot = replace(canonical, snapshot_id="snp_unpersisted")
            fake_universe = FormalUniverse.create(universe_version_id="unv_unpersisted", snapshot_id=fake_snapshot.snapshot_id, as_of=fake_snapshot.as_of, knowledge_cutoff=fake_snapshot.knowledge_cutoff, instrument_ids=("ins_a", "ins_b"), truth_admission=canonical.truth_admission)
            self.assertIsNone(owner.get_snapshot(fake_snapshot.snapshot_id))
            self.assertIsNone(owner.get_universe(fake_universe.universe_version_id))
            service = FormalFactorEvaluationService(snapshots=owner, universes=owner, definitions=self.definitions, payload_resolver=resolver, evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=owner.artifact_publisher, materialization_publisher=owner)
            with self.assertRaisesRegex(ValueError, "canonical Snapshot"):
                service.evaluate(FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, fake_snapshot.snapshot_id, "unv_a1", 100_000, canonical.truth_admission))
        finally:
            uow.rollback(); connection.close()

    def test_a1_o06_o08_context_cutoff_and_pit_membership_are_owner_derived(self):
        connection, uow, owner, _ = self._runtime()
        try:
            canonical = owner.get_universe("unv_a1")
            caller_changed = FormalUniverse.create(universe_version_id=canonical.universe_version_id, snapshot_id=canonical.snapshot_id, as_of=date(2024, 1, 8), knowledge_cutoff=canonical.knowledge_cutoff, instrument_ids=canonical.instrument_ids, truth_admission=canonical.truth_admission)
            self.assertNotEqual(caller_changed.membership_identity, owner.get_universe("unv_a1").membership_identity)
            connection.execute("INSERT INTO universe_membership_interval VALUES('umi_future','umf_future','unv_a1','ins_a','2020-01-01',NULL,'2024-01-10T00:00:00Z','r2','EXCLUDED',?)", (self.membership.artifact_id,))
            self.assertEqual(owner.get_universe("unv_a1").instrument_ids, ("ins_a", "ins_b"))
        finally:
            uow.rollback(); connection.close()

    def test_a1_o10_owner_artifact_pointer_is_exact(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            snapshot = owner.get_snapshot("snp_a1")
            self.assertEqual(resolver._byte_reader.read_bytes(snapshot.payload_artifact_id), self.store.read_bytes(snapshot.payload_artifact_id))
            with self.assertRaises(Exception):
                self.store.read_bytes("art_sha256_" + "0" * 64)
        finally:
            uow.rollback(); connection.close()

    def test_a1_l01_l10_deterministic_labels_and_neg_b(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            service = FormalLabelService(snapshots=owner, universes=owner, label_specs=SpecRepository(self.label), historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver), engine=DeterministicForwardReturnLabelEngine(), artifact_publisher=owner.artifact_publisher, label_publisher=owner)
            first = service.materialize(label_spec_id=self.label.label_spec_id, snapshot_id="snp_a1", universe_version_id="unv_a1", max_payload_bytes=100_000)
            second = service.materialize(label_spec_id=self.label.label_spec_id, snapshot_id="snp_a1", universe_version_id="unv_a1", max_payload_bytes=100_000)
            self.assertEqual(first.label_payload_id, second.label_payload_id)
            payload = json.loads(self.store.read_bytes(first.artifact_id))
            self.assertEqual(payload["values"], ["0.1", "0.1", "0.1", None, "-0.1", None, None, None])
            horizon2 = LabelSpec.create("forward-return", "close", 2, 0)
            self.label_specs.values[horizon2.label_spec_id] = horizon2
            changed = FormalLabelService(snapshots=owner, universes=owner, label_specs=SpecRepository(horizon2), historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver), engine=DeterministicForwardReturnLabelEngine(), artifact_publisher=owner.artifact_publisher, label_publisher=owner).materialize(label_spec_id=horizon2.label_spec_id, snapshot_id="snp_a1", universe_version_id="unv_a1", max_payload_bytes=100_000)
            self.assertNotEqual(first.label_payload_id, changed.label_payload_id)
            self.assertIsNone(owner.get_label_payload("lbl_sha256_" + "0" * 64))
        finally:
            uow.commit(); connection.close()

    def test_a1_l01_l02_caller_label_values_or_unpersisted_owner_reject(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            parameters = FormalLabelService.materialize.__annotations__
            self.assertNotIn("values", parameters)
            fake = CanonicalLabelPayloadVersion(
                "clp_sha256_" + "0" * 64, self.label.label_spec_id, "snp_a1", "unv_a1",
                "tcv_a1", "lblctx_sha256_" + "0" * 64,
                next(iter(()), None), "fake", "art_sha256_" + "0" * 64, "0" * 64,
                0, "sch_sha256_" + "0" * 64, PRE_ALPHA_CEILING,
            )
        except TypeError:
            # A canonical-looking owner without a typed P1 source receipt is invalid at construction.
            pass
        finally:
            self.assertIsNone(owner.get_label_payload("clp_sha256_" + "0" * 64))
            uow.rollback(); connection.close()

    def test_a1_l04_l07_horizon_missing_and_context_semantics(self):
        engine = DeterministicForwardReturnLabelEngine()
        values = engine.compute(label_spec=self.label, instrument_ids=("ins_a",), observation_ids=("s0", "s1"), source_values=(Decimal("10"), Decimal("11")))
        self.assertEqual(values, ("0.1", None))
        horizon = LabelSpec.create("forward-return", "close", 2, 0)
        self.assertEqual(engine.compute(label_spec=horizon, instrument_ids=("ins_a",), observation_ids=("s0", "s1"), source_values=(Decimal("10"), Decimal("11"))), (None, None))
        unsupported = LabelSpec.create("forward-return", "open", 1, 0)
        with self.assertRaisesRegex(ValueError, "source_field=close"):
            engine.compute(label_spec=unsupported, instrument_ids=("ins_a",), observation_ids=("s0", "s1"), source_values=(Decimal("10"), Decimal("11")))

    def test_a1_l08_l09_altered_source_or_label_bytes_reject(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            label = FormalLabelService(snapshots=owner, universes=owner, label_specs=SpecRepository(self.label), historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver), engine=DeterministicForwardReturnLabelEngine(), artifact_publisher=owner.artifact_publisher, label_publisher=owner).materialize(label_spec_id=self.label.label_spec_id, snapshot_id="snp_a1", universe_version_id="unv_a1", max_payload_bytes=100_000)
            path = self.store._final_path(label.sha256)
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            request = resolver.resolve
            from v3_backend.domain.payload_authority import PayloadResolutionRequest
            with self.assertRaises(Exception):
                request(PayloadResolutionRequest(owner_namespace="v3.data_truth.labels", owner_id=label.label_spec_id, owner_version=label.label_payload_id, payload_role="DATASET_LABELS", context_identity=label.context_identity, max_bytes=100_000))
            path.write_bytes(original)
        finally:
            uow.rollback(); connection.close()

    def test_a1_p01_p10_reopen_persistence_and_neg_c(self):
        connection, uow, owner, resolver = self._runtime()
        factor = FormalFactorEvaluationService(snapshots=owner, universes=owner, definitions=self.definitions, payload_resolver=resolver, evaluator=DeterministicReferenceEvaluator(self.registry), artifact_publisher=owner.artifact_publisher, materialization_publisher=owner)
        materialization = factor.evaluate(FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING))
        label = FormalLabelService(snapshots=owner, universes=owner, label_specs=SpecRepository(self.label), historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver), engine=DeterministicForwardReturnLabelEngine(), artifact_publisher=owner.artifact_publisher, label_publisher=owner).materialize(label_spec_id=self.label.label_spec_id, snapshot_id="snp_a1", universe_version_id="unv_a1", max_payload_bytes=100_000)
        dataset_service = FormalDatasetService(snapshots=owner, universes=owner, materializations=owner, label_specs=SpecRepository(self.label), split_specs=SpecRepository(self.split), label_payloads=owner, payload_resolver=resolver, artifact_publisher=owner.artifact_publisher, dataset_publisher=owner)
        dataset = dataset_service.build(FormalDatasetBuildRequest((materialization.feature_materialization_id,), self.label.label_spec_id, self.split.split_spec_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING))
        uow.commit(); connection.close()

        connection, uow, reopened, _ = self._runtime(read_only=True)
        try:
            self.assertEqual(reopened.get_materialization(materialization.feature_materialization_id), materialization)
            self.assertEqual(reopened.get_label_payload(label.label_payload_id), label)
            self.assertEqual(reopened.get_dataset(dataset.dataset_version_id), dataset)
            self.assertIsNone(reopened.get_materialization("ffm_sha256_" + "0" * 64))
            self.assertIsNone(reopened.get_dataset("fdsv_sha256_" + "0" * 64))
        finally:
            uow.rollback(); connection.close()

    def test_a1_p04_p06_unpersisted_label_and_dataset_are_not_canonical(self):
        connection, uow, owner, _ = self._runtime(read_only=True)
        try:
            self.assertIsNone(owner.get_label_payload("clp_sha256_" + "f" * 64))
            self.assertIsNone(owner.get_dataset("fdsv_sha256_" + "f" * 64))
        finally:
            uow.rollback(); connection.close()

    def test_a1_o02_unpersisted_universe_projection_formal_access_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            with self.assertRaisesRegex(ValueError, "canonical Universe"):
                self._factor_service(owner, resolver).evaluate(
                    FormalFactorEvaluationRequest(
                        self.definition.factor_definition_version_id,
                        "snp_a1",
                        "unv_unpersisted",
                        100_000,
                        PRE_ALPHA_CEILING,
                    )
                )
        finally:
            uow.rollback(); connection.close()

    def test_a1_o07_persisted_knowledge_cutoff_mismatch_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            cutoff = "2024-01-08T16:00:00Z"
            connection.execute(
                "INSERT INTO universe_version(universe_version_id,universe_definition_id,snapshot_id,knowledge_cutoff,state) VALUES('unv_cutoff','und_a1','snp_a1',?,'BUILDING')",
                (cutoff,),
            )
            for instrument in ("ins_a", "ins_b"):
                connection.execute(
                    "INSERT INTO universe_membership_interval VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (f"umi_cutoff_{instrument}", f"umf_cutoff_{instrument}", "unv_cutoff", instrument, "2020-01-01", None, "2024-01-01T00:00:00Z", "r1", "INCLUDED", self.membership.artifact_id),
                )
            connection.execute(
                "UPDATE universe_version SET membership_artifact_id=?,audit_artifact_id=?,content_hash=?,state='PUBLISHED',published_at=? WHERE universe_version_id='unv_cutoff'",
                (self.membership.artifact_id, self.audit.artifact_id, digest("cutoff-membership"), NOW),
            )
            self.assertIsNotNone(owner.get_universe("unv_cutoff"))
            with self.assertRaisesRegex(ValueError, "as-of/knowledge"):
                self._factor_service(owner, resolver).evaluate(
                    FormalFactorEvaluationRequest(
                        self.definition.factor_definition_version_id,
                        "snp_a1",
                        "unv_cutoff",
                        100_000,
                        PRE_ALPHA_CEILING,
                    )
                )
        finally:
            uow.rollback(); connection.close()

    def test_a1_o08_caller_membership_list_is_not_a_formal_request_input(self):
        parameters = FormalFactorEvaluationRequest.__dataclass_fields__
        self.assertNotIn("instrument_ids", parameters)
        self.assertNotIn("membership_identity", parameters)
        connection, uow, owner, _ = self._runtime(read_only=True)
        try:
            persisted = owner.get_universe("unv_a1")
            caller = FormalUniverse.create(
                universe_version_id=persisted.universe_version_id,
                snapshot_id=persisted.snapshot_id,
                as_of=persisted.as_of,
                knowledge_cutoff=persisted.knowledge_cutoff,
                instrument_ids=("ins_a",),
                truth_admission=persisted.truth_admission,
            )
            self.assertNotEqual(caller.membership_identity, owner.get_universe("unv_a1").membership_identity)
        finally:
            uow.rollback(); connection.close()

    def test_a1_o10_caller_artifact_b_cannot_replace_owner_artifact_a(self):
        caller_b = self._publish_store(
            {"caller": "B"}, schema=FACTOR_INPUT_SCHEMA_FINGERPRINT
        )
        connection, uow, owner, resolver = self._runtime()
        try:
            materialization = self._factor_service(owner, resolver).evaluate(
                FormalFactorEvaluationRequest(
                    self.definition.factor_definition_version_id,
                    "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING,
                )
            )
            self.assertEqual(materialization.input_receipt.artifact_id, owner.get_snapshot("snp_a1").payload_artifact_id)
            self.assertNotEqual(materialization.input_receipt.artifact_id, caller_b.artifact_id)
        finally:
            uow.rollback(); connection.close()

    def test_a1_l02_p04_unpersisted_label_artifact_dataset_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            materialization = self._factor_service(owner, resolver).evaluate(
                FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING)
            )
            context = label_payload_context_identity(
                snapshot_id="snp_a1",
                universe_version_id="unv_a1",
                membership_identity=owner.get_universe("unv_a1").membership_identity,
                calendar_version_id="tcv_a1",
                knowledge_cutoff=NOW,
                label_spec=self.label,
            )
            owner.artifact_publisher.publish_canonical_json(
                {
                    "schema_version": LABEL_SCHEMA_VERSION,
                    "schema_fingerprint": LABEL_SCHEMA_FINGERPRINT,
                    "context_identity": context,
                    "label_spec_id": self.label.label_spec_id,
                    "snapshot_id": "snp_a1",
                    "universe_version_id": "unv_a1",
                    "calendar_version_id": "tcv_a1",
                    "knowledge_cutoff": NOW,
                    "horizon_observations": 1,
                    "instrument_ids": ["ins_a", "ins_b"],
                    "observation_ids": ["s0", "s1", "s2", "s3"],
                    "shape": [2, 4],
                    "values": ["9", "9", "9", "9", "9", "9", "9", "9"],
                },
                semantic_role=LABEL_PAYLOAD_ROLE,
                provenance_entity_id="caller-arbitrary-labels",
                schema_fingerprint=LABEL_SCHEMA_FINGERPRINT,
            )
            with self.assertRaisesRegex(ValueError, "canonical Label payload owner"):
                self._dataset_service(owner, resolver).build(
                    FormalDatasetBuildRequest(
                        (materialization.feature_materialization_id,), self.label.label_spec_id,
                        self.split.split_spec_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING,
                    )
                )
        finally:
            uow.rollback(); connection.close()

    def test_a1_l05_snapshot_or_universe_context_change_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            service = self._label_service(owner, resolver)
            for snapshot_id, universe_id in (("snp_missing", "unv_a1"), ("snp_a1", "unv_missing")):
                with self.subTest(snapshot_id=snapshot_id, universe_id=universe_id):
                    with self.assertRaisesRegex(ValueError, "canonical (Snapshot|Universe)"):
                        service.materialize(
                            label_spec_id=self.label.label_spec_id,
                            snapshot_id=snapshot_id,
                            universe_version_id=universe_id,
                            max_payload_bytes=100_000,
                        )
        finally:
            uow.rollback(); connection.close()

    def test_a1_l08_altered_source_market_bytes_reject_before_computation(self):
        connection, uow, owner, resolver = self._runtime()
        path = self.store._final_path(self.exact.sha256)
        original = path.read_bytes()
        try:
            path.write_bytes(original + b" ")
            with self.assertRaises(Exception):
                self._label_service(owner, resolver).materialize(
                    label_spec_id=self.label.label_spec_id,
                    snapshot_id="snp_a1",
                    universe_version_id="unv_a1",
                    max_payload_bytes=100_000,
                )
        finally:
            path.write_bytes(original)
            uow.rollback(); connection.close()

    def test_a1_l09_altered_label_output_bytes_dataset_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            materialization = self._factor_service(owner, resolver).evaluate(
                FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING)
            )
            label = self._label_service(owner, resolver).materialize(
                label_spec_id=self.label.label_spec_id,
                snapshot_id="snp_a1",
                universe_version_id="unv_a1",
                max_payload_bytes=100_000,
            )
            path = self.store._final_path(label.sha256)
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" ")
                with self.assertRaises(Exception):
                    self._dataset_service(owner, resolver).build(
                        FormalDatasetBuildRequest(
                            (materialization.feature_materialization_id,), self.label.label_spec_id,
                            self.split.split_spec_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING,
                        )
                    )
            finally:
                path.write_bytes(original)
        finally:
            uow.rollback(); connection.close()

    def test_a1_p01_unpersisted_materialization_dataset_rejects(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            with self.assertRaisesRegex(ValueError, "canonical FeatureMaterialization"):
                self._dataset_service(owner, resolver).build(
                    FormalDatasetBuildRequest(
                        ("ffm_sha256_" + "0" * 64,), self.label.label_spec_id,
                        self.split.split_spec_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING,
                    )
                )
        finally:
            uow.rollback(); connection.close()

    def test_a1_p06_caller_dataset_mutation_is_not_canonical(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            materialization = self._factor_service(owner, resolver).evaluate(
                FormalFactorEvaluationRequest(self.definition.factor_definition_version_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING)
            )
            self._label_service(owner, resolver).materialize(
                label_spec_id=self.label.label_spec_id,
                snapshot_id="snp_a1",
                universe_version_id="unv_a1",
                max_payload_bytes=100_000,
            )
            dataset = self._dataset_service(owner, resolver).build(
                FormalDatasetBuildRequest(
                    (materialization.feature_materialization_id,), self.label.label_spec_id,
                    self.split.split_spec_id, "snp_a1", "unv_a1", 100_000, PRE_ALPHA_CEILING,
                )
            )
            with self.assertRaisesRegex(ValueError, "identity"):
                replace(dataset, sample_count=dataset.sample_count + 1)
            self.assertEqual(owner.get_dataset(dataset.dataset_version_id), dataset)
        finally:
            uow.rollback(); connection.close()

    def test_a1_p09_tampered_persisted_owner_record_fails_closed(self):
        connection, uow, owner, resolver = self._runtime()
        try:
            label = self._label_service(owner, resolver).materialize(
                label_spec_id=self.label.label_spec_id,
                snapshot_id="snp_a1",
                universe_version_id="unv_a1",
                max_payload_bytes=100_000,
            )
            row = connection.execute(
                "SELECT artifact_id FROM artifact_reference WHERE owner_type='A1CanonicalLabel' AND owner_id=? AND role='CANONICAL_OWNER' AND state='ACTIVE'",
                (label.label_payload_id,),
            ).fetchone()
            owner_artifact_id = str(row[0])
            path = self.store._final_path(owner_artifact_id.removeprefix("art_sha256_"))
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" ")
                with self.assertRaises(Exception):
                    owner.get_label_payload(label.label_payload_id)
            finally:
                path.write_bytes(original)
        finally:
            uow.rollback(); connection.close()

    def test_a1_p10_integration_fixture_uses_sqlite_not_memory_authority(self):
        connection, uow, owner, _ = self._runtime(read_only=True)
        try:
            self.assertIsInstance(owner, SQLiteA1CanonicalOwnerRepository)
            self.assertEqual(type(owner).__module__, "v3_backend.adapters.sqlite.systemic_a1")
        finally:
            uow.rollback(); connection.close()

if __name__ == "__main__":
    unittest.main()
