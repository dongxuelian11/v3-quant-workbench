from __future__ import annotations

import math
from dataclasses import dataclass


class QuantitativeMetricError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FactorSample:
    sample_id: str
    factor_value: float | None
    forward_return: float | None

    def __post_init__(self) -> None:
        if not self.sample_id or self.sample_id != self.sample_id.strip():
            raise QuantitativeMetricError("sample_id is required")
        for name in ("factor_value", "forward_return"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise QuantitativeMetricError(f"{name} must be numeric or None")
            if not math.isfinite(float(value)):
                raise QuantitativeMetricError(
                    f"{name} must be finite; missing values use explicit None"
                )


@dataclass(frozen=True, slots=True)
class RewardMetrics:
    coverage: float
    ic: float
    rank_ic: float
    lower_quantile_return: float
    upper_quantile_return: float
    quantile_spread: float
    turnover: float
    complexity: int


def _mean(values: tuple[float, ...]) -> float:
    return math.fsum(values) / len(values)


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise QuantitativeMetricError("correlation requires at least two paired samples")
    left_mean = _mean(left)
    right_mean = _mean(right)
    numerator = math.fsum(
        (lhs - left_mean) * (rhs - right_mean)
        for lhs, rhs in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(math.fsum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(math.fsum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        raise QuantitativeMetricError("correlation is undefined for constant inputs")
    return numerator / (left_scale * right_scale)


def _average_ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return tuple(ranks)


def compute_reward_metrics(
    samples: tuple[FactorSample, ...],
    *,
    previous_top_sample_ids: tuple[str, ...],
    quantiles: int,
    complexity: int,
) -> RewardMetrics:
    if not samples:
        raise QuantitativeMetricError("factor evaluation requires samples")
    if quantiles < 2:
        raise QuantitativeMetricError("quantiles must be at least two")
    if not isinstance(complexity, int) or isinstance(complexity, bool) or complexity < 1:
        raise QuantitativeMetricError("complexity must be a positive integer")
    sample_ids = tuple(sample.sample_id for sample in samples)
    if len(sample_ids) != len(set(sample_ids)):
        raise QuantitativeMetricError("sample_id values must be unique")
    valid = tuple(
        sample
        for sample in samples
        if sample.factor_value is not None and sample.forward_return is not None
    )
    if len(valid) < max(2, quantiles):
        raise QuantitativeMetricError("insufficient valid samples for requested quantiles")
    factor_values = tuple(float(sample.factor_value) for sample in valid)
    returns = tuple(float(sample.forward_return) for sample in valid)
    coverage = len(valid) / len(samples)
    ic = _correlation(factor_values, returns)
    rank_ic = _correlation(_average_ranks(factor_values), _average_ranks(returns))

    ordered = tuple(
        sorted(valid, key=lambda sample: (float(sample.factor_value), sample.sample_id))
    )
    bucket_size = max(1, len(ordered) // quantiles)
    lower = ordered[:bucket_size]
    upper = ordered[-bucket_size:]
    lower_return = _mean(tuple(float(sample.forward_return) for sample in lower))
    upper_return = _mean(tuple(float(sample.forward_return) for sample in upper))
    current_top_ids = frozenset(sample.sample_id for sample in upper)
    previous_top_ids = frozenset(previous_top_sample_ids)
    if len(previous_top_ids) != len(previous_top_sample_ids):
        raise QuantitativeMetricError("previous top sample ids must be unique")
    turnover = (
        0.0
        if not previous_top_ids
        else 1.0 - len(previous_top_ids & current_top_ids) / len(current_top_ids)
    )
    return RewardMetrics(
        coverage=coverage,
        ic=ic,
        rank_ic=rank_ic,
        lower_quantile_return=lower_return,
        upper_quantile_return=upper_return,
        quantile_spread=upper_return - lower_return,
        turnover=turnover,
        complexity=complexity,
    )


__all__ = [
    "FactorSample",
    "QuantitativeMetricError",
    "RewardMetrics",
    "compute_reward_metrics",
]
