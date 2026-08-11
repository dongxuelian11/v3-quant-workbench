from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from v3_backend.adapters.market_data.akshare import (
    AKSHARE_PROVIDER_REPOSITORY_REVISION,
    AKSHARE_PROVIDER_VERSION,
    AkshareAShareEodAdapter,
    ProviderAcquisitionError,
    ProviderVersionMismatch,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.data_truth import (
    MissingValueReason,
    PitCapabilityUnavailable,
    PitEvidenceState,
    normalize_a_share_eod,
)


UTC = timezone.utc
ACQUIRED_AT = datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)
REQUEST = {
    "symbol": "000001",
    "period": "daily",
    "start_date": "20260105",
    "end_date": "20260106",
    "adjust": "",
    "timeout": 10,
}
ROWS = [
    {
        "日期": "2026-01-06",
        "股票代码": "000001",
        "开盘": 10.1,
        "收盘": 10.5,
        "最高": 10.8,
        "最低": 10.0,
        "成交量": 1200,
        "成交额": 12500.5,
        "振幅": 8.0,
    },
    {
        "日期": "2026-01-05",
        "股票代码": "000001",
        "开盘": 9.8,
        "收盘": 10.0,
        "最高": 10.2,
        "最低": 9.7,
        "成交量": 1000,
        "成交额": 9900.0,
        "振幅": 5.0,
    },
]


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError("unexpected orientation")
        return [dict(row) for row in self.rows]


class FakeAkshare:
    __version__ = AKSHARE_PROVIDER_VERSION

    def __init__(
        self, rows: list[dict[str, object]], *, failure: Exception | None = None
    ) -> None:
        self.rows = rows
        self.failure = failure
        self.calls: list[dict[str, object]] = []

    def stock_zh_a_hist(self, **request: object) -> FakeFrame:
        self.calls.append(dict(request))
        if self.failure is not None:
            raise self.failure
        return FakeFrame(self.rows)


def adapter(
    provider: FakeAkshare,
    *,
    acquired_at: datetime = ACQUIRED_AT,
) -> AkshareAShareEodAdapter:
    return AkshareAShareEodAdapter(
        connector_version_id="cov_akshare_1_18_84_v0",
        loader=lambda: provider,
        clock=lambda: acquired_at,
    )


