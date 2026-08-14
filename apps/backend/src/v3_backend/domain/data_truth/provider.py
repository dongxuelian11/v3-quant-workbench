from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Protocol

from .capabilities import FieldCapabilityPolicy
from .model import ConnectorDataCapability, ProviderDescriptor, RawCaptureEnvelope


PROVIDER_NEUTRAL_EOD_CONTRACT = "v3.provider-neutral-eod-observation/1.0.0"


@dataclass(frozen=True, slots=True)
class ProviderNeutralEodRow:
    """Provider-neutral EOD values; vendor column names terminate in the adapter."""

    symbol: str
    session_date: date
    open: object | None
    high: object | None
    low: object | None
    close: object | None
    volume: object | None
    amount: object | None
    trading_status: str | None
    available_time: datetime | None
    revision_id: str | None
    source_semantics: Mapping[str, str]
    missing_reasons: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("provider-neutral symbol is required")
        if self.available_time is not None and (
            self.available_time.tzinfo is None
            or self.available_time.utcoffset() is None
        ):
            raise ValueError("provider available_time must be timezone-aware")
        semantics = {str(key): str(value) for key, value in self.source_semantics.items()}
        reasons = {str(key): str(value) for key, value in self.missing_reasons.items()}
        required = {"open", "high", "low", "close", "volume", "amount"}
        if not required.issubset(semantics):
            raise ValueError("provider-neutral EOD row lacks source field semantics")
        if any(not key or not value for key, value in (*semantics.items(), *reasons.items())):
            raise ValueError("source semantics and missing reasons require non-empty values")
        object.__setattr__(self, "source_semantics", MappingProxyType(semantics))
        object.__setattr__(self, "missing_reasons", MappingProxyType(reasons))

    def to_wire(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "session_date": self.session_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "trading_status": self.trading_status,
            "available_time": self.available_time,
            "revision_id": self.revision_id,
            "source_semantics": dict(self.source_semantics),
            "missing_reasons": dict(self.missing_reasons),
        }


@dataclass(frozen=True, slots=True)
class ProviderNeutralObservationBatch:
    logical_dataset: str
    frequency: str
    rows: tuple[ProviderNeutralEodRow, ...]
    contract_version: str = PROVIDER_NEUTRAL_EOD_CONTRACT

    def __post_init__(self) -> None:
        if self.contract_version != PROVIDER_NEUTRAL_EOD_CONTRACT:
            raise ValueError("unsupported provider-neutral observation contract")
        if not self.logical_dataset or not self.frequency:
            raise ValueError("provider-neutral observations require dataset and frequency")
        if any(not isinstance(row, ProviderNeutralEodRow) for row in self.rows):
            raise TypeError("provider-neutral observation batch contains an invalid row")

    def to_wire(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "logical_dataset": self.logical_dataset,
            "frequency": self.frequency,
            "rows": tuple(row.to_wire() for row in self.rows),
        }


@dataclass(frozen=True, slots=True)
class RawCaptureSubmission:
    envelope: RawCaptureEnvelope
    source_metadata: Mapping[str, Any]
    observations: ProviderNeutralObservationBatch

    def __post_init__(self) -> None:
        if self.observations.logical_dataset != self.envelope.provider_dataset:
            raise ValueError("observation dataset must match Raw Capture dataset")


class MarketDataProviderPort(Protocol):
    """Runtime adapter seam; its declarations do not establish canonical authority."""

    def descriptor(self) -> ProviderDescriptor: ...
    def capabilities(self) -> tuple[ConnectorDataCapability, ...]: ...
    def field_capability_policy(self) -> FieldCapabilityPolicy: ...
    def capture(self, request: Mapping[str, Any]) -> RawCaptureSubmission: ...


# Compatibility name for the already accepted WS-F seam.
ProviderAdapterPort = MarketDataProviderPort


class RawCaptureSink(Protocol):
    def submit_raw_capture(self, submission: RawCaptureSubmission) -> str: ...


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfig:
    provider_id: str
    connector_version_id: str
    runtime_profile_id: str
    credential_reference_id: str | None = None
    usage_policy_reference_id: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id.startswith("pvd_"):
            raise ValueError("runtime config requires a provider descriptor identity")
        if not self.connector_version_id.startswith("cov_"):
            raise ValueError("runtime config requires an exact ConnectorVersion")
        if not self.runtime_profile_id:
            raise ValueError("runtime_profile_id is required")
        if self.credential_reference_id is not None and not self.credential_reference_id.startswith(
            "crf_"
        ):
            raise ValueError("credentials must be injected by canonical reference only")
        if self.usage_policy_reference_id is not None and not self.usage_policy_reference_id.startswith(
            "art_sha256_"
        ):
            raise ValueError("provider usage/licensing metadata must be a non-secret Artifact reference")


