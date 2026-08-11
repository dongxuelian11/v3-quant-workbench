from __future__ import annotations

import unittest
from datetime import datetime, timezone

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    UpstreamRequirement,
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
    default_operator_registry,
)


def artifact(character: str) -> str:
    return "art_sha256_" + character * 64


class DatasetIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_operator_registry()
        self.definition = FactorDefinitionVersion.create(
            "close", FeatureNode("close", "eod.close/1.0.0"), self.registry
        )
        self.evaluator = DeterministicReferenceEvaluator(self.registry)
        self.result = self.evaluator.evaluate(
            self.definition, {"close": [1.0, 2.0, None, 4.0]}
        )
        self.upstream = (
            UpstreamRequirement("snapshot-truth", PRE_ALPHA_CEILING),
            UpstreamRequirement("universe-truth", FORMAL_ADMITTED_CEILING),
        )

    def context(
        self,
        snapshot_id: str = "snapshot-1",
        universe_id: str = "universe-1",
        cutoff_hour: int = 8,
    ) -> FactorEvaluationContext:
        return FactorEvaluationContext(
            snapshot_id=snapshot_id,
            universe_version_id=universe_id,
            knowledge_cutoff=datetime(2026, 1, 5, cutoff_hour, tzinfo=timezone.utc),
            calendar_version_id="calendar-1",
            schema_version_id="schema-1",
            environment_fingerprint="python-3.14-talib-0.7.1",
            evaluator_version=self.evaluator.evaluator_version,
            upstream_requirements=self.upstream,
        )

    def evaluation(self, context: FactorEvaluationContext, suffix: str):
        materialization = FeatureMaterialization.create(
            self.definition,
            self.result,
            context,
            artifact(suffix),
            FORMAL_ADMITTED_CEILING,
        )
        evaluation = FactorEvaluation.create(
            self.definition,
            materialization,
            artifact("e"),
            FORMAL_ADMITTED_CEILING,
        )
        return materialization, evaluation

    @staticmethod
    def split() -> SplitSpec:
        return SplitSpec.create(
            train_start=0,
            train_end=9,
            validation_start=12,
            validation_end=19,
            test_start=22,
            test_end=29,
            purge_observations=1,
            embargo_observations=1,
        )

    def dataset(self, context: FactorEvaluationContext, suffix: str) -> DatasetVersion:
        _, evaluation = self.evaluation(context, suffix)
        feature_set = FeatureSetVersion.create((evaluation,), artifact("f"))
        label = LabelSpec.create("next_return", "close", 1, 0)
        binding = DatasetBinding(
            snapshot_id=context.snapshot_id,
            universe_version_id=context.universe_version_id,
            knowledge_cutoff=context.knowledge_cutoff,
            calendar_version_id=context.calendar_version_id,
            schema_version_id=context.schema_version_id,
            environment_fingerprint=context.environment_fingerprint,
            evaluator_version=context.evaluator_version,
        )
        return DatasetVersion.create(
            feature_set=feature_set,
            evaluations=(evaluation,),
            label_spec=label,
            split_spec=self.split(),
            binding=binding,
            dataset_artifact_id=artifact("d"),
            provenance_artifact_id=artifact("c"),
            required_upstreams=self.upstream,
            proposed_state=FORMAL_ADMITTED_CEILING,
        )

    def test_definition_identity_is_independent_from_evaluation_identity(self) -> None:
        first_materialization, first_evaluation = self.evaluation(
            self.context(), "a"
        )
        second_materialization, second_evaluation = self.evaluation(
            self.context(snapshot_id="snapshot-2"), "b"
        )
        self.assertEqual(
            first_evaluation.factor_definition_version_id,
            second_evaluation.factor_definition_version_id,
        )
        self.assertNotEqual(
            first_materialization.feature_materialization_id,
            second_materialization.feature_materialization_id,
        )
        self.assertNotEqual(
            first_evaluation.factor_evaluation_id,
            second_evaluation.factor_evaluation_id,
        )

    def test_snapshot_universe_and_pit_change_dataset_identity(self) -> None:
        base = self.dataset(self.context(), "a")
        changed = (
            self.dataset(self.context(snapshot_id="snapshot-2"), "b"),
            self.dataset(self.context(universe_id="universe-2"), "c"),
            self.dataset(self.context(cutoff_hour=9), "d"),
        )
        self.assertEqual(len({base.dataset_version_id, *(v.dataset_version_id for v in changed)}), 4)

    def test_leakage_unsafe_split_is_rejected(self) -> None:
        split = SplitSpec.create(
            train_start=0,
            train_end=9,
            validation_start=10,
            validation_end=19,
            test_start=20,
            test_end=29,
            purge_observations=0,
            embargo_observations=0,
        )
        label = LabelSpec.create("five_day_return", "close", 5, 0)
        with self.assertRaisesRegex(ValueError, "purge-safe"):
            split.validate_for_label(label)

    def test_a0_truth_ceiling_propagates(self) -> None:
        dataset = self.dataset(self.context(), "a")
        self.assertEqual(dataset.truth_admission, PRE_ALPHA_CEILING)


if __name__ == "__main__":
    unittest.main()
