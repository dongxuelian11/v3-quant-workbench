from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from v3_backend.control_plane.resource_governor import OperationProfile
from v3_backend.domain.agent_research_loop import (
    BudgetLimitMode,
    ResearchLoopBudgetVersion,
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
from v3_backend.domain.datasets import FormalDatasetVersion
from v3_backend.domain.factors import (
    FactorDefinitionVersion,
    FactorEvaluation,
    FactorEvaluationContext,
    FactorNode,
    FormalFeatureMaterialization,
    OperatorRegistry,
    ValueType,
)
from v3_backend.domain.payload_authority import PayloadResolutionReceipt
from v3_backend.provenance.canonical_hash import canonical_sha256


class AlphaMiningContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AlphaMiningContractError("INVALID_ALPHA_MINING_CONTRACT", f"{name} is required")
    return value


def _positive(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AlphaMiningContractError(
            "INVALID_ALPHA_MINING_BUDGET", f"{name} must be a positive integer"
        )
    return value


def _non_negative(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AlphaMiningContractError(
            "INVALID_MINING_RUN", f"{name} must be a non-negative integer"
        )
    return value


def _closed_bool(value: object, name: str, code: str) -> bool:
    if not isinstance(value, bool):
        raise AlphaMiningContractError(code, f"{name} must be boolean")
    return value


def _unique(values: object, name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values or any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in values
    ):
        raise AlphaMiningContractError(
            "INVALID_ALPHA_MINING_CONTRACT",
            f"{name} must be an exact tuple of non-empty refs",
        )
    if len(values) != len(set(values)):
        raise AlphaMiningContractError(
            "INVALID_ALPHA_MINING_CONTRACT", f"{name} must be unique"
        )
    return tuple(sorted(values))


def _decimal_text(value: str | int | float | Decimal, name: str) -> str:
    if isinstance(value, bool):
        raise AlphaMiningContractError("INVALID_REWARD_POLICY", f"{name} must be numeric")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AlphaMiningContractError("INVALID_REWARD_POLICY", f"{name} is invalid") from error
    if not decimal_value.is_finite():
        raise AlphaMiningContractError("INVALID_REWARD_POLICY", f"{name} must be finite")
    if decimal_value == 0:
        return "0"
    normalized = format(decimal_value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


@dataclass(frozen=True, slots=True)
class AlphaMiningSourceField:
    feature_name: str
    field_semantic_version: str
    data_truth_ref: str

    def __post_init__(self) -> None:
        _text(self.feature_name, "feature_name")
        _text(self.field_semantic_version, "field_semantic_version")
        _text(self.data_truth_ref, "data_truth_ref")
        if not self.data_truth_ref.startswith("data-truth-field:"):
            raise AlphaMiningContractError(
                "UNSUPPORTED_DATA_FIELD", "an exact Data Truth field ref is required"
            )

    def to_wire(self) -> dict[str, str]:
        return {
            "feature_name": self.feature_name,
            "field_semantic_version": self.field_semantic_version,
            "data_truth_ref": self.data_truth_ref,
        }


@dataclass(frozen=True, slots=True)
class AlphaMiningSearchSpaceVersion:
    search_space_version_id: str
    operator_registry_version: str
    operator_allowlist: tuple[str, ...]
    source_fields: tuple[AlphaMiningSourceField, ...]
    generation_policy_version: str

    @classmethod
    def create(
        cls,
        *,
        registry: OperatorRegistry,
        operator_allowlist: tuple[str, ...],
        source_fields: tuple[AlphaMiningSourceField, ...],
        generation_policy_version: str,
    ) -> AlphaMiningSearchSpaceVersion:
        operators = _unique(operator_allowlist, "operator_allowlist")
        if not source_fields:
            raise AlphaMiningContractError(
                "UNSUPPORTED_DATA_FIELD", "search space requires registered source fields"
            )
        ordered_fields = tuple(
            sorted(source_fields, key=lambda value: (value.feature_name, value.field_semantic_version))
        )
        field_keys = tuple((value.feature_name, value.field_semantic_version) for value in ordered_fields)
        if len(field_keys) != len(set(field_keys)):
            raise AlphaMiningContractError(
                "UNSUPPORTED_DATA_FIELD", "source fields must have unique exact semantics"
            )
        for key in operators:
            try:
                name, version = key.rsplit("@", 1)
            except ValueError as error:
                raise AlphaMiningContractError(
                    "UNREGISTERED_MINING_OPERATOR", key
                ) from error
            try:
                spec = registry.resolve(name, version)
            except ValueError as error:
                raise AlphaMiningContractError(
                    "UNREGISTERED_MINING_OPERATOR", key
                ) from error
            if not spec.pit_safe or not spec.deterministic or name == "LEAD":
                raise AlphaMiningContractError("UNSAFE_MINING_OPERATOR", key)
            if spec.output_type is not ValueType.FLOAT_SERIES or any(
                input_type is not ValueType.FLOAT_SERIES for input_type in spec.input_types
            ):
                raise AlphaMiningContractError(
                    "UNSUPPORTED_MINING_OPERATOR_TYPE", key
                )
        payload = {
            "operator_registry_version": registry.registry_version,
            "operator_allowlist": list(operators),
            "source_fields": [value.to_wire() for value in ordered_fields],
            "generation_policy_version": _text(
                generation_policy_version, "generation_policy_version"
            ),
        }
        return cls(
            "amss_sha256_" + canonical_sha256(payload),
            registry.registry_version,
            operators,
            ordered_fields,
            generation_policy_version,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "search_space_version_id": self.search_space_version_id,
            "operator_registry_version": self.operator_registry_version,
            "operator_allowlist": list(self.operator_allowlist),
            "source_fields": [value.to_wire() for value in self.source_fields],
            "generation_policy_version": self.generation_policy_version,
        }


class MissingRewardComponentPolicy(StrEnum):
    NOT_AVAILABLE = "NOT_AVAILABLE"
    EXPLICIT_ZERO = "EXPLICIT_ZERO"


class RewardComponentName(StrEnum):
    IC = "IC"
    RANK_IC = "RANK_IC"
    COVERAGE = "COVERAGE"
    TURNOVER = "TURNOVER"
    COMPLEXITY = "COMPLEXITY"


@dataclass(frozen=True, slots=True)
class RewardComponentRule:
    component: RewardComponentName
    weight: str
    missing_policy: MissingRewardComponentPolicy

    @classmethod
    def create(
        cls,
        component: RewardComponentName,
        weight: str | int | float | Decimal,
        missing_policy: MissingRewardComponentPolicy = MissingRewardComponentPolicy.NOT_AVAILABLE,
    ) -> RewardComponentRule:
        if not isinstance(component, RewardComponentName):
            raise AlphaMiningContractError("INVALID_REWARD_POLICY", "closed component required")
        if not isinstance(missing_policy, MissingRewardComponentPolicy):
            raise AlphaMiningContractError("INVALID_REWARD_POLICY", "closed missing policy required")
        return cls(component, _decimal_text(weight, "weight"), missing_policy)

    def to_wire(self) -> dict[str, str]:
        return {
            "component": self.component.value,
            "weight": self.weight,
            "missing_policy": self.missing_policy.value,
        }


@dataclass(frozen=True, slots=True)
class AlphaMiningRewardPolicyVersion:
    reward_policy_version_id: str
    policy_version: str
    component_rules: tuple[RewardComponentRule, ...]
    block_on_blocking_finding: bool

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        component_rules: tuple[RewardComponentRule, ...],
        block_on_blocking_finding: bool,
    ) -> AlphaMiningRewardPolicyVersion:
        if not component_rules:
            raise AlphaMiningContractError("INVALID_REWARD_POLICY", "component rules required")
        ordered = tuple(sorted(component_rules, key=lambda value: value.component.value))
        if len({value.component for value in ordered}) != len(ordered):
            raise AlphaMiningContractError("INVALID_REWARD_POLICY", "components must be unique")
        if not any(value.component is RewardComponentName.COMPLEXITY for value in ordered):
            raise AlphaMiningContractError(
                "INVALID_REWARD_POLICY", "deterministic complexity rule is required"
            )
        closed_blocking = _closed_bool(
            block_on_blocking_finding,
            "block_on_blocking_finding",
            "INVALID_REWARD_POLICY",
        )
        payload = {
            "policy_version": _text(policy_version, "policy_version"),
            "component_rules": [value.to_wire() for value in ordered],
            "block_on_blocking_finding": closed_blocking,
        }
        return cls(
            "amrp_sha256_" + canonical_sha256(payload),
            policy_version,
            ordered,
            closed_blocking,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "reward_policy_version_id": self.reward_policy_version_id,
            "policy_version": self.policy_version,
            "component_rules": [value.to_wire() for value in self.component_rules],
            "block_on_blocking_finding": self.block_on_blocking_finding,
        }

    def assert_canonical(self) -> None:
        rebuilt = AlphaMiningRewardPolicyVersion.create(
            policy_version=self.policy_version,
            component_rules=tuple(
                RewardComponentRule.create(
                    value.component, value.weight, value.missing_policy
                )
                for value in self.component_rules
            ),
            block_on_blocking_finding=self.block_on_blocking_finding,
        )
        if rebuilt != self:
            raise AlphaMiningContractError(
                "REWARD_POLICY_IDENTITY_MISMATCH", self.reward_policy_version_id
            )


@dataclass(frozen=True, slots=True)
class AlphaMiningEvaluationContext:
    dataset_version_id: str
    factor_context: FactorEvaluationContext
    period_start: str
    period_end: str
    label_ref: str
    horizon: str
    evaluation_policy_version: str
    cost_turnover_context_ref: str

    def __post_init__(self) -> None:
        for name in (
            "dataset_version_id",
            "period_start",
            "period_end",
            "label_ref",
            "horizon",
            "evaluation_policy_version",
            "cost_turnover_context_ref",
        ):
            _text(getattr(self, name), name)
        if not isinstance(self.factor_context, FactorEvaluationContext):
            raise AlphaMiningContractError(
                "INVALID_EVALUATION_CONTEXT", "typed FactorEvaluationContext required"
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "dataset_version_id": self.dataset_version_id,
            "factor_context": self.factor_context.to_wire(),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "label_ref": self.label_ref,
            "horizon": self.horizon,
            "evaluation_policy_version": self.evaluation_policy_version,
            "cost_turnover_context_ref": self.cost_turnover_context_ref,
        }


@dataclass(frozen=True, slots=True)
class AlphaMiningStoppingRules:
    target_evaluated_candidates: int
    stop_on_blocking_finding: bool

    def __post_init__(self) -> None:
        _positive(self.target_evaluated_candidates, "target_evaluated_candidates")
        _closed_bool(
            self.stop_on_blocking_finding,
            "stop_on_blocking_finding",
            "INVALID_ALPHA_MINING_BUDGET",
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "target_evaluated_candidates": self.target_evaluated_candidates,
            "stop_on_blocking_finding": self.stop_on_blocking_finding,
        }


def _operation_profile_wire(profile: OperationProfile) -> dict[str, object]:
    return {
        "operation_id": profile.operation_id,
        "resource_class": profile.resource_class,
        "cpu_slots": profile.cpu_slots,
        "memory_hard_limit_bytes": profile.memory_hard_limit_bytes,
        "scratch_budget_bytes": profile.scratch_budget_bytes,
        "wall_clock_seconds": profile.wall_clock_seconds,
        "heartbeat_interval_seconds": profile.heartbeat_interval_seconds,
        "gpu_device": profile.gpu_device,
        "resumable": profile.resumable,
    }


def _validate_operation_profile(profile: OperationProfile) -> None:
    _text(profile.operation_id, "operation_profile.operation_id")
    _text(profile.resource_class, "operation_profile.resource_class")
    for name in (
        "cpu_slots",
        "memory_hard_limit_bytes",
        "scratch_budget_bytes",
        "wall_clock_seconds",
        "heartbeat_interval_seconds",
    ):
        _positive(getattr(profile, name), f"operation_profile.{name}")
    if profile.gpu_device is not None:
        _text(profile.gpu_device, "operation_profile.gpu_device")
    _closed_bool(profile.resumable, "operation_profile.resumable", "INVALID_ALPHA_MINING_BUDGET")


@dataclass(frozen=True, slots=True)
class AlphaMiningJobSpec:
    alpha_mining_job_spec_id: str
    universe_version_id: str
    dataset_version_id: str
    input_data_refs: tuple[str, ...]
    data_semantic_profile_id: str
    search_space: AlphaMiningSearchSpaceVersion
    max_expression_depth: int
    max_node_count: int
    max_candidate_count: int
    max_generation_count: int
    max_evaluation_count: int
    deterministic_seed: int
    search_mutation_policy_version: str
    evaluation_context: AlphaMiningEvaluationContext
    reward_policy: AlphaMiningRewardPolicyVersion
    operation_profile: OperationProfile
    research_loop_budget: ResearchLoopBudgetVersion
    stopping_rules: AlphaMiningStoppingRules

    @classmethod
    def create(cls, **values: object) -> AlphaMiningJobSpec:
        search_space = values.get("search_space")
        evaluation_context = values.get("evaluation_context")
        reward_policy = values.get("reward_policy")
        operation_profile = values.get("operation_profile")
        research_budget = values.get("research_loop_budget")
        stopping_rules = values.get("stopping_rules")
        typed = (
            (search_space, AlphaMiningSearchSpaceVersion, "search_space"),
            (evaluation_context, AlphaMiningEvaluationContext, "evaluation_context"),
            (reward_policy, AlphaMiningRewardPolicyVersion, "reward_policy"),
            (operation_profile, OperationProfile, "operation_profile"),
            (research_budget, ResearchLoopBudgetVersion, "research_loop_budget"),
            (stopping_rules, AlphaMiningStoppingRules, "stopping_rules"),
        )
        for value, expected, name in typed:
            if not isinstance(value, expected):
                raise AlphaMiningContractError(
                    "INVALID_ALPHA_MINING_CONTRACT", f"typed {name} required"
                )
        universe_id = _text(values.get("universe_version_id"), "universe_version_id")
        dataset_id = _text(values.get("dataset_version_id"), "dataset_version_id")
        assert isinstance(evaluation_context, AlphaMiningEvaluationContext)
        assert isinstance(search_space, AlphaMiningSearchSpaceVersion)
        assert isinstance(reward_policy, AlphaMiningRewardPolicyVersion)
        assert isinstance(operation_profile, OperationProfile)
        assert isinstance(research_budget, ResearchLoopBudgetVersion)
        assert isinstance(stopping_rules, AlphaMiningStoppingRules)
        _validate_operation_profile(operation_profile)
        reward_policy.assert_canonical()
        if evaluation_context.dataset_version_id != dataset_id:
            raise AlphaMiningContractError(
                "EVALUATION_CONTEXT_BINDING_MISMATCH", "dataset identity"
            )
        if evaluation_context.factor_context.universe_version_id != universe_id:
            raise AlphaMiningContractError(
                "EVALUATION_CONTEXT_BINDING_MISMATCH", "universe identity"
            )
        if not isinstance(values.get("deterministic_seed"), int) or isinstance(
            values.get("deterministic_seed"), bool
        ):
            raise AlphaMiningContractError(
                "INVALID_ALPHA_MINING_BUDGET", "deterministic_seed must be an integer"
            )
        limits = {
            "max_expression_depth": _positive(values.get("max_expression_depth"), "max_expression_depth"),
            "max_node_count": _positive(values.get("max_node_count"), "max_node_count"),
            "max_candidate_count": _positive(values.get("max_candidate_count"), "max_candidate_count"),
            "max_generation_count": _positive(values.get("max_generation_count"), "max_generation_count"),
            "max_evaluation_count": _positive(values.get("max_evaluation_count"), "max_evaluation_count"),
        }
        if limits["max_node_count"] < limits["max_expression_depth"]:
            raise AlphaMiningContractError(
                "INVALID_ALPHA_MINING_BUDGET", "node bound cannot be smaller than depth bound"
            )
        # A target above max_evaluation_count intentionally expresses truthful
        # evaluation-budget exhaustion and needs no additional upper-bound rejection.
        budget_limits = (
            research_budget.max_iterations,
            research_budget.max_actions,
            research_budget.max_candidates,
            research_budget.max_experiments,
            research_budget.max_model_calls,
        )
        if any(value.mode is not BudgetLimitMode.FINITE for value in budget_limits):
            raise AlphaMiningContractError(
                "INVALID_ALPHA_MINING_BUDGET", "S requires finite ResearchLoop limits"
            )
        canonical_research_budget = ResearchLoopBudgetVersion.create(
            max_iterations=research_budget.max_iterations,
            max_actions=research_budget.max_actions,
            max_candidates=research_budget.max_candidates,
            max_experiments=research_budget.max_experiments,
            max_model_calls=research_budget.max_model_calls,
            resource_profile_ref=research_budget.resource_profile_ref,
            max_wallclock_seconds=research_budget.max_wallclock_seconds,
        )
        if canonical_research_budget != research_budget:
            raise AlphaMiningContractError(
                "RESEARCH_BUDGET_IDENTITY_MISMATCH",
                research_budget.budget_version_id,
            )
        if research_budget.resource_profile_ref != operation_profile.operation_id:
            raise AlphaMiningContractError(
                "RESOURCE_PROFILE_BINDING_MISMATCH", operation_profile.operation_id
            )
        comparisons = (
            (research_budget.max_iterations.value, limits["max_generation_count"], "iterations"),
            (research_budget.max_actions.value, limits["max_evaluation_count"], "actions"),
            (research_budget.max_candidates.value, limits["max_candidate_count"], "candidates"),
            (research_budget.max_experiments.value, limits["max_evaluation_count"], "experiments"),
        )
        for outer, inner, name in comparisons:
            if outer is None or outer < inner:
                raise AlphaMiningContractError(
                    "RESEARCH_BUDGET_BINDING_MISMATCH", name
                )
        if (
            research_budget.max_wallclock_seconds is None
            or research_budget.max_wallclock_seconds.mode is not BudgetLimitMode.FINITE
            or research_budget.max_wallclock_seconds.value != operation_profile.wall_clock_seconds
        ):
            raise AlphaMiningContractError(
                "RESEARCH_BUDGET_BINDING_MISMATCH", "wallclock"
            )
        payload = {
            "universe_version_id": universe_id,
            "dataset_version_id": dataset_id,
            "input_data_refs": list(_unique(values.get("input_data_refs"), "input_data_refs")),
            "data_semantic_profile_id": _text(
                values.get("data_semantic_profile_id"), "data_semantic_profile_id"
            ),
            "search_space": search_space.to_wire(),
            **limits,
            "deterministic_seed": values["deterministic_seed"],
            "search_mutation_policy_version": _text(
                values.get("search_mutation_policy_version"),
                "search_mutation_policy_version",
            ),
            "evaluation_context": evaluation_context.to_wire(),
            "reward_policy": reward_policy.to_wire(),
            "operation_profile": _operation_profile_wire(operation_profile),
            "research_loop_budget_version_id": research_budget.budget_version_id,
            "stopping_rules": stopping_rules.to_wire(),
        }
        return cls(
            alpha_mining_job_spec_id="amjs_sha256_" + canonical_sha256(payload),
            universe_version_id=universe_id,
            dataset_version_id=dataset_id,
            input_data_refs=tuple(payload["input_data_refs"]),
            data_semantic_profile_id=payload["data_semantic_profile_id"],
            search_space=search_space,
            max_expression_depth=limits["max_expression_depth"],
            max_node_count=limits["max_node_count"],
            max_candidate_count=limits["max_candidate_count"],
            max_generation_count=limits["max_generation_count"],
            max_evaluation_count=limits["max_evaluation_count"],
            deterministic_seed=values["deterministic_seed"],  # type: ignore[arg-type]
            search_mutation_policy_version=payload["search_mutation_policy_version"],
            evaluation_context=evaluation_context,
            reward_policy=reward_policy,
            operation_profile=operation_profile,
            research_loop_budget=research_budget,
            stopping_rules=stopping_rules,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "alpha_mining_job_spec_id": self.alpha_mining_job_spec_id,
            "universe_version_id": self.universe_version_id,
            "dataset_version_id": self.dataset_version_id,
            "input_data_refs": list(self.input_data_refs),
            "data_semantic_profile_id": self.data_semantic_profile_id,
            "search_space": self.search_space.to_wire(),
            "max_expression_depth": self.max_expression_depth,
            "max_node_count": self.max_node_count,
            "max_candidate_count": self.max_candidate_count,
            "max_generation_count": self.max_generation_count,
            "max_evaluation_count": self.max_evaluation_count,
            "deterministic_seed": self.deterministic_seed,
            "search_mutation_policy_version": self.search_mutation_policy_version,
            "evaluation_context": self.evaluation_context.to_wire(),
            "reward_policy": self.reward_policy.to_wire(),
            "operation_profile": _operation_profile_wire(self.operation_profile),
            "research_loop_budget_version_id": self.research_loop_budget.budget_version_id,
            "stopping_rules": self.stopping_rules.to_wire(),
        }

    def assert_canonical(self) -> None:
        rebuilt = AlphaMiningJobSpec.create(
            universe_version_id=self.universe_version_id,
            dataset_version_id=self.dataset_version_id,
            input_data_refs=self.input_data_refs,
            data_semantic_profile_id=self.data_semantic_profile_id,
            search_space=self.search_space,
            max_expression_depth=self.max_expression_depth,
            max_node_count=self.max_node_count,
            max_candidate_count=self.max_candidate_count,
            max_generation_count=self.max_generation_count,
            max_evaluation_count=self.max_evaluation_count,
            deterministic_seed=self.deterministic_seed,
            search_mutation_policy_version=self.search_mutation_policy_version,
            evaluation_context=self.evaluation_context,
            reward_policy=self.reward_policy,
            operation_profile=self.operation_profile,
            research_loop_budget=self.research_loop_budget,
            stopping_rules=self.stopping_rules,
        )
        if rebuilt != self:
            raise AlphaMiningContractError(
                "ALPHA_MINING_JOB_IDENTITY_MISMATCH",
                self.alpha_mining_job_spec_id,
            )


@dataclass(frozen=True, slots=True)
class AlphaMiningCandidateProposal:
    candidate: MiningFactorCandidate
    root: FactorNode
    source_lineage_ref: str
    source_format: str = "V3_FACTOR_IR_JSON/1.0.0"

    @classmethod
    def create(
        cls, *, root: FactorNode, source_lineage_ref: str
    ) -> AlphaMiningCandidateProposal:
        source = json.dumps(root.to_wire(), sort_keys=True, separators=(",", ":"))
        return cls(MiningFactorCandidate.create(source), root, _text(source_lineage_ref, "source_lineage_ref"))

    def __post_init__(self) -> None:
        if self.source_format != "V3_FACTOR_IR_JSON/1.0.0":
            raise AlphaMiningContractError(
                "UNSUPPORTED_CANDIDATE_SOURCE_FORMAT", self.source_format
            )
        expected = json.dumps(self.root.to_wire(), sort_keys=True, separators=(",", ":"))
        if self.candidate.expression_source != expected:
            raise AlphaMiningContractError(
                "CANDIDATE_SOURCE_BINDING_MISMATCH", self.candidate.candidate_id
            )
        if self.candidate.authority_status != "NON_CANONICAL" or self.candidate.lifecycle_state != "DRAFT":
            raise AlphaMiningContractError(
                "CANDIDATE_AUTHORITY_VIOLATION", self.candidate.candidate_id
            )


@dataclass(frozen=True, slots=True)
class AlphaResearchFactorEvaluation:
    """Research-only evidence bound to formal Factor/Dataset owners and P1 bytes."""

    factor_evaluation_id: str
    factor_definition_version_id: str
    feature_materialization_id: str
    dataset_version_id: str
    context: FactorEvaluationContext
    evaluation_provenance_artifact_id: str
    dataset_resolution_receipt: PayloadResolutionReceipt
    feature_resolution_receipt: PayloadResolutionReceipt
    truth_admission: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        definition: FactorDefinitionVersion,
        materialization: FormalFeatureMaterialization,
        dataset: FormalDatasetVersion,
        context: FactorEvaluationContext,
        dataset_resolution_receipt: PayloadResolutionReceipt,
        feature_resolution_receipt: PayloadResolutionReceipt,
        proposed_state: TruthAdmissionState,
    ) -> "AlphaResearchFactorEvaluation":
        if materialization.factor_definition_version_id != definition.factor_definition_version_id:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "formal FeatureMaterialization definition"
            )
        if (
            materialization.snapshot_id != dataset.snapshot_id
            or materialization.universe_version_id != dataset.universe_version_id
            or context.snapshot_id != dataset.snapshot_id
            or context.universe_version_id != dataset.universe_version_id
            or context.evaluator_version != materialization.evaluator_version
        ):
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "formal Factor/Dataset context"
            )
        if (
            dataset_resolution_receipt.artifact_id != dataset.dataset_descriptor.artifact_id
            or feature_resolution_receipt.artifact_id != materialization.output_descriptor.artifact_id
        ):
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "P1 actual-payload receipts"
            )
        truth = propagate_downstream_ceiling(
            proposed_state,
            (
                UpstreamRequirement(dataset.dataset_version_id, dataset.truth_admission),
                UpstreamRequirement(
                    materialization.feature_materialization_id,
                    materialization.truth_admission,
                ),
            ),
        )
        payload = {
            "factor_definition_version_id": definition.factor_definition_version_id,
            "feature_materialization_id": materialization.feature_materialization_id,
            "dataset_version_id": dataset.dataset_version_id,
            "context": context.to_wire(),
            "evaluation_provenance_artifact_id": materialization.output_descriptor.artifact_id,
            "dataset_resolution_receipt_id": dataset_resolution_receipt.receipt_identity,
            "feature_resolution_receipt_id": feature_resolution_receipt.receipt_identity,
            "truth_admission": truth.to_wire(),
        }
        return cls(
            "fev_sha256_" + canonical_sha256(payload),
            definition.factor_definition_version_id,
            materialization.feature_materialization_id,
            dataset.dataset_version_id,
            context,
            materialization.output_descriptor.artifact_id,
            dataset_resolution_receipt,
            feature_resolution_receipt,
            truth,
        )


