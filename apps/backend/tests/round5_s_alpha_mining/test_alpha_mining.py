from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timezone

from v3_backend.adapters.alpha_mining import AlphaMiningUserJobService
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.control_plane.resource_governor import (
    OperationProfile,
)
from v3_backend.domain.agent_research_loop import (
    BudgetLimit,
    ResearchActionDraft,
    ResearchActionState,
    ResearchActionType,
    ResearchLoopBudgetVersion,
)
from v3_backend.domain.alpha_mining import (
    AlphaMiningCandidateDisposition,
    AlphaMiningCandidateProposal,
    AlphaMiningCandidateRecord,
    AlphaMiningContractError,
    AlphaMiningEngine,
    AlphaMiningEvaluationContext,
    AlphaMiningEvaluationEvidence,
    AlphaMiningJobDraft,
    AlphaMiningJobSpec,
    AlphaMiningReward,
    AlphaMiningRewardPolicyVersion,
    AlphaMiningRewardStatus,
    AlphaMiningRunStatus,
    AlphaMiningSearchSpaceVersion,
    AlphaMiningSourceField,
    AlphaMiningStopReason,
    AlphaMiningStoppingRules,
    DeterministicGrammarCandidateGenerator,
    MissingRewardComponentPolicy,
    RewardComponentName,
    RewardComponentRule,
)
from v3_backend.domain.experiments import (
    EvidenceStatus,
    ExperimentAttempt,
    ExperimentAttemptState,
    ExperimentRun,
    FindingSeverity,
    ReviewerEvidence,
    ReviewerFinding,
    RewardVector,
)
from v3_backend.domain.factor_assets import MiningFactorCandidate
from v3_backend.domain.factors import (
    DeterministicReferenceEvaluator,
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FeatureMaterialization,
    FeatureNode,
    OperatorNode,
    UnresolvedIdUpstreamTruthBinding,
    default_operator_registry,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


def artifact(character: str) -> str:
    return "art_sha256_" + character * 64


def object_id(prefix: str, payload: object) -> str:
    return prefix + canonical_sha256(payload)


class ExactExistingEvaluationFixture:
    """Test port proving S delegates all math to the existing evaluator."""

    def __init__(
        self,
        registry,
        *,
        available_components: tuple[RewardComponentName, ...] | None = None,
        blocking: bool = False,
    ) -> None:
        self.registry = registry
        self.evaluator = DeterministicReferenceEvaluator(registry)
        self.available_components = available_components or tuple(RewardComponentName)
        self.blocking = blocking
        self.calls: list[FactorDefinitionVersion] = []

    def evaluate_existing(
        self, definition: FactorDefinitionVersion, job: AlphaMiningJobSpec
    ) -> AlphaMiningEvaluationEvidence:
        self.calls.append(definition)
        features = {
            name: tuple(float(index + offset + 1) for index in range(12))
            for offset, name in enumerate(definition.metadata.input_features)
        }
        result = self.evaluator.evaluate(definition, features)
        materialization = FeatureMaterialization.create(
            definition,
            result,
            job.evaluation_context.factor_context,
            artifact("a"),
            PRE_ALPHA_CEILING,
        )
        evaluation = FactorEvaluation.create(
            definition,
            materialization,
            artifact("b"),
            PRE_ALPHA_CEILING,
        )
        run_id = object_id(
            "exprun_sha256_",
            {
                "dataset": job.dataset_version_id,
                "evaluation": evaluation.factor_evaluation_id,
            },
        )
        run = ExperimentRun(
            experiment_run_id=run_id,
            experiment_version_id="expv_sha256_" + "1" * 64,
            dataset_version_id=job.dataset_version_id,
            factor_evaluation_id=evaluation.factor_evaluation_id,
            code_version="round5-s-fixture/1.0.0",
            environment_fingerprint=evaluation.context.environment_fingerprint,
            input_artifact_ids=(artifact("c"), materialization.output_artifact_id),
            run_provenance_artifact_id=artifact("d"),
            truth_admission=PRE_ALPHA_CEILING,
        )
        started = datetime(2026, 8, 13, 1, tzinfo=timezone.utc)
        attempt = ExperimentAttempt.create(
            run=run,
            ordinal=1,
            state=ExperimentAttemptState.SUCCEEDED,
            started_at=started,
            ended_at=started,
            evidence_artifact_ids=(artifact("e"),),
            result_artifact_id=artifact("f"),
        )
        finding = ReviewerFinding.create(
            category="leakage",
            code="BLOCKING_FIXTURE" if self.blocking else "PIT_SAFE_FIXTURE",
            severity=FindingSeverity.BLOCKING if self.blocking else FindingSeverity.INFO,
            status=EvidenceStatus.FAIL if self.blocking else EvidenceStatus.PASS,
            evidence_artifact_ids=(artifact("1"),),
        )
        reviewer = ReviewerEvidence.create(
            lookahead=EvidenceStatus.FAIL if self.blocking else EvidenceStatus.PASS,
            leakage=EvidenceStatus.FAIL if self.blocking else EvidenceStatus.PASS,
            split=EvidenceStatus.PASS,
            sample_coverage=EvidenceStatus.PASS,
            missingness=EvidenceStatus.PASS,
            turnover=EvidenceStatus.PASS,
            complexity=EvidenceStatus.PASS,
            multiple_testing_robustness=EvidenceStatus.NOT_RUN,
            findings=(finding,),
            provenance_artifact_id=artifact("2"),
        )
        reward = RewardVector.create(
            run=run,
            attempt=attempt,
            coverage=1.0,
            ic=0.2,
            rank_ic=0.25,
            lower_quantile_return=-0.01,
            upper_quantile_return=0.03,
            quantile_spread=0.04,
            turnover=0.1,
            complexity=definition.metadata.complexity,
            reviewer_evidence=reviewer,
            provenance_artifact_id=artifact("3"),
            proposed_state=PRE_ALPHA_CEILING,
        )
        return AlphaMiningEvaluationEvidence(
            evaluation_context=job.evaluation_context,
            factor_evaluation=evaluation,
            experiment_run=run,
            experiment_attempt=attempt,
            reward_vector=reward,
            reviewer_evidence=reviewer,
            reviewer_findings=(finding,),
            available_components=self.available_components,
        )


class SequenceGenerator:
    def __init__(self, proposals: tuple[AlphaMiningCandidateProposal, ...]) -> None:
        self.proposals = proposals

    def propose(self, job, *, generation_index: int, candidate_ordinal: int):
        proposal = self.proposals[(candidate_ordinal - 1) % len(self.proposals)]
        return dataclasses.replace(
            proposal,
            source_lineage_ref=(
                f"sequence:{generation_index}:{candidate_ordinal}:"
                f"{proposal.source_lineage_ref}"
            ),
        )


class CallerClaimedAuthorization:
    actor_kind = "USER"
    issued_by = "V3_CONTROL_PLANE"
    resolution_status = "RESOLVED_EXPLICIT_USER_REQUEST"

    def __init__(self, job_id: str) -> None:
        self.alpha_mining_job_spec_id = job_id


class FakeAuthorizationPersistence:
    def __init__(self) -> None:
        self.calls = 0

    def assert_explicit_user_authorized(self, authorization, job) -> None:
        del authorization, job
        self.calls += 1


class RecordingProductionEngine:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, job, *, resource_observation: str):
        del job, resource_observation
        self.calls += 1
        raise AssertionError("denied production start reached engine.run")


