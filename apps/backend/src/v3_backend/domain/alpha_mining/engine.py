from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from v3_backend.domain.factors import (
    FactorDefinitionVersion,
    FactorIrError,
    FeatureNode,
    OperatorNode,
    OperatorRegistry,
    OperatorSpec,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .model import (
    AlphaMiningCandidateDisposition,
    AlphaMiningCandidateProposal,
    AlphaMiningCandidateRecord,
    AlphaMiningContractError,
    AlphaMiningEvaluationEvidence,
    AlphaMiningJobSpec,
    AlphaMiningReward,
    AlphaMiningRewardStatus,
    AlphaMiningRunRecord,
    AlphaMiningRunStatus,
    AlphaMiningSearchSpaceVersion,
    AlphaMiningStopReason,
)


class ExistingFactorEvaluationPort(Protocol):
    """Existing evaluator/experiment/reviewer boundary; S never computes factor values."""

    def evaluate_existing(
        self, definition: FactorDefinitionVersion, job: AlphaMiningJobSpec
    ) -> AlphaMiningEvaluationEvidence: ...


class AlphaMiningCandidateGenerator(Protocol):
    def propose(
        self,
        job: AlphaMiningJobSpec,
        *,
        generation_index: int,
        candidate_ordinal: int,
    ) -> AlphaMiningCandidateProposal: ...


def factor_node_count(node: object) -> int:
    if isinstance(node, OperatorNode):
        return 1 + sum(factor_node_count(value) for value in node.inputs)
    if isinstance(node, FeatureNode):
        return 1
    # Canonical numeric literals are supported by validation but not emitted by V1 generation.
    if hasattr(node, "to_wire"):
        return 1
    raise AlphaMiningContractError("INVALID_CANDIDATE_IR", "unknown node type")


def factor_node_depth(node: object) -> int:
    if isinstance(node, OperatorNode):
        return 1 + max(factor_node_depth(value) for value in node.inputs)
    if isinstance(node, FeatureNode) or hasattr(node, "to_wire"):
        return 1
    raise AlphaMiningContractError("INVALID_CANDIDATE_IR", "unknown node type")


def _index(seed: int, token: str, length: int) -> int:
    if length < 1:
        raise AlphaMiningContractError("EMPTY_MINING_CHOICE", token)
    digest = hashlib.sha256(f"{seed}|{token}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % length


class DeterministicGrammarCandidateGenerator:
    """Versioned hash-selection grammar over the exact registered V3 operator set."""

    def __init__(self, registry: OperatorRegistry) -> None:
        self.registry = registry
        self._rewarded: dict[str, list[tuple[int, Decimal, str, str]]] = {}

    def begin_run(self, *, job: AlphaMiningJobSpec) -> None:
        self._rewarded.pop(job.alpha_mining_job_spec_id, None)

    def observe_reward(
        self,
        *,
        job: AlphaMiningJobSpec,
        generation_index: int,
        definition: FactorDefinitionVersion,
        reward: AlphaMiningReward,
    ) -> None:
        if reward.status is not AlphaMiningRewardStatus.SCORED or reward.total_reward is None:
            return
        self._rewarded.setdefault(job.alpha_mining_job_spec_id, []).append(
            (
                generation_index,
                Decimal(reward.total_reward),
                reward.alpha_mining_reward_id,
                definition.factor_definition_version_id,
            )
        )

    def _operators(self, job: AlphaMiningJobSpec) -> tuple[OperatorSpec, ...]:
        values: list[OperatorSpec] = []
        for key in job.search_space.operator_allowlist:
            name, version = key.rsplit("@", 1)
            values.append(self.registry.resolve(name, version))
        return tuple(values)

    def _feature(self, job: AlphaMiningJobSpec, token: str) -> FeatureNode:
        fields = job.search_space.source_fields
        selected = fields[_index(job.deterministic_seed, token, len(fields))]
        return FeatureNode(selected.feature_name, selected.field_semantic_version)

    def _parameter_values(
        self, spec: OperatorSpec, job: AlphaMiningJobSpec, token: str
    ) -> dict[str, int]:
        values: dict[str, int] = {}
        for parameter in spec.parameters:
            span = parameter.maximum - parameter.minimum + 1
            values[parameter.name] = parameter.minimum + _index(
                job.deterministic_seed, f"{token}|param|{parameter.name}", span
            )
        return values

    def _build(
        self,
        job: AlphaMiningJobSpec,
        operators: tuple[OperatorSpec, ...],
        *,
        token: str,
        depth_budget: int,
        node_budget: int,
    ) -> object:
        if depth_budget <= 1 or node_budget <= 1:
            return self._feature(job, f"{token}|feature")
        viable = tuple(value for value in operators if value.arity + 1 <= node_budget)
        if not viable:
            return self._feature(job, f"{token}|feature-fallback")
        spec = viable[_index(job.deterministic_seed, f"{token}|operator", len(viable))]
        remaining = node_budget - 1
        base = remaining // spec.arity
        extra = remaining % spec.arity
        children = tuple(
            self._build(
                job,
                operators,
                token=f"{token}|child|{position}",
                depth_budget=depth_budget - 1,
                node_budget=base + (1 if position < extra else 0),
            )
            for position in range(spec.arity)
        )
        return OperatorNode(
            spec.name,
            spec.semantic_version,
            children,  # type: ignore[arg-type]
            self._parameter_values(spec, job, token),
        )

    def propose(
        self,
        job: AlphaMiningJobSpec,
        *,
        generation_index: int,
        candidate_ordinal: int,
    ) -> AlphaMiningCandidateProposal:
        if self.registry.registry_version != job.search_space.operator_registry_version:
            raise AlphaMiningContractError(
                "OPERATOR_REGISTRY_BINDING_MISMATCH", self.registry.registry_version
            )
        eligible_parents = tuple(
            value
            for value in self._rewarded.get(job.alpha_mining_job_spec_id, ())
            if value[0] < generation_index
        )
        parent = (
            sorted(eligible_parents, key=lambda value: (-value[1], value[3]))[0]
            if eligible_parents
            else None
        )
        parent_reward_id = parent[2] if parent is not None else "SEED_GENERATION"
        token = (
            f"g{generation_index}|c{candidate_ordinal}|{job.search_mutation_policy_version}|"
            f"parent-reward:{parent_reward_id}"
        )
        # Emit exact registered terminals first, then bounded operator trees.
        if candidate_ordinal <= len(job.search_space.source_fields):
            field = job.search_space.source_fields[candidate_ordinal - 1]
            root = FeatureNode(field.feature_name, field.field_semantic_version)
        else:
            target_depth = 2 + _index(
                job.deterministic_seed,
                f"{token}|depth",
                max(1, job.max_expression_depth - 1),
            )
            target_depth = min(target_depth, job.max_expression_depth)
            minimum_nodes = target_depth
            node_span = max(1, job.max_node_count - minimum_nodes + 1)
            target_nodes = minimum_nodes + _index(
                job.deterministic_seed, f"{token}|nodes", node_span
            )
            root = self._build(
                job,
                self._operators(job),
                token=token,
                depth_budget=target_depth,
                node_budget=target_nodes,
            )
        return AlphaMiningCandidateProposal.create(
            root=root,  # type: ignore[arg-type]
            source_lineage_ref=(
                f"alpha-mining:{job.alpha_mining_job_spec_id}:generation:{generation_index}:"
                f"candidate:{candidate_ordinal}:parent-reward:{parent_reward_id}"
            ),
        )


def _reason(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    return str(code) if code else fallback


@dataclass(frozen=True, slots=True)
class _CanonicalCandidate:
    proposal: AlphaMiningCandidateProposal
    definition: FactorDefinitionVersion
    generation_index: int
    candidate_ordinal: int


@dataclass(slots=True)
class _MiningRunState:
    records: list[AlphaMiningCandidateRecord] = field(default_factory=list)
    seen_definition_ids: set[str] = field(default_factory=set)
    generated: int = 0
    canonicalized: int = 0
    deduplicated: int = 0
    evaluated: int = 0
    rejected: int = 0
    stop_reason: AlphaMiningStopReason | None = None


class AlphaMiningEngine:
    def __init__(
        self,
        *,
        registry: OperatorRegistry,
        evaluation_port: ExistingFactorEvaluationPort,
        candidate_generator: AlphaMiningCandidateGenerator | None = None,
        clock: callable = time.perf_counter,
    ) -> None:
        self.registry = registry
        self.evaluation_port = evaluation_port
        self.candidate_generator = candidate_generator or DeterministicGrammarCandidateGenerator(
            registry
        )
        self.clock = clock

    def _definition(
        self, proposal: AlphaMiningCandidateProposal, job: AlphaMiningJobSpec
    ) -> FactorDefinitionVersion:
        if factor_node_depth(proposal.root) > job.max_expression_depth:
            raise AlphaMiningContractError("MAX_EXPRESSION_DEPTH_EXCEEDED", proposal.candidate.candidate_id)
        if factor_node_count(proposal.root) > job.max_node_count:
            raise AlphaMiningContractError("MAX_NODE_COUNT_EXCEEDED", proposal.candidate.candidate_id)
        root_digest = canonical_sha256(proposal.root.to_wire())
        definition = FactorDefinitionVersion.create(
            f"mined_{root_digest[:20]}", proposal.root, self.registry
        )
        allowed_fields = {value.feature_name for value in job.search_space.source_fields}
        if not set(definition.metadata.input_features).issubset(allowed_fields):
            raise AlphaMiningContractError(
                "UNSUPPORTED_DATA_FIELD", ",".join(definition.metadata.input_features)
            )
        if not set(definition.metadata.operator_keys).issubset(
            set(job.search_space.operator_allowlist)
        ):
            raise AlphaMiningContractError(
                "UNREGISTERED_MINING_OPERATOR", ",".join(definition.metadata.operator_keys)
            )
        return definition

    def _validate_job(self, job: AlphaMiningJobSpec) -> None:
        canonical_search_space = AlphaMiningSearchSpaceVersion.create(
            registry=self.registry,
            operator_allowlist=job.search_space.operator_allowlist,
            source_fields=job.search_space.source_fields,
            generation_policy_version=job.search_space.generation_policy_version,
        )
        if canonical_search_space != job.search_space:
            raise AlphaMiningContractError(
                "SEARCH_SPACE_IDENTITY_MISMATCH",
                job.search_space.search_space_version_id,
            )
        job.assert_canonical()
        if self.registry.registry_version != job.search_space.operator_registry_version:
            raise AlphaMiningContractError(
                "OPERATOR_REGISTRY_BINDING_MISMATCH", self.registry.registry_version
            )

    def _begin_generator_run(self, job: AlphaMiningJobSpec) -> None:
        begin_run = getattr(self.candidate_generator, "begin_run", None)
        if callable(begin_run):
            begin_run(job=job)

    def _generate_candidate(
        self,
        job: AlphaMiningJobSpec,
        generation_index: int,
        state: _MiningRunState,
    ) -> AlphaMiningCandidateProposal | None:
        candidate_ordinal = state.generated + 1
        try:
            proposal = self.candidate_generator.propose(
                job,
                generation_index=generation_index,
                candidate_ordinal=candidate_ordinal,
            )
        except (FactorIrError, AlphaMiningContractError, ValueError) as error:
            state.generated += 1
            state.rejected += 1
            state.records.append(
                AlphaMiningCandidateRecord.create(
                    candidate_id=f"candidate-generation-failure:{candidate_ordinal}",
                    source_lineage_ref=(
                        f"generation:{generation_index}:candidate:{candidate_ordinal}"
                    ),
                    generation_index=generation_index,
                    candidate_ordinal=candidate_ordinal,
                    disposition=AlphaMiningCandidateDisposition.REJECTED,
                    reason_code=_reason(error, "CANDIDATE_GENERATION_REJECTED"),
                    factor_definition_version_id=None,
                    duplicate_of_factor_definition_version_id=None,
                    factor_evaluation_id=None,
                    alpha_mining_reward_id=None,
                )
            )
            return None
        state.generated += 1
        return proposal

    def _canonicalize_candidate(
        self,
        proposal: AlphaMiningCandidateProposal,
        job: AlphaMiningJobSpec,
        generation_index: int,
        state: _MiningRunState,
    ) -> _CanonicalCandidate | None:
        candidate_ordinal = state.generated
        try:
            definition = self._definition(proposal, job)
        except (FactorIrError, AlphaMiningContractError, ValueError) as error:
            state.rejected += 1
            state.records.append(
                AlphaMiningCandidateRecord.create(
                    candidate_id=proposal.candidate.candidate_id,
                    source_lineage_ref=proposal.source_lineage_ref,
                    generation_index=generation_index,
                    candidate_ordinal=candidate_ordinal,
                    disposition=AlphaMiningCandidateDisposition.REJECTED,
                    reason_code=_reason(error, "CANONICAL_IR_REJECTED"),
                    factor_definition_version_id=None,
                    duplicate_of_factor_definition_version_id=None,
                    factor_evaluation_id=None,
                    alpha_mining_reward_id=None,
                )
            )
            return None
        state.canonicalized += 1
        return _CanonicalCandidate(
            proposal,
            definition,
            generation_index,
            candidate_ordinal,
        )

    @staticmethod
    def _record_duplicate(
        candidate: _CanonicalCandidate, state: _MiningRunState
    ) -> bool:
        definition_id = candidate.definition.factor_definition_version_id
        if definition_id not in state.seen_definition_ids:
            return False
        state.deduplicated += 1
        state.records.append(
            AlphaMiningCandidateRecord.create(
                candidate_id=candidate.proposal.candidate.candidate_id,
                source_lineage_ref=candidate.proposal.source_lineage_ref,
                generation_index=candidate.generation_index,
                candidate_ordinal=candidate.candidate_ordinal,
                disposition=AlphaMiningCandidateDisposition.DEDUPLICATED,
                reason_code="CANONICAL_DEFINITION_ALREADY_EVALUATED_IN_CONTEXT",
                factor_definition_version_id=definition_id,
                duplicate_of_factor_definition_version_id=definition_id,
                factor_evaluation_id=None,
                alpha_mining_reward_id=None,
            )
        )
        return True

    @staticmethod
    def _record_evaluation_budget_exhaustion(
        candidate: _CanonicalCandidate,
        job: AlphaMiningJobSpec,
        state: _MiningRunState,
    ) -> bool:
        if state.evaluated < job.max_evaluation_count:
            return False
        state.rejected += 1
        state.records.append(
            AlphaMiningCandidateRecord.create(
                candidate_id=candidate.proposal.candidate.candidate_id,
                source_lineage_ref=candidate.proposal.source_lineage_ref,
                generation_index=candidate.generation_index,
                candidate_ordinal=candidate.candidate_ordinal,
                disposition=AlphaMiningCandidateDisposition.REJECTED,
                reason_code="EVALUATION_BUDGET_EXHAUSTED",
                factor_definition_version_id=(
                    candidate.definition.factor_definition_version_id
                ),
                duplicate_of_factor_definition_version_id=None,
                factor_evaluation_id=None,
                alpha_mining_reward_id=None,
            )
        )
        state.stop_reason = AlphaMiningStopReason.EVALUATION_BUDGET_EXHAUSTED
        return True

    def _evaluate_candidate(
        self,
        candidate: _CanonicalCandidate,
        job: AlphaMiningJobSpec,
        state: _MiningRunState,
    ) -> AlphaMiningReward | None:
        definition_id = candidate.definition.factor_definition_version_id
        try:
            evidence = self.evaluation_port.evaluate_existing(candidate.definition, job)
            evidence.validate_exact(candidate.definition, job)
            reward = AlphaMiningReward.create(policy=job.reward_policy, evidence=evidence)
            observe_reward = getattr(self.candidate_generator, "observe_reward", None)
            if callable(observe_reward):
                observe_reward(
                    job=job,
                    generation_index=candidate.generation_index,
                    definition=candidate.definition,
                    reward=reward,
                )
        except (AlphaMiningContractError, ValueError, TypeError) as error:
            state.rejected += 1
            state.records.append(
                AlphaMiningCandidateRecord.create(
                    candidate_id=candidate.proposal.candidate.candidate_id,
                    source_lineage_ref=candidate.proposal.source_lineage_ref,
                    generation_index=candidate.generation_index,
                    candidate_ordinal=candidate.candidate_ordinal,
                    disposition=AlphaMiningCandidateDisposition.REJECTED,
                    reason_code=_reason(error, "EXACT_EVALUATION_EVIDENCE_REJECTED"),
                    factor_definition_version_id=definition_id,
                    duplicate_of_factor_definition_version_id=None,
                    factor_evaluation_id=None,
                    alpha_mining_reward_id=None,
                )
            )
            return None
        self._record_evaluated_candidate(candidate, evidence, reward, state)
        return reward

    @staticmethod
    def _record_evaluated_candidate(
        candidate: _CanonicalCandidate,
        evidence: AlphaMiningEvaluationEvidence,
        reward: AlphaMiningReward,
        state: _MiningRunState,
    ) -> None:
        state.evaluated += 1
        state.records.append(
            AlphaMiningCandidateRecord.create(
                candidate_id=candidate.proposal.candidate.candidate_id,
                source_lineage_ref=candidate.proposal.source_lineage_ref,
                generation_index=candidate.generation_index,
                candidate_ordinal=candidate.candidate_ordinal,
                disposition=AlphaMiningCandidateDisposition.EVALUATED,
                reason_code=reward.status.value,
                factor_definition_version_id=(
                    candidate.definition.factor_definition_version_id
                ),
                duplicate_of_factor_definition_version_id=None,
                factor_evaluation_id=evidence.factor_evaluation_id,
                alpha_mining_reward_id=reward.alpha_mining_reward_id,
            )
        )

    @staticmethod
    def _apply_reward_stop(
        reward: AlphaMiningReward,
        job: AlphaMiningJobSpec,
        state: _MiningRunState,
    ) -> None:
        if (
            reward.status is AlphaMiningRewardStatus.BLOCKED_BY_REVIEWER
            and job.stopping_rules.stop_on_blocking_finding
        ):
            state.stop_reason = AlphaMiningStopReason.BLOCKING_REVIEWER_FINDING
        elif state.evaluated >= job.stopping_rules.target_evaluated_candidates:
            state.stop_reason = AlphaMiningStopReason.TARGET_EVALUATED_CANDIDATES_REACHED

    def _run_candidate(
        self,
        job: AlphaMiningJobSpec,
        generation_index: int,
        state: _MiningRunState,
    ) -> None:
        if state.generated >= job.max_candidate_count:
            state.stop_reason = AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED
            return
        proposal = self._generate_candidate(job, generation_index, state)
        if proposal is None:
            return
        candidate = self._canonicalize_candidate(
            proposal, job, generation_index, state
        )
        if candidate is None or self._record_duplicate(candidate, state):
            return
        state.seen_definition_ids.add(candidate.definition.factor_definition_version_id)
        if self._record_evaluation_budget_exhaustion(candidate, job, state):
            return
        reward = self._evaluate_candidate(candidate, job, state)
        if reward is not None:
            self._apply_reward_stop(reward, job, state)

    @staticmethod
    def _finalize_stop_reason(
        job: AlphaMiningJobSpec, state: _MiningRunState
    ) -> AlphaMiningStopReason:
        if state.stop_reason is not None:
            return state.stop_reason
        if state.generated >= job.max_candidate_count:
            return AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED
        return AlphaMiningStopReason.GENERATION_BUDGET_EXHAUSTED

    def _create_run_record(
        self,
        job: AlphaMiningJobSpec,
        resource_observation: str,
        state: _MiningRunState,
        started: float,
    ) -> AlphaMiningRunRecord:
        stop_reason = self._finalize_stop_reason(job, state)
        status = (
            AlphaMiningRunStatus.SUCCEEDED
            if stop_reason is AlphaMiningStopReason.TARGET_EVALUATED_CANDIDATES_REACHED
            else AlphaMiningRunStatus.PARTIAL
        )
        elapsed = max(0.0, float(self.clock() - started))
        return AlphaMiningRunRecord.create(
            alpha_mining_job_spec_id=job.alpha_mining_job_spec_id,
            status=status,
            stop_reason=stop_reason,
            candidate_records=tuple(state.records),
            generated_count=state.generated,
            canonicalized_count=state.canonicalized,
            deduplicated_count=state.deduplicated,
            evaluated_count=state.evaluated,
            rejected_count=state.rejected,
            elapsed_seconds=f"{elapsed:.9f}",
            resource_observation=resource_observation,
        )

    def run(
        self, job: AlphaMiningJobSpec, *, resource_observation: str
    ) -> AlphaMiningRunRecord:
        self._validate_job(job)
        self._begin_generator_run(job)
        started = self.clock()
        state = _MiningRunState()
        candidates_per_generation = math.ceil(
            job.max_candidate_count / job.max_generation_count
        )
        for generation_index in range(1, job.max_generation_count + 1):
            for _ in range(candidates_per_generation):
                self._run_candidate(job, generation_index, state)
                if state.stop_reason is not None:
                    break
            if state.stop_reason is not None:
                break
        return self._create_run_record(job, resource_observation, state, started)


__all__ = [
    "AlphaMiningCandidateGenerator",
    "AlphaMiningEngine",
    "DeterministicGrammarCandidateGenerator",
    "ExistingFactorEvaluationPort",
    "factor_node_count",
    "factor_node_depth",
]
