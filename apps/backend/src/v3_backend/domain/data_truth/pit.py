from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from .model import (
    CanonicalEodRecord,
    ExecutionPriceBasis,
    InstrumentLifecycle,
    UniverseMembershipInterval,
)


class PitCapabilityUnavailable(RuntimeError):
    """Strict PIT cannot be proven and therefore fails closed."""


class AdjustmentDoubleCountError(ValueError):
    pass


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")


def resolve_eod_as_of(
    records: Iterable[CanonicalEodRecord], decision_time: datetime, *, strict: bool = True
) -> tuple[CanonicalEodRecord, ...]:
    """Resolve the newest visible revision without admitting future knowledge."""
    _aware(decision_time)
    selected: dict[tuple[str, str], CanonicalEodRecord] = {}
    for record in records:
        if record.effective_time > decision_time:
            continue
        if record.available_time is None:
            if strict:
                raise PitCapabilityUnavailable(
                    f"available_time unavailable for {record.instrument_id}/{record.session_id}"
                )
            continue
        if record.available_time > decision_time:
            continue
        key = (record.instrument_id, record.session_id)
        current = selected.get(key)
        rank = (record.available_time, record.ingested_at, record.revision_id, record.content_hash)
        if current is None or rank > (
            current.available_time,
            current.ingested_at,
            current.revision_id,
            current.content_hash,
        ):
            selected[key] = record
    return tuple(selected[key] for key in sorted(selected))


def resolve_universe_as_of(
    memberships: Iterable[UniverseMembershipInterval],
    *,
    as_of: date,
    decision_time: datetime,
    instruments: Iterable[InstrumentLifecycle] = (),
    strict: bool = True,
) -> tuple[str, ...]:
    """Resolve historical membership; current membership is never backfilled."""
    _aware(decision_time)
    lifecycle = {item.instrument_id: item for item in instruments}
    selected: dict[str, UniverseMembershipInterval] = {}
    for membership in memberships:
        if not membership.contains(as_of):
            continue
        if membership.available_time is None:
            if strict:
                raise PitCapabilityUnavailable(
                    f"available_time unavailable for Universe member {membership.instrument_id}"
                )
            continue
        if membership.available_time > decision_time:
            continue
        instrument = lifecycle.get(membership.instrument_id)
        if instrument is not None and not instrument.is_listed_on(as_of):
            continue
        current = selected.get(membership.instrument_id)
        if current is None or (
            membership.available_time,
            membership.revision_id,
        ) > (current.available_time, current.revision_id):
            selected[membership.instrument_id] = membership
    return tuple(sorted(selected))


def assert_execution_price_policy(
    price_basis: ExecutionPriceBasis | str, *, apply_corporate_actions: bool
) -> None:
    basis = price_basis if isinstance(price_basis, ExecutionPriceBasis) else ExecutionPriceBasis(price_basis)
    if basis is ExecutionPriceBasis.ADJUSTED and apply_corporate_actions:
        raise AdjustmentDoubleCountError(
            "adjusted execution prices and corporate-action ledger cannot both affect returns"
        )
