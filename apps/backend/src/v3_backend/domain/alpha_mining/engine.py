from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Sequence
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
        token = f"g{generation_index}|c{candidate_ordinal}|{job.search_mutation_policy_version}"
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
                f"candidate:{candidate_ordinal}"
            ),
        )


def _reason(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    return str(code) if code else fallback


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

    def run(
        self, job: AlphaMiningJobSpec, *, resource_observation: str
    ) -> AlphaMiningRunRecord:
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
        started = self.clock()
        records: list[AlphaMiningCandidateRecord] = []
        seen_definitions: set[str] = set()
        generated = canonicalized = deduplicated = evaluated = rejected = 0
        stop_reason: AlphaMiningStopReason | None = None
        candidates_per_generation = math.ceil(
            job.max_candidate_count / job.max_generation_count
        )

        for generation_index in range(1, job.max_generation_count + 1):
            for _ in range(candidates_per_generation):
                if generated >= job.max_candidate_count:
                    stop_reason = AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED
                    break
                candidate_ordinal = generated + 1
                try:
                    proposal = self.candidate_generator.propose(
                        job,
                        generation_index=generation_index,
                        candidate_ordinal=candidate_ordinal,
                    )
                except (FactorIrError, AlphaMiningContractError, ValueError) as error:
                    generated += 1
                    rejected += 1
                    records.append(
                        AlphaMiningCandidateRecord.create(
                            candidate_id=f"candidate-generation-failure:{candidate_ordinal}",
                            source_lineage_ref=f"generation:{generation_index}:candidate:{candidate_ordinal}",
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
                    continue

                generated += 1
                try:
                    definition = self._definition(proposal, job)
                    canonicalized += 1
                except (FactorIrError, AlphaMiningContractError, ValueError) as error:
                    rejected += 1
                    records.append(
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
                    continue

                definition_id = definition.factor_definition_version_id
                if definition_id in seen_definitions:
                    deduplicated += 1
                    records.append(
                        AlphaMiningCandidateRecord.create(
                            candidate_id=proposal.candidate.candidate_id,
                            source_lineage_ref=proposal.source_lineage_ref,
                            generation_index=generation_index,
                            candidate_ordinal=candidate_ordinal,
                            disposition=AlphaMiningCandidateDisposition.DEDUPLICATED,
                            reason_code="CANONICAL_DEFINITION_ALREADY_EVALUATED_IN_CONTEXT",
                            factor_definition_version_id=definition_id,
                            duplicate_of_factor_definition_version_id=definition_id,
                            factor_evaluation_id=None,
                            alpha_mining_reward_id=None,
                        )
                    )
                    continue
                # One canonical definition is attempted at most once per exact job context.
                # A failed evaluation remains part of truthful lineage; retry requires a new
                # explicit job/reason rather than an accidental duplicate source candidate.
                seen_definitions.add(definition_id)
                if evaluated >= job.max_evaluation_count:
                    rejected += 1
                    records.append(
                        AlphaMiningCandidateRecord.create(
                            candidate_id=proposal.candidate.candidate_id,
                            source_lineage_ref=proposal.source_lineage_ref,
                            generation_index=generation_index,
                            candidate_ordinal=candidate_ordinal,
                            disposition=AlphaMiningCandidateDisposition.REJECTED,
                            reason_code="EVALUATION_BUDGET_EXHAUSTED",
                            factor_definition_version_id=definition_id,
                            duplicate_of_factor_definition_version_id=None,
                            factor_evaluation_id=None,
                            alpha_mining_reward_id=None,
                        )
                    )
                    stop_reason = AlphaMiningStopReason.EVALUATION_BUDGET_EXHAUSTED
                    break

                try:
                    evidence = self.evaluation_port.evaluate_existing(definition, job)
                    evidence.validate_exact(definition, job)
                    reward = AlphaMiningReward.create(
                        policy=job.reward_policy, evidence=evidence
                    )
                except (AlphaMiningContractError, ValueError, TypeError) as error:
                    rejected += 1
                    records.append(
                        AlphaMiningCandidateRecord.create(
                            candidate_id=proposal.candidate.candidate_id,
                            source_lineage_ref=proposal.source_lineage_ref,
                            generation_index=generation_index,
                            candidate_ordinal=candidate_ordinal,
                            disposition=AlphaMiningCandidateDisposition.REJECTED,
                            reason_code=_reason(error, "EXACT_EVALUATION_EVIDENCE_REJECTED"),
                            factor_definition_version_id=definition_id,
                            duplicate_of_factor_definition_version_id=None,
                            factor_evaluation_id=None,
                            alpha_mining_reward_id=None,
                        )
                    )
                    continue

                evaluated += 1
                records.append(
                    AlphaMiningCandidateRecord.create(
                        candidate_id=proposal.candidate.candidate_id,
                        source_lineage_ref=proposal.source_lineage_ref,
                        generation_index=generation_index,
                        candidate_ordinal=candidate_ordinal,
                        disposition=AlphaMiningCandidateDisposition.EVALUATED,
                        reason_code=reward.status.value,
                        factor_definition_version_id=definition_id,
                        duplicate_of_factor_definition_version_id=None,
                        factor_evaluation_id=evidence.factor_evaluation.factor_evaluation_id,
                        alpha_mining_reward_id=reward.alpha_mining_reward_id,
                    )
                )
                if (
                    reward.status is AlphaMiningRewardStatus.BLOCKED_BY_REVIEWER
                    and job.stopping_rules.stop_on_blocking_finding
                ):
                    stop_reason = AlphaMiningStopReason.BLOCKING_REVIEWER_FINDING
                    break
                if evaluated >= job.stopping_rules.target_evaluated_candidates:
                    stop_reason = (
                        AlphaMiningStopReason.TARGET_EVALUATED_CANDIDATES_REACHED
                    )
                    break
            if stop_reason is not None:
                break

        if stop_reason is None:
            stop_reason = (
                AlphaMiningStopReason.CANDIDATE_BUDGET_EXHAUSTED
                if generated >= job.max_candidate_count
                else AlphaMiningStopReason.GENERATION_BUDGET_EXHAUSTED
            )
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
            candidate_records=tuple(records),
            generated_count=generated,
            canonicalized_count=canonicalized,
            deduplicated_count=deduplicated,
            evaluated_count=evaluated,
            rejected_count=rejected,
            elapsed_seconds=f"{elapsed:.9f}",
            resource_observation=resource_observation,
        )


__all__ = [
    "AlphaMiningCandidateGenerator",
    "AlphaMiningEngine",
    "DeterministicGrammarCandidateGenerator",
    "ExistingFactorEvaluationPort",
    "factor_node_count",
    "factor_node_depth",
]
