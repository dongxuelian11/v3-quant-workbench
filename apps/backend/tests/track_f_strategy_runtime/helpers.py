from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.datasets import (
    DatasetBinding,
    DatasetVersion,
    FeatureSetVersion,
    LabelSpec,
    SplitSpec,
)
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.domain.strategies import (
    BindingInputRef,
    BindingSlot,
    BoundInputReference,
    CrossSectionInputArtifact,
    EvaluationPeriod,
    ExactCalendarReference,
    ExactSnapshotReference,
    ExactUniverseReference,
    MissingSemantics,
    NodeOutputRef,
    PortCardinality,
    PortSpec,
    PortValueType,
    StrategyCompiler,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
    StrategyIr,
    StrategyNode,
    default_component_registry,
)


def sha(character: str) -> str:
    return character * 64


def artifact(character: str) -> str:
    return "art_sha256_" + sha(character)


INSTRUMENTS = ("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ")


def score_port() -> PortSpec:
    return PortSpec(
        value_type=PortValueType.SCORE_MAP,
        cardinality=PortCardinality.CROSS_SECTION,
        time_basis="BOUND_DECISION_TIME",
        universe_basis="BOUND_UNIVERSE_MEMBERSHIP",
        missing_semantics=MissingSemantics.EXPLICIT,
    )


def build_strategy_ir(
    *,
    node_order: tuple[str, ...] | None = None,
    projection_tag: str = "first",
    explicit_defaults: bool = False,
) -> StrategyIr:
    nodes = {
        "input.scores": StrategyNode(
            "input.scores",
            "v3.strategy.input.bound_scores",
            "1.0.0",
            {"artifact": BindingInputRef("scores")},
            {},
            {"position": {"x": 10, "y": 20}, "tag": projection_tag},
        ),
        "gate.nonnegative": StrategyNode(
            "gate.nonnegative",
            "v3.strategy.condition.minimum",
            "1.0.0",
            {"scores": NodeOutputRef("input.scores", "scores")},
            {"threshold": "0", "inclusive": True} if explicit_defaults else {},
            {"position": {"x": 30, "y": 40}},
        ),
        "rank.primary": StrategyNode(
            "rank.primary",
            "v3.strategy.rank.score",
            "1.0.0",
            {
                "scores": NodeOutputRef("input.scores", "scores"),
                "eligible": NodeOutputRef("gate.nonnegative", "eligible"),
            },
            {"descending": True, "missing_policy": "EXCLUDE"}
            if explicit_defaults
            else {},
        ),
        "select.top2": StrategyNode(
            "select.top2",
            "v3.strategy.select.top_n",
            "1.0.0",
            {"ranked": NodeOutputRef("rank.primary", "ranked")},
            {"count": 2},
        ),
        "output.signal": StrategyNode(
            "output.signal",
            "v3.strategy.output.signal",
            "1.0.0",
            {"scores": NodeOutputRef("input.scores", "scores")},
            {"signal_kind": "SCORE"} if explicit_defaults else {},
        ),
        "output.selection": StrategyNode(
            "output.selection",
            "v3.strategy.output.selection",
            "1.0.0",
            {"selection": NodeOutputRef("select.top2", "selection")},
            {},
        ),
        "output.intent": StrategyNode(
            "output.intent",
            "v3.strategy.output.portfolio_intent",
            "1.0.0",
            {
                "scores": NodeOutputRef("input.scores", "scores"),
                "selection": NodeOutputRef("select.top2", "selection"),
            },
            {
                "gross_exposure": "1",
                "exposure_mode": "ABSOLUTE_DESIRED_EXPOSURE",
                "cash_policy": "RESIDUAL",
                "rebalance_intent": "AT_BOUND_DECISION_TIME",
            }
            if explicit_defaults
            else {},
        ),
    }
    order = node_order or tuple(nodes)
    return StrategyIr(
        required_bindings=(
            BindingSlot("scores", "FEATURE_MATERIALIZATION", score_port()),
        ),
        nodes=tuple(nodes[node_id] for node_id in order),
        outputs={
            "signal": NodeOutputRef("output.signal", "artifact"),
            "selection": NodeOutputRef("output.selection", "artifact"),
            "portfolio_intent": NodeOutputRef("output.intent", "artifact"),
        },
        projection_metadata={"viewport": projection_tag, "formatting": "ignored"},
    )


@dataclass(frozen=True)
class RuntimeFixture:
    definition: StrategyDefinitionVersion
    binding: StrategyEvaluationBindingVersion
    runtime_input: CrossSectionInputArtifact
    dataset: DatasetVersion
    factor_evaluation: FactorEvaluation
    materialization: FeatureMaterialization


