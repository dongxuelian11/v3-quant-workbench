"""Provider-independent financial truth primitives for daily/EOD research."""

from .model import (
    AdjustmentFactorVersion,
    CanonicalEodRecord,
    CorporateAction,
    ExecutionPriceBasis,
    InstrumentLifecycle,
    ProviderCapability,
    ProviderDescriptor,
    RawCaptureEnvelope,
    TradingSession,
    TradingStatus,
    UniverseMembershipInterval,
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
    "CorporateAction",
    "ExecutionPriceBasis",
    "InstrumentLifecycle",
    "PitCapabilityUnavailable",
    "ProviderAdapterPort",
    "ProviderCapability",
    "ProviderDescriptor",
    "RawCaptureEnvelope",
    "RawCaptureSink",
    "RawCaptureSubmission",
    "TradingSession",
    "TradingStatus",
    "UniverseMembershipInterval",
    "assert_execution_price_policy",
    "ingest_from_provider",
    "resolve_eod_as_of",
    "resolve_universe_as_of",
]
