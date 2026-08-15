from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _aware(value: datetime | None, name: str, *, required: bool = True) -> None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _hash(value: str, name: str = "content_hash") -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


@dataclass(frozen=True)
class InstrumentLifecycle:
    instrument_id: str
    listing_date: date
    delisting_date: date | None
    exchange: str
    board: str
    security_category: str

    def __post_init__(self) -> None:
        if self.delisting_date is not None and self.delisting_date < self.listing_date:
            raise ValueError("delisting_date cannot precede listing_date")
        if self.exchange not in {"SSE", "SZSE", "BSE"}:
            raise ValueError("unsupported exchange")
        if not self.board or not self.security_category:
            raise ValueError("board and security_category are required")

    def is_listed_on(self, session_date: date) -> bool:
        return self.listing_date <= session_date and (
            self.delisting_date is None or session_date <= self.delisting_date
        )


@dataclass(frozen=True)
class TradingSession:
    session_id: str
    calendar_version_id: str
    session_date: date
    is_trading_day: bool
    session_ordinal: int
    open_time: datetime | None
    close_time: datetime | None
    available_time: datetime

    def __post_init__(self) -> None:
        if self.session_ordinal < 0:
            raise ValueError("session_ordinal must be non-negative")
        _aware(self.available_time, "available_time")
        _aware(self.open_time, "open_time", required=False)
        _aware(self.close_time, "close_time", required=False)
        if self.is_trading_day:
            if self.open_time is None or self.close_time is None:
                raise ValueError("trading day requires open_time and close_time")
            if self.close_time <= self.open_time:
                raise ValueError("close_time must follow open_time")
        elif self.open_time is not None or self.close_time is not None:
            raise ValueError("non-trading day cannot carry an open/close window")


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    stable_name: str
    source_authority: str
    metadata_hash: str

    def __post_init__(self) -> None:
        if not self.stable_name or not self.source_authority:
            raise ValueError("provider stable_name and source_authority are required")
        _hash(self.metadata_hash, "metadata_hash")


class RevisionSemantics(str, Enum):
    REVISION_AWARE = "REVISION_AWARE"
    SOURCE_IMMUTABLE = "SOURCE_IMMUTABLE"
    UNKNOWN = "UNKNOWN"


class CapabilityTruthState(str, Enum):
    FORMAL = "FORMAL"
    DEMO = "DEMO"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ConnectorDataCapability:
    connector_version_id: str
    provider_id: str
    capability_code: str
    logical_dataset: str
    frequency: str
    revision_semantics: RevisionSemantics
    provenance_required: bool
    policy_artifact_id: str

    def __post_init__(self) -> None:
        if not self.connector_version_id.startswith("cov_"):
            raise ValueError("capability must identify an exact ConnectorVersion")
        if not self.provider_id.startswith("pvd_"):
            raise ValueError("capability must identify an exact provider descriptor")
        if not isinstance(self.revision_semantics, RevisionSemantics):
            object.__setattr__(
                self, "revision_semantics", RevisionSemantics(self.revision_semantics)
            )
        if self.provenance_required is not True:
            raise ValueError("Data Truth capability policy requires provenance")
        if not self.policy_artifact_id.startswith("art_sha256_"):
            raise ValueError("Data Truth capability must bind a policy Artifact")


@dataclass(frozen=True)
class ConnectorCapabilityResolution:
    connector_version_id: str
    capability_code: str
    truth_state: CapabilityTruthState
    reason_code: str
    revision_semantics: RevisionSemantics | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.truth_state, CapabilityTruthState):
            object.__setattr__(self, "truth_state", CapabilityTruthState(self.truth_state))
        if self.revision_semantics is not None and not isinstance(
            self.revision_semantics, RevisionSemantics
        ):
            object.__setattr__(
                self, "revision_semantics", RevisionSemantics(self.revision_semantics)
            )


