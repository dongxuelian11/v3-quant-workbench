from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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


def artifact(character: str) -> str:
    return "art_sha256_" + character * 64


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


def build_evidence_fixture(*, instrument_count: int = 1) -> EvidenceFixture:
    snapshot = ResearchDataSnapshot(
        snapshot_id="snapshot-1",
        normalization_version=NORMALIZATION_VERSION,
        raw_capture_ids=("raw_capture-1",),
        acquisition_ids=("acquisition-1",),
        records=(),
        truth_ceiling=PRE_ALPHA_CEILING,
        pit_evidence=PitEvidenceState.UNKNOWN,
        revision_evidence=PitEvidenceState.UNKNOWN,
        reason_codes=(
            "PROVIDER_AVAILABLE_TIME_UNKNOWN",
            "PROVIDER_REVISION_UNKNOWN",
        ),
        research_universe_input=ResearchUniverseInput(
            research_universe_input_id="research-universe-input-1",
            snapshot_id="snapshot-1",
            instrument_ids=tuple(
                f"ins_cn_sse_{index:06d}" for index in range(instrument_count)
            ),
        ),
    )
    registry = default_operator_registry()
    definition = FactorDefinitionVersion.create(
        "close", FeatureNode("close", "eod.close/1.0.0"), registry
    )
    evaluator = DeterministicReferenceEvaluator(registry)
    context = FactorEvaluationContext(
        snapshot_id=snapshot.snapshot_id,
        universe_version_id="universe-1",
        snapshot_truth_binding=UnresolvedIdUpstreamTruthBinding.snapshot(
            snapshot.snapshot_id, PRE_ALPHA_CEILING
        ),
        universe_truth_binding=UnresolvedIdUpstreamTruthBinding.universe(
            "universe-1", FORMAL_ADMITTED_CEILING
        ),
        knowledge_cutoff=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
        calendar_version_id="calendar-1",
        schema_version_id="schema-1",
        environment_fingerprint="python-3.14-track-g-test",
        evaluator_version=evaluator.evaluator_version,
    )
    result = evaluator.evaluate(definition, {"close": [1.0, 2.0, 3.0]})
    materialization = FeatureMaterialization.create(
        definition, result, context, artifact("a"), FORMAL_ADMITTED_CEILING
    )
    evaluation = FactorEvaluation.create(
        definition, materialization, artifact("b"), FORMAL_ADMITTED_CEILING
    )
    feature_set = FeatureSetVersion.create((evaluation,), artifact("c"))
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
        dataset_artifact_id=artifact("d"),
        provenance_artifact_id=artifact("e"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    experiment = ExperimentVersion.create(
        "track-g-factor", "evaluate deterministic evidence", "1.0.0"
    )
    run = ExperimentRun.create(
        experiment=experiment,
        dataset=dataset,
        factor_evaluation=evaluation,
        code_version="track-g-test/1",
        environment_fingerprint=context.environment_fingerprint,
        input_artifact_ids=(dataset.dataset_artifact_id, materialization.output_artifact_id),
        run_provenance_artifact_id=artifact("f"),
        proposed_state=FORMAL_ADMITTED_CEILING,
    )
    started = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)
    attempt = ExperimentAttempt.create(
        run=run,
        ordinal=1,
        state=ExperimentAttemptState.SUCCEEDED,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        evidence_artifact_ids=(artifact("1"),),
        result_artifact_id=artifact("2"),
    )
    reviewer_finding = ReviewerFinding.create(
        category="lookahead",
        code="NO_RIGHT_LOOKAHEAD",
        severity=FindingSeverity.INFO,
        status=EvidenceStatus.PASS,
        evidence_artifact_ids=(artifact("3"),),
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
        provenance_artifact_id=artifact("4"),
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
        provenance_artifact_id=artifact("5"),
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
