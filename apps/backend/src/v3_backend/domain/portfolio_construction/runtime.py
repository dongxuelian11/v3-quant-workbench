from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_FLOOR, localcontext

from v3_backend.domain.strategies import (
    PortfolioIntent,
    StrategyDefinitionVersion,
    StrategyEvaluationBindingVersion,
)
from v3_backend.domain.weights import (
    PortfolioIntentSource,
    RuntimeIdentity,
    TargetWeightRow,
    TargetWeightVector,
)

from .model import (
    ConstructionMethod,
    ConstructionRejectionReason,
    ConstraintCheck,
    ConstraintCheckStatus,
    IntentConstraintNormalization,
    OptimizerCandidate,
    PortfolioConstructionDiagnostics,
    PortfolioConstructionProvenance,
    PortfolioConstructionRejected,
    PortfolioConstructionResult,
    PortfolioConstructionSpecVersion,
)


def _reject(reason: ConstructionRejectionReason, detail: str) -> None:
    raise PortfolioConstructionRejected(reason, detail)


def _wire_decimal(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _largest_remainder_weights(
    raw_by_instrument: tuple[tuple[str, Decimal], ...],
    budget: Decimal,
    decimal_places: int,
) -> tuple[tuple[TargetWeightRow, ...], Decimal]:
    quantum = Decimal(1).scaleb(-decimal_places)
    floored: dict[str, Decimal] = {}
    fractions: list[tuple[Decimal, str]] = []
    for instrument_id, raw_weight in raw_by_instrument:
        base = raw_weight.quantize(quantum, rounding=ROUND_FLOOR)
        floored[instrument_id] = base
        fractions.append((raw_weight - base, instrument_id))
    residual = budget - sum(floored.values(), Decimal(0))
    units = int((residual / quantum).to_integral_exact())
    if units < 0 or units > len(floored):
        _reject(
            ConstructionRejectionReason.INVALID_DESIRED_EXPOSURE,
            "rounding residual is outside the deterministic largest-remainder bound",
        )
    for _, instrument_id in sorted(fractions, key=lambda value: (-value[0], value[1]))[:units]:
        floored[instrument_id] += quantum
    rows = tuple(
        TargetWeightRow(instrument_id, _wire_decimal(weight))
        for instrument_id, weight in sorted(floored.items())
        if not weight.is_zero()
    )
    return rows, residual


class DeterministicPortfolioConstruction:
    runtime_version = "v3.portfolio-construction-runtime/1.0.0"

    def construct(
        self,
        *,
        intent: PortfolioIntent,
        definition: StrategyDefinitionVersion,
        binding: StrategyEvaluationBindingVersion,
        construction_spec: PortfolioConstructionSpecVersion,
        runtime_identity: RuntimeIdentity,
        base_currency: str,
        as_of: datetime,
        decision_time: datetime,
        rebalance_time: datetime,
        valid_until: datetime,
        optimizer_candidate: OptimizerCandidate | None = None,
    ) -> PortfolioConstructionResult:
        if not isinstance(intent, PortfolioIntent):
            _reject(
                ConstructionRejectionReason.INVALID_PORTFOLIO_INTENT,
                "the actual canonical PortfolioIntent object is required",
            )
        try:
            source = PortfolioIntentSource.create(
                intent=intent,
                definition=definition,
                binding=binding,
            )
        except (TypeError, ValueError) as error:
            _reject(
                ConstructionRejectionReason.INVALID_PORTFOLIO_INTENT,
                str(error),
            )
        if not isinstance(construction_spec, PortfolioConstructionSpecVersion):
            raise TypeError("construction_spec must be PortfolioConstructionSpecVersion")
        construction_spec.assert_canonical()
        if runtime_identity != construction_spec.runtime_identity:
            _reject(
                ConstructionRejectionReason.SPEC_RUNTIME_MISMATCH,
                "runtime identity must exactly match the construction spec",
            )
        if optimizer_candidate is not None:
            _reject(
                ConstructionRejectionReason.OPTIMIZER_NOT_CONFIGURED,
                "V0 deterministic baselines do not admit an external optimizer candidate",
            )
        if intent.exposure_mode != construction_spec.accepted_intent_exposure_mode.value:
            _reject(
                ConstructionRejectionReason.EXPOSURE_MODE_MISMATCH,
                "PortfolioIntent exposure mode does not match the pinned construction spec",
            )
        if intent.cash_policy != construction_spec.accepted_intent_cash_policy.value:
            _reject(
                ConstructionRejectionReason.CASH_POLICY_MISMATCH,
                "PortfolioIntent cash policy does not match the pinned construction spec",
            )
        if (
            intent.rebalance_intent
            != construction_spec.accepted_intent_rebalance_intent.value
        ):
            _reject(
                ConstructionRejectionReason.REBALANCE_INTENT_MISMATCH,
                "PortfolioIntent rebalance intent does not match the pinned construction spec",
            )
        supported_constraint_keys = {
            "proposal_only",
            "normalization",
            "portfolio_service_required",
        }
        constraint_keys = set(intent.constraints)
        if constraint_keys != supported_constraint_keys:
            unknown = sorted(str(value) for value in constraint_keys - supported_constraint_keys)
            missing = sorted(supported_constraint_keys - constraint_keys)
            _reject(
                ConstructionRejectionReason.UNSUPPORTED_INTENT_CONSTRAINT,
                f"PortfolioIntent constraint keys must be exact; unknown={unknown}, missing={missing}",
            )
        if intent.constraints["proposal_only"] is not True:
            _reject(
                ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
                "PortfolioIntent proposal_only must be exactly true",
            )
        if intent.constraints["portfolio_service_required"] is not True:
            _reject(
                ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
                "PortfolioIntent portfolio_service_required must be exactly true",
            )
        if (
            intent.constraints["normalization"]
            != construction_spec.accepted_intent_constraint_normalization.value
        ):
            _reject(
                ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
                "PortfolioIntent normalization marker does not match the closed method policy",
            )

        for name, value in (
            ("as_of", as_of),
            ("decision_time", decision_time),
            ("rebalance_time", rebalance_time),
            ("valid_until", valid_until),
        ):
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                _reject(
                    ConstructionRejectionReason.INVALID_TARGET_TIMING,
                    f"{name} must be timezone-aware",
                )
        if not binding.period.start <= as_of <= binding.period.end:
            _reject(
                ConstructionRejectionReason.AS_OF_OUTSIDE_BINDING_PERIOD,
                "as_of must be inside the exact StrategyEvaluationBinding period",
            )
        if not binding.period.start <= decision_time <= binding.period.end:
            _reject(
                ConstructionRejectionReason.DECISION_TIME_OUTSIDE_BINDING_PERIOD,
                "decision_time must be inside the exact StrategyEvaluationBinding period",
            )
        if as_of > binding.knowledge_cutoff:
            _reject(
                ConstructionRejectionReason.AS_OF_AFTER_KNOWLEDGE_CUTOFF,
                "as_of must not exceed the exact StrategyEvaluationBinding knowledge cutoff",
            )
        if decision_time > binding.knowledge_cutoff:
            _reject(
                ConstructionRejectionReason.DECISION_TIME_AFTER_KNOWLEDGE_CUTOFF,
                "decision_time must not exceed the exact StrategyEvaluationBinding knowledge cutoff",
            )
        if not as_of <= decision_time <= rebalance_time <= valid_until:
            _reject(
                ConstructionRejectionReason.INVALID_TARGET_TIMING,
                "target timing must satisfy as_of <= decision_time <= rebalance_time <= valid_until",
            )

        item_ids = tuple(value.instrument_id for value in intent.items)
        if len(item_ids) != len(set(item_ids)):
            _reject(
                ConstructionRejectionReason.DUPLICATE_INSTRUMENT,
                "PortfolioIntent instruments must be unique",
            )
        if not set(item_ids).issubset(source.universe_instrument_ids):
            _reject(
                ConstructionRejectionReason.OUTSIDE_EXACT_UNIVERSE,
                "PortfolioIntent instrument is outside the exact bound universe",
            )
        desired: list[tuple[str, Decimal]] = []
        for item in intent.items:
            try:
                value = Decimal(item.desired_exposure)
            except Exception as error:
                raise PortfolioConstructionRejected(
                    ConstructionRejectionReason.INVALID_DESIRED_EXPOSURE,
                    f"{item.instrument_id} desired exposure is not a decimal",
                ) from error
            if not value.is_finite() or value < 0:
                _reject(
                    ConstructionRejectionReason.INVALID_DESIRED_EXPOSURE,
                    f"{item.instrument_id} desired exposure must be finite and non-negative",
                )
            desired.append((item.instrument_id, value))
        desired_tuple = tuple(sorted(desired))
        if (
            construction_spec.accepted_intent_constraint_normalization
            is IntentConstraintNormalization.EQUAL_DESIRED_EXPOSURE
            and desired_tuple
            and len({value for _, value in desired_tuple}) != 1
        ):
            _reject(
                ConstructionRejectionReason.DESIRED_EXPOSURE_SEMANTICS_MISMATCH,
                "EQUAL_DESIRED_EXPOSURE requires equal item desired exposures",
            )
        cash = Decimal(construction_spec.target_cash_weight)
        budget = Decimal(1) - cash
        if not desired_tuple:
            if not budget.is_zero():
                _reject(
                    ConstructionRejectionReason.EMPTY_SELECTION_INFEASIBLE,
                    "empty selection requires a pinned all-cash construction spec",
                )
            rows: tuple[TargetWeightRow, ...] = ()
            normalization_total = Decimal(0)
            residual = Decimal(0)
        else:
            with localcontext() as context:
                context.prec = 64
                if construction_spec.method is ConstructionMethod.EQUAL_WEIGHT_SELECTED:
                    normalization_total = Decimal(len(desired_tuple))
                    raw = tuple(
                        (instrument_id, budget / normalization_total)
                        for instrument_id, _ in desired_tuple
                    )
                else:
                    normalization_total = sum(
                        (value for _, value in desired_tuple), Decimal(0)
                    )
                    if normalization_total.is_zero():
                        _reject(
                            ConstructionRejectionReason.ZERO_DESIRED_EXPOSURE_TOTAL,
                            "NORMALIZED_DESIRED_EXPOSURE requires a positive exposure total",
                        )
                    raw = tuple(
                        (instrument_id, budget * value / normalization_total)
                        for instrument_id, value in desired_tuple
                    )
                rows, residual = _largest_remainder_weights(
                    raw,
                    budget,
                    construction_spec.decimal_places,
                )

        weights = tuple(Decimal(value.target_weight) for value in rows)
        minimum = Decimal(construction_spec.min_instrument_weight)
        maximum = Decimal(construction_spec.max_instrument_weight)
        if any(weight < minimum or weight > maximum for weight in weights):
            _reject(
                ConstructionRejectionReason.INSTRUMENT_WEIGHT_BOUND,
                "constructed weight violates the pinned instrument bound",
            )
        gross = sum(weights, Decimal(0))
        net = gross
        if gross > Decimal(construction_spec.max_gross_exposure):
            _reject(
                ConstructionRejectionReason.GROSS_EXPOSURE_BOUND,
                "constructed gross exposure exceeds the pinned maximum",
            )
        if net > Decimal(construction_spec.max_net_exposure):
            _reject(
                ConstructionRejectionReason.NET_EXPOSURE_BOUND,
                "constructed net exposure exceeds the pinned maximum",
            )
        checks = (
            ConstraintCheck(
                "PORTFOLIO_INTENT_SEMANTIC_ADMISSION",
                ConstraintCheckStatus.PASSED,
                (
                    intent.exposure_mode
                    + "/"
                    + intent.cash_policy
                    + "/"
                    + intent.rebalance_intent
                ),
                "CLOSED_METHOD_DERIVED_POLICY_V1",
            ),
            ConstraintCheck(
                "TARGET_TIMING_BINDING",
                ConstraintCheckStatus.PASSED,
                "PERIOD_AND_KNOWLEDGE_CUTOFF_VALIDATED",
                "EXACT_STRATEGY_EVALUATION_BINDING",
            ),
            ConstraintCheck(
                "EXACT_UNIVERSE_SCOPE",
                ConstraintCheckStatus.PASSED,
                str(len(item_ids)),
                str(len(source.universe_instrument_ids)),
            ),
            ConstraintCheck(
                "LONG_ONLY",
                ConstraintCheckStatus.PASSED,
                "minimum=" + (_wire_decimal(min(weights)) if weights else "NOT_APPLICABLE"),
                ">=" + construction_spec.min_instrument_weight,
            ),
            ConstraintCheck(
                "MAX_INSTRUMENT_WEIGHT",
                ConstraintCheckStatus.PASSED,
                "maximum=" + (_wire_decimal(max(weights)) if weights else "NOT_APPLICABLE"),
                "<=" + construction_spec.max_instrument_weight,
            ),
            ConstraintCheck(
                "BUDGET_EQUATION",
                ConstraintCheckStatus.PASSED,
                _wire_decimal(gross + cash),
                "1",
            ),
            ConstraintCheck(
                "GROSS_EXPOSURE",
                ConstraintCheckStatus.PASSED,
                _wire_decimal(gross),
                "<=" + construction_spec.max_gross_exposure,
            ),
            ConstraintCheck(
                "NET_EXPOSURE",
                ConstraintCheckStatus.PASSED,
                _wire_decimal(net),
                "<=" + construction_spec.max_net_exposure,
            ),
        )
        diagnostics = PortfolioConstructionDiagnostics.create(
            selected_count=len(item_ids),
            excluded_count=len(source.universe_instrument_ids) - len(item_ids),
            cash_weight=cash,
            gross_exposure=gross,
            net_exposure=net,
            normalization_input_total=normalization_total,
            rounding_residual_allocated=residual,
            portfolio_intent_id=source.portfolio_intent_id,
            strategy_evaluation_binding_version_id=(
                source.strategy_evaluation_binding_version_id
            ),
            source_reference_sha256=source.source_reference_sha256,
            method=construction_spec.method,
            intent_exposure_mode=construction_spec.accepted_intent_exposure_mode,
            intent_cash_policy=construction_spec.accepted_intent_cash_policy,
            intent_rebalance_intent=(
                construction_spec.accepted_intent_rebalance_intent
            ),
            intent_constraint_normalization=(
                construction_spec.accepted_intent_constraint_normalization
            ),
            desired_exposure_magnitude_policy=(
                construction_spec.desired_exposure_magnitude_policy
            ),
            selection_transform=construction_spec.selection_transform,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            binding_period_start=binding.period.start,
            binding_period_end=binding.period.end,
            binding_knowledge_cutoff=binding.knowledge_cutoff,
            constraint_checks=checks,
        )
        provenance = PortfolioConstructionProvenance.create(
            source_reference_sha256=source.source_reference_sha256,
            construction_spec_version_id=(
                construction_spec.portfolio_construction_spec_version_id
            ),
            diagnostics_id=diagnostics.diagnostics_id,
            rows=rows,
            cash_weight=construction_spec.target_cash_weight,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            binding_period_start=binding.period.start,
            binding_period_end=binding.period.end,
            binding_knowledge_cutoff=binding.knowledge_cutoff,
            rebalance_intent=construction_spec.accepted_intent_rebalance_intent,
            runtime_identity=runtime_identity,
        )
        target = TargetWeightVector.create(
            source=source,
            construction_spec=construction_spec.to_reference(),
            evidence_refs=(diagnostics.to_reference(), provenance.to_reference()),
            runtime_identity=runtime_identity,
            base_currency=base_currency,
            as_of=as_of,
            decision_time=decision_time,
            rebalance_time=rebalance_time,
            valid_until=valid_until,
            cash_weight=construction_spec.target_cash_weight,
            rows=rows,
        )
        return PortfolioConstructionResult(
            target=target,
            diagnostics=diagnostics,
            provenance=provenance,
        )


__all__ = ["DeterministicPortfolioConstruction"]
