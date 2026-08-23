"""Thin, optional AKShare adapter for unadjusted A-share daily/EOD captures."""

from __future__ import annotations

import hashlib
import importlib
import math
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from ...domain.data_truth import (
    ConnectorDataCapability,
    ProviderDescriptor,
    RawCaptureEnvelope,
    RevisionSemantics,
)
from ...domain.data_truth.capabilities import (
    AvailableTimeSemantics,
    FieldCapability,
    FieldCapabilityPolicy,
    FieldCapabilityState,
    MarketDataFieldCode,
    SourceCostClass,
)
from ...domain.data_truth.provider import (
    PROVIDER_NEUTRAL_EOD_CONTRACT,
    ProviderNeutralEodRow,
    ProviderNeutralObservationBatch,
    RawCaptureSubmission,
)
from ...provenance.canonical_hash import canonical_json_bytes, canonical_sha256


AKSHARE_PROVIDER_VERSION = "1.18.84"
AKSHARE_PROVIDER_REPOSITORY_REVISION = (
    "1a0c07ca4017f26f8dc817829b074d857227f562"
)
_PROVIDER_ID = "pvd_akshare_eastmoney_a_share_eod_v1"
_PROVIDER_DATASET = "CN_A_SHARE_EOD"
_RAW_SCHEMA_ID = "akshare-stock-zh-a-hist-raw-v1"
_SOURCE_AUTHORITY = "Eastmoney via AKShare stock_zh_a_hist"
_ENDPOINT = "stock_zh_a_hist"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


class ProviderAcquisitionError(RuntimeError):
    """The selected provider did not produce a valid bounded capture."""


class ProviderDependencyUnavailable(ProviderAcquisitionError):
    """The optional provider dependency is unavailable."""


class ProviderVersionMismatch(ProviderAcquisitionError):
    """The loaded provider version differs from the admitted adapter version."""


def _default_loader() -> object:
    try:
        return importlib.import_module("akshare")
    except (ImportError, ModuleNotFoundError) as error:
        raise ProviderDependencyUnavailable(
            "AKShare is optional; install the exact admitted version in an isolated runtime"
        ) from error


def _aware_now() -> datetime:
    return datetime.now().astimezone()


def _wire_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat(timespec="microseconds")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is not value:
            return _wire_value(scalar)
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return None
    raise ProviderAcquisitionError(
        f"unsupported provider cell type: {value.__class__.__name__}"
    )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    return value


def _request(request: Mapping[str, Any]) -> dict[str, object]:
    allowed = {"symbol", "period", "start_date", "end_date", "adjust", "timeout"}
    unknown = set(request) - allowed
    if unknown:
        raise ProviderAcquisitionError(
            f"unsupported AKShare request keys: {','.join(sorted(unknown))}"
        )
    required = {"symbol", "start_date", "end_date"}
    missing = required - set(request)
    if missing:
        raise ProviderAcquisitionError(
            f"missing AKShare request keys: {','.join(sorted(missing))}"
        )
    symbol = str(request["symbol"])
    if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
        raise ProviderAcquisitionError("symbol must be exactly six ASCII digits")
    period = str(request.get("period", "daily"))
    adjust = str(request.get("adjust", ""))
    if period != "daily":
        raise ProviderAcquisitionError("V0 admits daily period only")
    if adjust != "":
        raise ProviderAcquisitionError(
            "V0 admits unadjusted prices only; adjustment evidence is out of scope"
        )
    start_date = str(request["start_date"])
    end_date = str(request["end_date"])
    try:
        start = datetime.strptime(start_date, "%Y%m%d").date()
        end = datetime.strptime(end_date, "%Y%m%d").date()
    except ValueError as error:
        raise ProviderAcquisitionError("dates must use YYYYMMDD") from error
    if end < start:
        raise ProviderAcquisitionError("end_date cannot precede start_date")
    timeout = request.get("timeout")
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ProviderAcquisitionError("timeout must be a positive number or null")
        if timeout <= 0 or not math.isfinite(float(timeout)):
            raise ProviderAcquisitionError("timeout must be a positive finite number")
    return {
        "symbol": symbol,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "adjust": adjust,
        "timeout": timeout,
    }