def build_runtime_fixture(
    *,
    snapshot_id: str = "snapshot-1",
    universe_id: str = "universe-1",
    cutoff_hour: int = 16,
    factor_values: tuple[float | None, ...] = (3.0, 3.0, 2.0, None),
    runtime_values: dict[str, object | None] | None = None,
    definition: StrategyDefinitionVersion | None = None,
) -> RuntimeFixture:
    factor_registry = default_operator_registry()
    factor_definition = FactorDefinitionVersion.create(
        "close", FeatureNode("close", "eod.close/1.0.0"), factor_registry
    )
    factor_evaluator = DeterministicReferenceEvaluator(factor_registry)
    factor_context = FactorEvaluationContext(
        snapshot_id=snapshot_id,
        universe_version_id=universe_id,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            snapshot_id, FORMAL_ADMITTED_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            universe_id, FORMAL_ADMITTED_CEILING
        ),
        knowledge_cutoff=datetime(2026, 1, 5, cutoff_hour, tzinfo=timezone.utc),
        calendar_version_id="calendar-1",
        schema_version_id="schema-1",
        environment_fingerprint="cpython-3.14.7-track-f-v0",
        evaluator_version=factor_evaluator.evaluator_version,
    )
    factor_result = factor_evaluator.evaluate(
        factor_definition, {"close": list(factor_values)}
    )
    materialization = FeatureMaterialization.create(
        factor_definition,
        factor_result,
        factor_context,
        artifact("a"),
        FORMAL_ADMITTED_CEILING,
    )
    factor_evaluation = FactorEvaluation.create(
        factor_definition,
        materialization,
        artifact("b"),
        FORMAL_ADMITTED_CEILING,
    )
    feature_set = FeatureSetVersion.create((factor_evaluation,), artifact("c"))
    label = LabelSpec.create("next_return", "close", 1, 0)
    split = SplitSpec.create(
        train_start=0,
        train_end=9,
        validation_start=12,
        validation_end=19,
        test_start=22,
        test_end=29,
        purge_observations=1,
        embargo_observations=1,
    )
    dataset = DatasetVersion.create(
        feature_set=feature_set,
        evaluations=(factor_evaluation,),
        label_spec=label,
        split_spec=split,
        binding=DatasetBinding(
            snapshot_id=factor_context.snapshot_id,
            universe_version_id=factor_context.universe_version_id,
            snapshot_truth_binding=factor_context.snapshot_truth_binding,
            universe_truth_binding=factor_context.universe_truth_binding,
            knowledge_cutoff=factor_context.knowledge_cutoff,
            calendar_version_id=factor_context.calendar_version_id,
            schema_version_id=factor_context.schema_version_id,
            environment_fingerprint=factor_context.environment_fingerprint,
            evaluator_version=factor_context.evaluator_version,
        ),
        dataset_artifact_id=artifact("d"),
        provenance_artifact_id=artifact("e"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    definition = definition or StrategyCompiler(default_component_registry()).compile(
        build_strategy_ir()
    )
    input_reference = BoundInputReference.from_feature_materialization(
        "scores", materialization
    )
    membership_hash = sha("f")
    binding = StrategyEvaluationBindingVersion.create(
        definition=definition,
        dataset=dataset,
        factor_evaluations=(factor_evaluation,),
        feature_materializations=(materialization,),
        snapshot=ExactSnapshotReference(
            snapshot_id, sha("1"), PRE_ALPHA_CEILING
        ),
        universe=ExactUniverseReference(
            universe_id,
            sha("2"),
            "art_sha256_" + membership_hash,
            membership_hash,
            INSTRUMENTS,
            PRE_ALPHA_CEILING,
        ),
        period=EvaluationPeriod(
            datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
            datetime(2026, 1, 5, cutoff_hour, tzinfo=timezone.utc),
        ),
        knowledge_cutoff=factor_context.knowledge_cutoff,
        calendar=ExactCalendarReference(
            "calendar-1", sha("3"), "Asia/Shanghai", PRE_ALPHA_CEILING
        ),
        compiler_version=definition.compiler_version,
        runtime_profile_id=definition.runtime_profile_id,
        environment_fingerprint=factor_context.environment_fingerprint,
        input_references=(input_reference,),
    )
    values = runtime_values or {
        "000001.SZ": "3",
        "000002.SZ": "3.0",
        "000003.SZ": "2",
        "000004.SZ": None,
    }
    runtime_input = CrossSectionInputArtifact(
        binding_key="scores",
        artifact_id=input_reference.artifact_id,
        content_sha256=input_reference.content_sha256,
        decision_time=datetime(2026, 1, 5, 15, tzinfo=timezone.utc),
        values=values,
    )
    return RuntimeFixture(
        definition=definition,
        binding=binding,
        runtime_input=runtime_input,
        dataset=dataset,
        factor_evaluation=factor_evaluation,
        materialization=materialization,
    )
