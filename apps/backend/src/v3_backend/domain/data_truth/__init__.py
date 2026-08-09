"""Provider-independent financial truth primitives for daily/EOD research."""

from .model import (
    AdjustmentFactorVersion,
    CanonicalEodRecord,
    CapabilityTruthState,
    ConnectorCapabilityResolution,
    ConnectorDataCapability,
    CorporateAction,
    ExecutionPriceBasis,
    InstrumentLifecycle,
    ProviderDescriptor,
    RawCaptureEnvelope,
    RevisionSemantics,
    TradingSession,
    TradingStatus,
    UniverseMembershipInterval,
    UniverseResolution,
)
from .pit import (
    AdjustmentDoubleCountError,
    PitCapabilityUnavailable,
    assert_execution_price_policy,
    resolve_eod_as_of,
    resolve_universe_as_of,
)
from .provider import ProviderAdapterPort, RawCaptureSink, RawCaptureSubmission, ingest_from_provider

__all__ = [
    "AdjustmentDoubleCountError",
    "AdjustmentFactorVersion",
    "CanonicalEodRecord",
    "CapabilityTruthState",
    "ConnectorCapabilityResolution",
    "ConnectorDataCapability",
    "CorporateAction",
    "ExecutionPriceBasis",
    "InstrumentLifecycle",
    "PitCapabilityUnavailable",
    "ProviderAdapterPort",
    "ProviderDescriptor",
    "RawCaptureEnvelope",
    "RevisionSemantics",
    "RawCaptureSink",
    "RawCaptureSubmission",
    "TradingSession",
    "TradingStatus",
    "UniverseMembershipInterval",
    "UniverseResolution",
    "assert_execution_price_policy",
    "ingest_from_provider",
    "resolve_eod_as_of",
    "resolve_universe_as_of",
]