class RecordingResourceGovernor:
    def __init__(self) -> None:
        self.admit_calls = 0
        self.release_calls = 0

    def admit(self, lease_id, profile):
        del lease_id, profile
        self.admit_calls += 1
        raise AssertionError("denied production start reached ResourceGovernor.admit")

    def release(self, lease_id) -> None:
        del lease_id
        self.release_calls += 1


class AlphaMiningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_operator_registry()
        self.evaluator = DeterministicReferenceEvaluator(self.registry)
        self.factor_context = FactorEvaluationContext(
            snapshot_id="snapshot-round5-s-fixture",
            universe_version_id="universe-round5-s-fixture",
            snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
                "snapshot-round5-s-fixture", PRE_ALPHA_CEILING
            ),
            universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
                "universe-round5-s-fixture", PRE_ALPHA_CEILING
            ),
            knowledge_cutoff=datetime(2026, 8, 12, 8, tzinfo=timezone.utc),
            calendar_version_id="calendar-cn-a-share/1.0.0",
            schema_version_id="schema-eod/1.0.0",
            environment_fingerprint="python-3.14.7-windows-round5-s",
            evaluator_version=self.evaluator.evaluator_version,
        )
        self.source_fields = (
            AlphaMiningSourceField(
                "close",
                "eod.close/1.0.0",
                "data-truth-field:eod.close/1.0.0",
            ),
            AlphaMiningSourceField(
                "open",
                "eod.open/1.0.0",
                "data-truth-field:eod.open/1.0.0",
            ),
        )
        self.search_space = AlphaMiningSearchSpaceVersion.create(
            registry=self.registry,
            operator_allowlist=(
                "ADD@1.0.0",
                "SUBTRACT@1.0.0",
                "MULTIPLY@1.0.0",
                "DIVIDE@1.0.0",
                "LAG@1.0.0",
            ),
            source_fields=self.source_fields,
            generation_policy_version="v3.alpha-mining.grammar/1.0.0",
        )
        self.reward_policy = AlphaMiningRewardPolicyVersion.create(
            policy_version="v3.alpha-mining.reward/1.0.0",
            component_rules=(
                RewardComponentRule.create(RewardComponentName.IC, "0.5"),
                RewardComponentRule.create(RewardComponentName.RANK_IC, "1"),
                RewardComponentRule.create(RewardComponentName.COVERAGE, "0.25"),
                RewardComponentRule.create(RewardComponentName.TURNOVER, "-0.2"),
                RewardComponentRule.create(RewardComponentName.COMPLEXITY, "-0.01"),
            ),
            block_on_blocking_finding=True,
        )
        self.operation_profile = OperationProfile(
            operation_id="alpha-mining-bounded/1.0.0",
            resource_class="ALPHA_MINING_CPU",
            cpu_slots=1,
            memory_hard_limit_bytes=256 * 1024 * 1024,
            scratch_budget_bytes=64 * 1024 * 1024,
            wall_clock_seconds=30,
            heartbeat_interval_seconds=5,
            resumable=False,
        )

    def job(self, **overrides) -> AlphaMiningJobSpec:
        max_candidates = overrides.pop("max_candidate_count", 8)
        max_generations = overrides.pop("max_generation_count", 4)
        max_evaluations = overrides.pop("max_evaluation_count", 6)
        target = overrides.pop("target_evaluated_candidates", 3)
        budget = ResearchLoopBudgetVersion.create(
            max_iterations=BudgetLimit.finite(max_generations),
            max_actions=BudgetLimit.finite(max_evaluations),
            max_candidates=BudgetLimit.finite(max_candidates),
            max_experiments=BudgetLimit.finite(max_evaluations),
            max_model_calls=BudgetLimit.finite(1),
            resource_profile_ref=self.operation_profile.operation_id,
            max_wallclock_seconds=BudgetLimit.finite(
                self.operation_profile.wall_clock_seconds
            ),
        )
        values = {
            "universe_version_id": self.factor_context.universe_version_id,
            "dataset_version_id": "dsv_sha256_" + "9" * 64,
            "input_data_refs": (artifact("8"), "feature-view:eod-v1"),
            "data_semantic_profile_id": "data-profile:eod/1.0.0",
            "search_space": self.search_space,
            "max_expression_depth": 4,
            "max_node_count": 12,
            "max_candidate_count": max_candidates,
            "max_generation_count": max_generations,
            "max_evaluation_count": max_evaluations,
            "deterministic_seed": 20260813,
            "search_mutation_policy_version": "v3.alpha-mining.hash-mutation/1.0.0",
            "evaluation_context": AlphaMiningEvaluationContext(
                dataset_version_id="dsv_sha256_" + "9" * 64,
                factor_context=self.factor_context,
                period_start="2025-01-01",
                period_end="2025-12-31",
                label_ref="label:forward-return-5d/1.0.0",
                horizon="5d",
                evaluation_policy_version="factor-evaluation/1.0.0",
                cost_turnover_context_ref="cost-context:a-share/1.0.0",
            ),
            "reward_policy": self.reward_policy,
            "operation_profile": self.operation_profile,
            "research_loop_budget": budget,
            "stopping_rules": AlphaMiningStoppingRules(target, True),
        }
        values.update(overrides)
        return AlphaMiningJobSpec.create(**values)

    def engine(self, port=None, generator=None) -> tuple[AlphaMiningEngine, ExactExistingEvaluationFixture]:
        selected = port or ExactExistingEvaluationFixture(self.registry)
        return (
            AlphaMiningEngine(
                registry=self.registry,
                evaluation_port=selected,
                candidate_generator=generator,
            ),
            selected,
        )

    def test_job_identity_and_candidate_order_are_deterministic(self) -> None:
        first_job = self.job()
        second_job = self.job()
        self.assertEqual(first_job, second_job)
        generator = DeterministicGrammarCandidateGenerator(self.registry)
        first = [
            generator.propose(first_job, generation_index=1, candidate_ordinal=index)
            for index in range(1, 7)
        ]
        second = [
            generator.propose(second_job, generation_index=1, candidate_ordinal=index)
            for index in range(1, 7)
        ]
        self.assertEqual(
            [value.candidate.expression_source for value in first],
            [value.candidate.expression_source for value in second],
        )
        self.assertTrue(all(value.candidate.authority_status == "NON_CANONICAL" for value in first))
        self.assertTrue(all(value.candidate.lifecycle_state == "DRAFT" for value in first))
        engine, _ = self.engine()
        forged = dataclasses.replace(
            first_job, alpha_mining_job_spec_id="amjs_sha256_" + "0" * 64
        )
        with self.assertRaisesRegex(
            AlphaMiningContractError, "ALPHA_MINING_JOB_IDENTITY_MISMATCH"
        ):
            engine.run(forged, resource_observation="test-governor")
        execution_changing_tampering = (
            dataclasses.replace(
                first_job, deterministic_seed=first_job.deterministic_seed + 1
            ),
            dataclasses.replace(
                first_job, max_candidate_count=first_job.max_candidate_count - 1
            ),
            dataclasses.replace(
                first_job,
                evaluation_context=dataclasses.replace(
                    first_job.evaluation_context, period_end="2026-01-31"
                ),
            ),
            dataclasses.replace(
                first_job,
                reward_policy=dataclasses.replace(
                    first_job.reward_policy, block_on_blocking_finding=False
                ),
            ),
            dataclasses.replace(
                first_job,
                operation_profile=dataclasses.replace(
                    first_job.operation_profile,
                    memory_hard_limit_bytes=(
                        first_job.operation_profile.memory_hard_limit_bytes + 1
                    ),
                ),
            ),
        )
        for tampered in execution_changing_tampering:
            self.assertEqual(
                tampered.alpha_mining_job_spec_id,
                first_job.alpha_mining_job_spec_id,
            )
            with self.assertRaises(AlphaMiningContractError):
                engine.run(tampered, resource_observation="test-governor")

    def test_job_and_lineage_bounds_reject_coercible_or_invalid_values(self) -> None:
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_ALPHA_MINING_BUDGET"
        ):
            self.job(max_expression_depth="4")
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_ALPHA_MINING_BUDGET"
        ):
            self.job(
                operation_profile=dataclasses.replace(
                    self.operation_profile, cpu_slots=0
                )
            )
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_REWARD_POLICY"
        ):
            AlphaMiningRewardPolicyVersion.create(
                policy_version="invalid-bool",
                component_rules=(
                    RewardComponentRule.create(
                        RewardComponentName.COMPLEXITY, "-0.01"
                    ),
                ),
                block_on_blocking_finding="false",
            )
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_ALPHA_MINING_BUDGET"
        ):
            AlphaMiningStoppingRules(1, "false")
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_CANDIDATE_RECORD"
        ):
            AlphaMiningCandidateRecord.create(
                candidate_id="candidate",
                source_lineage_ref="lineage",
                generation_index=1,
                candidate_ordinal=1,
                disposition="EVALUATED",
                reason_code="fixture",
            )
        with self.assertRaisesRegex(
            AlphaMiningContractError, "INVALID_ALPHA_MINING_BUDGET"
        ):
            AlphaMiningCandidateRecord.create(
                candidate_id="candidate",
                source_lineage_ref="lineage",
                generation_index=1.5,
                candidate_ordinal=1,
                disposition=AlphaMiningCandidateDisposition.REJECTED,
                reason_code="fixture",
            )

    def test_candidate_depth_node_and_count_bounds_are_enforced(self) -> None:
        deep = FeatureNode("close", "eod.close/1.0.0")
        for _ in range(4):
            deep = OperatorNode("LAG", "1.0.0", (deep,), {"periods": 1})
        generator = SequenceGenerator(
            (AlphaMiningCandidateProposal.create(root=deep, source_lineage_ref="deep"),)
        )
        engine, port = self.engine(generator=generator)
        result = engine.run(
            self.job(
                max_expression_depth=3,
                max_node_count=3,
                max_candidate_count=2,
                max_generation_count=1,
                max_evaluation_count=1,
                target_evaluated_candidates=2,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(result.generated_count, 2)
        self.assertEqual(result.rejected_count, 2)
        self.assertEqual(len(port.calls), 0)
        self.assertTrue(all(value.reason_code == "MAX_EXPRESSION_DEPTH_EXCEEDED" for value in result.candidate_records))

    def test_candidate_and_evaluation_budgets_are_truthful_partial_stops(self) -> None:
        engine, _ = self.engine()
        candidate_limited = engine.run(
            self.job(
                max_candidate_count=1,
                max_generation_count=1,
                max_evaluation_count=1,
                target_evaluated_candidates=3,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(candidate_limited.generated_count, 1)
        self.assertIs(candidate_limited.status, AlphaMiningRunStatus.PARTIAL)
        self.assertIs(
            candidate_limited.stop_reason,
            AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED,
        )
        engine, _ = self.engine()
        evaluation_limited = engine.run(
            self.job(
                max_candidate_count=4,
                max_generation_count=2,
                max_evaluation_count=1,
                target_evaluated_candidates=3,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(evaluation_limited.evaluated_count, 1)
        self.assertIs(
            evaluation_limited.stop_reason,
            AlphaMiningStopReason.EVALUATION_BUDGET_EXHAUSTED,
        )

    def test_pit_operator_data_and_arbitrary_python_gates_fail_closed(self) -> None:
        with self.assertRaisesRegex(AlphaMiningContractError, "UNSAFE_MINING_OPERATOR"):
            AlphaMiningSearchSpaceVersion.create(
                registry=self.registry,
                operator_allowlist=("LEAD@1.0.0",),
                source_fields=self.source_fields,
                generation_policy_version="unsafe",
            )
        with self.assertRaisesRegex(AlphaMiningContractError, "UNSUPPORTED_DATA_FIELD"):
            AlphaMiningSourceField("future_label", "label/1", "unresolved")
        python_candidate = MiningFactorCandidate.create("__import__('os').system('whoami')")
        with self.assertRaisesRegex(
            AlphaMiningContractError, "CANDIDATE_SOURCE_BINDING_MISMATCH"
        ):
            AlphaMiningCandidateProposal(
                python_candidate,
                FeatureNode("close", "eod.close/1.0.0"),
                "arbitrary-python",
            )

    def test_invalid_ir_and_unsupported_field_are_rejected_before_evaluation(self) -> None:
        unsafe = AlphaMiningCandidateProposal.create(
            root=OperatorNode(
                "LEAD",
                "1.0.0",
                (FeatureNode("close", "eod.close/1.0.0"),),
                {},
            ),
            source_lineage_ref="unsafe-lead",
        )
        unsupported = AlphaMiningCandidateProposal.create(
            root=FeatureNode("future_label", "label.future/1.0.0"),
            source_lineage_ref="future-label",
        )
        engine, port = self.engine(generator=SequenceGenerator((unsafe, unsupported)))
        result = engine.run(
            self.job(
                max_candidate_count=2,
                max_generation_count=1,
                max_evaluation_count=2,
                target_evaluated_candidates=2,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(len(port.calls), 0)
        self.assertEqual(result.rejected_count, 2)
        self.assertEqual(
            tuple(value.reason_code for value in result.candidate_records),
            ("CANONICAL_IR_REJECTED", "UNSUPPORTED_DATA_FIELD"),
        )

    def test_canonical_identity_dedup_prevents_second_evaluation(self) -> None:
        root = FeatureNode("close", "eod.close/1.0.0")
        proposal = AlphaMiningCandidateProposal.create(root=root, source_lineage_ref="family-a")
        engine, port = self.engine(generator=SequenceGenerator((proposal, proposal)))
        result = engine.run(
            self.job(
                max_candidate_count=2,
                max_generation_count=1,
                max_evaluation_count=2,
                target_evaluated_candidates=2,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(result.deduplicated_count, 1)
        self.assertEqual(
            result.candidate_records[0].factor_definition_version_id,
            result.candidate_records[1].duplicate_of_factor_definition_version_id,
        )

    def test_existing_evaluator_and_exact_evidence_are_the_only_math_path(self) -> None:
        engine, port = self.engine()
        job = self.job(target_evaluated_candidates=2)
        result = engine.run(job, resource_observation="test-governor")
        self.assertEqual(result.evaluated_count, 2)
        self.assertEqual(len(port.calls), 2)
        self.assertTrue(all(isinstance(value, FactorDefinitionVersion) for value in port.calls))
        self.assertTrue(
            all(
                record.factor_evaluation_id is not None
                for record in result.candidate_records
                if record.reason_code == AlphaMiningRewardStatus.SCORED.value
            )
        )
        self.assertFalse(hasattr(engine, "evaluate_factor_values"))

    def test_mismatched_evaluation_context_is_rejected_as_typed_lineage(self) -> None:
        class MismatchedDatasetPort(ExactExistingEvaluationFixture):
            def evaluate_existing(self, definition, job):
                evidence = super().evaluate_existing(definition, job)
                return dataclasses.replace(
                    evidence,
                    experiment_run=dataclasses.replace(
                        evidence.experiment_run,
                        dataset_version_id="dsv_sha256_" + "0" * 64,
                    ),
                )

        port = MismatchedDatasetPort(self.registry)
        engine, _ = self.engine(port=port)
        result = engine.run(
            self.job(
                max_candidate_count=1,
                max_generation_count=1,
                max_evaluation_count=1,
                target_evaluated_candidates=1,
            ),
            resource_observation="test-governor",
        )
        self.assertEqual(result.evaluated_count, 0)
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(
            result.candidate_records[0].reason_code,
            "EVALUATION_BINDING_MISMATCH",
        )

    def test_reward_missing_component_and_complexity_penalty_are_explicit(self) -> None:
        missing = tuple(
            value for value in RewardComponentName if value is not RewardComponentName.IC
        )
        port = ExactExistingEvaluationFixture(self.registry, available_components=missing)
        definition = FactorDefinitionVersion.create(
            "close",
            FeatureNode("close", "eod.close/1.0.0"),
            self.registry,
        )
        job = self.job()
        evidence = port.evaluate_existing(definition, job)
        reward = AlphaMiningReward.create(policy=job.reward_policy, evidence=evidence)
        self.assertIs(reward.status, AlphaMiningRewardStatus.NOT_AVAILABLE)
        missing_result = next(
            value for value in reward.components if value.component is RewardComponentName.IC
        )
        self.assertEqual(missing_result.status.value, "NOT_AVAILABLE")
        self.assertIsNone(missing_result.contribution)

        explicit_policy = AlphaMiningRewardPolicyVersion.create(
            policy_version="explicit-zero/1",
            component_rules=(
                RewardComponentRule.create(
                    RewardComponentName.IC,
                    "1",
                    MissingRewardComponentPolicy.EXPLICIT_ZERO,
                ),
                RewardComponentRule.create(RewardComponentName.COMPLEXITY, "-0.1"),
            ),
            block_on_blocking_finding=True,
        )
        explicit = AlphaMiningReward.create(policy=explicit_policy, evidence=evidence)
        self.assertIs(explicit.status, AlphaMiningRewardStatus.SCORED)
        self.assertEqual(explicit.total_reward, "-0.1")
        complexity = next(
            value
            for value in explicit.components
            if value.component is RewardComponentName.COMPLEXITY
        )
        self.assertEqual(complexity.contribution, "-0.1")

    def test_blocking_reviewer_finding_stops_without_promotion(self) -> None:
        port = ExactExistingEvaluationFixture(self.registry, blocking=True)
        engine, _ = self.engine(port=port)
        result = engine.run(self.job(), resource_observation="test-governor")
        self.assertIs(result.stop_reason, AlphaMiningStopReason.BLOCKING_REVIEWER_FINDING)
        self.assertIs(result.status, AlphaMiningRunStatus.PARTIAL)
        self.assertEqual(result.factor_asset_lifecycle_transition, "NOT_RUN")
        self.assertEqual(result.candidate_records[0].reason_code, "BLOCKED_BY_REVIEWER")

    def test_production_user_start_has_no_local_or_caller_authority(self) -> None:
        job = self.job(target_evaluated_candidates=1)
        draft = AlphaMiningJobDraft.create(
            proposed_job_spec_id=job.alpha_mining_job_spec_id,
            rationale="L1 bounded draft only",
        )
        self.assertFalse(draft.started)
        self.assertEqual(draft.authority_status, "NON_CANONICAL")
        engine = RecordingProductionEngine()
        governor = RecordingResourceGovernor()
        service = AlphaMiningUserJobService(
            engine=engine,  # type: ignore[arg-type]
            resources=governor,  # type: ignore[arg-type]
        )
        claimed = CallerClaimedAuthorization(job.alpha_mining_job_spec_id)
        fake_persistence = FakeAuthorizationPersistence()
        for untrusted in (draft, claimed, fake_persistence):
            with self.assertRaisesRegex(
                AlphaMiningContractError,
                "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE",
            ) as raised:
                service.start_user_job(authorization=untrusted, job=job)
            self.assertEqual(
                raised.exception.code, "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE"
            )
        with self.assertRaises(TypeError):
            AlphaMiningUserJobService(
                engine=engine,  # type: ignore[arg-type]
                resources=governor,  # type: ignore[arg-type]
                authorization_port=fake_persistence,  # type: ignore[call-arg]
            )
        self.assertEqual(fake_persistence.calls, 0)
        self.assertEqual(governor.admit_calls, 0)
        self.assertEqual(governor.release_calls, 0)
        self.assertEqual(engine.calls, 0)

    def test_direct_domain_engine_remains_bounded_without_production_authority(
        self,
    ) -> None:
        job = self.job(
            max_candidate_count=1,
            max_generation_count=1,
            max_evaluation_count=1,
            target_evaluated_candidates=3,
        )
        engine, _ = self.engine()
        result = engine.run(
            job,
            resource_observation="TEST_ONLY_DIRECT_DOMAIN_ENGINE_NO_USER_AUTHORITY",
        )
        self.assertIs(result.status, AlphaMiningRunStatus.PARTIAL)
        self.assertIs(
            result.stop_reason, AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED
        )
        self.assertEqual(result.generated_count, 1)
        self.assertEqual(
            result.resource_observation,
            "TEST_ONLY_DIRECT_DOMAIN_ENGINE_NO_USER_AUTHORITY",
        )

    def test_w0_production_action_remains_not_run(self) -> None:
        job = self.job()
        action = ResearchActionDraft.create(
            action_type=ResearchActionType.FACTOR_EVALUATE,
            exact_input_refs=(job.alpha_mining_job_spec_id,),
            requested_capability="alpha-mining.draft-only",
            expected_output_kind="AlphaMiningJobDraft",
            resource_profile_ref=job.operation_profile.operation_id,
            budget_version_id=job.research_loop_budget.budget_version_id,
        )
        self.assertIs(action.state, ResearchActionState.NOT_RUN)
        self.assertEqual(action.authority_status, "NON_CANONICAL")

    def test_lineage_is_truthful_and_bounded_benchmark_reports_counts(self) -> None:
        engine, _ = self.engine()
        result = engine.run(
            self.job(target_evaluated_candidates=4),
            resource_observation=(
                "RESOURCE_GOVERNOR_ADMITTED:class=ALPHA_MINING_CPU;cpu=1;"
                "memory=268435456;scratch=67108864;wallclock=30;gpu=NONE"
            ),
        )
        self.assertEqual(result.generated_count, len(result.candidate_records))
        self.assertEqual(
            result.generated_count,
            result.evaluated_count + result.deduplicated_count + result.rejected_count,
        )
        self.assertTrue(all(value.source_lineage_ref for value in result.candidate_records))
        payload = {
            "candidates_generated": result.generated_count,
            "canonicalized": result.canonicalized_count,
            "deduplicated": result.deduplicated_count,
            "evaluated": result.evaluated_count,
            "rejected": result.rejected_count,
            "elapsed_seconds": result.elapsed_seconds,
            "resource_observation": result.resource_observation,
        }
        print("ROUND5_S_BOUNDED_BENCHMARK=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