@dataclass(frozen=True)
class RawCaptureEnvelope:
    raw_capture_id: str
    provider_id: str
    connector_version_id: str
    provider_dataset: str
    artifact_id: str
    effective_range_start: datetime | None
    effective_range_end: datetime | None
    available_time: datetime | None
    ingested_at: datetime
    content_hash: str
    provider_revision_id: str | None = None

    def __post_init__(self) -> None:
        _aware(self.effective_range_start, "effective_range_start", required=False)
        _aware(self.effective_range_end, "effective_range_end", required=False)
        _aware(self.available_time, "available_time", required=False)
        _aware(self.ingested_at, "ingested_at")
        _hash(self.content_hash)
        if self.artifact_id != f"art_sha256_{self.content_hash}":
            raise ValueError("raw capture Artifact identity must match content_hash")
        if (
            self.effective_range_start is not None
            and self.effective_range_end is not None
            and self.effective_range_end < self.effective_range_start
        ):
            raise ValueError("effective range is reversed")


class TradingStatus(str, Enum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"
    DELISTED = "DELISTED"


@dataclass(frozen=True)
class CanonicalEodRecord:
    instrument_id: str
    session_id: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    trading_status: TradingStatus
    raw_capture_id: str
    effective_time: datetime
    available_time: datetime | None
    revision_id: str
    provider: str
    ingested_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        _aware(self.effective_time, "effective_time")
        _aware(self.available_time, "available_time", required=False)
        _aware(self.ingested_at, "ingested_at")
        _hash(self.content_hash)
        if not isinstance(self.trading_status, TradingStatus):
            object.__setattr__(self, "trading_status", TradingStatus(self.trading_status))
        if self.volume < 0 or self.amount < 0:
            raise ValueError("volume and amount must be non-negative")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC envelope is inconsistent")
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if not self.revision_id or not self.provider:
            raise ValueError("revision_id and provider are required")


@dataclass(frozen=True)
class UniverseMembershipInterval:
    universe_version_id: str
    membership_fact_id: str
    instrument_id: str
    effective_from: date
    effective_to: date | None
    available_time: datetime | None
    revision_id: str
    membership_state: str
    provenance_artifact_id: str

    def __post_init__(self) -> None:
        _aware(self.available_time, "available_time", required=False)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("membership interval is reversed")
        if not self.revision_id or not self.provenance_artifact_id.startswith("art_sha256_"):
            raise ValueError("membership revision and provenance Artifact are required")
        if not self.membership_fact_id.startswith("umf_"):
            raise ValueError("membership_fact_id is required")
        if self.membership_state not in {"INCLUDED", "EXCLUDED"}:
            raise ValueError("membership_state must be INCLUDED or EXCLUDED")

    def contains(self, as_of: date) -> bool:
        return self.effective_from <= as_of and (
            self.effective_to is None or as_of < self.effective_to
        )


@dataclass(frozen=True)
class UniverseResolution:
    members: tuple[dict[str, object], ...]
    audit: dict[str, object]

    def __iter__(self):
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    def __getitem__(self, index: int) -> dict[str, object]:
        return self.members[index]

@dataclass(frozen=True)
class CorporateAction:
    corporate_action_id: str
    instrument_id: str
    action_type: str
    effective_time: datetime
    available_time: datetime | None
    revision_id: str
    raw_capture_id: str
    ledger_artifact_id: str
    content_hash: str

    def __post_init__(self) -> None:
        _aware(self.effective_time, "effective_time")
        _aware(self.available_time, "available_time", required=False)
        _hash(self.content_hash)
        if not self.ledger_artifact_id.startswith("art_sha256_"):
            raise ValueError("corporate action requires a ledger Artifact")


@dataclass(frozen=True)
class AdjustmentFactorVersion:
    adjustment_factor_version_id: str
    snapshot_id: str
    basis: str
    manifest_artifact_id: str
    content_hash: str

    def __post_init__(self) -> None:
        _hash(self.content_hash)
        if self.manifest_artifact_id != f"art_sha256_{self.content_hash}":
            raise ValueError("adjustment manifest identity must match content_hash")


class ExecutionPriceBasis(str, Enum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
