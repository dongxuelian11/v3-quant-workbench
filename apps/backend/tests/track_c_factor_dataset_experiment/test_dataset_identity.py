from __future__ import annotations

import dataclasses
import inspect
import unittest
from datetime import datetime, timezone

from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
    UNKNOWN_CEILING,
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
    UnresolvedIdUpstreamTruthBinding,
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

    def context(
        self,
        snapshot_id: str = "snapshot-1",
        universe_id: str = "universe-1",
        cutoff_hour: int = 8,
    ) -> FactorEvaluationContext:
        return FactorEvaluationContext(
            snapshot_id=snapshot_id,
            universe_version_id=universe_id,
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                snapshot_id, PRE_ALPHA_CEILING
            ),
            universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                universe_id, FORMAL_ADMITTED_CEILING
            ),
            knowledge_cutoff=datetime(2026, 1, 5, cutoff_hour, tzinfo=timezone.utc),
            calendar_version_id="calendar-1",
            schema_version_id="schema-1",
            environment_fingerprint="python-3.14-talib-0.7.1",
            evaluator_version=self.evaluator.evaluator_version,
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

    def alternate_evaluation(
        self, context: FactorEvaluationContext, suffix: str
    ) -> FactorEvaluation:
        definition = FactorDefinitionVersion.create(
            "open", FeatureNode("open", "eod.open/1.0.0"), self.registry
        )
        result = self.evaluator.evaluate(
            definition, {"open": [1.5, 2.5, None, 4.5]}
        )
        materialization = FeatureMaterialization.create(
            definition,
            result,
            context,
            artifact(suffix),
            FORMAL_ADMITTED_CEILING,
        )
        return FactorEvaluation.create(
            definition,
            materialization,
            artifact("g"),
            FORMAL_ADMITTED_CEILING,
        )

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

    def dataset(
        self,
        context: FactorEvaluationContext,
        suffix: str,
        binding: DatasetBinding | None = None,
    ) -> DatasetVersion:
        _, evaluation = self.evaluation(context, suffix)
        return self.dataset_from_evaluations(context, (evaluation,), binding)

    def dataset_from_evaluations(
        self,
        context: FactorEvaluationContext,
        evaluations: tuple[FactorEvaluation, ...],
        binding: DatasetBinding | None = None,
    ) -> DatasetVersion:
        feature_set = FeatureSetVersion.create(evaluations, artifact("f"))
        label = LabelSpec.create("next_return", "close", 1, 0)
        binding = binding or DatasetBinding(
            snapshot_id=context.snapshot_id,
            universe_version_id=context.universe_version_id,
            snapshot_truth_binding=context.snapshot_truth_binding,
            universe_truth_binding=context.universe_truth_binding,
            knowledge_cutoff=context.knowledge_cutoff,
            calendar_version_id=context.calendar_version_id,
            schema_version_id=context.schema_version_id,
            environment_fingerprint=context.environment_fingerprint,
            evaluator_version=context.evaluator_version,
        )
        return DatasetVersion.create(
            feature_set=feature_set,
            evaluations=evaluations,
            label_spec=label,
            split_spec=self.split(),
            binding=binding,
            dataset_artifact_id=artifact("d"),
            provenance_artifact_id=artifact("c"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )

    def test_snapshot_and_universe_truth_bindings_are_exact(self) -> None:
        context = self.context()
        self.assertEqual(
            tuple(item.source_id for item in context.upstream_requirements),
            (context.snapshot_id, context.universe_version_id),
        )
        self.assertEqual(
            context.snapshot_truth_binding.source_id,
            context.snapshot_id,
        )
        self.assertEqual(
            context.universe_truth_binding.source_id,
            context.universe_version_id,
        )

    def test_mismatched_and_synthetic_core_source_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact bound identity"):
            FactorEvaluationContext(
                snapshot_id="snapshot-1",
                universe_version_id="universe-1",
                snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                    "snapshot-truth", PRE_ALPHA_CEILING
                ),
                universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                    "universe-1", PRE_ALPHA_CEILING
                ),
                knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
                calendar_version_id="calendar-1",
                schema_version_id="schema-1",
                environment_fingerprint="python-3.14-talib-0.7.1",
                evaluator_version=self.evaluator.evaluator_version,
            )
        with self.assertRaisesRegex(ValueError, "exact bound identity"):
            FactorEvaluationContext(
                snapshot_id="snapshot-1",
                universe_version_id="universe-1",
                snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                    "snapshot-1", PRE_ALPHA_CEILING
                ),
                universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                    "universe-truth", PRE_ALPHA_CEILING
                ),
                knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
                calendar_version_id="calendar-1",
                schema_version_id="schema-1",
                environment_fingerprint="python-3.14-talib-0.7.1",
                evaluator_version=self.evaluator.evaluator_version,
            )

    def test_old_synthetic_upstream_requirement_injection_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "upstream_requirements"):
            FactorEvaluationContext(  # type: ignore[call-arg]
                snapshot_id="snapshot-1",
                universe_version_id="universe-1",
                snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                    "snapshot-1", PRE_ALPHA_CEILING
                ),
                universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                    "universe-1", PRE_ALPHA_CEILING
                ),
                knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
                calendar_version_id="calendar-1",
                schema_version_id="schema-1",
                environment_fingerprint="python-3.14-talib-0.7.1",
                evaluator_version=self.evaluator.evaluator_version,
                upstream_requirements=(
                    UpstreamRequirement("snapshot-truth", PRE_ALPHA_CEILING),
                    UpstreamRequirement("universe-truth", FORMAL_ADMITTED_CEILING),
                ),
            )

    def test_raw_formal_state_is_capped_and_propagates_to_dataset(self) -> None:
        context = FactorEvaluationContext(
            snapshot_id="snapshot-formal-claim",
            universe_version_id="universe-formal-claim",
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                "snapshot-formal-claim", FORMAL_ADMITTED_CEILING
            ),
            universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                "universe-formal-claim", FORMAL_ADMITTED_CEILING
            ),
            knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
            calendar_version_id="calendar-1",
            schema_version_id="schema-1",
            environment_fingerprint="python-3.14-talib-0.7.1",
            evaluator_version=self.evaluator.evaluator_version,
        )
        materialization, evaluation = self.evaluation(context, "a")
        dataset = self.dataset(context, "a")
        self.assertEqual(context.snapshot_truth_binding.truth_ceiling, PRE_ALPHA_CEILING)
        self.assertEqual(context.universe_truth_binding.truth_ceiling, PRE_ALPHA_CEILING)
        self.assertEqual(materialization.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(evaluation.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(dataset.truth_admission, PRE_ALPHA_CEILING)

    def test_dataset_rejects_conflicting_context_authority_binding(self) -> None:
        context = self.context()
        conflicting_binding = DatasetBinding(
            snapshot_id=context.snapshot_id,
            universe_version_id=context.universe_version_id,
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                context.snapshot_id, UNKNOWN_CEILING
            ),
            universe_truth_binding=context.universe_truth_binding,
            knowledge_cutoff=context.knowledge_cutoff,
            calendar_version_id=context.calendar_version_id,
            schema_version_id=context.schema_version_id,
            environment_fingerprint=context.environment_fingerprint,
            evaluator_version=context.evaluator_version,
        )
        with self.assertRaisesRegex(ValueError, "must match every FactorEvaluation"):
            self.dataset(context, "a", conflicting_binding)

    def test_dataset_has_no_independent_upstream_authority_parameter(self) -> None:
        parameters = inspect.signature(DatasetVersion.create).parameters
        self.assertNotIn("required_upstreams", parameters)
        self.assertNotIn("factor_evaluation_ids", parameters)

    def test_dataset_membership_is_derived_deterministic_and_immutable(self) -> None:
        context = self.context()
        _, first_evaluation = self.evaluation(context, "a")
        second_evaluation = self.alternate_evaluation(context, "b")
        first = self.dataset_from_evaluations(
            context, (first_evaluation, second_evaluation)
        )
        reordered = self.dataset_from_evaluations(
            context, (second_evaluation, first_evaluation)
        )
        single = self.dataset_from_evaluations(context, (first_evaluation,))
        expected = tuple(
            sorted(
                (
                    first_evaluation.factor_evaluation_id,
                    second_evaluation.factor_evaluation_id,
                )
            )
        )
        self.assertEqual(first.factor_evaluation_ids, expected)
        self.assertEqual(first.to_wire()["factor_evaluation_ids"], list(expected))
        self.assertEqual(first.dataset_version_id, reordered.dataset_version_id)
        self.assertNotEqual(first.dataset_version_id, single.dataset_version_id)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.factor_evaluation_ids = ()  # type: ignore[misc]

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
