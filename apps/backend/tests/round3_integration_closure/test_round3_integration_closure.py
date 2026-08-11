from __future__ import annotations

import unittest
from dataclasses import replace

from v3_backend.adapters.round3_evidence.development_runtime import (
    SESSION_VIEW_ID,
    build_development_bundle,
    build_development_chain,
)
from v3_backend.adapters.round3_evidence.projection import (
    EVIDENCE_KINDS,
    EvidenceLineageBindingError,
    EvidenceSourceMode,
    Round3RebalanceEvidence,
    build_round3_evidence_bundle,
)
from v3_backend.adapters.round3_evidence.provider import (
    EmptyRound3EvidenceProvider,
    InMemoryRound3EvidenceProvider,
)
from v3_backend.domain.risk_runtime import RiskRuntimeResult


def project(chain, *, evidence=None, spec=None, result=None):
    return build_round3_evidence_bundle(
        session_view_id=SESSION_VIEW_ID,
        source_mode=EvidenceSourceMode.DEVELOPMENT_INTEGRATION_FIXTURE,
        rebalance_evidence=(
            chain.rebalance_evidence if evidence is None else evidence
        ),
        backtest_run_spec=chain.backtest_run_spec if spec is None else spec,
        backtest_run_result=(
            chain.backtest_run_result if result is None else result
        ),
    )


