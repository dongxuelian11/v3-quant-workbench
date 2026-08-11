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
        if intent.exposure_mode != construction_spec.accepted_intent_exposure_mode:
            _reject(
                ConstructionRejectionReason.EXPOSURE_MODE_MISMATCH,
                "PortfolioIntent exposure mode does not match the pinned construction spec",
            )
        if intent.cash_policy != construction_spec.accepted_intent_cash_policy:
            _reject(
                ConstructionRejectionReason.CASH_POLICY_MISMATCH,
                "PortfolioIntent cash policy does not match the pinned construction spec",
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