@dataclass(frozen=True, slots=True)
class PersistedProviderAdmission:
    """Authority result returned by a trusted resolver; construction grants nothing."""

    provider_id: str
    connector_version_id: str
    policy_artifact_id: str
    admitted: bool

    def __post_init__(self) -> None:
        if not self.provider_id.startswith("pvd_"):
            raise ValueError("admission requires provider identity")
        if not self.connector_version_id.startswith("cov_"):
            raise ValueError("admission requires exact ConnectorVersion")
        if not self.policy_artifact_id.startswith("art_sha256_"):
            raise ValueError("admission requires persisted capability-policy Artifact")
        if not isinstance(self.admitted, bool):
            raise TypeError("admitted must be bool")


class ProviderExecutionUnavailable(RuntimeError):
    pass


class ProviderCanonicalAdmissionUnavailable(RuntimeError):
    pass


class ProviderPolicyMismatch(RuntimeError):
    pass


class ProviderAdmissionResolver(Protocol):
    """Resolve persisted connector/provider admission through the canonical owner."""

    def resolve(self, config: ProviderRuntimeConfig) -> PersistedProviderAdmission | None: ...


class ProviderCapabilityPolicyResolver(Protocol):
    """Resolve the exact authority-backed field policy, normally through P1."""

    def resolve(self, admission: PersistedProviderAdmission) -> FieldCapabilityPolicy: ...


ProviderAdapterFactory = Callable[[ProviderRuntimeConfig], MarketDataProviderPort]


@dataclass(frozen=True, slots=True)
class ProviderExecutionBinding:
    adapter: MarketDataProviderPort
    config: ProviderRuntimeConfig
    admission: PersistedProviderAdmission
    persisted_policy: FieldCapabilityPolicy

    def capture(self, request: Mapping[str, Any]) -> RawCaptureSubmission:
        descriptor = self.adapter.descriptor()
        if descriptor.provider_id != self.admission.provider_id:
            raise ProviderPolicyMismatch("adapter provider differs from admitted provider")
        declared = self.adapter.field_capability_policy()
        if declared.policy_artifact_id != self.persisted_policy.policy_artifact_id:
            raise ProviderPolicyMismatch(
                "adapter code capability disagrees with persisted policy Artifact"
            )
        submission = self.adapter.capture(request)
        if (
            submission.envelope.provider_id != self.admission.provider_id
            or submission.envelope.connector_version_id
            != self.admission.connector_version_id
        ):
            raise ProviderPolicyMismatch("Raw Capture identity differs from admission")
        return submission


class ProviderAdapterRegistry:
    """Non-authoritative runtime discovery only; admission remains persisted authority."""

    def __init__(self, factories: Mapping[str, ProviderAdapterFactory]) -> None:
        observed = dict(factories)
        if any(not provider_id.startswith("pvd_") for provider_id in observed):
            raise ValueError("runtime registry keys must be provider IDs")
        self._factories = MappingProxyType(observed)

    def bind(
        self,
        config: ProviderRuntimeConfig,
        admission_resolver: ProviderAdmissionResolver,
        policy_resolver: ProviderCapabilityPolicyResolver,
    ) -> ProviderExecutionBinding:
        admission = admission_resolver.resolve(config)
        if admission is None or not isinstance(admission, PersistedProviderAdmission):
            raise ProviderCanonicalAdmissionUnavailable(
                "canonical provider admission is unavailable"
            )
        if (
            config.provider_id != admission.provider_id
            or config.connector_version_id != admission.connector_version_id
        ):
            raise ProviderCanonicalAdmissionUnavailable(
                "runtime config does not match persisted provider admission"
            )
        if not admission.admitted:
            raise ProviderCanonicalAdmissionUnavailable(
                "adapter installation cannot replace canonical provider admission"
            )
        persisted_policy = policy_resolver.resolve(admission)
        if not isinstance(persisted_policy, FieldCapabilityPolicy):
            raise ProviderPolicyMismatch(
                "capability policy resolver returned a non-canonical policy value"
            )
        if (
            persisted_policy.provider_id != admission.provider_id
            or persisted_policy.connector_version_id != admission.connector_version_id
            or persisted_policy.policy_artifact_id != admission.policy_artifact_id
        ):
            raise ProviderPolicyMismatch("resolved capability policy does not match admission")
        factory = self._factories.get(config.provider_id)
        if factory is None:
            raise ProviderExecutionUnavailable(
                "provider is admitted but its runtime adapter is unavailable"
            )
        adapter = factory(config)
        return ProviderExecutionBinding(adapter, config, admission, persisted_policy)


def ingest_from_provider(
    binding: ProviderExecutionBinding,
    sink: RawCaptureSink,
    request: Mapping[str, Any],
) -> str:
    submission = binding.capture(request)
    if not isinstance(submission, RawCaptureSubmission):
        raise TypeError("provider connector must submit RawCaptureSubmission")
    return sink.submit_raw_capture(submission)
