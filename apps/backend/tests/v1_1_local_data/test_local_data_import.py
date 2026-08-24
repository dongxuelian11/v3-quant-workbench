from __future__ import annotations

import io
import unittest
from datetime import date
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq

from v3_backend.adapters.local_data import (
    LocalDataImportError,
    LocalDataImportIntentV1,
    LocalDataImportLimits,
    import_csv_stream,
    import_parquet_stream,
)


CSV_SHARES = b"""symbol,date,open,high,low,close,volume,amount\n600519,2026-01-05,1400,1420,1395,1410,10000,14100000\n000001,2026-01-05,10,10.5,9.8,10.2,20000,204000\n"""
CSV_HANDS = b"""symbol,date,open,high,low,close,volume,amount\n600519,2026-01-05,1400,1420,1395,1410,100,14100000\n000001,2026-01-05,10,10.5,9.8,10.2,200,204000\n"""


def intent(*, media_type: str, volume_unit: str) -> LocalDataImportIntentV1:
    return LocalDataImportIntentV1(
        media_type=media_type,
        volume_unit=volume_unit,
        amount_unit="CNY",
        timezone="Asia/Shanghai",
        adjustment="UNADJUSTED",
    )


class LocalDataImportTests(unittest.TestCase):
    def test_csv_is_closed_bounded_and_normalized_without_float_truth(self) -> None:
        result = import_csv_stream(
            io.BytesIO(CSV_SHARES),
            intent=intent(media_type="text/csv", volume_unit="SHARES"),
        )

        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.instrument_count, 2)
        self.assertEqual(result.rows[0].session_date, date(2026, 1, 5))
        rows_by_symbol = {row.symbol: row for row in result.rows}
        self.assertEqual(rows_by_symbol["000001"].instrument_id, "ins_cn_szse_000001")
        self.assertEqual(rows_by_symbol["600519"].volume_shares, 10_000)
        self.assertEqual(rows_by_symbol["600519"].amount_cny, Decimal("14100000"))
        self.assertNotIn(b"NaN", result.normalized_payload)
        self.assertEqual(result.raw_byte_size, len(CSV_SHARES))

        unknown = CSV_SHARES.replace(
            b"symbol,date,open,high,low,close,volume,amount",
            b"symbol,date,open,high,low,close,volume,amount,unexpected",
        ).replace(b"14100000\n", b"14100000,x\n")
        with self.assertRaisesRegex(LocalDataImportError, "closed header"):
            import_csv_stream(
                io.BytesIO(unknown),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
            )

    def test_resource_and_encoding_boundaries_fail_before_publication(self) -> None:
        with self.assertRaisesRegex(LocalDataImportError, "max_bytes"):
            import_csv_stream(
                io.BytesIO(CSV_SHARES),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
                limits=LocalDataImportLimits(max_bytes=32),
            )
        with self.assertRaisesRegex(LocalDataImportError, "max_rows"):
            import_csv_stream(
                io.BytesIO(CSV_SHARES),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
                limits=LocalDataImportLimits(max_rows=1),
            )
        with self.assertRaisesRegex(LocalDataImportError, "max_instruments"):
            import_csv_stream(
                io.BytesIO(CSV_SHARES),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
                limits=LocalDataImportLimits(max_instruments=1),
            )
        invalid_utf8 = CSV_SHARES.replace(b"600519", b"\xff00519")
        with self.assertRaisesRegex(LocalDataImportError, "UTF-8"):
            import_csv_stream(
                io.BytesIO(invalid_utf8),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
            )
        with self.assertRaisesRegex(LocalDataImportError, "volume_unit"):
            intent(media_type="text/csv", volume_unit="UNKNOWN")

    def test_shares_and_hands_have_identical_canonical_rows_and_mj(self) -> None:
        shares = import_csv_stream(
            io.BytesIO(CSV_SHARES),
            intent=intent(media_type="text/csv", volume_unit="SHARES"),
        )
        hands = import_csv_stream(
            io.BytesIO(CSV_HANDS),
            intent=intent(media_type="text/csv", volume_unit="HANDS"),
        )

        self.assertEqual(shares.normalized_payload_hash, hands.normalized_payload_hash)
        self.assertEqual(shares.rows, hands.rows)
        for row in shares.rows:
            tdx_volume_hands = Decimal(row.volume_shares) * Decimal("0.01")
            mj = row.amount_cny / tdx_volume_hands / Decimal(100)
            self.assertEqual(mj, row.amount_cny / Decimal(row.volume_shares))

    def test_csv_and_parquet_have_identical_normalized_payload_hash(self) -> None:
        csv_result = import_csv_stream(
            io.BytesIO(CSV_SHARES),
            intent=intent(media_type="text/csv", volume_unit="SHARES"),
        )
        table = pa.table(
            {
                "symbol": ["600519", "000001"],
                "date": ["2026-01-05", "2026-01-05"],
                "open": ["1400", "10"],
                "high": ["1420", "10.5"],
                "low": ["1395", "9.8"],
                "close": ["1410", "10.2"],
                "volume": ["10000", "20000"],
                "amount": ["14100000", "204000"],
            }
        )
        parquet = io.BytesIO()
        pq.write_table(table, parquet, row_group_size=1)
        parquet.seek(0)

        parquet_result = import_parquet_stream(
            parquet,
            intent=intent(
                media_type="application/vnd.apache.parquet",
                volume_unit="SHARES",
            ),
        )

        self.assertEqual(csv_result.normalized_payload_hash, parquet_result.normalized_payload_hash)
        self.assertEqual(csv_result.rows, parquet_result.rows)

    def test_duplicate_invalid_ohlc_and_nested_parquet_fail_closed(self) -> None:
        duplicate = CSV_SHARES + CSV_SHARES.splitlines(keepends=True)[1]
        with self.assertRaisesRegex(LocalDataImportError, "duplicate"):
            import_csv_stream(
                io.BytesIO(duplicate),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
            )

        invalid_ohlc = CSV_SHARES.replace(b"1400,1420,1395,1410", b"1400,1390,1395,1410")
        with self.assertRaisesRegex(LocalDataImportError, "OHLC"):
            import_csv_stream(
                io.BytesIO(invalid_ohlc),
                intent=intent(media_type="text/csv", volume_unit="SHARES"),
            )

        nested = pa.table(
            {
                "symbol": ["600519"],
                "date": ["2026-01-05"],
                "open": ["1400"],
                "high": ["1420"],
                "low": ["1395"],
                "close": ["1410"],
                "volume": ["10000"],
                "amount": ["14100000"],
                "nested": pa.array([[1, 2]], type=pa.list_(pa.int64())),
            }
        )
        parquet = io.BytesIO()
        pq.write_table(nested, parquet)
        parquet.seek(0)
        with self.assertRaisesRegex(LocalDataImportError, "flat primitive"):
            import_parquet_stream(
                parquet,
                intent=intent(
                    media_type="application/vnd.apache.parquet",
                    volume_unit="SHARES",
                ),
            )


if __name__ == "__main__":
    unittest.main()
