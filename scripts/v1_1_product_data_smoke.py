"""V1.1 canonical local Data import and restart smoke."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_runtime import ProductRuntime


CSV = b"""symbol,date,open,high,low,close,volume,amount
600519,2026-01-05,100,101,99,100,10000,1000000
000001,2026-01-05,10,11,9,10,20000,200000
600519,2026-01-06,100,102,99,101,11000,1111000
000001,2026-01-06,10,12,9,11,21000,231000
"""


def main(storage: Path) -> None:
    product = ProductRuntime(storage)
    project = create_project(
        product,
        display_name="V1.1 Data smoke",
        notes=None,
        idempotency_key="v1-1-data-smoke-project",
    )
    imported = ProductDataService(product).import_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=project["project_context_revision_id"],
        display_name="data-smoke.csv",
        source=io.BytesIO(CSV),
        intent=LocalDataImportIntentV1(
            media_type="text/csv",
            volume_unit="SHARES",
            amount_unit="CNY",
            timezone="Asia/Shanghai",
            adjustment="UNADJUSTED",
        ),
    )
    reopened = ProductDataService(ProductRuntime(storage)).get_local_dataset(
        project_id=project["project_id"],
        project_context_revision_id=imported["project_context_revision_id"],
        snapshot_id=imported["snapshot_id"],
    )
    if (
        reopened["snapshot_id"] != imported["snapshot_id"]
        or reopened["universe_version_id"] != imported["universe_version_id"]
        or reopened["normalized_payload_hash"] != imported["normalized_payload_hash"]
        or reopened["row_count"] != 4
        or reopened["instrument_count"] != 2
    ):
        raise RuntimeError("canonical Data restart identity drifted")
    print(
        json.dumps(
            {
                "status": "PASS",
                "truth": reopened["truth"],
                "admission": reopened["admission"],
                "project_id": project["project_id"],
                "project_context_revision_id": imported["project_context_revision_id"],
                "snapshot_id": imported["snapshot_id"],
                "universe_version_id": imported["universe_version_id"],
                "normalized_payload_hash": imported["normalized_payload_hash"],
                "row_count": reopened["row_count"],
                "instrument_count": reopened["instrument_count"],
                "restart_readback": "PASS",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
