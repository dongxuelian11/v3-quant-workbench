from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from types import MappingProxyType
from typing import TypeVar

from v3_backend.domain.data_truth import ResearchDataSnapshot
from v3_backend.domain.datasets import (
    DatasetVersion,
    FeatureSetVersion,
    LabelSpec,
    SplitSpec,
)
from v3_backend.domain.experiments import (
    ExperimentAttempt,
    ExperimentRun,
    ExperimentVersion,
    ReviewerEvidence as DomainReviewerEvidence,
    RewardVector,
)
from v3_backend.domain.factors import FactorEvaluation

from .contracts import (
    DatasetEvidence,
    DatasetLookup,
    DatasetSplitEvidence,
    EvidenceObjectKind,
    ExperimentAttemptEvidence,
    ExperimentEvidence,
    ExperimentLookup,
    MissingEvidence,
    ProvenanceEvidence,
    ProvenanceLookup,
    ReviewerEvidenceLookup,
    ReviewerEvidenceView,
    RewardVectorEvidence,
    RewardVectorLookup,
    SnapshotEvidence,
    SnapshotLookup,
    TruthAdmissionEvidence,
)


_T = TypeVar("_T")


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded(values: Iterable[str], limit: int) -> tuple[tuple[str, ...], bool]:
    ordered = tuple(sorted(set(values)))
    return ordered[:limit], len(ordered) > limit


def _index(
    values: tuple[_T, ...],
    identity: Callable[[_T], str],
    *,
    label: str,
) -> MappingProxyType[str, _T]:
    observed: dict[str, _T] = {}
    for value in values:
        object_id = identity(value)
        if object_id in observed:
            raise ValueError(f"duplicate {label} identity: {object_id}")
        observed[object_id] = value
    return MappingProxyType(observed)


