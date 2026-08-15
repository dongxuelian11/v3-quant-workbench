"""Role/format admission policy with explicit fail-closed outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .exceptions import CapabilityUnavailable, FormatRejected


ADMITTED = "ADMITTED"
QUARANTINED = "QUARANTINED"
UNAVAILABLE = "UNAVAILABLE"
REJECTED = "REJECTED"
_OUTCOMES = {ADMITTED, QUARANTINED, UNAVAILABLE, REJECTED}


@dataclass(frozen=True, slots=True)
class FormatRule:
    role: str
    media_type: str
    outcome: str
    safe_format_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if not self.role or not self.media_type or "/" not in self.media_type:
            raise ValueError("format rule requires role and MIME media type")
        if self.outcome not in _OUTCOMES:
            raise ValueError("unknown format outcome")
        if self.outcome == ADMITTED and not self.safe_format_id:
            raise ValueError("admitted formats require a safe_format_id")
        if not self.reason:
            raise ValueError("format rule requires a reason")


@dataclass(frozen=True, slots=True)
class FormatDecision:
    outcome: str
    role: str
    media_type: str
    safe_format_id: str | None
    reason: str

    @property
    def publishable(self) -> bool:
        return self.outcome == ADMITTED


class SafeFormatPolicy:
    """Closed allow-list; unknown role/format pairs are rejected."""

    def __init__(self, rules: tuple[FormatRule, ...]) -> None:
        indexed: dict[tuple[str, str], FormatRule] = {}
        for rule in rules:
            key = (rule.role, rule.media_type)
            if key in indexed:
                raise ValueError(f"duplicate format rule: {key!r}")
            indexed[key] = rule
        self._rules: Mapping[tuple[str, str], FormatRule] = MappingProxyType(indexed)

    @classmethod
    def baseline(cls) -> "SafeFormatPolicy":
        return cls(
            (
                FormatRule(
                    "PARQUET_DATASET_MANIFEST",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical manifest JSON is non-executable and schema-validated",
                ),
                FormatRule(
                    "GC_PLAN",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical GC plan JSON is non-executable and schema-validated",
                ),
                FormatRule(
                    "TARGET_WEIGHT_VECTOR",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical TargetWeightVector JSON is non-executable and identity-checked",
                ),
                FormatRule(
                    "RISK_POLICY_SET",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical RiskPolicySetVersion JSON is non-executable and identity-checked",
                ),
                FormatRule(
                    "RISK_APPLICATION_RECEIPT",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical Risk receipt JSON is non-executable and identity-checked",
                ),
                FormatRule(
                    "RISK_ADJUSTED_WEIGHT_VECTOR",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "canonical Risk-adjusted weight JSON is non-executable and identity-checked",
                ),
                FormatRule(
                    "DATA_TRUTH_CAPABILITY_POLICY",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "field capability policy JSON is non-executable and content-addressed",
                ),
                FormatRule(
                    "DATA_TRUTH_SOURCE_AUTHORITY_EVIDENCE",
                    "application/json",
                    ADMITTED,
                    "canonical-json-v1",
                    "source authority evidence JSON is non-executable and content-addressed",
                ),
                FormatRule(
                    "MODEL_SAFE_LINEAR",
                    "application/vnd.v3.safe-linear-model+json;version=1",
                    ADMITTED,
                    "canonical-finite-json-v1",
                    "closed finite coefficient JSON is non-executable and identity-checked",
                ),
                FormatRule(
                    "MODEL_PIPELINE_RECORD",
                    "application/json",
                    ADMITTED,
                    "canonical-finite-json-v1",
                    "model pipeline receipts and predictions are bounded finite canonical JSON",
                ),
                FormatRule(
                    "TEXT_REPORT",
                    "text/plain",
                    ADMITTED,
                    "utf8-text-v1",
                    "UTF-8 text is non-executable",
                ),
                FormatRule(
                    "PARQUET_PARTITION",
                    "application/vnd.apache.parquet",
                    UNAVAILABLE,
                    None,
                    "no Parquet runtime/environment profile is admitted",
                ),
                FormatRule(
                    "MODEL",
                    "application/python-pickle",
                    REJECTED,
                    None,
                    "pickle-like arbitrary object loading is forbidden",
                ),
                FormatRule(
                    "PLUGIN",
                    "application/x-executable",
                    QUARANTINED,
                    None,
                    "executable artifacts require scanner and dependency admission",
                ),
            )
        )

    def decide(self, role: str, media_type: str) -> FormatDecision:
        rule = self._rules.get((role, media_type))
        if rule is None:
            return FormatDecision(REJECTED, role, media_type, None, "role/format pair is not allow-listed")
        return FormatDecision(rule.outcome, role, media_type, rule.safe_format_id, rule.reason)

    def require_publishable(self, role: str, media_type: str) -> FormatDecision:
        decision = self.decide(role, media_type)
        if decision.outcome == UNAVAILABLE:
            raise CapabilityUnavailable(f"format:{role}:{media_type}", decision.reason)
        if decision.outcome != ADMITTED:
            raise FormatRejected(f"{decision.outcome}: {decision.reason}")
        return decision