@dataclass(frozen=True, slots=True)
class AlphaMiningEvaluationEvidence:
    evaluation_context: AlphaMiningEvaluationContext
    factor_evaluation: FactorEvaluation | AlphaResearchFactorEvaluation
    experiment_run: ExperimentRun
    experiment_attempt: ExperimentAttempt
    reward_vector: RewardVector
    reviewer_evidence: ReviewerEvidence
    reviewer_findings: tuple[ReviewerFinding, ...]
    available_components: tuple[RewardComponentName, ...]

    @property
    def factor_evaluation_id(self) -> str:
        return self.factor_evaluation.factor_evaluation_id

    def validate_exact(
        self, definition: FactorDefinitionVersion, job: AlphaMiningJobSpec
    ) -> None:
        if self.evaluation_context != job.evaluation_context:
            raise AlphaMiningContractError(
                "EVALUATION_CONTEXT_BINDING_MISMATCH", "period/label/horizon/policy/cost"
            )
        if self.factor_evaluation.factor_definition_version_id != definition.factor_definition_version_id:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "FactorDefinitionVersion"
            )
        if self.factor_evaluation.context != job.evaluation_context.factor_context:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "FactorEvaluationContext"
            )
        if self.experiment_run.factor_evaluation_id != self.factor_evaluation.factor_evaluation_id:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "ExperimentRun FactorEvaluation"
            )
        if self.experiment_run.dataset_version_id != job.dataset_version_id:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "ExperimentRun DatasetVersion"
            )
        if self.experiment_attempt.experiment_run_id != self.experiment_run.experiment_run_id:
            raise AlphaMiningContractError(
                "EVALUATION_BINDING_MISMATCH", "ExperimentAttempt"
            )
        if self.experiment_attempt.state is not ExperimentAttemptState.SUCCEEDED:
            raise AlphaMiningContractError(
                "EVALUATION_NOT_SUCCESSFUL", self.experiment_attempt.experiment_attempt_id
            )
        if self.reward_vector.experiment_run_id != self.experiment_run.experiment_run_id:
            raise AlphaMiningContractError("REWARD_BINDING_MISMATCH", "ExperimentRun")
        if self.reward_vector.experiment_attempt_id != self.experiment_attempt.experiment_attempt_id:
            raise AlphaMiningContractError("REWARD_BINDING_MISMATCH", "ExperimentAttempt")
        if self.reward_vector.reviewer_evidence_id != self.reviewer_evidence.reviewer_evidence_id:
            raise AlphaMiningContractError("REWARD_BINDING_MISMATCH", "ReviewerEvidence")
        if self.reward_vector.complexity != definition.metadata.complexity:
            raise AlphaMiningContractError("REWARD_BINDING_MISMATCH", "complexity")
        finding_ids = tuple(sorted(value.finding_id for value in self.reviewer_findings))
        if finding_ids != self.reviewer_evidence.finding_ids:
            raise AlphaMiningContractError("REVIEW_BINDING_MISMATCH", "finding identities")
        if len(self.available_components) != len(set(self.available_components)):
            raise AlphaMiningContractError("REWARD_BINDING_MISMATCH", "duplicate components")


class RewardComponentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    EXPLICIT_ZERO_BY_POLICY = "EXPLICIT_ZERO_BY_POLICY"


@dataclass(frozen=True, slots=True)
class RewardComponentResult:
    component: RewardComponentName
    status: RewardComponentStatus
    observed_value: str | None
    weight: str
    contribution: str | None

    def to_wire(self) -> dict[str, str | None]:
        return {
            "component": self.component.value,
            "status": self.status.value,
            "observed_value": self.observed_value,
            "weight": self.weight,
            "contribution": self.contribution,
        }


class AlphaMiningRewardStatus(StrEnum):
    SCORED = "SCORED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    BLOCKED_BY_REVIEWER = "BLOCKED_BY_REVIEWER"


@dataclass(frozen=True, slots=True)
class AlphaMiningReward:
    alpha_mining_reward_id: str
    reward_policy_version_id: str
    reward_vector_id: str
    reviewer_evidence_id: str
    status: AlphaMiningRewardStatus
    components: tuple[RewardComponentResult, ...]
    total_reward: str | None

    @classmethod
    def create(
        cls,
        *,
        policy: AlphaMiningRewardPolicyVersion,
        evidence: AlphaMiningEvaluationEvidence,
    ) -> AlphaMiningReward:
        blocking = any(
            value.severity is FindingSeverity.BLOCKING and value.status is EvidenceStatus.FAIL
            for value in evidence.reviewer_findings
        )
        values = {
            RewardComponentName.IC: evidence.reward_vector.ic,
            RewardComponentName.RANK_IC: evidence.reward_vector.rank_ic,
            RewardComponentName.COVERAGE: evidence.reward_vector.coverage,
            RewardComponentName.TURNOVER: evidence.reward_vector.turnover,
            RewardComponentName.COMPLEXITY: evidence.reward_vector.complexity,
        }
        components: list[RewardComponentResult] = []
        missing_required = False
        total = Decimal("0")
        available = set(evidence.available_components)
        for rule in policy.component_rules:
            if rule.component not in available:
                if rule.missing_policy is MissingRewardComponentPolicy.EXPLICIT_ZERO:
                    components.append(
                        RewardComponentResult(
                            rule.component,
                            RewardComponentStatus.EXPLICIT_ZERO_BY_POLICY,
                            None,
                            rule.weight,
                            "0",
                        )
                    )
                else:
                    missing_required = True
                    components.append(
                        RewardComponentResult(
                            rule.component,
                            RewardComponentStatus.NOT_AVAILABLE,
                            None,
                            rule.weight,
                            None,
                        )
                    )
                continue
            observed = _decimal_text(values[rule.component], rule.component.value)
            contribution = Decimal(observed) * Decimal(rule.weight)
            total += contribution
            components.append(
                RewardComponentResult(
                    rule.component,
                    RewardComponentStatus.AVAILABLE,
                    observed,
                    rule.weight,
                    _decimal_text(contribution, "contribution"),
                )
            )
        if blocking and policy.block_on_blocking_finding:
            status = AlphaMiningRewardStatus.BLOCKED_BY_REVIEWER
            total_text = None
        elif missing_required:
            status = AlphaMiningRewardStatus.NOT_AVAILABLE
            total_text = None
        else:
            status = AlphaMiningRewardStatus.SCORED
            total_text = _decimal_text(total, "total_reward")
        payload = {
            "reward_policy_version_id": policy.reward_policy_version_id,
            "reward_vector_id": evidence.reward_vector.reward_vector_id,
            "reviewer_evidence_id": evidence.reviewer_evidence.reviewer_evidence_id,
            "status": status.value,
            "components": [value.to_wire() for value in components],
            "total_reward": total_text,
        }
        return cls(
            "amrw_sha256_" + canonical_sha256(payload),
            policy.reward_policy_version_id,
            evidence.reward_vector.reward_vector_id,
            evidence.reviewer_evidence.reviewer_evidence_id,
            status,
            tuple(components),
            total_text,
        )


