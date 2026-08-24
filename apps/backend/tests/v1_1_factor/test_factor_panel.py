from __future__ import annotations

import io
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from v3_backend.adapters.local_data import LocalDataImportIntentV1, LocalDataImportLimits
from v3_backend.adapters.tdx_formula import (
    TdxFormulaError,
    TdxTranslator,
    registered_tdx_data_semantic_profile,
)
from v3_backend.domain.factors import (
    DeterministicPanelEvaluator,
    FactorDefinitionVersion,
    FeatureNode,
    OperatorNode,
    UnsafeFactorExpression,
    panel_operator_registry,
)
from v3_backend.runtime.product_data import ProductDataService
from v3_backend.runtime.product_entry import create_project
from v3_backend.runtime.product_factor import ManifestAwareLocalSnapshotReader
from v3_backend.runtime.product_runtime import ProductRuntime


GOLDEN_FORMULA = """MJ:=AMOUNT/VOL/100;
MA5:=MA(MJ,5);
MA20:=MA(MJ,20);
MA60:=MA(MJ,60);
GOLDEN_CROSS:CROSS(MA20,MA60) AND MA5>MA20;
DEATH_CROSS:CROSS(MA60,MA20) AND MA5<MA20;
"""


def _panel_csv() -> bytes:
    rows = ["symbol,date,open,high,low,close,volume,amount"]
    first = date(2025, 1, 1)
    for offset in range(70):
        session = first + timedelta(days=offset)
        a_price = 100 if offset < 60 else 200
        b_price = 300 if offset < 60 else 150
        for symbol, price in (("600519", a_price), ("000001", b_price)):
            volume = 0 if symbol == "000001" and offset == 65 else 10_000
            amount = price * volume
            rows.append(
                f"{symbol},{session.isoformat()},{price},{price},{price},{price},{volume},{amount}"
            )
    return ("\n".join(rows) + "\n").encode("utf-8")


