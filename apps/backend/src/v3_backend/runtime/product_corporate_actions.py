"""Project-scoped PRE_ALPHA Corporate Action payload ownership for Product Backtest."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Mapping

from v3_backend.domain.backtest_runtime import CorporateAction, CorporateActionType
from v3_backend.errors.exceptions import (
    CapabilityUnavailableError,
    InvalidArgumentError,
    NotFoundError,
    TruthPreconditionFailedError,
)
from v3_backend.provenance.canonical_hash import canonical_json_bytes, canonical_sha256

if TYPE_CHECKING:
    from .product_factor import ResolvedLocalSnapshotPanel
    from .product_runtime import ProductRuntime


CORPORATE_ACTION_SET_ROLE = "DATA_TRUTH_CORPORATE_ACTION_SET"
CORPORATE_ACTION_SET_SCHEMA = "v3.product-corporate-action-set/1.1.0"
_REF_PATTERN = re.compile(r"cax_sha256_[0-9a-f]{64}")
_INSTRUMENT_PATTERN = re.compile(r"ins_cn_(?:sse|szse|bse)_[0-9]{6}")
_EVENT_KEYS = {
    "instrument_id",
    "ex_date",
    "action_type",
    "cash_per_share",
    "ratio_numerator",
    "ratio_denominator",
}
_KNOWN_ACTION_TYPES = {
    "CASH_DIVIDEND",
    "BONUS_OR_SPLIT",
    "RIGHTS_ISSUE",
    "DELISTING",
    "OTHER",
}
_SUPPORTED_ACTION_TYPES = {"CASH_DIVIDEND", "BONUS_OR_SPLIT"}
_MAX_ACTION_SET_BYTES = 1024 * 1024


def _decimal_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InvalidArgumentError(f"{name} must be canonical decimal text")
    try:
        observed = Decimal(value)
    except InvalidOperation as error:
        raise InvalidArgumentError(f"{name} must be canonical decimal text") from error
    if not observed.is_finite() or observed < 0:
        raise InvalidArgumentError(f"{name} must be finite and non-negative")
    normalized = format(observed.normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InvalidArgumentError(f"{name} must be a positive integer")
    return value


def _canonical_event(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _EVENT_KEYS:
        raise InvalidArgumentError("Corporate Action event does not match the closed shape")
    instrument_id = value["instrument_id"]
    if not isinstance(instrument_id, str) or _INSTRUMENT_PATTERN.fullmatch(instrument_id) is None:
        raise InvalidArgumentError("Corporate Action instrument_id is not canonical A-share")
    ex_date = value["ex_date"]
    if not isinstance(ex_date, str):
        raise InvalidArgumentError("Corporate Action ex_date must be ISO text")
    try:
        date.fromisoformat(ex_date)
    except ValueError as error:
        raise InvalidArgumentError("Corporate Action ex_date is invalid") from error
    action_type = value["action_type"]
    if not isinstance(action_type, str) or action_type not in _KNOWN_ACTION_TYPES:
        raise InvalidArgumentError("Corporate Action type is unknown")
    cash_per_share = _decimal_text(value["cash_per_share"], "cash_per_share")
    ratio_numerator = _positive_int(value["ratio_numerator"], "ratio_numerator")
    ratio_denominator = _positive_int(value["ratio_denominator"], "ratio_denominator")
    if action_type == "CASH_DIVIDEND":
        if Decimal(cash_per_share) <= 0 or (ratio_numerator, ratio_denominator) != (1, 1):
            raise InvalidArgumentError("cash dividend semantics are inconsistent")
    elif action_type == "BONUS_OR_SPLIT":
        if Decimal(cash_per_share) != 0 or ratio_numerator == ratio_denominator:
            raise InvalidArgumentError("bonus/split semantics are inconsistent")
    elif Decimal(cash_per_share) != 0 or (ratio_numerator, ratio_denominator) != (1, 1):
        raise InvalidArgumentError("unsupported Corporate Action payload is inconsistent")
    semantic = {
        "instrument_id": instrument_id,
        "ex_date": ex_date,
        "action_type": action_type,
        "cash_per_share": cash_per_share,
        "ratio_numerator": ratio_numerator,
        "ratio_denominator": ratio_denominator,
    }
    return {"action_id": "cae_sha256_" + canonical_sha256(semantic), **semantic}


@dataclass(frozen=True, slots=True)
class ResolvedProductCorporateActions:
    set_ids: tuple[str, ...]
    events_by_date: Mapping[date, tuple[CorporateAction, ...]]
    source_id: str
    content_sha256: str
    event_count: int

    @classmethod
    def empty(cls) -> "ResolvedProductCorporateActions":
        digest = canonical_sha256(
            {"schema_version": "v3.corporate-actions-empty/1.0.0", "rows": []}
        )
        return cls((), {}, "cax_sha256_" + digest, digest, 0)


class ProductCorporateActionService:
    """Publish and resolve actual action-set bytes without treating a ref as payload."""

    def __init__(self, product: ProductRuntime) -> None:
        self.product = product

    def publish_set(
        self,
        *,
        project_id: str,
        events: tuple[Mapping[str, object], ...],
    ) -> dict[str, object]:
        self.product.require_project(project_id)
        if not events:
            raise InvalidArgumentError("Corporate Action set must be non-empty")
        canonical_events = tuple(_canonical_event(value) for value in events)
        canonical_events = tuple(
            sorted(
                canonical_events,
                key=lambda item: (
                    str(item["ex_date"]),
                    str(item["instrument_id"]),
                    str(item["action_id"]),
                ),
            )
        )
        action_ids = tuple(str(item["action_id"]) for item in canonical_events)
        if len(action_ids) != len(set(action_ids)):
            raise InvalidArgumentError("Corporate Action events must be unique")
        payload = canonical_json_bytes(
            {
                "schema_version": CORPORATE_ACTION_SET_SCHEMA,
                "project_id": project_id,
                "truth": "NOT_FORMAL",
                "admission": "PRE_ALPHA",
                "events": canonical_events,
            }
        )
        digest = canonical_sha256(json.loads(payload.decode("utf-8")))
        set_id = "cax_sha256_" + digest
        published = self.product.execution._publish_artifact_batch(
            payloads=(
                (
                    set_id,
                    payload,
                    CORPORATE_ACTION_SET_ROLE,
                    canonical_sha256({"schema_version": CORPORATE_ACTION_SET_SCHEMA}),
                ),
            ),
            references=((project_id, CORPORATE_ACTION_SET_ROLE, 0),),
        )[0]
        if published.descriptor.artifact_id != "art_sha256_" + digest:
            raise TruthPreconditionFailedError("Corporate Action Artifact identity mismatch")
        return {
            "corporate_action_set_id": set_id,
            "artifact_id": published.descriptor.artifact_id,
            "content_sha256": digest,
            "event_count": len(canonical_events),
            "truth": "NOT_FORMAL",
            "admission": "PRE_ALPHA",
        }

    def preflight_refs(self, *, project_id: str, refs: tuple[str, ...]) -> None:
        if not refs:
            return
        for ref in refs:
            payload = self._load_set(project_id=project_id, set_id=ref)
            for event in payload["events"]:
                action_type = str(event["action_type"])
                if action_type not in _SUPPORTED_ACTION_TYPES:
                    raise CapabilityUnavailableError(
                        f"{action_type} Corporate Action is not admitted",
                        details={"reason_code": "CORPORATE_ACTION_NOT_AVAILABLE"},
                    )
                if action_type == "BONUS_OR_SPLIT" and int(event["ratio_denominator"]) != 1:
                    raise CapabilityUnavailableError(
                        "fractional Corporate Action entitlement is not admitted",
                        details={"reason_code": "CORPORATE_ACTION_NOT_AVAILABLE"},
                    )

    def resolve_for_panel(
        self,
        *,
        project_id: str,
        panel: ResolvedLocalSnapshotPanel,
        session_start: date,
        session_end: date,
    ) -> ResolvedProductCorporateActions:
        referenced_rows: dict[str, set[tuple[date, str]]] = {}
        for row in panel.market_rows:
            if row.corporate_action_ref is not None:
                referenced_rows.setdefault(row.corporate_action_ref, set()).add(
                    (row.session_date, row.instrument_id)
                )
        refs = tuple(sorted(referenced_rows))
        if not refs:
            return ResolvedProductCorporateActions.empty()
        self.preflight_refs(project_id=project_id, refs=refs)
        events: list[CorporateAction] = []
        matched_rows: dict[str, set[tuple[date, str]]] = {ref: set() for ref in refs}
        for ref in refs:
            payload = self._load_set(project_id=project_id, set_id=ref)
            for item in payload["events"]:
                event_date = date.fromisoformat(str(item["ex_date"]))
                instrument_id = str(item["instrument_id"])
                key = (event_date, instrument_id)
                if key not in referenced_rows[ref]:
                    raise TruthPreconditionFailedError(
                        "Corporate Action event is not bound to its exact Snapshot row"
                    )
                matched_rows[ref].add(key)
                if session_start <= event_date <= session_end:
                    events.append(
                        CorporateAction(
                            action_id=str(item["action_id"]),
                            instrument_id=instrument_id,
                            ex_date=event_date,
                            action_type=CorporateActionType(str(item["action_type"])),
                            cash_per_share=str(item["cash_per_share"]),
                            ratio_numerator=int(item["ratio_numerator"]),
                            ratio_denominator=int(item["ratio_denominator"]),
                        )
                    )
        if any(matched_rows[ref] != referenced_rows[ref] for ref in refs):
            raise TruthPreconditionFailedError(
                "Snapshot Corporate Action ref has no exact owner event payload"
            )
        events.sort(key=lambda item: (item.ex_date, item.action_id))
        if len({item.action_id for item in events}) != len(events):
            raise TruthPreconditionFailedError("Corporate Action IDs are not unique")
        grouped: dict[date, list[CorporateAction]] = {}
        for event in events:
            grouped.setdefault(event.ex_date, []).append(event)
        aggregate = (
            refs[0].removeprefix("cax_sha256_")
            if len(refs) == 1
            else canonical_sha256(
                {
                    "schema_version": "v3.product-corporate-action-resolution/1.0.0",
                    "set_ids": refs,
                }
            )
        )
        return ResolvedProductCorporateActions(
            refs,
            {key: tuple(value) for key, value in grouped.items()},
            "cax_sha256_" + aggregate,
            aggregate,
            len(events),
        )

    def _load_set(self, *, project_id: str, set_id: str) -> Mapping[str, object]:
        if not isinstance(set_id, str) or _REF_PATTERN.fullmatch(set_id) is None:
            raise TruthPreconditionFailedError("Corporate Action ref is not canonical")
        digest = set_id.removeprefix("cax_sha256_")
        artifact_id = "art_sha256_" + digest
        try:
            descriptor = self.product.require_project_reachable_artifact(
                project_id, artifact_id
            )
        except NotFoundError as error:
            raise CapabilityUnavailableError(
                "known corporate-action refs require an admitted Corporate Action owner",
                details={"reason_code": "CORPORATE_ACTION_NOT_AVAILABLE"},
            ) from error
        if (
            descriptor["semantic_role"] != CORPORATE_ACTION_SET_ROLE
            or descriptor["sha256"] != digest
            or int(descriptor["byte_size"]) > _MAX_ACTION_SET_BYTES
            or descriptor["schema_fingerprint"]
            != canonical_sha256({"schema_version": CORPORATE_ACTION_SET_SCHEMA})
        ):
            raise TruthPreconditionFailedError("Corporate Action descriptor binding mismatch")
        connection = self.product._connection(read_only=True)
        try:
            project_owner = connection.execute(
                """
                SELECT 1 FROM artifact_reference
                WHERE owner_type='Project' AND owner_id=? AND role=?
                  AND artifact_id=? AND state='ACTIVE'
                """,
                (project_id, CORPORATE_ACTION_SET_ROLE, artifact_id),
            ).fetchone()
        finally:
            connection.close()
        if project_owner is None:
            raise TruthPreconditionFailedError(
                "Corporate Action Artifact lacks its exact project owner reference"
            )
        try:
            raw = self.product.read_verified_bytes(artifact_id)
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError) as error:
            raise TruthPreconditionFailedError("Corporate Action owner bytes are invalid") from error
        if canonical_json_bytes(value) != raw:
            raise TruthPreconditionFailedError("Corporate Action owner bytes are not canonical")
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "project_id",
            "truth",
            "admission",
            "events",
        }:
            raise TruthPreconditionFailedError("Corporate Action owner shape is invalid")
        if (
            value["schema_version"] != CORPORATE_ACTION_SET_SCHEMA
            or value["project_id"] != project_id
            or value["truth"] != "NOT_FORMAL"
            or value["admission"] != "PRE_ALPHA"
            or not isinstance(value["events"], list)
            or not value["events"]
        ):
            raise TruthPreconditionFailedError("Corporate Action owner semantics are invalid")
        observed = tuple(value["events"])
        try:
            rebuilt = tuple(
                _canonical_event({key: item[key] for key in _EVENT_KEYS})
                if isinstance(item, dict) and set(item) == {*_EVENT_KEYS, "action_id"}
                else None
                for item in observed
            )
        except (KeyError, InvalidArgumentError) as error:
            raise TruthPreconditionFailedError(
                "Corporate Action events are invalid"
            ) from error
        if any(item is None for item in rebuilt) or tuple(rebuilt) != observed:
            raise TruthPreconditionFailedError("Corporate Action events are not canonical")
        if tuple(observed) != tuple(
            sorted(
                observed,
                key=lambda item: (
                    str(item["ex_date"]),
                    str(item["instrument_id"]),
                    str(item["action_id"]),
                ),
            )
        ):
            raise TruthPreconditionFailedError("Corporate Action events are not ordered")
        return value


__all__ = [
    "CORPORATE_ACTION_SET_ROLE",
    "CORPORATE_ACTION_SET_SCHEMA",
    "ProductCorporateActionService",
    "ResolvedProductCorporateActions",
]