class AlphaMiningCandidateDisposition(StrEnum):
    REJECTED = "REJECTED"
    DEDUPLICATED = "DEDUPLICATED"
    EVALUATED = "EVALUATED"


@dataclass(frozen=True, slots=True)
class AlphaMiningCandidateRecord:
    candidate_record_id: str
    candidate_id: str
    source_lineage_ref: str
    generation_index: int
    candidate_ordinal: int
    disposition: AlphaMiningCandidateDisposition
    reason_code: str
    factor_definition_version_id: str | None
    duplicate_of_factor_definition_version_id: str | None
    factor_evaluation_id: str | None
    alpha_mining_reward_id: str | None

    @classmethod
    def create(cls, **values: object) -> AlphaMiningCandidateRecord:
        disposition = values.get("disposition")
        if not isinstance(disposition, AlphaMiningCandidateDisposition):
            raise AlphaMiningContractError("INVALID_CANDIDATE_RECORD", "closed disposition required")
        payload = {
            "candidate_id": _text(values.get("candidate_id"), "candidate_id"),
            "source_lineage_ref": _text(
                values.get("source_lineage_ref"), "source_lineage_ref"
            ),
            "generation_index": _positive(values.get("generation_index"), "generation_index"),
            "candidate_ordinal": _positive(values.get("candidate_ordinal"), "candidate_ordinal"),
            "disposition": disposition.value,
            "reason_code": _text(values.get("reason_code"), "reason_code"),
            "factor_definition_version_id": values.get("factor_definition_version_id"),
            "duplicate_of_factor_definition_version_id": values.get(
                "duplicate_of_factor_definition_version_id"
            ),
            "factor_evaluation_id": values.get("factor_evaluation_id"),
            "alpha_mining_reward_id": values.get("alpha_mining_reward_id"),
        }
        if disposition is AlphaMiningCandidateDisposition.EVALUATED and (
            payload["factor_definition_version_id"] is None
            or payload["factor_evaluation_id"] is None
            or payload["alpha_mining_reward_id"] is None
        ):
            raise AlphaMiningContractError(
                "INVALID_CANDIDATE_RECORD", "evaluated record requires exact evidence"
            )
        return cls("amcr_sha256_" + canonical_sha256(payload), disposition=disposition, **{
            key: value for key, value in payload.items() if key != "disposition"
        })


class AlphaMiningRunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"


class AlphaMiningStopReason(StrEnum):
    TARGET_EVALUATED_CANDIDATES_REACHED = "TARGET_EVALUATED_CANDIDATES_REACHED"
    CANDIDATE_BUDGET_EXHAUSTED = "CANDIDATE_BUDGET_EXHAUSTED"
    EVALUATION_BUDGET_EXHAUSTED = "EVALUATION_BUDGET_EXHAUSTED"
    GENERATION_BUDGET_EXHAUSTED = "GENERATION_BUDGET_EXHAUSTED"
    BLOCKING_REVIEWER_FINDING = "BLOCKING_REVIEWER_FINDING"


@dataclass(frozen=True, slots=True)
class AlphaMiningRunRecord:
    alpha_mining_run_id: str
    alpha_mining_job_spec_id: str
    status: AlphaMiningRunStatus
    stop_reason: AlphaMiningStopReason
    candidate_records: tuple[AlphaMiningCandidateRecord, ...]
    generated_count: int
    canonicalized_count: int
    deduplicated_count: int
    evaluated_count: int
    rejected_count: int
    elapsed_seconds: str
    resource_observation: str
    factor_asset_lifecycle_transition: str = "NOT_RUN"

    @classmethod
    def create(cls, **values: object) -> AlphaMiningRunRecord:
        records = values.get("candidate_records")
        if not isinstance(records, tuple) or any(
            not isinstance(value, AlphaMiningCandidateRecord) for value in records
        ):
            raise AlphaMiningContractError("INVALID_MINING_RUN", "typed candidate records required")
        status = values.get("status")
        reason = values.get("stop_reason")
        if not isinstance(status, AlphaMiningRunStatus) or not isinstance(
            reason, AlphaMiningStopReason
        ):
            raise AlphaMiningContractError("INVALID_MINING_RUN", "closed terminal state required")
        counts = {
            name: _non_negative(values.get(name), name)
            for name in (
                "generated_count",
                "canonicalized_count",
                "deduplicated_count",
                "evaluated_count",
                "rejected_count",
            )
        }
        if counts["generated_count"] != len(records):
            raise AlphaMiningContractError("INVALID_MINING_RUN", "generated count mismatch")
        elapsed = _decimal_text(values.get("elapsed_seconds", "0"), "elapsed_seconds")  # type: ignore[arg-type]
        payload = {
            "alpha_mining_job_spec_id": _text(
                values.get("alpha_mining_job_spec_id"), "alpha_mining_job_spec_id"
            ),
            "status": status.value,
            "stop_reason": reason.value,
            "candidate_record_ids": [value.candidate_record_id for value in records],
            **counts,
            "elapsed_seconds": elapsed,
            "resource_observation": _text(
                values.get("resource_observation"), "resource_observation"
            ),
            "factor_asset_lifecycle_transition": "NOT_RUN",
        }
        return cls(
            "amrun_sha256_" + canonical_sha256(payload),
            payload["alpha_mining_job_spec_id"],
            status,
            reason,
            records,
            counts["generated_count"],
            counts["canonicalized_count"],
            counts["deduplicated_count"],
            counts["evaluated_count"],
            counts["rejected_count"],
            elapsed,
            payload["resource_observation"],
        )


