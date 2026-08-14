"""Provider-specific V0 normalization and research snapshot binding."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo

from ...contracts.common.truth_admission import (
    PRE_ALPHA_CEILING,
    TruthAdmissionState,
    UpstreamRequirement,
    propagate_downstream_ceiling,
)
from ...provenance.canonical_hash import canonical_sha256
from .capabilities import (
    FieldCapabilityPolicy,
    FieldCapabilityState,
    MarketDataFieldCode,
)
from .pit import PitCapabilityUnavailable
from .provider import ProviderNeutralEodRow, RawCaptureSubmission
from .resolution import FieldCandidate, FieldProvenance, FieldValueKind


NORMALIZATION_VERSION = "v3-cn-a-share-eod-normalization-v0.1.0"
SNAPSHOT_SCHEMA_VERSION = "v3-cn-a-share-eod-research-snapshot-v0"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class NormalizationError(ValueError):
    """Raw provider payload cannot be normalized without guessing."""


class MissingValueReason(str, Enum):
    PROVIDER_NULL = "PROVIDER_NULL"
    PROVIDER_COLUMN_ABSENT = "PROVIDER_COLUMN_ABSENT"
    PROVIDER_FIELD_UNAVAILABLE = "PROVIDER_FIELD_UNAVAILABLE"


class PitEvidenceState(str, Enum):
    UNKNOWN = "UNKNOWN"
    PROVIDER_ASSERTED = "PROVIDER_ASSERTED"


@dataclass(frozen=True)
class MissingField:
    field: str
    reason: MissingValueReason


@dataclass(frozen=True)
class NormalizedEodObservation:
    instrument_id: str
    symbol: str
    exchange: str
    session_date: date
    event_time: datetime
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    amount: Decimal | None
    trading_status: str | None
    available_time: datetime | None
    acquisition_time: datetime
    acquisition_id: str
    revision_id: str | None
    raw_capture_id: str
    provider_id: str
    connector_version_id: str
    logical_dataset: str
    artifact_id: str
    content_hash: str
    source_semantics: tuple[tuple[str, str], ...]
    missing_fields: tuple[MissingField, ...]

    def identity_wire(self) -> dict[str, object]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "session_date": self.session_date,
            "event_time": self.event_time,
            "open": None if self.open is None else format(self.open, "f"),
            "high": None if self.high is None else format(self.high, "f"),
            "low": None if self.low is None else format(self.low, "f"),
            "close": None if self.close is None else format(self.close, "f"),
            "volume": self.volume,
            "amount": None if self.amount is None else format(self.amount, "f"),
            "trading_status": self.trading_status,
            "available_time": self.available_time,
            "acquisition_time": self.acquisition_time,
            "acquisition_id": self.acquisition_id,
            "revision_id": self.revision_id,
            "raw_capture_id": self.raw_capture_id,
            "provider_id": self.provider_id,
            "connector_version_id": self.connector_version_id,
            "logical_dataset": self.logical_dataset,
            "artifact_id": self.artifact_id,
            "content_hash": self.content_hash,
            "source_semantics": self.source_semantics,
            "missing_fields": tuple(
                {"field": item.field, "reason": item.reason.value}
                for item in self.missing_fields
            ),
        }


@dataclass(frozen=True)
class ResearchUniverseInput:
    research_universe_input_id: str
    snapshot_id: str
    instrument_ids: tuple[str, ...]
    role: str = "OBSERVED_PROVIDER_SYMBOLS_ONLY"


@dataclass(frozen=True)
class ResearchDataSnapshot:
    snapshot_id: str
    normalization_version: str
    raw_capture_ids: tuple[str, ...]
    acquisition_ids: tuple[str, ...]
    records: tuple[NormalizedEodObservation, ...]
    truth_ceiling: TruthAdmissionState
    pit_evidence: PitEvidenceState
    revision_evidence: PitEvidenceState
    reason_codes: tuple[str, ...]
    research_universe_input: ResearchUniverseInput

    def require_strict_pit(self) -> tuple[NormalizedEodObservation, ...]:
        if self.pit_evidence is not PitEvidenceState.PROVIDER_ASSERTED:
            raise PitCapabilityUnavailable("provider available-time evidence is unavailable")
        if self.revision_evidence is not PitEvidenceState.PROVIDER_ASSERTED:
            raise PitCapabilityUnavailable("provider revision evidence is unavailable")
        if any(record.available_time is None for record in self.records):
            raise PitCapabilityUnavailable("record available-time is unavailable")
        return self.records


def field_candidates_from_eod(
    record: NormalizedEodObservation,
    policy: FieldCapabilityPolicy,
) -> tuple[FieldCandidate, ...]:
    """Project one normalized row into field candidates with exact raw provenance."""

    if (
        policy.provider_id != record.provider_id
        or policy.connector_version_id != record.connector_version_id
        or policy.logical_dataset != record.logical_dataset
    ):
        raise ValueError("field capability policy does not bind the normalized observation")
    semantics = dict(record.source_semantics)
    missing = {item.field: item.reason.value for item in record.missing_fields}
    values: dict[MarketDataFieldCode, object | None] = {
        MarketDataFieldCode.OHLC: (
            None
            if any(
                item is None
                for item in (record.open, record.high, record.low, record.close)
            )
            else (
                format(record.open, "f"),
                format(record.high, "f"),
                format(record.low, "f"),
                format(record.close, "f"),
            )
        ),
        MarketDataFieldCode.VOLUME: record.volume,
        MarketDataFieldCode.AMOUNT: (
            None if record.amount is None else format(record.amount, "f")
        ),
        MarketDataFieldCode.TRADING_STATUS: record.trading_status,
    }
    source_names = {
        MarketDataFieldCode.OHLC: "/".join(
            semantics[name] for name in ("open", "high", "low", "close")
        ),
        MarketDataFieldCode.VOLUME: semantics["volume"],
        MarketDataFieldCode.AMOUNT: semantics["amount"],
        MarketDataFieldCode.TRADING_STATUS: "missing_reason:"
        + missing.get("trading_status", "PROVIDER_FIELD_UNAVAILABLE"),
    }
    candidates: list[FieldCandidate] = []
    for code, value in values.items():
        capability = policy.capability(code)
        if capability is None:
            raise ValueError(f"field capability policy omits {code.value}")
        kind = (
            FieldValueKind.DIRECT
            if value is not None
            else (
                FieldValueKind.UNAVAILABLE
                if capability.state is FieldCapabilityState.UNAVAILABLE
                else FieldValueKind.MISSING
            )
        )
        candidates.append(
            FieldCandidate(
                field_code=code,
                value=value,
                capability_state=capability.state,
                provenance=FieldProvenance(
                    provider_id=record.provider_id,
                    connector_version_id=record.connector_version_id,
                    logical_dataset=record.logical_dataset,
                    raw_capture_id=record.raw_capture_id,
                    artifact_id=record.artifact_id,
                    content_hash=record.content_hash,
                    source_field_semantic=source_names[code],
                    effective_time=record.event_time,
                    available_time=record.available_time,
                    revision_id=record.revision_id,
                    revision_semantics=capability.revision_semantics,
                    acquired_at=record.acquisition_time,
                    value_kind=kind,
                ),
            )
        )
    return tuple(candidates)


def _null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    return isinstance(value, str) and value.strip().lower() in {"", "nan", "nat", "none"}


def _decimal(
    value: object, target: str, missing: list[MissingField]
) -> Decimal | None:
    if _null(value):
        missing.append(MissingField(target, MissingValueReason.PROVIDER_NULL))
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizationError(f"{target} must be a finite decimal") from error
    if not parsed.is_finite():
        raise NormalizationError(f"{target} must be a finite decimal")
    return parsed


def _volume(value: object, missing: list[MissingField]) -> int | None:
    if _null(value):
        missing.append(MissingField("volume", MissingValueReason.PROVIDER_NULL))
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizationError("volume must be an integer") from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 0:
        raise NormalizationError("volume must be a non-negative integer")
    return int(parsed)


def _exchange(symbol: str) -> str:
    if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
        raise NormalizationError("provider symbol must be exactly six ASCII digits")
    if symbol.startswith(("4", "8", "92")):
        return "BSE"
    if symbol.startswith(("5", "6", "9")):
        return "SSE"
    if symbol.startswith(("0", "1", "2", "3")):
        return "SZSE"
    raise NormalizationError(f"unsupported A-share symbol prefix: {symbol}")


def _records(submission: RawCaptureSubmission) -> tuple[ProviderNeutralEodRow, ...]:
    metadata = submission.source_metadata
    payload = metadata.get("raw_payload")
    if not isinstance(payload, Mapping):
        raise NormalizationError("raw payload is unavailable")
    if canonical_sha256(payload) != submission.envelope.content_hash:
        raise NormalizationError("raw payload no longer matches immutable capture identity")
    projected = payload.get("provider_neutral_observations")
    if canonical_sha256(projected) != canonical_sha256(submission.observations.to_wire()):
        raise NormalizationError(
            "provider-neutral observations do not match immutable capture bytes"
        )
    return submission.observations.rows


def _acquisition_provenance(
    submission: RawCaptureSubmission,
) -> tuple[str, datetime]:
    metadata = submission.source_metadata
    acquisition_id = metadata.get("acquisition_id")
    acquisition_time = metadata.get("acquired_at")
    provider_version = metadata.get("provider_package_version")
    request_fingerprint = metadata.get("request_fingerprint")
    if not isinstance(acquisition_id, str) or not acquisition_id:
        raise NormalizationError("acquisition identity evidence is unavailable")
    if not isinstance(acquisition_time, datetime):
        raise NormalizationError("acquisition time evidence is unavailable")
    if acquisition_time.tzinfo is None or acquisition_time.utcoffset() is None:
        raise NormalizationError("acquisition time evidence must be timezone-aware")
    if not isinstance(provider_version, str) or not provider_version:
        raise NormalizationError("provider version evidence is unavailable")
    if not isinstance(request_fingerprint, str) or not request_fingerprint:
        raise NormalizationError("request fingerprint evidence is unavailable")
    expected_id = "acq_sha256_" + canonical_sha256(
        {
            "provider_id": submission.envelope.provider_id,
            "provider_version": provider_version,
            "request_fingerprint": request_fingerprint,
            "acquired_at": acquisition_time,
        }
    )
    if acquisition_id != expected_id:
        raise NormalizationError("acquisition identity does not match its provenance")
    return acquisition_id, acquisition_time


def _normalize_row(
    row: ProviderNeutralEodRow,
    submission: RawCaptureSubmission,
    *,
    acquisition_id: str,
    acquisition_time: datetime,
) -> NormalizedEodObservation:
    symbol = row.symbol
    exchange = _exchange(symbol)
    session_date = row.session_date
    missing: list[MissingField] = []
    open_price = _decimal(row.open, "open", missing)
    close_price = _decimal(row.close, "close", missing)
    high = _decimal(row.high, "high", missing)
    low = _decimal(row.low, "low", missing)
    volume = _volume(row.volume, missing)
    amount = _decimal(row.amount, "amount", missing)
    for field, reason in row.missing_reasons.items():
        if field not in {item.field for item in missing}:
            try:
                typed_reason = MissingValueReason(reason)
            except ValueError as error:
                raise NormalizationError(f"unsupported missing reason: {reason}") from error
            missing.append(MissingField(field, typed_reason))
    if all(value is not None for value in (open_price, close_price, high, low)):
        assert open_price is not None and close_price is not None
        assert high is not None and low is not None
        if low > high or low > min(open_price, close_price) or high < max(
            open_price, close_price
        ):
            raise NormalizationError("provider OHLC envelope is inconsistent")
    return NormalizedEodObservation(
        instrument_id=f"ins_cn_{exchange.lower()}_{symbol}",
        symbol=symbol,
        exchange=exchange,
        session_date=session_date,
        event_time=datetime.combine(session_date, time(15, 0), tzinfo=_SHANGHAI),
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=volume,
        amount=amount,
        trading_status=row.trading_status,
        available_time=row.available_time,
        acquisition_time=acquisition_time,
        acquisition_id=acquisition_id,
        revision_id=row.revision_id,
        raw_capture_id=submission.envelope.raw_capture_id,
        provider_id=submission.envelope.provider_id,
        connector_version_id=submission.envelope.connector_version_id,
        logical_dataset=submission.observations.logical_dataset,
        artifact_id=submission.envelope.artifact_id,
        content_hash=submission.envelope.content_hash,
        source_semantics=tuple(sorted(row.source_semantics.items())),
        missing_fields=tuple(sorted(missing, key=lambda item: item.field)),
    )


def normalize_a_share_eod(
    submission: RawCaptureSubmission,
    *,
    proposed_state: TruthAdmissionState = PRE_ALPHA_CEILING,
) -> ResearchDataSnapshot:
    """Normalize one capture and bind it to the A0 ceiling without promotion."""

    rows = _records(submission)
    acquisition_id, acquisition_time = _acquisition_provenance(submission)
    records = tuple(
        sorted(
            (
                _normalize_row(
                    row,
                    submission,
                    acquisition_id=acquisition_id,
                    acquisition_time=acquisition_time,
                )
                for row in rows
            ),
            key=lambda item: (item.instrument_id, item.session_date),
        )
    )
    acquisition_ids = (acquisition_id,)
    pit_evidence = (
        PitEvidenceState.PROVIDER_ASSERTED
        if records
        and all(record.available_time is not None for record in records)
        and submission.source_metadata.get("available_time_evidence") == "PROVIDER_ASSERTED"
        else PitEvidenceState.UNKNOWN
    )
    revision_evidence = (
        PitEvidenceState.PROVIDER_ASSERTED
        if records
        and all(record.revision_id is not None for record in records)
        and submission.source_metadata.get("revision_evidence") == "PROVIDER_ASSERTED"
        else PitEvidenceState.UNKNOWN
    )
    ceiling = propagate_downstream_ceiling(
        proposed_state,
        (
            UpstreamRequirement(
                source_id=submission.envelope.raw_capture_id,
                state=PRE_ALPHA_CEILING,
            ),
        ),
    )
    identity = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "raw_capture_content_hash": submission.envelope.content_hash,
        "acquisition_ids": acquisition_ids,
        "records": tuple(record.identity_wire() for record in records),
        "truth_ceiling": ceiling,
        "pit_evidence": pit_evidence,
        "revision_evidence": revision_evidence,
    }
    snapshot_id = "snp_sha256_" + canonical_sha256(identity)
    instruments = tuple(sorted({record.instrument_id for record in records}))
    universe_id = "rui_sha256_" + canonical_sha256(
        {
            "snapshot_id": snapshot_id,
            "instrument_ids": instruments,
            "role": "OBSERVED_PROVIDER_SYMBOLS_ONLY",
        }
    )
    universe_input = ResearchUniverseInput(
        research_universe_input_id=universe_id,
        snapshot_id=snapshot_id,
        instrument_ids=instruments,
    )
    return ResearchDataSnapshot(
        snapshot_id=snapshot_id,
        normalization_version=NORMALIZATION_VERSION,
        raw_capture_ids=(submission.envelope.raw_capture_id,),
        acquisition_ids=acquisition_ids,
        records=records,
        truth_ceiling=ceiling,
        pit_evidence=pit_evidence,
        revision_evidence=revision_evidence,
        reason_codes=tuple(
            code
            for condition, code in (
                (
                    pit_evidence is PitEvidenceState.UNKNOWN,
                    "PROVIDER_AVAILABLE_TIME_UNKNOWN",
                ),
                (
                    revision_evidence is PitEvidenceState.UNKNOWN,
                    "PROVIDER_REVISION_UNKNOWN",
                ),
                (True, "PROVIDER_DATA_IS_NOT_CANONICAL_MARKET_TRUTH"),
            )
            if condition
        ),
        research_universe_input=universe_input,
    )