def _records(frame: object) -> tuple[dict[str, object], ...]:
    to_dict = getattr(frame, "to_dict", None)
    if not callable(to_dict):
        raise ProviderAcquisitionError("AKShare response must support to_dict(orient='records')")
    try:
        observed = to_dict(orient="records")
    except Exception as error:  # provider boundary: preserve cause without fallback
        raise ProviderAcquisitionError("AKShare response could not be materialized") from error
    if not isinstance(observed, list):
        raise ProviderAcquisitionError("AKShare response records must be a list")
    normalized: list[dict[str, object]] = []
    for index, row in enumerate(observed):
        if not isinstance(row, Mapping):
            raise ProviderAcquisitionError(f"AKShare row {index} must be a mapping")
        normalized.append({str(key): _wire_value(value) for key, value in row.items()})
    normalized.sort(
        key=lambda row: (
            str(row.get("股票代码", "")),
            str(row.get("日期", "")),
            canonical_sha256(row),
        )
    )
    return tuple(normalized)


def _range(records: Sequence[Mapping[str, object]]) -> tuple[datetime | None, datetime | None]:
    dates: list[date] = []
    for row in records:
        value = row.get("日期")
        if value is None:
            continue
        try:
            dates.append(date.fromisoformat(str(value)))
        except ValueError as error:
            raise ProviderAcquisitionError("AKShare 日期 must use ISO calendar dates") from error
    if not dates:
        return None, None
    return (
        datetime.combine(min(dates), time(15, 0), tzinfo=_SHANGHAI),
        datetime.combine(max(dates), time(15, 0), tzinfo=_SHANGHAI),
    )


def _provider_neutral_rows(
    records: Sequence[Mapping[str, object]],
) -> tuple[ProviderNeutralEodRow, ...]:
    rows: list[ProviderNeutralEodRow] = []
    semantics = {
        "open": "AKShare.stock_zh_a_hist.开盘",
        "high": "AKShare.stock_zh_a_hist.最高",
        "low": "AKShare.stock_zh_a_hist.最低",
        "close": "AKShare.stock_zh_a_hist.收盘",
        "volume": "AKShare.stock_zh_a_hist.成交量",
        "amount": "AKShare.stock_zh_a_hist.成交额",
    }
    for row in records:
        try:
            session_date = date.fromisoformat(str(row["日期"]))
        except (KeyError, ValueError) as error:
            raise ProviderAcquisitionError("AKShare 日期 must use ISO calendar dates") from error
        rows.append(
            ProviderNeutralEodRow(
                symbol=str(row.get("股票代码", "")),
                session_date=session_date,
                open=row.get("开盘"),
                high=row.get("最高"),
                low=row.get("最低"),
                close=row.get("收盘"),
                volume=row.get("成交量"),
                amount=row.get("成交额"),
                trading_status=None,
                available_time=None,
                revision_id=None,
                source_semantics=semantics,
                missing_reasons={
                    "trading_status": "PROVIDER_COLUMN_ABSENT",
                    "available_time": "PROVIDER_FIELD_UNAVAILABLE",
                    "revision_id": "PROVIDER_FIELD_UNAVAILABLE",
                },
            )
        )
    return tuple(rows)