@dataclass(frozen=True, slots=True)
class AlphaMiningJobDraft:
    alpha_mining_job_draft_id: str
    proposed_job_spec_id: str
    rationale: str
    authority_status: str = "NON_CANONICAL"
    lifecycle_state: str = "DRAFT"
    started: bool = False

    @classmethod
    def create(
        cls, *, proposed_job_spec_id: str, rationale: str
    ) -> AlphaMiningJobDraft:
        payload = {
            "proposed_job_spec_id": _text(proposed_job_spec_id, "proposed_job_spec_id"),
            "rationale": _text(rationale, "rationale"),
            "authority_status": "NON_CANONICAL",
            "lifecycle_state": "DRAFT",
            "started": False,
        }
        return cls(
            "amjd_sha256_" + canonical_sha256(payload),
            proposed_job_spec_id,
            rationale,
        )


__all__ = [
    "AlphaMiningCandidateDisposition",
    "AlphaMiningCandidateProposal",
    "AlphaMiningCandidateRecord",
    "AlphaMiningContractError",
    "AlphaMiningEvaluationContext",
    "AlphaMiningEvaluationEvidence",
    "AlphaMiningJobDraft",
    "AlphaMiningJobSpec",
    "AlphaMiningReward",
    "AlphaMiningRewardPolicyVersion",
    "AlphaMiningRewardStatus",
    "AlphaMiningRunRecord",
    "AlphaMiningRunStatus",
    "AlphaMiningSearchSpaceVersion",
    "AlphaMiningSourceField",
    "AlphaMiningStopReason",
    "AlphaMiningStoppingRules",
    "AlphaResearchFactorEvaluation",
    "MissingRewardComponentPolicy",
    "RewardComponentName",
    "RewardComponentResult",
    "RewardComponentRule",
    "RewardComponentStatus",
]
