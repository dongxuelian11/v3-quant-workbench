from __future__ import annotations

import math
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType
from typing import Mapping

from v3_backend.provenance.canonical_hash import canonical_sha256


ALPHALENS_DISTRIBUTION = "alphalens-reloaded"
ALPHALENS_VERSION = "0.4.6"
ALPHALENS_LICENSE = "Apache-2.0"
ALLOWED_REFERENCE_METRICS = frozenset(
    {"coverage", "ic", "rank_ic", "quantile_spread", "turnover"}
)


class AlphalensReferenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AlphalensCompatibility:
    distribution: str
    expected_version: str
    observed_version: str | None
    available: bool
    authority: str = "REFERENCE_ONLY"
    license: str = ALPHALENS_LICENSE


@dataclass(frozen=True, slots=True)
class AlphalensReferencePayload:
    factor_evaluation_id: str
    dataset_version_id: str
    input_artifact_id: str
    output_artifact_id: str
    provenance_artifact_id: str
    metrics: Mapping[str, float]
    dependency_version: str = ALPHALENS_VERSION

    def __post_init__(self) -> None:
        for name in ("factor_evaluation_id", "dataset_version_id"):
            value = getattr(self, name)
            if not value or value != value.strip():
                raise AlphalensReferenceError(f"{name} is required")
        for name in (
            "input_artifact_id",
            "output_artifact_id",
            "provenance_artifact_id",
        ):
            if not getattr(self, name).startswith("art_sha256_"):
                raise AlphalensReferenceError(f"{name} must be content-addressed")
        if self.dependency_version != ALPHALENS_VERSION:
            raise AlphalensReferenceError(
                f"Alphalens reference payload must use {ALPHALENS_VERSION}"
            )
        observed = dict(self.metrics)
        if not observed or not set(observed).issubset(ALLOWED_REFERENCE_METRICS):
            raise AlphalensReferenceError("unknown or empty Alphalens metric payload")
        for name, value in observed.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AlphalensReferenceError(f"metric {name} must be numeric")
            if not math.isfinite(float(value)):
                raise AlphalensReferenceError(f"metric {name} must be finite")
        object.__setattr__(
            self,
            "metrics",
            MappingProxyType({name: float(observed[name]) for name in sorted(observed)}),
        )


@dataclass(frozen=True, slots=True)
class AlphalensReferenceEvidence:
    reference_evidence_id: str
    factor_evaluation_id: str
    dataset_version_id: str
    input_artifact_id: str
    output_artifact_id: str
    provenance_artifact_id: str
    metrics: Mapping[str, float]
    dependency_version: str
    authority: str = "REFERENCE_ONLY"


class AlphalensReferenceAdapter:
    """Ingests isolated Alphalens output; never builds labels or canonical identity."""

    @staticmethod
    def probe_dependency() -> AlphalensCompatibility:
        try:
            observed = metadata.version(ALPHALENS_DISTRIBUTION)
        except metadata.PackageNotFoundError:
            return AlphalensCompatibility(
                ALPHALENS_DISTRIBUTION, ALPHALENS_VERSION, None, False
            )
        return AlphalensCompatibility(
            ALPHALENS_DISTRIBUTION,
            ALPHALENS_VERSION,
            observed,
            observed == ALPHALENS_VERSION,
        )

    @staticmethod
    def ingest(payload: AlphalensReferencePayload) -> AlphalensReferenceEvidence:
        identity_payload = {
            "factor_evaluation_id": payload.factor_evaluation_id,
            "dataset_version_id": payload.dataset_version_id,
            "input_artifact_id": payload.input_artifact_id,
            "output_artifact_id": payload.output_artifact_id,
            "provenance_artifact_id": payload.provenance_artifact_id,
            "metrics": dict(payload.metrics),
            "dependency_version": payload.dependency_version,
            "authority": "REFERENCE_ONLY",
        }
        return AlphalensReferenceEvidence(
            reference_evidence_id="alref_sha256_"
            + canonical_sha256(identity_payload),
            factor_evaluation_id=payload.factor_evaluation_id,
            dataset_version_id=payload.dataset_version_id,
            input_artifact_id=payload.input_artifact_id,
            output_artifact_id=payload.output_artifact_id,
            provenance_artifact_id=payload.provenance_artifact_id,
            metrics=payload.metrics,
            dependency_version=payload.dependency_version,
        )


__all__ = [
    "ALPHALENS_DISTRIBUTION",
    "ALPHALENS_LICENSE",
    "ALPHALENS_VERSION",
    "AlphalensCompatibility",
    "AlphalensReferenceAdapter",
    "AlphalensReferenceError",
    "AlphalensReferenceEvidence",
    "AlphalensReferencePayload",
]
