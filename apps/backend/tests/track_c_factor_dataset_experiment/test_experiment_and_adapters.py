from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone

from v3_backend.adapters.alphalens import (
    AlphalensReferenceAdapter,
    AlphalensReferenceError,
    AlphalensReferencePayload,
)
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
from v3_backend.domain.experiments import (
    EvidenceStatus,
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentResult,
    ExperimentRun,
    ExperimentVersion,
    FactorSample,
    FindingSeverity,
    ReviewerEvidence,
    ReviewerFinding,
    RewardVector,
    compute_reward_metrics,
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


def build_bindings():
    registry = default_operator_registry()
    definition = FactorDefinitionVersion.create(
        "close", FeatureNode("close", "eod.close/1.0.0"), registry
    )
    evaluator = DeterministicReferenceEvaluator(registry)
    context = FactorEvaluationContext(
        snapshot_id="snapshot-1",
        universe_version_id="universe-1",
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            "snapshot-1", PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            "universe-1", FORMAL_ADMITTED_CEILING
        ),
        knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
        calendar_version_id="calendar-1",
        schema_version_id="schema-1",
        environment_fingerprint="python-3.14-talib-0.7.1",
        evaluator_version=evaluator.evaluator_version,
    )
    result = evaluator.evaluate(definition, {"close": [1.0, 2.0, 3.0]})
    materialization = FeatureMaterialization.create(
        definition, result, context, artifact("a"), FORMAL_ADMITTED_CEILING
    )
    factor_evaluation = FactorEvaluation.create(
        definition, materialization, artifact("b"), FORMAL_ADMITTED_CEILING
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
    binding = DatasetBinding(
        context.snapshot_id,
        context.universe_version_id,
        context.snapshot_truth_binding,
        context.universe_truth_binding,
        context.knowledge_cutoff,
        context.calendar_version_id,
        context.schema_version_id,
        context.environment_fingerprint,
        context.evaluator_version,
    )
    dataset = DatasetVersion.create(
        feature_set=feature_set,
        evaluations=(factor_evaluation,),
        label_spec=label,
        split_spec=split,
        binding=binding,
        dataset_artifact_id=artifact("d"),
        provenance_artifact_id=artifact("e"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    experiment = ExperimentVersion.create(
        "factor-v0", "evaluate deterministic factor", "1.0.0"
    )
    run = ExperimentRun.create(
        experiment=experiment,
        dataset=dataset,
        factor_evaluation=factor_evaluation,
        code_version="track-c-v0/1",
        environment_fingerprint=context.environment_fingerprint,
        input_artifact_ids=(dataset.dataset_artifact_id, materialization.output_artifact_id),
        run_provenance_artifact_id=artifact("f"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    return definition, factor_evaluation, dataset, run


class ExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition, self.evaluation, self.dataset, self.run = build_bindings()
        self.started = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)

    def finding_and_evidence(self):
        finding = ReviewerFinding.create(
            category="lookahead",
            code="NO_RIGHT_LOOKAHEAD",
            severity=FindingSeverity.INFO,
            status=EvidenceStatus.PASS,
            evidence_artifact_ids=(artifact("1"),),
        )
        evidence = ReviewerEvidence.create(
            lookahead=EvidenceStatus.PASS,
            leakage=EvidenceStatus.PASS,
            split=EvidenceStatus.PASS,
            sample_coverage=EvidenceStatus.PASS,
            missingness=EvidenceStatus.PASS,
            turnover=EvidenceStatus.PASS,
            complexity=EvidenceStatus.PASS,
            multiple_testing_robustness=EvidenceStatus.NOT_RUN,
            findings=(finding,),
            provenance_artifact_id=artifact("2"),
        )
        return finding, evidence

    def test_dataset_member_factor_evaluation_is_accepted(self) -> None:
        self.assertIn(
            self.evaluation.factor_evaluation_id,
            self.dataset.factor_evaluation_ids,
        )
        self.assertEqual(
            self.run.factor_evaluation_id,
            self.evaluation.factor_evaluation_id,
        )

    def test_same_environment_non_member_factor_evaluation_is_rejected(self) -> None:
        registry = default_operator_registry()
        definition = FactorDefinitionVersion.create(
            "open", FeatureNode("open", "eod.open/1.0.0"), registry
        )
        evaluator = DeterministicReferenceEvaluator(registry)
        result = evaluator.evaluate(definition, {"open": [1.5, 2.5, 3.5]})
        materialization = FeatureMaterialization.create(
            definition,
            result,
            self.evaluation.context,
            artifact("9"),
            FORMAL_ADMITTED_CEILING,
        )
        non_member = FactorEvaluation.create(
            definition,
            materialization,
            artifact("a"),
            FORMAL_ADMITTED_CEILING,
        )
        self.assertEqual(
            non_member.context.environment_fingerprint,
            self.dataset.binding.environment_fingerprint,
        )
        self.assertNotIn(
            non_member.factor_evaluation_id,
            self.dataset.factor_evaluation_ids,
        )
        experiment = ExperimentVersion.create(
            "membership-check", "reject same-environment non-member", "1.0.0"
        )
        with self.assertRaisesRegex(ValueError, "exact DatasetVersion"):
            ExperimentRun.create(
                experiment=experiment,
                dataset=self.dataset,
                factor_evaluation=non_member,
                code_version="track-c-v0/1",
                environment_fingerprint=self.dataset.binding.environment_fingerprint,
                input_artifact_ids=(
                    self.dataset.dataset_artifact_id,
                    materialization.output_artifact_id,
                ),
                run_provenance_artifact_id=artifact("b"),
                proposed_state=FORMAL_ADMITTED_CEILING,
            )

    def test_run_binding_is_immutable(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.run.dataset_version_id = "different"  # type: ignore[misc]

    def test_failed_attempt_cannot_masquerade_as_success(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot publish"):
            ExperimentAttempt.create(
                run=self.run,
                ordinal=1,
                state=ExperimentAttemptState.FAILED,
                started_at=self.started,
                ended_at=self.started + timedelta(seconds=1),
                evidence_artifact_ids=(artifact("3"),),
                result_artifact_id=artifact("4"),
                error_code="BACKEND_FAILURE",
            )
        failed = ExperimentAttempt.create(
            run=self.run,
            ordinal=1,
            state=ExperimentAttemptState.FAILED,
            started_at=self.started,
            ended_at=self.started + timedelta(seconds=1),
            evidence_artifact_ids=(artifact("3"),),
            error_code="BACKEND_FAILURE",
        )
        _, evidence = self.finding_and_evidence()
        with self.assertRaisesRegex(ValueError, "failed Attempt"):
            RewardVector.create(
                run=self.run,
                attempt=failed,
                coverage=0.9,
                ic=0.1,
                rank_ic=0.12,
                lower_quantile_return=0.01,
                upper_quantile_return=0.04,
                quantile_spread=0.03,
                turnover=0.2,
                complexity=self.definition.metadata.complexity,
                reviewer_evidence=evidence,
                provenance_artifact_id=artifact("5"),
                proposed_state=FORMAL_ADMITTED_CEILING,
            )

    def test_reward_vector_and_result_preserve_provenance_and_truth_ceiling(self) -> None:
        attempt = ExperimentAttempt.create(
            run=self.run,
            ordinal=2,
            state=ExperimentAttemptState.SUCCEEDED,
            started_at=self.started,
            ended_at=self.started + timedelta(seconds=1),
            evidence_artifact_ids=(artifact("6"),),
            result_artifact_id=artifact("7"),
        )
        finding, evidence = self.finding_and_evidence()
        metrics = compute_reward_metrics(
            (
                FactorSample("A", 1.0, 0.01),
                FactorSample("B", 2.0, 0.02),
                FactorSample("C", 3.0, 0.03),
                FactorSample("D", 4.0, 0.04),
                FactorSample("MISSING", None, 0.05),
            ),
            previous_top_sample_ids=("B", "D"),
            quantiles=2,
            complexity=self.definition.metadata.complexity,
        )
        reward = RewardVector.create(
            run=self.run,
            attempt=attempt,
            coverage=metrics.coverage,
            ic=metrics.ic,
            rank_ic=metrics.rank_ic,
            lower_quantile_return=metrics.lower_quantile_return,
            upper_quantile_return=metrics.upper_quantile_return,
            quantile_spread=metrics.quantile_spread,
            turnover=metrics.turnover,
            complexity=metrics.complexity,
            reviewer_evidence=evidence,
            provenance_artifact_id=artifact("8"),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        result = ExperimentResult.create(self.run, attempt, reward)
        self.assertEqual(self.evaluation.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(self.dataset.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(self.run.truth_admission, PRE_ALPHA_CEILING)
        self.assertTrue(reward.reward_vector_id.startswith("rwv_sha256_"))
        self.assertEqual(reward.provenance_artifact_id, artifact("8"))
        self.assertEqual(reward.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(evidence.canonical_ceiling, PRE_ALPHA_CEILING)
        self.assertAlmostEqual(reward.coverage, 0.8)
        self.assertAlmostEqual(reward.ic, 1.0)
        self.assertAlmostEqual(reward.rank_ic, 1.0)
        self.assertAlmostEqual(reward.lower_quantile_return, 0.015)
        self.assertAlmostEqual(reward.upper_quantile_return, 0.035)
        self.assertAlmostEqual(reward.quantile_spread, 0.02)
        self.assertAlmostEqual(reward.turnover, 0.5)
        self.assertEqual(evidence.finding_ids, (finding.finding_id,))
        self.assertEqual(result.successful_attempt_id, attempt.experiment_attempt_id)


class AlphalensAdapterTests(unittest.TestCase):
    def test_reference_payload_is_non_authoritative_and_content_identified(self) -> None:
        _, evaluation, dataset, _ = build_bindings()
        payload = AlphalensReferencePayload(
            factor_evaluation_id=evaluation.factor_evaluation_id,
            dataset_version_id=dataset.dataset_version_id,
            input_artifact_id=artifact("a"),
            output_artifact_id=artifact("b"),
            provenance_artifact_id=artifact("c"),
            metrics={"ic": 0.1, "rank_ic": 0.12, "turnover": 0.2},
        )
        first = AlphalensReferenceAdapter.ingest(payload)
        second = AlphalensReferenceAdapter.ingest(payload)
        self.assertEqual(first, second)
        self.assertEqual(first.authority, "REFERENCE_ONLY")
        self.assertEqual(first.dependency_version, "0.4.6")

    def test_reference_adapter_rejects_second_authority_fields(self) -> None:
        with self.assertRaises(AlphalensReferenceError):
            AlphalensReferencePayload(
                factor_evaluation_id="fev",
                dataset_version_id="dsv",
                input_artifact_id=artifact("a"),
                output_artifact_id=artifact("b"),
                provenance_artifact_id=artifact("c"),
                metrics={"formal_admission": 1.0},
            )


if __name__ == "__main__":
    unittest.main()
