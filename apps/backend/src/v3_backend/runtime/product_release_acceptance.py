"""Explicit packaged V1 acceptance-only provider boundary.

This module is never selected by normal product startup. The packaged Electron
acceptance harness must opt in through a closed bootstrap CLI argument. Its
successful records are marked TEST_EXTERNAL_PROVIDER_BOUNDARY and remain
DEMO / PRE_ALPHA / RESEARCH_ONLY / APPROXIMATE; they must never be reported as
live Eastmoney observations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v3_backend.adapters.market_data.akshare import AkshareAShareEodAdapter

DETERMINISTIC_SUCCESS = "DETERMINISTIC_SUCCESS"
DETERMINISTIC_UNAVAILABLE = "DETERMINISTIC_UNAVAILABLE"
ACCEPTANCE_PROVIDER_MODES = (DETERMINISTIC_SUCCESS, DETERMINISTIC_UNAVAILABLE)


class _Frame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise ValueError("acceptance provider requires records orientation")
        return list(self._rows)


class _AcceptanceAkshare:
    __version__ = "1.18.84"
    __v3_source_kind__ = "TEST_EXTERNAL_PROVIDER_BOUNDARY"

    def __init__(self, mode: str) -> None:
        self._mode = mode

    def stock_zh_a_hist(self, **request: Any) -> _Frame:
        if self._mode == DETERMINISTIC_UNAVAILABLE:
            raise ConnectionError("deterministic V1 acceptance provider unavailable")
        symbol = str(request.get("symbol", "000001"))
        return _Frame(
            [
                {
                    "股票代码": symbol,
                    "日期": "2026-01-06",
                    "开盘": "10.00",
                    "最高": "11.00",
                    "最低": "9.50",
                    "收盘": "10.50",
                    "成交量": "1000",
                    "成交额": "10500",
                },
                {
                    "股票代码": symbol,
                    "日期": "2026-01-07",
                    "开盘": "10.50",
                    "最高": "11.50",
                    "最低": "10.00",
                    "收盘": "11.00",
                    "成交量": "1200",
                    "成交额": "13200",
                },
            ]
        )


def product_release_acceptance_provider_factory(mode: str):
    if mode not in ACCEPTANCE_PROVIDER_MODES:
        raise ValueError("unknown product release acceptance provider mode")

    def factory(config):
        return AkshareAShareEodAdapter(
            connector_version_id=config.connector_version_id,
            loader=lambda: _AcceptanceAkshare(mode),
            clock=lambda: datetime(2026, 1, 8, 8, 0, tzinfo=timezone.utc),
        )

    return factory


__all__ = [
    "ACCEPTANCE_PROVIDER_MODES",
    "DETERMINISTIC_SUCCESS",
    "DETERMINISTIC_UNAVAILABLE",
    "product_release_acceptance_provider_factory",
]
