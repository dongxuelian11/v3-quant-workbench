from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from v3_backend.adapters.artifact_store.filesystem import FileSystemArtifactStore
from v3_backend.adapters.systemic_a1_payload import (
    A1CanonicalHistoricalLabelSource,
    A1CanonicalPayloadBindingResolver,
    FileSystemCanonicalJsonArtifactPublisher,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.control_plane.resource_governor import (
    FakeResourceSampler,
    OperationProfile,
    ResourceGovernor,
)
from v3_backend.domain.agent_research_loop import BudgetLimit, ResearchLoopBudgetVersion
from v3_backend.domain.alpha_mining import (
    AlphaMiningEvaluationContext,
    AlphaMiningJobSpec,
    AlphaMiningRewardPolicyVersion,
    AlphaMiningSearchSpaceVersion,
    AlphaMiningSourceField,
    AlphaMiningStoppingRules,
    AlphaResearchLoopService,
    RewardComponentName,
    RewardComponentRule,
)
from v3_backend.domain.data_truth import CanonicalSnapshotVersion, CanonicalUniverseVersion
from v3_backend.domain.datasets import (
    DeterministicForwardReturnLabelEngine,
    FormalDatasetBuildRequest,
    FormalDatasetService,
    FormalLabelService,
    LabelSpec,
    SplitSpec,
    label_source_payload_context_identity,
)
from v3_backend.domain.factors import (
    FACTOR_INPUT_PAYLOAD_ROLE,
    FACTOR_INPUT_SCHEMA_FINGERPRINT,
    FACTOR_INPUT_SCHEMA_VERSION,
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluationContext,
    FeatureNode,
    FormalFactorEvaluationRequest,
    FormalFactorEvaluationService,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
    factor_payload_context_identity,
)
from v3_backend.domain.payload_authority import CanonicalPayloadResolver


class MemoryCanonicalOwners:
    def __init__(self) -> None:
        self.snapshots: dict[str, object] = {}
        self.universes: dict[str, object] = {}
        self.definitions: dict[str, object] = {}
        self.materializations: dict[str, object] = {}
        self.label_specs: dict[str, object] = {}
        self.split_specs: dict[str, object] = {}
        self.label_payloads: dict[str, object] = {}
        self.datasets: dict[str, object] = {}
        self.factor_contexts: dict[str, object] = {}
        self.label_contexts: dict[str, object] = {}

    def get_snapshot(self, identity):
        return self.snapshots.get(identity)

    def get_universe(self, identity):
        return self.universes.get(identity)

    def get_definition(self, identity):
        return self.definitions.get(identity)

    def get_materialization(self, identity):
        return self.materializations.get(identity)

    def get_label_spec(self, identity):
        return self.label_specs.get(identity)

    def get_split_spec(self, identity):
        return self.split_specs.get(identity)

    def get_label_payload(self, identity, context_identity=None):
        direct = self.label_payloads.get(identity)
        if direct is not None:
            return direct
        matches = tuple(
            value
            for value in self.label_payloads.values()
            if value.label_spec_id == identity
            and (context_identity is None or value.context_identity == context_identity)
        )
        return matches[0] if len(matches) == 1 else None

    def get_dataset(self, identity):
        return self.datasets.get(identity)

    def get_factor_context(self, identity):
        return self.factor_contexts.get(identity)

    def get_label_context(self, identity):
        return self.label_contexts.get(identity)

    def publish_materialization(self, value):
        existing = self.materializations.get(value.feature_materialization_id)
        if existing is not None:
            return existing
        self.materializations[value.feature_materialization_id] = value
        return value

    def publish_label_payload(self, value):
        existing = self.label_payloads.get(value.label_payload_id)
        if existing is not None and existing != value:
            raise ValueError("conflicting Label fixture owner")
        self.label_payloads[value.label_payload_id] = value
        return value

    def publish_dataset(self, value):
        existing = self.datasets.get(value.dataset_version_id)
        if existing is not None and existing != value:
            raise ValueError("conflicting Dataset fixture owner")
        self.datasets[value.dataset_version_id] = value
        return value


class MemoryDefinitionBinder:
    def __init__(self, owners, snapshot, universe) -> None:
        self.owners = owners
        self.snapshot = snapshot
        self.universe = universe

    def bind_for_dataset(self, definition, dataset) -> None:
        if (
            dataset.snapshot_id != self.snapshot.snapshot_id
            or dataset.universe_version_id != self.universe.universe_version_id
        ):
            raise ValueError("definition binder Dataset context mismatch")
        self.owners.definitions[definition.factor_definition_version_id] = definition
        context = factor_payload_context_identity(
            snapshot=self.snapshot,
            universe=self.universe,
            definition=definition,
        )
        self.owners.factor_contexts[context] = (
            self.snapshot,
            self.universe,
            definition,
        )


@dataclass
class AlphaResearchFixture:
    temporary: tempfile.TemporaryDirectory
    store: FileSystemArtifactStore
    owners: MemoryCanonicalOwners
    resolver: CanonicalPayloadResolver
    publisher: FileSystemCanonicalJsonArtifactPublisher
    service: AlphaResearchLoopService
    job: AlphaMiningJobSpec
    dataset: object

    def close(self) -> None:
        self.temporary.cleanup()


def build_alpha_research_fixture() -> AlphaResearchFixture:
    temporary = tempfile.TemporaryDirectory()
    store = FileSystemArtifactStore(Path(temporary.name))
    publisher = FileSystemCanonicalJsonArtifactPublisher(store)
    owners = MemoryCanonicalOwners()
    registry = default_operator_registry()
    evaluator = DeterministicReferenceEvaluator(registry)
    observations = tuple(f"2024-01-{value:02d}" for value in range(1, 7))
    instruments = ("CN.000001", "CN.600000", "CN.600519")
    close_values = (
        "10", "11", "13", "12", "15", "18",
        "20", "19", "22", "24", "23", "27",
        "30", "33", "32", "36", "40", "39",
    )
    payload = {
        "schema_version": FACTOR_INPUT_SCHEMA_VERSION,
        "schema_fingerprint": FACTOR_INPUT_SCHEMA_FINGERPRINT,
        "context": {
            "snapshot_id": "snapshot-alpha-research-v1",
            "universe_version_id": "universe-alpha-research-v1",
            "membership_identity": "PENDING",
            "source_data_truth_id": "data-truth-alpha-research-fixture-v1",
            "as_of": "2024-01-06",
            "knowledge_cutoff": "2024-01-06T16:00:00Z",
        },
        "instrument_ids": list(instruments),
        "observation_ids": list(observations),
        "fields": [
            {"name": "close", "value_type": "FLOAT_SERIES", "shape": [3, 6], "values": list(close_values)},
        ],
    }
    knowledge = datetime(2024, 1, 6, 16, tzinfo=timezone.utc)
    universe = CanonicalUniverseVersion.create(
        universe_version_id="universe-alpha-research-v1",
        snapshot_id="snapshot-alpha-research-v1",
        as_of=date(2024, 1, 6),
        knowledge_cutoff=knowledge,
        instrument_ids=instruments,
        truth_admission=FORMAL_ADMITTED_CEILING,
    )
    payload["context"]["membership_identity"] = universe.membership_identity
    descriptor = publisher.publish_canonical_json(
        payload,
        semantic_role=FACTOR_INPUT_PAYLOAD_ROLE,
        provenance_entity_id="data-truth-alpha-research-fixture-v1",
        schema_fingerprint=FACTOR_INPUT_SCHEMA_FINGERPRINT,
    )
    snapshot = CanonicalSnapshotVersion(
        "snapshot-alpha-research-v1",
        "data-truth-alpha-research-fixture-v1",
        date(2024, 1, 6),
        knowledge,
        "calendar-cn-a-share-fixture-v1",
        descriptor.artifact_id,
        descriptor.sha256,
        descriptor.byte_size,
        FACTOR_INPUT_SCHEMA_FINGERPRINT,
        FORMAL_ADMITTED_CEILING,
    )
    owners.snapshots[snapshot.snapshot_id] = snapshot
    owners.universes[universe.universe_version_id] = universe
    base_definition = FactorDefinitionVersion.create(
        "alpha_research_base_close", FeatureNode("close", "a-share-eod/1"), registry
    )
    owners.definitions[base_definition.factor_definition_version_id] = base_definition
    base_context = factor_payload_context_identity(
        snapshot=snapshot, universe=universe, definition=base_definition
    )
    owners.factor_contexts[base_context] = (snapshot, universe, base_definition)
    label = LabelSpec.create("forward-return", "close", 1, 0)
    split = SplitSpec.create(
        train_start=0,
        train_end=0,
        validation_start=2,
        validation_end=2,
        test_start=4,
        test_end=4,
        purge_observations=0,
        embargo_observations=0,
    )
    owners.label_specs[label.label_spec_id] = label
    owners.split_specs[split.split_spec_id] = split
    label_source_context = label_source_payload_context_identity(
        snapshot=snapshot, universe=universe, label_spec=label
    )
    owners.label_contexts[label_source_context] = (snapshot, universe, label)
    binding = A1CanonicalPayloadBindingResolver(
        snapshots=owners,
        factor_contexts=owners,
        materializations=owners,
        label_payloads=owners,
        label_contexts=owners,
        datasets=owners,
    )
    resolver = CanonicalPayloadResolver(binding_resolver=binding, byte_reader=store)
    factor_service = FormalFactorEvaluationService(
        snapshots=owners,
        universes=owners,
        definitions=owners,
        payload_resolver=resolver,
        evaluator=evaluator,
        artifact_publisher=publisher,
        materialization_publisher=owners,
    )
    base_materialization = factor_service.evaluate(
        FormalFactorEvaluationRequest(
            base_definition.factor_definition_version_id,
            snapshot.snapshot_id,
            universe.universe_version_id,
            1_000_000,
            PRE_ALPHA_CEILING,
        )
    )
    label_service = FormalLabelService(
        snapshots=owners,
        universes=owners,
        label_specs=owners,
        historical_source=A1CanonicalHistoricalLabelSource(payload_resolver=resolver),
        engine=DeterministicForwardReturnLabelEngine(),
        artifact_publisher=publisher,
        label_publisher=owners,
    )
    label_service.materialize(
        label_spec_id=label.label_spec_id,
        snapshot_id=snapshot.snapshot_id,
        universe_version_id=universe.universe_version_id,
        max_payload_bytes=1_000_000,
    )
    dataset_service = FormalDatasetService(
        snapshots=owners,
        universes=owners,
        materializations=owners,
        label_specs=owners,
        split_specs=owners,
        label_payloads=owners,
        payload_resolver=resolver,
        artifact_publisher=publisher,
        dataset_publisher=owners,
    )
    dataset = dataset_service.build(
        FormalDatasetBuildRequest(
            (base_materialization.feature_materialization_id,),
            label.label_spec_id,
            split.split_spec_id,
            snapshot.snapshot_id,
            universe.universe_version_id,
            1_000_000,
            PRE_ALPHA_CEILING,
        )
    )
    factor_context = FactorEvaluationContext(
        snapshot_id=snapshot.snapshot_id,
        universe_version_id=universe.universe_version_id,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            snapshot.snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            universe.universe_version_id, PRE_ALPHA_CEILING
        ),
        knowledge_cutoff=knowledge,
        calendar_version_id=snapshot.calendar_version_id,
        schema_version_id=FACTOR_INPUT_SCHEMA_VERSION,
        environment_fingerprint="python-3.14-alpha-research-fixture-v1",
        evaluator_version=evaluator.evaluator_version,
    )
    search_space = AlphaMiningSearchSpaceVersion.create(
        registry=registry,
        operator_allowlist=(
            "ADD@1.0.0",
            "SUBTRACT@1.0.0",
            "MULTIPLY@1.0.0",
            "DIVIDE@1.0.0",
            "LAG@1.0.0",
        ),
        source_fields=(
            AlphaMiningSourceField(
                "close", "a-share-eod/1", "data-truth-field:eod.close/1.0.0"
            ),
        ),
        generation_policy_version="v3.alpha-mining.grammar/1.1.0",
    )
    reward_policy = AlphaMiningRewardPolicyVersion.create(
        policy_version="v3.alpha-mining.reward/1.1.0",
        component_rules=(
            RewardComponentRule.create(RewardComponentName.IC, "0.5"),
            RewardComponentRule.create(RewardComponentName.RANK_IC, "1"),
            RewardComponentRule.create(RewardComponentName.COVERAGE, "0.25"),
            RewardComponentRule.create(RewardComponentName.TURNOVER, "-0.2"),
            RewardComponentRule.create(RewardComponentName.COMPLEXITY, "-0.01"),
        ),
        block_on_blocking_finding=True,
    )
    operation = OperationProfile(
        operation_id="alpha-research-bounded/1.0.0",
        resource_class="ALPHA_RESEARCH_CPU",
        cpu_slots=1,
        memory_hard_limit_bytes=256 * 1024 * 1024,
        scratch_budget_bytes=64 * 1024 * 1024,
        wall_clock_seconds=30,
        heartbeat_interval_seconds=5,
        resumable=False,
    )
    budget = ResearchLoopBudgetVersion.create(
        max_iterations=BudgetLimit.finite(2),
        max_actions=BudgetLimit.finite(4),
        max_candidates=BudgetLimit.finite(4),
        max_experiments=BudgetLimit.finite(4),
        max_model_calls=BudgetLimit.finite(1),
        resource_profile_ref=operation.operation_id,
        max_wallclock_seconds=BudgetLimit.finite(operation.wall_clock_seconds),
    )
    job = AlphaMiningJobSpec.create(
        universe_version_id=universe.universe_version_id,
        dataset_version_id=dataset.dataset_version_id,
        input_data_refs=(snapshot.payload_artifact_id, dataset.dataset_descriptor.artifact_id),
        data_semantic_profile_id="RESEARCH_FIXTURE_P1_ACTUAL_BYTES/1.0.0",
        search_space=search_space,
        max_expression_depth=4,
        max_node_count=12,
        max_candidate_count=4,
        max_generation_count=2,
        max_evaluation_count=4,
        deterministic_seed=20260814,
        search_mutation_policy_version="v3.alpha-mining.reward-guided-hash/1.0.0",
        evaluation_context=AlphaMiningEvaluationContext(
            dataset_version_id=dataset.dataset_version_id,
            factor_context=factor_context,
            period_start="2024-01-03",
            period_end="2024-01-05",
            label_ref=label.label_spec_id,
            horizon="1-observation",
            evaluation_policy_version="v3.alpha-research-evaluation/1.0.0",
            cost_turnover_context_ref="v3.alpha-research-top-quantile-turnover/1.0.0",
        ),
        reward_policy=reward_policy,
        operation_profile=operation,
        research_loop_budget=budget,
        stopping_rules=AlphaMiningStoppingRules(3, False),
    )
    service = AlphaResearchLoopService(
        registry=registry,
        datasets=owners,
        materializations=owners,
        payload_resolver=resolver,
        factor_service=factor_service,
        definition_binder=MemoryDefinitionBinder(owners, snapshot, universe),
        artifact_publisher=publisher,
        resources=ResourceGovernor(FakeResourceSampler()),
    )
    return AlphaResearchFixture(
        temporary, store, owners, resolver, publisher, service, job, dataset
    )


__all__ = ["AlphaResearchFixture", "build_alpha_research_fixture"]
