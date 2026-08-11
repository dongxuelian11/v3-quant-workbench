from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TypeVar

from v3_backend.agents.research_evidence_integration import (
    ResearchEvidenceReadAdapter,
    ResearchEvidenceToolComposition,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.data_truth import (
    NORMALIZATION_VERSION,
    PitEvidenceState,
    ResearchDataSnapshot,
    ResearchUniverseInput,
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
    ExperimentRun,
    ExperimentVersion,
    FindingSeverity,
    ReviewerEvidence,
    ReviewerFinding,
    RewardVector,
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


_T = TypeVar("_T")


def artifact(seed: str) -> str:
    return "art_sha256_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceFixture:
    snapshot: ResearchDataSnapshot
    feature_set: FeatureSetVersion
    label: LabelSpec
    split: SplitSpec
    evaluation: FactorEvaluation
    dataset: DatasetVersion
    experiment: ExperimentVersion
    run: ExperimentRun
    attempt: ExperimentAttempt
    reviewer_evidence: ReviewerEvidence
    reward: RewardVector
    adapter: ResearchEvidenceReadAdapter
    composition: ResearchEvidenceToolComposition


@dataclass(frozen=True)
class CrossChainFixture:
    primary: EvidenceFixture
    secondary: EvidenceFixture
    alternate_attempt: ExperimentAttempt
    alternate_reward: RewardVector


def build_evidence_fixture(
    *,
    instrument_count: int = 1,
    namespace: str = "1",
) -> EvidenceFixture:
    snapshot_id = f"snapshot-{namespace}"
    snapshot = ResearchDataSnapshot(
        snapshot_id=snapshot_id,
        normalization_version=NORMALIZATION_VERSION,
        raw_capture_ids=(f"raw_capture-{namespace}",),
        acquisition_ids=(f"acquisition-{namespace}",),
        records=(),
        truth_ceiling=PRE_ALPHA_CEILING,
        pit_evidence=PitEvidenceState.UNKNOWN,
        revision_evidence=PitEvidenceState.UNKNOWN,
        reason_codes=(
            "PROVIDER_AVAILABLE_TIME_UNKNOWN",
            "PROVIDER_REVISION_UNKNOWN",
        ),
        research_universe_input=ResearchUniverseInput(
            research_universe_input_id=f"research-universe-input-{namespace}",
            snapshot_id=snapshot_id,
            instrument_ids=tuple(
                f"ins_cn_sse_{namespace}_{index:06d}"
                for index in range(instrument_count)
            ),
        ),
    )
    registry = default_operator_registry()
    definition = FactorDefinitionVersion.create(
        "close", FeatureNode("close", "eod.close/1.0.0"), registry
    )
    evaluator = DeterministicReferenceEvaluator(registry)
    universe_version_id = f"universe-{namespace}"
    context = FactorEvaluationContext(
        snapshot_id=snapshot.snapshot_id,
        universe_version_id=universe_version_id,
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            snapshot.snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            universe_version_id, FORMAL_ADMITTED_CEILING
        ),
        knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
        calendar_version_id=f"calendar-{namespace}",
        schema_version_id=f"schema-{namespace}",
        environment_fingerprint=f"python-3.14-track-g-test-{namespace}",
        evaluator_version=evaluator.evaluator_version,
    )
    result = evaluator.evaluate(definition, {"close": [1.0, 2.0, 3.0]})
    materialization = FeatureMaterialization.create(
        definition,
        result,
        context,
        artifact(f"{namespace}:materialization"),
        FORMAL_ADMITTED_CEILING,
    )
    evaluation = FactorEvaluation.create(
        definition,
        materialization,
        artifact(f"{namespace}:evaluation"),
        FORMAL_ADMITTED_CEILING,
    )
    feature_set = FeatureSetVersion.create(
        (evaluation,), artifact(f"{namespace}:feature-set")
    )
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
    dataset = DatasetVersion.create(
        feature_set=feature_set,
        evaluations=(evaluation,),
        label_spec=label,
        split_spec=split,
        binding=binding,
        dataset_artifact_id=artifact(f"{namespace}:dataset"),
        provenance_artifact_id=artifact(f"{namespace}:dataset-provenance"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    experiment = ExperimentVersion.create(
        f"track-g-factor-{namespace}",
        "evaluate deterministic evidence",
        "1.0.0",
    )
    run = ExperimentRun.create(
        experiment=experiment,
        dataset=dataset,
        factor_evaluation=evaluation,
        code_version=f"track-g-test/{namespace}",
        environment_fingerprint=context.environment_fingerprint,
        input_artifact_ids=(dataset.dataset_artifact_id, materialization.output_artifact_id),
        run_provenance_artifact_id=artifact(f"{namespace}:run-provenance"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    started = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    attempt = ExperimentAttempt.create(
        run=run,
        ordinal=1,
        state=ExperimentAttemptState.SUCCEEDED,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        evidence_artifact_ids=(artifact(f"{namespace}:attempt-evidence"),),
        result_artifact_id=artifact(f"{namespace}:attempt-result"),
    )
    reviewer_finding = ReviewerFinding.create(
        category="lookahead",
        code="NO_RIGHT_LOOKAHEAD",
        severity=FindingSeverity.INFO,
        status=EvidenceStatus.PASS,
        evidence_artifact_ids=(artifact(f"{namespace}:review-finding"),),
    )
    reviewer_evidence = ReviewerEvidence.create(
        lookahead=EvidenceStatus.PASS,
        leakage=EvidenceStatus.PASS,
        split=EvidenceStatus.PASS,
        sample_coverage=EvidenceStatus.PASS,
        missingness=EvidenceStatus.PASS,
        turnover=EvidenceStatus.PASS,
        complexity=EvidenceStatus.PASS,
        multiple_testing_robustness=EvidenceStatus.NOT_RUN,
        findings=(reviewer_finding,),
        provenance_artifact_id=artifact(f"{namespace}:review-provenance"),
    )
    reward = RewardVector.create(
        run=run,
        attempt=attempt,
        coverage=0.8,
        ic=0.1,
        rank_ic=0.12,
        lower_quantile_return=0.01,
        upper_quantile_return=0.04,
        quantile_spread=0.03,
        turnover=0.2,
        complexity=definition.metadata.complexity,
        reviewer_evidence=reviewer_evidence,
        provenance_artifact_id=artifact(f"{namespace}:reward-provenance"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    adapter = ResearchEvidenceReadAdapter(
        snapshots=(snapshot,),
        datasets=(dataset,),
        feature_sets=(feature_set,),
        label_specs=(label,),
        split_specs=(split,),
        factor_evaluations=(evaluation,),
        experiments=(experiment,),
        runs=(run,),
        attempts=(attempt,),
        reward_vectors=(reward,),
        reviewer_evidence=(reviewer_evidence,),
    )
    composition = ResearchEvidenceToolComposition(adapter)
    return EvidenceFixture(
        snapshot=snapshot,
        feature_set=feature_set,
        label=label,
        split=split,
        evaluation=evaluation,
        dataset=dataset,
        experiment=experiment,
        run=run,
        attempt=attempt,
        reviewer_evidence=reviewer_evidence,
        reward=reward,
        adapter=adapter,
        composition=composition,
    )


def _unique(values: tuple[_T, ...], identity_name: str) -> tuple[_T, ...]:
    by_identity = {getattr(value, identity_name): value for value in values}
    return tuple(by_identity[key] for key in sorted(by_identity))


def build_cross_chain_fixture() -> CrossChainFixture:
    primary = build_evidence_fixture(namespace="primary")
    secondary = build_evidence_fixture(namespace="secondary")
    alternate_started = primary.attempt.ended_at + timedelta(seconds=1)
    alternate_attempt = ExperimentAttempt.create(
        run=primary.run,
        ordinal=2,
        state=ExperimentAttemptState.SUCCEEDED,
        started_at=alternate_started,
        ended_at=alternate_started + timedelta(seconds=1),
        evidence_artifact_ids=(artifact("primary:alternate-attempt-evidence"),),
        result_artifact_id=artifact("primary:alternate-attempt-result"),
    )
    alternate_reward = RewardVector.create(
        run=primary.run,
        attempt=alternate_attempt,
        coverage=primary.reward.coverage,
        ic=primary.reward.ic,
        rank_ic=primary.reward.rank_ic,
        lower_quantile_return=primary.reward.lower_quantile_return,
        upper_quantile_return=primary.reward.upper_quantile_return,
        quantile_spread=primary.reward.quantile_spread,
        turnover=primary.reward.turnover,
        complexity=primary.reward.complexity,
        reviewer_evidence=primary.reviewer_evidence,
        provenance_artifact_id=artifact("primary:alternate-reward-provenance"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    adapter = ResearchEvidenceReadAdapter(
        snapshots=(primary.snapshot, secondary.snapshot),
        datasets=(primary.dataset, secondary.dataset),
        feature_sets=(primary.feature_set, secondary.feature_set),
        label_specs=_unique(
            (primary.label, secondary.label), "label_spec_id"
        ),
        split_specs=_unique(
            (primary.split, secondary.split), "split_spec_id"
        ),
        factor_evaluations=(primary.evaluation, secondary.evaluation),
        experiments=(primary.experiment, secondary.experiment),
        runs=(primary.run, secondary.run),
        attempts=(primary.attempt, alternate_attempt, secondary.attempt),
        reward_vectors=(primary.reward, alternate_reward, secondary.reward),
        reviewer_evidence=(primary.reviewer_evidence, secondary.reviewer_evidence),
    )
    composition = ResearchEvidenceToolComposition(adapter)
    return CrossChainFixture(
        primary=replace(primary, adapter=adapter, composition=composition),
        secondary=replace(secondary, adapter=adapter, composition=composition),
        alternate_attempt=alternate_attempt,
        alternate_reward=alternate_reward,
    )