class ResearchEvidenceReadAdapter:
    """Read-only view over exact current-main owner objects; never a storage authority."""

    __slots__ = (
        "_snapshots",
        "_datasets",
        "_feature_sets",
        "_labels",
        "_splits",
        "_factor_evaluations",
        "_experiments",
        "_runs",
        "_attempts",
        "_attempts_by_run",
        "_rewards",
        "_reviewer_evidence",
        "_provenance_by_object",
    )

    def __init__(
        self,
        *,
        snapshots: tuple[ResearchDataSnapshot, ...],
        datasets: tuple[DatasetVersion, ...],
        feature_sets: tuple[FeatureSetVersion, ...],
        label_specs: tuple[LabelSpec, ...],
        split_specs: tuple[SplitSpec, ...],
        factor_evaluations: tuple[FactorEvaluation, ...],
        experiments: tuple[ExperimentVersion, ...],
        runs: tuple[ExperimentRun, ...],
        attempts: tuple[ExperimentAttempt, ...],
        reward_vectors: tuple[RewardVector, ...],
        reviewer_evidence: tuple[DomainReviewerEvidence, ...],
    ) -> None:
        self._snapshots = _index(snapshots, lambda value: value.snapshot_id, label="Snapshot")
        self._datasets = _index(
            datasets, lambda value: value.dataset_version_id, label="DatasetVersion"
        )
        self._feature_sets = _index(
            feature_sets,
            lambda value: value.feature_set_version_id,
            label="FeatureSetVersion",
        )
        self._labels = _index(
            label_specs, lambda value: value.label_spec_id, label="LabelSpec"
        )
        self._splits = _index(
            split_specs, lambda value: value.split_spec_id, label="SplitSpec"
        )
        self._factor_evaluations = _index(
            factor_evaluations,
            lambda value: value.factor_evaluation_id,
            label="FactorEvaluation",
        )
        self._experiments = _index(
            experiments,
            lambda value: value.experiment_version_id,
            label="ExperimentVersion",
        )
        self._runs = _index(runs, lambda value: value.experiment_run_id, label="ExperimentRun")
        self._attempts = _index(
            attempts,
            lambda value: value.experiment_attempt_id,
            label="ExperimentAttempt",
        )
        self._rewards = _index(
            reward_vectors,
            lambda value: value.reward_vector_id,
            label="RewardVector",
        )
        self._reviewer_evidence = _index(
            reviewer_evidence,
            lambda value: value.reviewer_evidence_id,
            label="ReviewerEvidence",
        )

        attempts_by_run: dict[str, list[ExperimentAttempt]] = {}
        for attempt in attempts:
            if attempt.experiment_run_id not in self._runs:
                raise ValueError("Attempt must bind an exact registered ExperimentRun")
            attempts_by_run.setdefault(attempt.experiment_run_id, []).append(attempt)
        self._attempts_by_run = MappingProxyType(
            {
                run_id: tuple(sorted(values, key=lambda value: value.ordinal))
                for run_id, values in attempts_by_run.items()
            }
        )

        provenance: dict[str, tuple[str, ...]] = {}
        for snapshot in snapshots:
            provenance[snapshot.snapshot_id] = tuple(
                sorted(set(snapshot.raw_capture_ids + snapshot.acquisition_ids))
            )
        for evaluation in factor_evaluations:
            provenance[evaluation.factor_evaluation_id] = (
                evaluation.evaluation_provenance_artifact_id,
            )
        for dataset in datasets:
            self._validate_dataset(dataset)
            provenance[dataset.dataset_version_id] = (
                dataset.dataset_artifact_id,
                dataset.provenance_artifact_id,
            )
        for run in runs:
            self._validate_run(run)
            refs = (*run.input_artifact_ids, run.run_provenance_artifact_id)
            provenance[run.experiment_run_id] = tuple(sorted(set(refs)))
        for attempt in attempts:
            refs = list(attempt.evidence_artifact_ids)
            if attempt.result_artifact_id is not None:
                refs.append(attempt.result_artifact_id)
            provenance[attempt.experiment_attempt_id] = tuple(sorted(set(refs)))
        for review in reviewer_evidence:
            provenance[review.reviewer_evidence_id] = (review.provenance_artifact_id,)
        for reward in reward_vectors:
            self._validate_reward(reward)
            provenance[reward.reward_vector_id] = (reward.provenance_artifact_id,)
        self._provenance_by_object = MappingProxyType(provenance)

    def _validate_dataset(self, dataset: DatasetVersion) -> None:
        feature_set = self._feature_sets.get(dataset.feature_set_version_id)
        if feature_set is None or feature_set.factor_evaluation_ids != dataset.factor_evaluation_ids:
            raise ValueError("Dataset must bind the exact registered FeatureSetVersion")
        if dataset.label_spec_id not in self._labels or dataset.split_spec_id not in self._splits:
            raise ValueError("Dataset label/split metadata must be registered")
        if any(value not in self._factor_evaluations for value in dataset.factor_evaluation_ids):
            raise ValueError("Dataset factor memberships must be registered")
        if dataset.binding.snapshot_id not in self._snapshots:
            raise ValueError("Dataset Snapshot evidence must be registered")

    def _validate_run(self, run: ExperimentRun) -> None:
        if run.experiment_version_id not in self._experiments:
            raise ValueError("Run must bind an exact registered ExperimentVersion")
        dataset = self._datasets.get(run.dataset_version_id)
        if dataset is None or run.factor_evaluation_id not in dataset.factor_evaluation_ids:
            raise ValueError("Run must bind exact registered Dataset/Factor evidence")

    def _validate_reward(self, reward: RewardVector) -> None:
        run = self._runs.get(reward.experiment_run_id)
        attempt = self._attempts.get(reward.experiment_attempt_id)
        if run is None or attempt is None or attempt.experiment_run_id != run.experiment_run_id:
            raise ValueError("RewardVector must bind exact registered Run/Attempt evidence")
        if reward.reviewer_evidence_id not in self._reviewer_evidence:
            raise ValueError("RewardVector reviewer evidence must be registered")

    @staticmethod
    def _missing(kind: EvidenceObjectKind, object_id: str) -> MissingEvidence:
        return MissingEvidence(object_kind=kind, requested_object_id=object_id)

    def get_snapshot(self, snapshot_id: str) -> SnapshotLookup:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            return self._missing(EvidenceObjectKind.SNAPSHOT, snapshot_id)
        instruments = snapshot.research_universe_input.instrument_ids
        sample_instruments, instruments_truncated = _bounded(instruments, 64)
        raw_capture_ids, raw_truncated = _bounded(snapshot.raw_capture_ids, 64)
        acquisition_ids, acquisition_truncated = _bounded(snapshot.acquisition_ids, 64)
        reason_codes, reasons_truncated = _bounded(snapshot.reason_codes, 64)
        provenance_refs, provenance_truncated = _bounded(
            self._provenance_by_object.get(snapshot_id, ()), 128
        )
        return SnapshotEvidence(
            snapshot_id=snapshot.snapshot_id,
            normalization_version=snapshot.normalization_version,
            truth_ceiling=TruthAdmissionEvidence.from_state(snapshot.truth_ceiling),
            pit_evidence=snapshot.pit_evidence,
            revision_evidence=snapshot.revision_evidence,
            reason_codes=reason_codes,
            raw_capture_ids=raw_capture_ids,
            acquisition_ids=acquisition_ids,
            research_universe_input_id=(
                snapshot.research_universe_input.research_universe_input_id
            ),
            instrument_count=len(set(instruments)),
            sample_instrument_ids=sample_instruments,
            instruments_truncated=instruments_truncated,
            record_count=len(snapshot.records),
            missing_value_count=sum(
                len(record.missing_fields) for record in snapshot.records
            ),
            provenance_refs=provenance_refs,
            response_truncated=any(
                (
                    instruments_truncated,
                    raw_truncated,
                    acquisition_truncated,
                    reasons_truncated,
                    provenance_truncated,
                )
            ),
        )

    def get_dataset(self, dataset_version_id: str) -> DatasetLookup:
        dataset = self._datasets.get(dataset_version_id)
        if dataset is None:
            return self._missing(EvidenceObjectKind.DATASET, dataset_version_id)
        split = self._splits[dataset.split_spec_id]
        factor_ids, factors_truncated = _bounded(dataset.factor_evaluation_ids, 64)
        provenance_refs, provenance_truncated = _bounded(
            self._provenance_by_object[dataset_version_id], 128
        )
        return DatasetEvidence(
            dataset_version_id=dataset.dataset_version_id,
            snapshot_id=dataset.binding.snapshot_id,
            universe_version_id=dataset.binding.universe_version_id,
            knowledge_cutoff=_wire_time(dataset.binding.knowledge_cutoff),
            feature_set_version_id=dataset.feature_set_version_id,
            factor_evaluation_count=len(dataset.factor_evaluation_ids),
            factor_evaluation_ids=factor_ids,
            factor_evaluations_truncated=factors_truncated,
            label_spec_id=dataset.label_spec_id,
            split=DatasetSplitEvidence(**split.to_wire()),
            truth_admission=TruthAdmissionEvidence.from_state(dataset.truth_admission),
            provenance_refs=provenance_refs,
            response_truncated=factors_truncated or provenance_truncated,
        )

    def get_experiment(self, experiment_run_id: str) -> ExperimentLookup:
        run = self._runs.get(experiment_run_id)
        if run is None:
            return self._missing(EvidenceObjectKind.EXPERIMENT_RUN, experiment_run_id)
        experiment = self._experiments[run.experiment_version_id]
        all_attempts = self._attempts_by_run.get(experiment_run_id, ())
        selected_attempts = all_attempts[:64]
        attempts = tuple(
            ExperimentAttemptEvidence(
                experiment_attempt_id=value.experiment_attempt_id,
                ordinal=value.ordinal,
                state=value.state,
                started_at=_wire_time(value.started_at),
                ended_at=_wire_time(value.ended_at),
                evidence_artifact_ids=_bounded(value.evidence_artifact_ids, 64)[0],
                result_artifact_id=value.result_artifact_id,
                error_code=value.error_code,
            )
            for value in selected_attempts
        )
        input_artifacts, input_truncated = _bounded(run.input_artifact_ids, 64)
        provenance_values = list(self._provenance_by_object[experiment_run_id])
        for attempt in selected_attempts:
            provenance_values.extend(
                self._provenance_by_object.get(attempt.experiment_attempt_id, ())
            )
        provenance_refs, provenance_truncated = _bounded(provenance_values, 128)
        nested_artifacts_truncated = any(
            len(value.evidence_artifact_ids) > 64 for value in selected_attempts
        )
        return ExperimentEvidence(
            experiment_version_id=experiment.experiment_version_id,
            logical_name=experiment.logical_name,
            objective=experiment.objective,
            protocol_version=experiment.protocol_version,
            experiment_run_id=run.experiment_run_id,
            dataset_version_id=run.dataset_version_id,
            factor_evaluation_id=run.factor_evaluation_id,
            code_version=run.code_version,
            environment_fingerprint=run.environment_fingerprint,
            input_artifact_ids=input_artifacts,
            attempt_count=len(all_attempts),
            attempts=attempts,
            attempts_truncated=len(all_attempts) > 64,
            truth_admission=TruthAdmissionEvidence.from_state(run.truth_admission),
            provenance_refs=provenance_refs,
            response_truncated=any(
                (
                    len(all_attempts) > 64,
                    input_truncated,
                    nested_artifacts_truncated,
                    provenance_truncated,
                )
            ),
        )

    def get_reward_vector(self, reward_vector_id: str) -> RewardVectorLookup:
        reward = self._rewards.get(reward_vector_id)
        if reward is None:
            return self._missing(EvidenceObjectKind.REWARD_VECTOR, reward_vector_id)
        provenance_refs, truncated = _bounded(
            self._provenance_by_object[reward_vector_id], 128
        )
        return RewardVectorEvidence(
            reward_vector_id=reward.reward_vector_id,
            experiment_run_id=reward.experiment_run_id,
            experiment_attempt_id=reward.experiment_attempt_id,
            reviewer_evidence_id=reward.reviewer_evidence_id,
            coverage=reward.coverage,
            ic=reward.ic,
            rank_ic=reward.rank_ic,
            lower_quantile_return=reward.lower_quantile_return,
            upper_quantile_return=reward.upper_quantile_return,
            quantile_spread=reward.quantile_spread,
            turnover=reward.turnover,
            complexity=reward.complexity,
            truth_admission=TruthAdmissionEvidence.from_state(reward.truth_admission),
            provenance_refs=provenance_refs,
            response_truncated=truncated,
        )

    def get_reviewer_evidence(
        self, reviewer_evidence_id: str
    ) -> ReviewerEvidenceLookup:
        review = self._reviewer_evidence.get(reviewer_evidence_id)
        if review is None:
            return self._missing(
                EvidenceObjectKind.REVIEWER_EVIDENCE, reviewer_evidence_id
            )
        finding_ids, findings_truncated = _bounded(review.finding_ids, 128)
        provenance_refs, provenance_truncated = _bounded(
            self._provenance_by_object[reviewer_evidence_id], 128
        )
        return ReviewerEvidenceView(
            reviewer_evidence_id=review.reviewer_evidence_id,
            lookahead=review.lookahead,
            leakage=review.leakage,
            split=review.split,
            sample_coverage=review.sample_coverage,
            missingness=review.missingness,
            turnover=review.turnover,
            complexity=review.complexity,
            multiple_testing_robustness=review.multiple_testing_robustness,
            finding_ids=finding_ids,
            truth_ceiling=TruthAdmissionEvidence.from_state(review.canonical_ceiling),
            provenance_refs=provenance_refs,
            response_truncated=findings_truncated or provenance_truncated,
        )

    def get_provenance(self, object_id: str) -> ProvenanceLookup:
        refs = self._provenance_by_object.get(object_id)
        if refs is None:
            return self._missing(EvidenceObjectKind.PROVENANCE, object_id)
        bounded, truncated = _bounded(refs, 128)
        return ProvenanceEvidence(
            object_id=object_id,
            provenance_refs=bounded,
            response_truncated=truncated,
        )


__all__ = ["ResearchEvidenceReadAdapter"]