class FactorPanelAcceptanceTests(unittest.TestCase):
    def _import(self, root: Path):
        product = ProductRuntime(root)
        project = create_project(
            product,
            display_name="Factor panel acceptance",
            notes=None,
            idempotency_key="create-factor-panel-acceptance",
        )
        imported = ProductDataService(product).import_local_dataset(
            project_id=project["project_id"],
            project_context_revision_id=project["project_context_revision_id"],
            display_name="panel.csv",
            source=io.BytesIO(_panel_csv()),
            intent=LocalDataImportIntentV1(
                media_type="text/csv",
                volume_unit="SHARES",
                amount_unit="CNY",
                timezone="Asia/Shanghai",
                adjustment="UNADJUSTED",
            ),
            limits=LocalDataImportLimits(max_partition_bytes=6_000),
        )
        return product, project, imported

    def test_manifest_reader_and_golden_tdx_preserve_instrument_time_axis_and_missing_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-factor-panel-") as directory:
            product, project, imported = self._import(Path(directory))
            panel = ManifestAwareLocalSnapshotReader(product).resolve(
                project_id=project["project_id"],
                snapshot_id=imported["snapshot_id"],
                universe_version_id=imported["universe_version_id"],
            )
            self.assertGreater(len({row.source_partition_artifact_id for row in panel.rows}), 1)
            self.assertTrue(
                all(
                    row.source_partition_artifact_id == "art_sha256_" + row.source_partition_sha256
                    for row in panel.rows
                )
            )

            registry = panel_operator_registry()
            translation = TdxTranslator(registry).translate(
                GOLDEN_FORMULA,
                data_profile=registered_tdx_data_semantic_profile(),
                provenance_ref="user-supplied:v1.1-golden",
            )
            evaluator = DeterministicPanelEvaluator(registry)
            mj = evaluator.evaluate(translation.output("MJ").definition, panel.rows)
            ma5 = evaluator.evaluate(translation.output("MA5").definition, panel.rows)
            golden = evaluator.evaluate(
                translation.output("GOLDEN_CROSS").definition,
                panel.rows,
            )
            death = evaluator.evaluate(
                translation.output("DEATH_CROSS").definition,
                panel.rows,
            )

            by_key = {(row.instrument_id, row.session_date): row for row in mj.rows}
            missing_key = ("ins_cn_szse_000001", date(2025, 3, 7))
            self.assertIsNone(by_key[missing_key].value)
            self.assertEqual(by_key[missing_key].missing_reason, "DIVIDE_BY_ZERO_OR_MISSING")
            self.assertEqual(by_key[("ins_cn_sse_600519", date(2025, 1, 1))].value, 100.0)

            ma5_by_instrument = {
                instrument: [row.value for row in ma5.rows if row.instrument_id == instrument]
                for instrument in ("ins_cn_sse_600519", "ins_cn_szse_000001")
            }
            self.assertEqual(ma5_by_instrument["ins_cn_sse_600519"][:4], [None] * 4)
            self.assertEqual(ma5_by_instrument["ins_cn_sse_600519"][4], 100.0)
            self.assertEqual(ma5_by_instrument["ins_cn_szse_000001"][4], 300.0)

            golden_dates = {
                row.session_date for row in golden.rows
                if row.instrument_id == "ins_cn_sse_600519" and row.value is True
            }
            death_dates = {
                row.session_date for row in death.rows
                if row.instrument_id == "ins_cn_szse_000001" and row.value is True
            }
            self.assertEqual(golden_dates, {date(2025, 3, 2)})
            self.assertEqual(death_dates, {date(2025, 3, 2)})

    def test_rank_is_cross_sectional_per_date_and_future_reads_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-factor-rank-") as directory:
            product, project, imported = self._import(Path(directory))
            panel = ManifestAwareLocalSnapshotReader(product).resolve(
                project_id=project["project_id"],
                snapshot_id=imported["snapshot_id"],
                universe_version_id=imported["universe_version_id"],
            )
            registry = panel_operator_registry()
            ranked = TdxTranslator(registry).translate(
                "PRICE_RANK:RANK(CLOSE);",
                data_profile=registered_tdx_data_semantic_profile(),
                provenance_ref="user-supplied:v1.1-rank",
            )
            output = DeterministicPanelEvaluator(registry).evaluate(
                ranked.output("PRICE_RANK").definition,
                panel.rows,
            )
            first_date = [row for row in output.rows if row.session_date == date(2025, 1, 1)]
            self.assertEqual(
                {row.instrument_id: row.value for row in first_date},
                {"ins_cn_sse_600519": 0.0, "ins_cn_szse_000001": 1.0},
            )

            with self.assertRaisesRegex(TdxFormulaError, "LOOKBACK_UNRESOLVED"):
                TdxTranslator(registry).translate(
                    "BAD:REF(CLOSE,-1);",
                    data_profile=registered_tdx_data_semantic_profile(),
                    provenance_ref="user-supplied:v1.1-negative-ref",
                )
            with self.assertRaises(UnsafeFactorExpression):
                FactorDefinitionVersion.create(
                    "future-read",
                    OperatorNode("LEAD", "1.0.0", (FeatureNode("close", "eod.close/1.0.0"),), {}),
                    registry,
                )

    def test_panel_axis_properties_hold_across_rolling_windows_and_symbol_perturbation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v3-v1-1-factor-properties-") as directory:
            product, project, imported = self._import(Path(directory))
            panel = ManifestAwareLocalSnapshotReader(product).resolve(
                project_id=project["project_id"],
                snapshot_id=imported["snapshot_id"],
                universe_version_id=imported["universe_version_id"],
            )
            registry = panel_operator_registry()
            evaluator = DeterministicPanelEvaluator(registry)
            for window in range(2, 13):
                with self.subTest(window=window):
                    translated = TdxTranslator(registry).translate(
                        f"ROLLING:MA(CLOSE,{window});",
                        data_profile=registered_tdx_data_semantic_profile(),
                        provenance_ref=f"property:rolling:{window}",
                    )
                    definition = translated.output("ROLLING").definition
                    baseline = evaluator.evaluate(definition, panel.rows).rows
                    by_instrument = {
                        instrument: [row for row in baseline if row.instrument_id == instrument]
                        for instrument in ("ins_cn_sse_600519", "ins_cn_szse_000001")
                    }
                    for instrument, expected in (
                        ("ins_cn_sse_600519", 100.0),
                        ("ins_cn_szse_000001", 300.0),
                    ):
                        self.assertEqual(
                            [row.value for row in by_instrument[instrument][: window - 1]],
                            [None] * (window - 1),
                        )
                        self.assertEqual(by_instrument[instrument][window - 1].value, expected)

                    perturbed = tuple(
                        replace(
                            row,
                            features={**row.features, "close": float(row.features["close"] or 0) + 10_000},
                        )
                        if row.instrument_id == "ins_cn_szse_000001"
                        else row
                        for row in panel.rows
                    )
                    rerun = evaluator.evaluate(definition, perturbed).rows
                    self.assertEqual(
                        [row.value for row in baseline if row.instrument_id == "ins_cn_sse_600519"],
                        [row.value for row in rerun if row.instrument_id == "ins_cn_sse_600519"],
                        "changing one symbol must not change another symbol's rolling state",
                    )


if __name__ == "__main__":
    unittest.main()