class RealAShareProviderV0Tests(unittest.TestCase):
    def test_stable_provider_and_source_identity(self) -> None:
        first = adapter(FakeAkshare(ROWS)).descriptor()
        second = adapter(FakeAkshare(list(reversed(ROWS)))).descriptor()
        self.assertEqual(first, second)
        self.assertEqual(first.provider_id, "pvd_akshare_eastmoney_a_share_eod_v1")
        self.assertIn("Eastmoney", first.source_authority)

    def test_capture_pins_provider_version_revision_and_request(self) -> None:
        provider = FakeAkshare(ROWS)
        capture = adapter(provider).capture(REQUEST)
        self.assertEqual(provider.calls, [REQUEST])
        self.assertEqual(
            capture.source_metadata["provider_package_version"],
            AKSHARE_PROVIDER_VERSION,
        )
        self.assertEqual(
            capture.source_metadata["provider_repository_revision"],
            AKSHARE_PROVIDER_REPOSITORY_REVISION,
        )
        self.assertIsNone(capture.source_metadata["provider_response_revision"])
        self.assertEqual(capture.source_metadata["revision_evidence"], "UNKNOWN")

    def test_raw_capture_identity_is_immutable_content_addressed(self) -> None:
        first = adapter(FakeAkshare(ROWS)).capture(REQUEST)
        later = adapter(
            FakeAkshare(list(reversed(ROWS))),
            acquired_at=ACQUIRED_AT + timedelta(hours=1),
        ).capture(REQUEST)
        changed_rows = [dict(row) for row in ROWS]
        changed_rows[0]["收盘"] = 10.6
        changed = adapter(FakeAkshare(changed_rows)).capture(REQUEST)
        self.assertEqual(first.envelope.raw_capture_id, later.envelope.raw_capture_id)
        self.assertEqual(first.envelope.content_hash, later.envelope.content_hash)
        self.assertNotEqual(
            first.source_metadata["acquisition_id"],
            later.source_metadata["acquisition_id"],
        )
        self.assertNotEqual(first.envelope.raw_capture_id, changed.envelope.raw_capture_id)
        self.assertEqual(
            first.envelope.artifact_id,
            "art_sha256_" + first.envelope.content_hash,
        )

    def test_deterministic_normalization_and_snapshot_identity(self) -> None:
        first = normalize_a_share_eod(adapter(FakeAkshare(ROWS)).capture(REQUEST))
        second = normalize_a_share_eod(
            adapter(
                FakeAkshare(list(reversed(ROWS))),
                acquired_at=ACQUIRED_AT + timedelta(days=1),
            ).capture(REQUEST)
        )
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(
            [record.session_date.isoformat() for record in first.records],
            ["2026-01-05", "2026-01-06"],
        )
        self.assertEqual(
            first.research_universe_input.instrument_ids,
            ("ins_cn_szse_000001",),
        )

    def test_missing_values_and_absent_fields_are_explicit(self) -> None:
        rows = [dict(ROWS[0])]
        rows[0]["成交额"] = None
        snapshot = normalize_a_share_eod(adapter(FakeAkshare(rows)).capture(REQUEST))
        record = snapshot.records[0]
        self.assertIsNone(record.amount)
        missing = {item.field: item.reason for item in record.missing_fields}
        self.assertEqual(missing["amount"], MissingValueReason.PROVIDER_NULL)
        self.assertEqual(
            missing["trading_status"],
            MissingValueReason.PROVIDER_COLUMN_ABSENT,
        )

    def test_unknown_available_time_fails_strict_pit_and_lowers_ceiling(self) -> None:
        snapshot = normalize_a_share_eod(adapter(FakeAkshare(ROWS)).capture(REQUEST))
        self.assertEqual(snapshot.pit_evidence, PitEvidenceState.UNKNOWN)
        self.assertTrue(all(record.available_time is None for record in snapshot.records))
        self.assertEqual(snapshot.truth_ceiling, PRE_ALPHA_CEILING)
        with self.assertRaises(PitCapabilityUnavailable):
            snapshot.require_strict_pit()

    def test_provider_data_cannot_self_promote_to_formal_admission(self) -> None:
        snapshot = normalize_a_share_eod(
            adapter(FakeAkshare(ROWS)).capture(REQUEST),
            proposed_state=FORMAL_ADMITTED_CEILING,
        )
        self.assertEqual(snapshot.truth_ceiling, PRE_ALPHA_CEILING)
        self.assertIn(
            "PROVIDER_DATA_IS_NOT_CANONICAL_MARKET_TRUTH", snapshot.reason_codes
        )

    def test_provider_failure_is_explicit_and_does_not_fallback(self) -> None:
        provider = FakeAkshare(ROWS, failure=TimeoutError("upstream timeout"))
        with self.assertRaisesRegex(ProviderAcquisitionError, "fallback is forbidden"):
            adapter(provider).capture(REQUEST)
        self.assertEqual(len(provider.calls), 1)

    def test_provider_version_mismatch_fails_closed(self) -> None:
        provider = FakeAkshare(ROWS)
        provider.__version__ = "1.18.64"
        with self.assertRaises(ProviderVersionMismatch):
            adapter(provider).capture(REQUEST)

    def test_adjusted_prices_are_rejected_without_corporate_action_evidence(self) -> None:
        request = {**REQUEST, "adjust": "qfq"}
        provider = FakeAkshare(ROWS)
        with self.assertRaisesRegex(ProviderAcquisitionError, "unadjusted"):
            adapter(provider).capture(request)
        self.assertEqual(provider.calls, [])

    def test_offline_suite_uses_injected_provider_only(self) -> None:
        provider = FakeAkshare(ROWS)
        snapshot = normalize_a_share_eod(adapter(provider).capture(REQUEST))
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(snapshot.records), 2)


if __name__ == "__main__":
    unittest.main()
