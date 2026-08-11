from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from types import MappingProxyType
from typing import Mapping

from .artifacts import (
    InputArtifactEvidence,
    PortfolioIntent,
    PortfolioIntentItem,
    SelectionArtifact,
    SelectionEntry,
    SignalArtifact,
    SignalDirection,
    SignalRow,
)
from .binding import StrategyEvaluationBindingVersion
from .ir import (
    ComponentRegistry,
    StrategyDefinitionVersion,
    default_component_registry,
    normalize_decimal_string,
)


class StrategyEvaluationError(ValueError):
    """Pure deterministic strategy evaluation failure."""


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise StrategyEvaluationError(f"{name} must be numeric or an explicit decimal string")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise StrategyEvaluationError(f"{name} must be finite") from error
    if not decimal.is_finite():
        raise StrategyEvaluationError(f"{name} must be finite")
    return decimal


def _wire_decimal(value: Decimal) -> str:
    return normalize_decimal_string(format(value, "f"), "runtime decimal")


@dataclass(frozen=True, slots=True)
class CrossSectionInputArtifact:
    binding_key: str
    artifact_id: str
    content_sha256: str
    decision_time: datetime
    values: Mapping[str, object | None]

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise StrategyEvaluationError("input decision_time must be timezone-aware")
        normalized: dict[str, str | None] = {}
        for instrument_id, value in self.values.items():
            if not isinstance(instrument_id, str) or not instrument_id.strip():
                raise StrategyEvaluationError("input instrument IDs must be non-empty")
            normalized[instrument_id] = None if value is None else _wire_decimal(
                _decimal(value, f"input value for {instrument_id}")
            )
        object.__setattr__(self, "values", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class _ScoreMap:
    values: Mapping[str, str | None]
    paths: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _EligibilityMap:
    values: Mapping[str, bool]
    paths: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class _RankedValue:
    instrument_id: str
    score: str
    rank: int
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SelectionPayload:
    selected: tuple[_RankedValue, ...]
    excluded: tuple[str, ...]
    output_node_id: str


@dataclass(frozen=True, slots=True)
class _SignalPayload:
    scores: _ScoreMap
    signal_kind: str
    output_node_id: str


@dataclass(frozen=True, slots=True)
class _IntentPayload:
    selection: _SelectionPayload
    scores: _ScoreMap
    exposure_mode: str
    cash_policy: str
    rebalance_intent: str
    gross_exposure: str
    output_node_id: str


@dataclass(frozen=True, slots=True)
class StrategyEvaluationResult:
    signal_artifact: SignalArtifact | None
    selection_artifact: SelectionArtifact | None
    portfolio_intent: PortfolioIntent | None

    def to_wire(self) -> dict[str, object | None]:
        return {
            "signal_artifact": (
                None if self.signal_artifact is None else self.signal_artifact.to_wire()
            ),
            "selection_artifact": (
                None
                if self.selection_artifact is None
                else self.selection_artifact.to_wire()
            ),
            "portfolio_intent": (
                None if self.portfolio_intent is None else self.portfolio_intent.to_wire()
            ),
        }


class DeterministicStrategyEvaluator:
    runtime_profile_id = "v3-strategy-deterministic-batch/1.0.0"

    def __init__(self, registry: ComponentRegistry | None = None) -> None:
        self._registry = registry or default_component_registry()

    def evaluate(
        self,
        *,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        inputs: tuple[CrossSectionInputArtifact, ...],
    ) -> StrategyEvaluationResult:
        if definition.component_registry_version != self._registry.registry_version:
            raise StrategyEvaluationError("definition/component registry version mismatch")
        if definition.runtime_profile_id != self.runtime_profile_id:
            raise StrategyEvaluationError("definition/runtime profile mismatch")
        if binding.runtime_profile_id != self.runtime_profile_id:
            raise StrategyEvaluationError("binding/runtime profile mismatch")
        if binding.strategy_definition_version_id != definition.strategy_definition_version_id:
            raise StrategyEvaluationError("binding does not reference the exact definition")

        input_by_key = {value.binding_key: value for value in inputs}
        if len(input_by_key) != len(inputs):
            raise StrategyEvaluationError("runtime input binding keys must be unique")
        bound_by_key = {value.binding_key: value for value in binding.input_references}
        if set(input_by_key) != set(bound_by_key):
            raise StrategyEvaluationError("runtime inputs must exactly match evaluation binding")
        universe = binding.universe.instrument_ids
        universe_set = set(universe)
        decision_times = set()
        input_evidence: list[InputArtifactEvidence] = []
        canonical_inputs: dict[str, CrossSectionInputArtifact] = {}
        for binding_key in sorted(input_by_key):
            value = input_by_key[binding_key]
            expected = bound_by_key[binding_key]
            if (
                value.artifact_id != expected.artifact_id
                or value.content_sha256 != expected.content_sha256
            ):
                raise StrategyEvaluationError(
                    f"runtime input {binding_key} does not match exact artifact binding"
                )
            extra = set(value.values) - universe_set
            if extra:
                raise StrategyEvaluationError(
                    f"runtime input {binding_key} contains out-of-universe instruments"
                )
            decision_times.add(value.decision_time)
            normalized = {
                instrument_id: value.values.get(instrument_id) for instrument_id in universe
            }
            canonical_inputs[binding_key] = CrossSectionInputArtifact(
                binding_key=value.binding_key,
                artifact_id=value.artifact_id,
                content_sha256=value.content_sha256,
                decision_time=value.decision_time,
                values=normalized,
            )
            input_evidence.append(
                InputArtifactEvidence(
                    binding_key=binding_key,
                    artifact_id=value.artifact_id,
                    content_sha256=value.content_sha256,
                )
            )
        if len(decision_times) != 1:
            raise StrategyEvaluationError("all exact inputs must share one decision_time")
        decision_time = next(iter(decision_times))
        if not binding.period.start <= decision_time <= binding.period.end:
            raise StrategyEvaluationError("decision_time is outside bound evaluation period")
        if decision_time > binding.knowledge_cutoff:
            raise StrategyEvaluationError("decision_time exceeds bound knowledge cutoff")

        canonical_nodes = {
            value["node_id"]: value
            for value in definition.canonical_ir["nodes"]  # type: ignore[index]
        }
        observed: dict[str, dict[str, object]] = {}
        for node_id in definition.topological_order:
            node = canonical_nodes[node_id]
            component_key = f"{node['component_type']}@{node['component_version']}"
            parameters = node["parameters"]
            resolved_inputs: dict[str, object] = {}
            for input_name, reference in node["inputs"].items():  # type: ignore[union-attr]
                if reference["kind"] == "BINDING":
                    resolved_inputs[input_name] = canonical_inputs[reference["binding_key"]]
                else:
                    resolved_inputs[input_name] = observed[reference["node_id"]][
                        reference["port"]
                    ]
            observed[node_id] = self._execute_component(
                component_key=component_key,
                node_id=node_id,
                parameters=parameters,  # type: ignore[arg-type]
                inputs=resolved_inputs,
                universe=universe,
            )

        outputs = definition.canonical_ir["outputs"]  # type: ignore[index]

        def resolved_output(name: str) -> object | None:
            if name not in outputs:
                return None
            reference = outputs[name]
            return observed[reference["node_id"]][reference["port"]]

        signal_payload = resolved_output("signal")
        selection_payload = resolved_output("selection")
        intent_payload = resolved_output("portfolio_intent")
        evidence = tuple(input_evidence)

        signal_artifact: SignalArtifact | None = None
        if signal_payload is not None:
            if not isinstance(signal_payload, _SignalPayload):
                raise StrategyEvaluationError("signal output did not produce SignalArtifact payload")
            rows: list[SignalRow] = []
            missing: list[str] = []
            for instrument_id in universe:
                score = signal_payload.scores.values[instrument_id]
                if score is None:
                    missing.append(instrument_id)
                    continue
                decimal = Decimal(score)
                direction = (
                    SignalDirection.POSITIVE
                    if decimal > 0
                    else SignalDirection.NEGATIVE
                    if decimal < 0
                    else SignalDirection.NEUTRAL
                )
                rows.append(
                    SignalRow(
                        instrument_id=instrument_id,
                        decision_time=decision_time,
                        signal_kind=signal_payload.signal_kind,
                        value=score,
                        direction=direction,
                        source_node_path=(
                            *signal_payload.scores.paths[instrument_id],
                            signal_payload.output_node_id,
                        ),
                    )
                )
            signal_artifact = SignalArtifact.create(
                definition=definition,
                binding=binding,
                input_artifacts=evidence,
                decision_time=decision_time,
                rows=tuple(rows),
                missing_instrument_ids=tuple(missing),
            )

        selection_artifact: SelectionArtifact | None = None
        if selection_payload is not None:
            if not isinstance(selection_payload, _SelectionPayload):
                raise StrategyEvaluationError(
                    "selection output did not produce SelectionArtifact payload"
                )
            selection_artifact = SelectionArtifact.create(
                definition=definition,
                binding=binding,
                entries=tuple(
                    SelectionEntry(
                        instrument_id=value.instrument_id,
                        rank=value.rank,
                        score=value.score,
                        reason="STABLE_TOP_N_AFTER_EXPLICIT_GATE",
                        source_node_path=(*value.path, selection_payload.output_node_id),
                    )
                    for value in selection_payload.selected
                ),
                excluded_instrument_ids=selection_payload.excluded,
                input_artifacts=evidence,
            )

        portfolio_intent: PortfolioIntent | None = None
        if intent_payload is not None:
            if not isinstance(intent_payload, _IntentPayload):
                raise StrategyEvaluationError(
                    "portfolio intent output did not produce PortfolioIntent payload"
                )
            if selection_artifact is None:
                raise StrategyEvaluationError(
                    "PortfolioIntent requires an explicitly published SelectionArtifact"
                )
            gross = Decimal(intent_payload.gross_exposure)
            if gross < 0:
                raise StrategyEvaluationError("gross_exposure cannot be negative")
            count = len(intent_payload.selection.selected)
            exposures: tuple[Decimal, ...]
            if count == 0:
                exposures = ()
            else:
                with localcontext() as context:
                    context.prec = 34
                    context.rounding = ROUND_HALF_EVEN
                    equal = gross / Decimal(count)
                    exposures = (equal,) * (count - 1) + (
                        gross - equal * Decimal(count - 1),
                    )
            portfolio_intent = PortfolioIntent.create(
                definition=definition,
                binding=binding,
                source_signal_artifact_id=(
                    None if signal_artifact is None else signal_artifact.signal_artifact_id
                ),
                source_selection_artifact_id=selection_artifact.selection_artifact_id,
                exposure_mode=intent_payload.exposure_mode,
                cash_policy=intent_payload.cash_policy,
                rebalance_intent=intent_payload.rebalance_intent,
                items=tuple(
                    PortfolioIntentItem(
                        instrument_id=value.instrument_id,
                        desired_exposure=_wire_decimal(exposure),
                        source_score=value.score,
                        source_node_path=(
                            *value.path,
                            intent_payload.output_node_id,
                        ),
                    )
                    for value, exposure in zip(
                        intent_payload.selection.selected, exposures, strict=True
                    )
                ),
                constraints={
                    "proposal_only": True,
                    "normalization": "EQUAL_DESIRED_EXPOSURE",
                    "portfolio_service_required": True,
                },
                input_artifacts=evidence,
            )
        return StrategyEvaluationResult(
            signal_artifact=signal_artifact,
            selection_artifact=selection_artifact,
            portfolio_intent=portfolio_intent,
        )

    @staticmethod
    def _execute_component(
        *,
        component_key: str,
        node_id: str,
        parameters: Mapping[str, object],
        inputs: Mapping[str, object],
        universe: tuple[str, ...],
    ) -> dict[str, object]:
        if component_key == "v3.strategy.input.bound_scores@1.0.0":
            artifact = inputs["artifact"]
            if not isinstance(artifact, CrossSectionInputArtifact):
                raise StrategyEvaluationError("bound score input has the wrong runtime type")
            return {
                "scores": _ScoreMap(
                    values=artifact.values,  # type: ignore[arg-type]
                    paths=MappingProxyType(
                        {instrument_id: (node_id,) for instrument_id in universe}
                    ),
                )
            }
        if component_key == "v3.strategy.condition.minimum@1.0.0":
            scores = inputs["scores"]
            if not isinstance(scores, _ScoreMap):
                raise StrategyEvaluationError("minimum condition requires score map")
            threshold = Decimal(parameters["threshold"])  # type: ignore[arg-type]
            inclusive = parameters["inclusive"]
            values = {
                instrument_id: (
                    False
                    if scores.values[instrument_id] is None
                    else Decimal(scores.values[instrument_id]) >= threshold
                    if inclusive
                    else Decimal(scores.values[instrument_id]) > threshold
                )
                for instrument_id in universe
            }
            return {
                "eligible": _EligibilityMap(
                    values=MappingProxyType(values),
                    paths=MappingProxyType(
                        {
                            instrument_id: (*scores.paths[instrument_id], node_id)
                            for instrument_id in universe
                        }
                    ),
                )
            }
        if component_key == "v3.strategy.combine.priority@1.0.0":
            primary = inputs["primary"]
            fallback = inputs["fallback"]
            if not isinstance(primary, _ScoreMap) or not isinstance(fallback, _ScoreMap):
                raise StrategyEvaluationError("priority combine requires two score maps")
            values: dict[str, str | None] = {}
            paths: dict[str, tuple[str, ...]] = {}
            for instrument_id in universe:
                if primary.values[instrument_id] is not None:
                    values[instrument_id] = primary.values[instrument_id]
                    paths[instrument_id] = (*primary.paths[instrument_id], node_id)
                else:
                    values[instrument_id] = fallback.values[instrument_id]
                    paths[instrument_id] = (*fallback.paths[instrument_id], node_id)
            return {
                "scores": _ScoreMap(
                    values=MappingProxyType(values), paths=MappingProxyType(paths)
                )
            }
        if component_key == "v3.strategy.rank.score@1.0.0":
            scores = inputs["scores"]
            eligible = inputs["eligible"]
            if not isinstance(scores, _ScoreMap) or not isinstance(
                eligible, _EligibilityMap
            ):
                raise StrategyEvaluationError("rank requires scores and eligibility")
            ranked = [
                (instrument_id, Decimal(scores.values[instrument_id]))
                for instrument_id in universe
                if eligible.values[instrument_id]
                and scores.values[instrument_id] is not None
            ]
            descending = parameters["descending"]
            ranked.sort(
                key=lambda item: (
                    -item[1] if descending else item[1],
                    item[0],
                )
            )
            return {
                "ranked": tuple(
                    _RankedValue(
                        instrument_id=instrument_id,
                        score=_wire_decimal(score),
                        rank=index,
                        path=(
                            *scores.paths[instrument_id],
                            *eligible.paths[instrument_id],
                            node_id,
                        ),
                    )
                    for index, (instrument_id, score) in enumerate(ranked, start=1)
                )
            }
        if component_key == "v3.strategy.select.top_n@1.0.0":
            ranked = inputs["ranked"]
            if not isinstance(ranked, tuple) or any(
                not isinstance(value, _RankedValue) for value in ranked
            ):
                raise StrategyEvaluationError("top_n requires ranked instruments")
            selected = tuple(
                _RankedValue(
                    instrument_id=value.instrument_id,
                    score=value.score,
                    rank=value.rank,
                    path=(*value.path, node_id),
                )
                for value in ranked[: parameters["count"]]  # type: ignore[index]
            )
            selected_ids = {value.instrument_id for value in selected}
            return {
                "selection": _SelectionPayload(
                    selected=selected,
                    excluded=tuple(
                        instrument_id
                        for instrument_id in universe
                        if instrument_id not in selected_ids
                    ),
                    output_node_id=node_id,
                )
            }
        if component_key == "v3.strategy.output.signal@1.0.0":
            scores = inputs["scores"]
            if not isinstance(scores, _ScoreMap):
                raise StrategyEvaluationError("signal output requires score map")
            return {
                "artifact": _SignalPayload(
                    scores=scores,
                    signal_kind=parameters["signal_kind"],  # type: ignore[arg-type]
                    output_node_id=node_id,
                )
            }
        if component_key == "v3.strategy.output.selection@1.0.0":
            selection = inputs["selection"]
            if not isinstance(selection, _SelectionPayload):
                raise StrategyEvaluationError("selection output requires selection")
            return {
                "artifact": _SelectionPayload(
                    selected=selection.selected,
                    excluded=selection.excluded,
                    output_node_id=node_id,
                )
            }
        if component_key == "v3.strategy.output.portfolio_intent@1.0.0":
            scores = inputs["scores"]
            selection = inputs["selection"]
            if not isinstance(scores, _ScoreMap) or not isinstance(
                selection, _SelectionPayload
            ):
                raise StrategyEvaluationError(
                    "portfolio intent requires scores and selection"
                )
            return {
                "artifact": _IntentPayload(
                    selection=selection,
                    scores=scores,
                    exposure_mode=parameters["exposure_mode"],  # type: ignore[arg-type]
                    cash_policy=parameters["cash_policy"],  # type: ignore[arg-type]
                    rebalance_intent=parameters["rebalance_intent"],  # type: ignore[arg-type]
                    gross_exposure=parameters["gross_exposure"],  # type: ignore[arg-type]
                    output_node_id=node_id,
                )
            }
        raise StrategyEvaluationError(f"unsupported closed component runtime: {component_key}")


__all__ = [
    "CrossSectionInputArtifact",
    "DeterministicStrategyEvaluator",
    "StrategyEvaluationError",
    "StrategyEvaluationResult",
]
