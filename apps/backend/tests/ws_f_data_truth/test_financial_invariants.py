from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from v3_backend.domain.data_truth import (
    AdjustmentDoubleCountError,
    CanonicalEodRecord,
    ExecutionPriceBasis,
    InstrumentLifecycle,
    PitCapabilityUnavailable,
    TradingStatus,
    UniverseMembershipInterval,
    assert_execution_price_policy,
    resolve_eod_as_of,
    resolve_universe_as_of,
)


UTC = timezone.utc


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def record(
    revision: str,
    *,
    available: datetime | None,
    effective: datetime | None = None,
    close: str = "10",
) -> CanonicalEodRecord:
    return CanonicalEodRecord(
        instrument_id="ins_test",
        session_id="trs_20200102",
        open=Decimal("9"),
        high=Decimal("11"),
        low=Decimal("8"),
        close=Decimal(close),
        volume=100,
        amount=Decimal("1000"),
        trading_status=TradingStatus.TRADING,
        raw_capture_id="raw_test",
        effective_time=effective or at("2020-01-02T15:00:00"),
        available_time=available,
        revision_id=revision,
        provider="TEST",
        ingested_at=(available or at("2020-01-03T00:00:00")),
        content_hash=("a" if revision == "r1" else "b") * 64,
    )


class PointInTimeTests(unittest.TestCase):
    def test_available_time_missing_fails_closed(self) -> None:
        with self.assertRaises(PitCapabilityUnavailable):
            resolve_eod_as_of(
                [record("r1", available=None)], at("2020-01-03T12:00:00")
            )

    def test_no_future_data_and_revision_as_of(self) -> None:
        original = record("r1", available=at("2020-01-03T08:00:00"), close="10")
        revision = record("r2", available=at("2020-01-10T08:00:00"), close="10.5")
        future = record(
            "r3",
            available=at("2020-01-04T08:00:00"),
            effective=at("2020-02-01T15:00:00"),
            close="10.8",
        )
        early = resolve_eod_as_of([original, revision, future], at("2020-01-05T00:00:00"))
        late = resolve_eod_as_of([original, revision, future], at("2020-01-11T00:00:00"))
        self.assertEqual([row.revision_id for row in early], ["r1"])
        self.assertEqual([row.revision_id for row in late], ["r2"])
        self.assertTrue(all(row.effective_time <= at("2020-01-11T00:00:00") for row in late))
        self.assertTrue(all(row.available_time <= at("2020-01-11T00:00:00") for row in late))

    def test_listing_lifecycle_is_historical(self) -> None:
        lifecycle = InstrumentLifecycle(
            "ins_old", date(2010, 1, 1), date(2020, 12, 31), "SSE", "MAIN", "EQUITY"
        )
        self.assertFalse(lifecycle.is_listed_on(date(2009, 12, 31)))
        self.assertTrue(lifecycle.is_listed_on(date(2020, 6, 30)))
        self.assertFalse(lifecycle.is_listed_on(date(2021, 1, 1)))

    def test_historical_universe_prevents_survivorship_backfill(self) -> None:
        evidence = "art_sha256_" + "c" * 64
        memberships = [
            UniverseMembershipInterval(
                "unv_test", "umf_old", "ins_old", date(2010, 1, 1), date(2021, 1, 1),
                at("2010-01-01T00:00:00"), "old-v1", "INCLUDED", evidence,
            ),
            UniverseMembershipInterval(
                "unv_test", "umf_new", "ins_new", date(2021, 1, 1), None,
                at("2021-01-01T00:00:00"), "new-v1", "INCLUDED", evidence,
            ),
        ]
        lifecycles = [
            InstrumentLifecycle("ins_old", date(2010, 1, 1), date(2020, 12, 31), "SSE", "MAIN", "EQUITY"),
            InstrumentLifecycle("ins_new", date(2021, 1, 1), None, "SSE", "STAR", "EQUITY"),
        ]
        historical = resolve_universe_as_of(
            memberships,
            as_of=date(2020, 6, 30),
            decision_time=at("2020-06-30T23:00:00"),
            instruments=lifecycles,
        )
        current = resolve_universe_as_of(
            memberships,
            as_of=date(2022, 6, 30),
            decision_time=at("2022-06-30T23:00:00"),
            instruments=lifecycles,
        )
        self.assertEqual(historical, ("ins_old",))
        self.assertEqual(current, ("ins_new",))

    def test_universe_missing_available_time_fails_closed(self) -> None:
        membership = UniverseMembershipInterval(
            "unv_test", "umf_test", "ins_test", date(2020, 1, 1), None, None, "r1", "INCLUDED",
            "art_sha256_" + "d" * 64,
        )
        with self.assertRaises(PitCapabilityUnavailable):
            resolve_universe_as_of(
                [membership], as_of=date(2020, 2, 1), decision_time=at("2020-02-01T23:00:00")
            )

    def test_adjusted_price_and_corporate_action_cannot_double_count(self) -> None:
        assert_execution_price_policy(ExecutionPriceBasis.RAW, apply_corporate_actions=True)
        with self.assertRaises(AdjustmentDoubleCountError):
            assert_execution_price_policy(
                ExecutionPriceBasis.ADJUSTED, apply_corporate_actions=True
            )
