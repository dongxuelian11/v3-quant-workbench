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
    build_round3_evidence_bundle,
)
from v3_backend.adapters.round3_evidence.provider import (
    EmptyRound3EvidenceProvider,
    InMemoryRound3EvidenceProvider,
)
from v3_backend.domain.risk_runtime import RiskRuntimeResult


def project(chain):
    return build_round3_evidence_bundle(
        session_view_id=SESSION_VIEW_ID,
        source_mode=EvidenceSourceMode.DEVELOPMENT_INTEGRATION_FIXTURE,
        portfolio_intent=chain.portfolio_intent,
        portfolio_result=chain.portfolio_result,
        risk_result=chain.risk_result,
        backtest_run_spec=chain.backtest_run_spec,
        backtest_run_result=chain.backtest_run_result,
    )


class Round3CanonicalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chain = build_development_chain()

    def test_actual_h_i_j_chain_projects_exact_ids_hashes_and_truth(self) -> None:
        bundle = project(self.chain)
        self.assertEqual(tuple(value.source_artifact_type for value in bundle.projections), EVIDENCE_KINDS)
        self.assertEqual(len(bundle.lineage_edges), 6)
        canonical_objects = (
            self.chain.portfolio_intent,
            self.chain.portfolio_result.target,
            self.chain.risk_result.adjusted_weights,
            self.chain.risk_result.decision_report,
            self.chain.backtest_run_spec,
            self.chain.backtest_run_result,
        )
        for projection, source in zip(bundle.projections, canonical_objects, strict=True):
            source_truth = source.truth_admission.to_wire()
            self.assertEqual(projection.canonical_truth_state, source_truth["canonical_truth_state"])
            self.assertEqual(projection.canonical_admission_state, source_truth["canonical_admission_state"])
            self.assertEqual(projection.validation_state, "NOT_RUN")
            self.assertTrue(projection.source_object_id.endswith(projection.source_content_sha256))

    def test_projection_is_deterministic(self) -> None:
        self.assertEqual(build_development_bundle().to_wire(), build_development_bundle().to_wire())

    def test_unknown_source_kind_rejects_before_projection(self) -> None:
        with self.assertRaises(TypeError):
            project(replace(self.chain, portfolio_intent=object()))

    def test_target_risk_receipt_mismatch_fails_closed(self) -> None:
        receipt = replace(
            self.chain.risk_result.application_receipt,
            source_target_weight_vector_id="twv_sha256_" + "0" * 64,
        )
        risk = RiskRuntimeResult(
            self.chain.risk_result.policy_set,
            self.chain.risk_result.decision_report,
            receipt,
            self.chain.risk_result.adjusted_weights,
        )
        with self.assertRaises((EvidenceLineageBindingError, ValueError)):
            project(replace(self.chain, risk_result=risk))

    def test_risk_schedule_mismatch_fails_closed(self) -> None:
        spec = replace(self.chain.backtest_run_spec, schedule=())
        with self.assertRaises(EvidenceLineageBindingError):
            project(replace(self.chain, backtest_run_spec=spec))

    def test_spec_result_mismatch_fails_closed(self) -> None:
        result = replace(
            self.chain.backtest_run_result,
            run_spec_id="btrs_sha256_" + "0" * 64,
        )
        with self.assertRaises(EvidenceLineageBindingError):
            project(replace(self.chain, backtest_run_result=result))

    def test_provider_is_read_only_session_bound_and_production_empty(self) -> None:
        bundle = project(self.chain)
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