class AkshareAShareEodAdapter:
    """Capture one explicit AKShare source without automatic fallback."""

    def __init__(
        self,
        *,
        connector_version_id: str,
        loader: Callable[[], object] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not connector_version_id.startswith("cov_"):
            raise ValueError("connector_version_id must identify an exact ConnectorVersion")
        self._connector_version_id = connector_version_id
        self._loader = loader or _default_loader
        self._clock = clock or _aware_now

    def descriptor(self) -> ProviderDescriptor:
        metadata = {
            "adapter_schema": _RAW_SCHEMA_ID,
            "endpoint": _ENDPOINT,
            "provider_package": "akshare",
            "source_authority": _SOURCE_AUTHORITY,
        }
        return ProviderDescriptor(
            provider_id=_PROVIDER_ID,
            stable_name="akshare-eastmoney-a-share-eod",
            source_authority=_SOURCE_AUTHORITY,
            metadata_hash=canonical_sha256(metadata),
        )

    def capabilities(self) -> tuple[ConnectorDataCapability, ...]:
        policy = self.field_capability_policy()
        return (
            ConnectorDataCapability(
                connector_version_id=self._connector_version_id,
                provider_id=_PROVIDER_ID,
                capability_code=_PROVIDER_DATASET,
                logical_dataset=_PROVIDER_DATASET,
                frequency="P1D",
                revision_semantics=RevisionSemantics.UNKNOWN,
                provenance_required=True,
                policy_artifact_id=policy.policy_artifact_id,
            ),
        )

    def field_capability_policy(self) -> FieldCapabilityPolicy:
        available = {
            MarketDataFieldCode.OHLC: "open/high/low/close",
            MarketDataFieldCode.VOLUME: "volume",
            MarketDataFieldCode.AMOUNT: "amount",
        }
        unavailable_reasons = {
            MarketDataFieldCode.TRADING_CALENDAR: "DATASET_DOES_NOT_DECLARE_CALENDAR",
            MarketDataFieldCode.TRADING_SESSION: "DATASET_DOES_NOT_DECLARE_SESSION",
            MarketDataFieldCode.TRADING_STATUS: "PROVIDER_COLUMN_ABSENT",
            MarketDataFieldCode.SUSPENSION_STATUS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.TRADABILITY: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.SECURITY_TYPE: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.BOARD: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.LISTING_STATUS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.DELISTING_STATUS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.ST_OR_RESTRICTED_STATUS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.PRICE_LIMIT_RULE_INPUTS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.NO_PRICE_LIMIT_SESSION_INPUTS: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.CORPORATE_ACTION: "DATASET_DOES_NOT_DECLARE_CORPORATE_ACTION",
            MarketDataFieldCode.ADJUSTMENT_FACTOR: "UNADJUSTED_DATASET_ONLY",
            MarketDataFieldCode.UNIVERSE_MEMBERSHIP: "OBSERVED_SYMBOLS_ARE_NOT_UNIVERSE_AUTHORITY",
            MarketDataFieldCode.AVAILABLE_TIME: "PROVIDER_FIELD_UNAVAILABLE",
            MarketDataFieldCode.REVISION_ID: "PROVIDER_FIELD_UNAVAILABLE",
        }
        fields = [
            FieldCapability(
                field_code=code,
                state=FieldCapabilityState.AVAILABLE,
                source_field_semantic=semantic,
                available_time_semantics=AvailableTimeSemantics.NOT_PROVIDED,
                revision_semantics=RevisionSemantics.UNKNOWN,
                provenance_required=True,
            )
            for code, semantic in available.items()
        ]
        fields.extend(
            FieldCapability(
                field_code=code,
                state=FieldCapabilityState.UNAVAILABLE,
                source_field_semantic=None,
                available_time_semantics=AvailableTimeSemantics.NOT_PROVIDED,
                revision_semantics=RevisionSemantics.UNKNOWN,
                provenance_required=True,
                reason_code=reason,
            )
            for code, reason in unavailable_reasons.items()
        )
        fields.extend(
            (
                FieldCapability(
                    field_code=MarketDataFieldCode.REVISION_SEMANTICS,
                    state=FieldCapabilityState.UNKNOWN,
                    source_field_semantic=None,
                    available_time_semantics=AvailableTimeSemantics.NOT_PROVIDED,
                    revision_semantics=RevisionSemantics.UNKNOWN,
                    provenance_required=True,
                    reason_code="PROVIDER_REVISION_SEMANTICS_UNKNOWN",
                ),
                FieldCapability(
                    field_code=MarketDataFieldCode.PIT_VISIBILITY,
                    state=FieldCapabilityState.UNKNOWN,
                    source_field_semantic=None,
                    available_time_semantics=AvailableTimeSemantics.UNKNOWN,
                    revision_semantics=RevisionSemantics.UNKNOWN,
                    provenance_required=True,
                    reason_code="PROVIDER_PIT_EVIDENCE_UNKNOWN",
                ),
            )
        )
        return FieldCapabilityPolicy(
            policy_version="akshare-eastmoney-a-share-eod-field-policy-v1",
            connector_version_id=self._connector_version_id,
            provider_id=_PROVIDER_ID,
            logical_dataset=_PROVIDER_DATASET,
            frequency="P1D",
            normalization_contract_version=PROVIDER_NEUTRAL_EOD_CONTRACT,
            source_cost_class=SourceCostClass.FREE,
            fields=tuple(fields),
        )

    def capture(self, request: Mapping[str, Any]) -> RawCaptureSubmission:
        canonical_request = _request(request)
        acquired_at = self._clock()
        if acquired_at.tzinfo is None or acquired_at.utcoffset() is None:
            raise ProviderAcquisitionError("acquisition clock must be timezone-aware")
        try:
            provider = self._loader()
        except ProviderAcquisitionError:
            raise
        except Exception as error:
            raise ProviderDependencyUnavailable("AKShare could not be loaded") from error
        version = getattr(provider, "__version__", None)
        if version != AKSHARE_PROVIDER_VERSION:
            raise ProviderVersionMismatch(
                f"expected AKShare {AKSHARE_PROVIDER_VERSION}, observed {version!r}"
            )
        source_kind = getattr(provider, "__v3_source_kind__", "REAL_EXTERNAL_PROVIDER")
        if source_kind not in {"REAL_EXTERNAL_PROVIDER", "TEST_EXTERNAL_PROVIDER_BOUNDARY"}:
            raise ProviderAcquisitionError("AKShare source kind is not admitted")
        endpoint = getattr(provider, _ENDPOINT, None)
        if not callable(endpoint):
            raise ProviderDependencyUnavailable(f"AKShare {_ENDPOINT} is unavailable")
        try:
            frame = endpoint(**canonical_request)
        except Exception as error:
            raise ProviderAcquisitionError(
                "AKShare acquisition failed; automatic fallback is forbidden"
            ) from error
        records = _records(frame)
        observations = ProviderNeutralObservationBatch(
            logical_dataset=_PROVIDER_DATASET,
            frequency="P1D",
            rows=_provider_neutral_rows(records),
        )
        raw_payload = {
            "schema_id": _RAW_SCHEMA_ID,
            "provider": {
                "provider_id": _PROVIDER_ID,
                "package": "akshare",
                "package_version": version,
                "repository_revision": AKSHARE_PROVIDER_REPOSITORY_REVISION,
                "source_authority": _SOURCE_AUTHORITY,
                "endpoint": _ENDPOINT,
                "source_kind": source_kind,
            },
            "records": records,
            "provider_neutral_observations": observations.to_wire(),
        }
        payload_bytes = canonical_json_bytes(raw_payload)
        content_hash = hashlib.sha256(payload_bytes).hexdigest()
        raw_capture_id = "raw_sha256_" + content_hash
        range_start, range_end = _range(records)
        request_fingerprint = canonical_sha256(canonical_request)
        acquisition_id = "acq_sha256_" + canonical_sha256(
            {
                "provider_id": _PROVIDER_ID,
                "provider_version": version,
                "request_fingerprint": request_fingerprint,
                "acquired_at": acquired_at,
            }
        )
        envelope = RawCaptureEnvelope(
            raw_capture_id=raw_capture_id,
            provider_id=_PROVIDER_ID,
            connector_version_id=self._connector_version_id,
            provider_dataset=_PROVIDER_DATASET,
            artifact_id="art_sha256_" + content_hash,
            effective_range_start=range_start,
            effective_range_end=range_end,
            available_time=None,
            ingested_at=acquired_at,
            content_hash=content_hash,
            provider_revision_id=None,
        )
        metadata = {
            "schema_id": _RAW_SCHEMA_ID,
            "acquisition_id": acquisition_id,
            "acquired_at": acquired_at,
            "request": canonical_request,
            "request_fingerprint": request_fingerprint,
            "provider_package_version": version,
            "source_kind": source_kind,
            "provider_repository_revision": AKSHARE_PROVIDER_REPOSITORY_REVISION,
            "provider_response_revision": None,
            "available_time_evidence": "UNKNOWN",
            "revision_evidence": "UNKNOWN",
            "provenance_complete": False,
            "field_capability_policy_artifact_id": self.field_capability_policy().policy_artifact_id,
            "raw_payload": raw_payload,
        }
        return RawCaptureSubmission(
            envelope=envelope,
            source_metadata=_freeze(metadata),
            observations=observations,
        )
