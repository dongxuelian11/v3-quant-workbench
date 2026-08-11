"""Provider-specific V0 normalization and research snapshot binding."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
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
from .pit import PitCapabilityUnavailable
from .provider import RawCaptureSubmission


NORMALIZATION_VERSION = "v3-cn-a-share-eod-normalization-v0.1.0"
SNAPSHOT_SCHEMA_VERSION = "v3-cn-a-share-eod-research-snapshot-v0"
_RAW_SCHEMA_ID = "akshare-stock-zh-a-hist-raw-v1"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REQUIRED_COLUMNS = frozenset(
    {"日期", "股票代码", "开盘", "收盘", "最高", "最低", "成交量", "成交额"}
)


class NormalizationError(ValueError):
    """Raw provider payload cannot be normalized without guessing."""


class MissingValueReason(str, Enum):
    PROVIDER_NULL = "PROVIDER_NULL"
    PROVIDER_COLUMN_ABSENT = "PROVIDER_COLUMN_ABSENT"


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
    available_time: datetime | None
    acquisition_time: datetime
    acquisition_id: str
    revision_id: str | None
    raw_capture_id: str
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
            "available_time": self.available_time,
            "acquisition_time": self.acquisition_time,
            "acquisition_id": self.acquisition_id,
            "revision_id": self.revision_id,
            "raw_capture_id": self.raw_capture_id,
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


def _null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    return isinstance(value, str) and value.strip().lower() in {"", "nan", "nat", "none"}


def _decimal(
    row: Mapping[str, object], source: str, target: str, missing: list[MissingField]
) -> Decimal | None:
    value = row.get(source)
    if _null(value):
        missing.append(MissingField(target, MissingValueReason.PROVIDER_NULL))
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizationError(f"{source} must be a finite decimal") from error
    if not parsed.is_finite():
        raise NormalizationError(f"{source} must be a finite decimal")
    return parsed


def _volume(
    row: Mapping[str, object], missing: list[MissingField]
) -> int | None:
    value = row.get("成交量")
    if _null(value):
        missing.append(MissingField("volume", MissingValueReason.PROVIDER_NULL))
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizationError("成交量 must be an integer") from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 0:
        raise NormalizationError("成交量 must be a non-negative integer")
    return int(parsed)


def _exchange(symbol: str) -> str:
    if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
        raise NormalizationError("股票代码 must be exactly six ASCII digits")
    if symbol.startswith(("4", "8", "92")):
        return "BSE"
    if symbol.startswith(("5", "6", "9")):
        return "SSE"
    if symbol.startswith(("0", "1", "2", "3")):
        return "SZSE"
    raise NormalizationError(f"unsupported A-share symbol prefix: {symbol}")


def _records(submission: RawCaptureSubmission) -> tuple[Mapping[str, object], ...]:
    metadata = submission.source_metadata
    if metadata.get("schema_id") != _RAW_SCHEMA_ID:
        raise NormalizationError("unsupported raw provider schema")
    payload = metadata.get("raw_payload")
    if not isinstance(payload, Mapping):
        raise NormalizationError("raw payload is unavailable")
    if canonical_sha256(payload) != submission.envelope.content_hash:
        raise NormalizationError("raw payload no longer matches immutable capture identity")
    observed = payload.get("records")
    if not isinstance(observed, Sequence) or isinstance(observed, (str, bytes, bytearray)):
        raise NormalizationError("raw payload records must be a sequence")
    rows: list[Mapping[str, object]] = []
    for row in observed:
        if not isinstance(row, Mapping):
            raise NormalizationError("raw provider row must be a mapping")
        absent = _REQUIRED_COLUMNS - set(row)
        if absent:
            raise NormalizationError(
                f"provider schema is missing required columns: {','.join(sorted(absent))}"
            )
        rows.append(row)
    return tuple(rows)


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
    row: Mapping[str, object],
    submission: RawCaptureSubmission,
    *,
    acquisition_id: str,
    acquisition_time: datetime,
) -> NormalizedEodObservation:
    symbol = str(row["股票代码"])
    exchange = _exchange(symbol)
    try:
        session_date = date.fromisoformat(str(row["日期"]))
    except ValueError as error:
        raise NormalizationError("日期 must use ISO calendar date") from error
    missing: list[MissingField] = []
    open_price = _decimal(row, "开盘", "open", missing)
    close_price = _decimal(row, "收盘", "close", missing)
    high = _decimal(row, "最高", "high", missing)
    low = _decimal(row, "最低", "low", missing)
    volume = _volume(row, missing)
    amount = _decimal(row, "成交额", "amount", missing)
    missing.append(
        MissingField("trading_status", MissingValueReason.PROVIDER_COLUMN_ABSENT)
    )
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
        available_time=None,
        acquisition_time=acquisition_time,
        acquisition_id=acquisition_id,
        revision_id=None,
        raw_capture_id=submission.envelope.raw_capture_id,
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
        "pit_evidence": PitEvidenceState.UNKNOWN,
        "revision_evidence": PitEvidenceState.UNKNOWN,
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
        pit_evidence=PitEvidenceState.UNKNOWN,
        revision_evidence=PitEvidenceState.UNKNOWN,
        reason_codes=(
            "PROVIDER_AVAILABLE_TIME_UNKNOWN",
            "PROVIDER_REVISION_UNKNOWN",
            "PROVIDER_DATA_IS_NOT_CANONICAL_MARKET_TRUTH",
        ),
        research_universe_input=universe_input,
    )