class Round3CanonicalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.single = build_development_chain(rebalance_count=1)
        cls.multi = build_development_chain()

    def test_single_rebalance_existing_path_remains_supported(self) -> None:
        bundle = project(self.single)
        self.assertEqual(
            tuple(value.source_artifact_type for value in bundle.projections),
            EVIDENCE_KINDS,
        )
        self.assertEqual(len(bundle.schedule_bindings), 1)
        self.assertEqual(len(bundle.lineage_edges), 6)

    def test_actual_two_rebalance_chain_projects_complete_graph(self) -> None:
        bundle = project(self.multi)
        counts = {
            kind: sum(
                value.source_artifact_type == kind for value in bundle.projections
            )
            for kind in EVIDENCE_KINDS
        }
        self.assertEqual(
            counts,
            {
                "PortfolioIntent": 2,
                "TargetWeightVector": 2,
                "RiskAdjustedWeightVector": 2,
                "RiskDecisionReport": 2,
                "BacktestRunSpec": 1,
                "BacktestRunResult": 1,
            },
        )
        self.assertEqual(len(bundle.schedule_bindings), 2)
        self.assertEqual(len(bundle.lineage_edges), 11)
        self.assertEqual(len(self.multi.backtest_run_result.target_quantity_vectors), 2)
        for projection in bundle.projections:
            self.assertEqual(projection.validation_state, "NOT_RUN")
            self.assertEqual(projection.canonical_admission_state, "PRE_ALPHA")
            self.assertTrue(
                projection.source_object_id.endswith(
                    projection.source_content_sha256
                )
            )

    def test_a_b_schedule_is_exactly_represented(self) -> None:
        bundle = project(self.multi)
        self.assertEqual(
            tuple(
                (
                    value.effective_at,
                    value.risk_adjusted_weight_vector_id,
                    value.content_sha256,
                )
                for value in bundle.schedule_bindings
            ),
            tuple(
                (
                    value.effective_at,
                    value.vector.risk_adjusted_weight_vector_id,
                    value.vector.content_sha256,
                )
                for value in self.multi.backtest_run_spec.schedule
            ),
        )

    def test_missing_risk_b_rejects(self) -> None:
        with self.assertRaisesRegex(
            EvidenceLineageBindingError, "missing exact RiskAdjusted evidence"
        ):
            project(self.multi, evidence=(self.multi.rebalance_evidence[0],))

    def test_orphan_risk_b_rejects(self) -> None:
        with self.assertRaises(EvidenceLineageBindingError):
            build_round3_evidence_bundle(
                session_view_id=SESSION_VIEW_ID,
                source_mode=EvidenceSourceMode.DEVELOPMENT_INTEGRATION_FIXTURE,
                rebalance_evidence=self.multi.rebalance_evidence,
                backtest_run_spec=self.single.backtest_run_spec,
                backtest_run_result=self.single.backtest_run_result,
            )

    def test_risk_b_wrong_target_rejects(self) -> None:
        a, b = self.multi.rebalance_evidence
        wrong = Round3RebalanceEvidence(
            b.portfolio_intent, a.portfolio_result, b.risk_result
        )
        with self.assertRaises(EvidenceLineageBindingError):
            project(self.multi, evidence=(a, wrong))

    def test_report_b_wrong_target_rejects(self) -> None:
        a, b = self.multi.rebalance_evidence
        wrong_risk = RiskRuntimeResult(
            b.risk_result.policy_set,
            a.risk_result.decision_report,
            b.risk_result.application_receipt,
            b.risk_result.adjusted_weights,
        )
        with self.assertRaises(EvidenceLineageBindingError):
            project(
                self.multi,
                evidence=(a, replace(b, risk_result=wrong_risk)),
            )

    def test_receipt_b_borrowed_from_a_rejects(self) -> None:
        a, b = self.multi.rebalance_evidence
        wrong_risk = RiskRuntimeResult(
            b.risk_result.policy_set,
            b.risk_result.decision_report,
            a.risk_result.application_receipt,
            b.risk_result.adjusted_weights,
        )
        with self.assertRaises(EvidenceLineageBindingError):
            project(
                self.multi,
                evidence=(a, replace(b, risk_result=wrong_risk)),
            )

    def test_target_b_wrong_intent_rejects(self) -> None:
        a, b = self.multi.rebalance_evidence
        with self.assertRaises(EvidenceLineageBindingError):
            project(
                self.multi,
                evidence=(a, replace(b, portfolio_intent=a.portfolio_intent)),
            )

    def test_shared_intent_is_deduplicated(self) -> None:
        chain = build_development_chain(shared_intent=True)
        bundle = project(chain)
        self.assertEqual(
            sum(
                value.source_artifact_type == "PortfolioIntent"
                for value in bundle.projections
            ),
            1,
        )
        self.assertEqual(len(bundle.schedule_bindings), 2)

    def test_duplicate_projection_rejects(self) -> None:
        bundle = project(self.multi)
        with self.assertRaisesRegex(
            EvidenceLineageBindingError, "duplicate canonical projection"
        ):
            replace(
                bundle,
                projections=(bundle.projections[0],) + bundle.projections,
            )

    def test_same_id_different_hash_rejects(self) -> None:
        bundle = project(self.multi)
        conflicting = replace(
            bundle.projections[0], source_content_sha256="0" * 64
        )
        with self.assertRaisesRegex(
            EvidenceLineageBindingError, "same canonical kind/ID"
        ):
            replace(
                bundle,
                projections=(bundle.projections[0], conflicting)
                + bundle.projections[1:],
            )

    def test_projection_order_is_deterministic_by_kind_and_id(self) -> None:
        first = build_development_bundle().to_wire()
        second = build_development_bundle().to_wire()
        self.assertEqual(first, second)
        bundle = project(self.multi)
        kind_order = {kind: index for index, kind in enumerate(EVIDENCE_KINDS)}
        self.assertEqual(
            tuple(
                (kind_order[value.source_artifact_type], value.source_object_id)
                for value in bundle.projections
            ),
            tuple(
                sorted(
                    (
                        kind_order[value.source_artifact_type],
                        value.source_object_id,
                    )
                    for value in bundle.projections
                )
            ),
        )

    def test_run_spec_projection_preserves_schedule_order_and_identity(self) -> None:
        bundle = project(self.multi)
        spec = next(
            value
            for value in bundle.projections
            if value.source_artifact_type == "BacktestRunSpec"
        )
        facts = {value.label: value.value for value in spec.view_facts}
        entries = {
            value["label"]: value["value"]
            for value in spec.renderer_payload["entries"]
        }
        for index, scheduled in enumerate(self.multi.backtest_run_spec.schedule):
            expected = {
                f"schedule[{index}].effective_at": scheduled.effective_at.isoformat(),
                f"schedule[{index}].risk_adjusted_weight_vector_id": (
                    scheduled.vector.risk_adjusted_weight_vector_id
                ),
                f"schedule[{index}].content_sha256": scheduled.vector.content_sha256,
            }
            for label, value in expected.items():
                self.assertEqual(facts[label], value)
                self.assertEqual(entries[label], value)
        self.assertNotIn("risk_adjusted_schedule_ids", facts)

    def test_result_spec_mismatch_still_rejects(self) -> None:
        result = replace(
            self.multi.backtest_run_result,
            run_spec_id="btrs_sha256_" + "0" * 64,
        )
        with self.assertRaises(EvidenceLineageBindingError):
            project(self.multi, result=result)

    def test_unknown_source_kind_rejects_before_projection(self) -> None:
        a, b = self.multi.rebalance_evidence
        with self.assertRaises(TypeError):
            project(
                self.multi,
                evidence=(replace(a, portfolio_intent=object()), b),
            )

    def test_provider_remains_read_only_session_bound_and_production_empty(self) -> None:
        bundle = project(self.multi)
        provider = InMemoryRound3EvidenceProvider({SESSION_VIEW_ID: bundle})
        self.assertIs(provider.get_bundle(SESSION_VIEW_ID), bundle)
        self.assertIsNone(provider.get_bundle("session-view-other"))
        with self.assertRaises(ValueError):
            InMemoryRound3EvidenceProvider({"session-view-other": bundle})
        empty = EmptyRound3EvidenceProvider()
        self.assertEqual(empty.reason_code, "NO_CANONICAL_EVIDENCE_AVAILABLE")
        self.assertIsNone(empty.get_bundle(SESSION_VIEW_ID))


if __name__ == "__main__":
    unittest.main()
