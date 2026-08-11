from __future__ import annotations

import dataclasses
import inspect
import unittest
from datetime import datetime, timedelta, timezone

from track_f_strategy_runtime.helpers import (
    build_runtime_fixture,
    build_strategy_ir,
    sha,
)
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.strategies import (
    DeterministicStrategyEvaluator,
    StrategyCompiler,
    default_component_registry,
)
from v3_backend.domain.weights import (
    AbsentMemberPolicy,
    ExposureProfile,
    PortfolioIntentSource,
    ReferenceKind,
    RiskAdjustedWeightVector,
    RiskApplicationReceipt,
    RiskDecision,
    RiskDecisionReason,
    RiskStageEvidence,
    RuntimeIdentity,
    TargetKind,
    TargetWeightRow,
    TargetWeightVector,
    UnresolvedExactReference,
    WEIGHT_BUDGET_TOLERANCE,
    WeightBasis,
    WeightContractError,
    normalize_weight_decimal,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


class WeightSeamFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_fixture()
        result = DeterministicStrategyEvaluator().evaluate(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            inputs=(self.fixture.runtime_input,),
        )
        assert result.portfolio_intent is not None
        self.intent = result.portfolio_intent
        self.source = PortfolioIntentSource.create(
            intent=self.intent,
            definition=self.fixture.definition,
            binding=self.fixture.binding,
        )
        self.runtime = RuntimeIdentity(
            code_version="git:round3-w0-test",
            runtime_profile_id="v3-weight-seam/1.0.0",
            environment_fingerprint="cpython-3.14.7-windows-x64",
        )
        self.construction = self.reference(
            ReferenceKind.CONSTRUCTION_SPEC, "construction-spec-1", "4"
        )
        self.evidence = (
            self.reference(ReferenceKind.DIAGNOSTICS, "diagnostics-1", "5"),
            self.reference(ReferenceKind.PROVENANCE, "provenance-1", "6"),
        )
        self.as_of = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        self.decision_time = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
        self.rebalance_time = datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)
        self.valid_until = datetime(2026, 1, 6, 7, 0, tzinfo=timezone.utc)

    @staticmethod
    def reference(
        kind: ReferenceKind,
        source_id: str,
        character: str,
    ) -> UnresolvedExactReference:
        return UnresolvedExactReference(
            kind,
            source_id,
            sha(character),
            FORMAL_ADMITTED_CEILING,
        )

    def target(
        self,
        *,
        source: PortfolioIntentSource | None = None,
        construction_spec: UnresolvedExactReference | None = None,
        rows: tuple[TargetWeightRow, ...] | None = None,
        cash_weight: str = "0.1",
        as_of: datetime | None = None,
    ) -> TargetWeightVector:
        return TargetWeightVector.create(
            source=source or self.source,
            construction_spec=construction_spec or self.construction,
            evidence_refs=self.evidence,
            runtime_identity=self.runtime,
            base_currency="CNY",
            as_of=as_of or self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
            cash_weight=cash_weight,
            rows=rows
            or (
                TargetWeightRow("000002.SZ", "0.4000"),
                TargetWeightRow("000001.SZ", "0.50"),
            ),
        )

    def risk_receipt(self) -> RiskApplicationReceipt:
        return RiskApplicationReceipt.create(
            risk_policy_set=self.reference(
                ReferenceKind.RISK_POLICY_SET,
                "risk_policy_set_pass_through_1",
                "7",
            ),
            decision=RiskDecision.PASS_THROUGH,
            decision_reason=RiskDecisionReason.NO_ADDITIONAL_RISK_TRANSFORM,
            stages=(
                RiskStageEvidence(
                    1,
                    "pass-through",
                    "NO_ADDITIONAL_RISK_TRANSFORM",
                    sha("8"),
                ),
            ),
            supporting_refs=(),
            runtime_identity=self.runtime,
        )


class TargetWeightContractTests(WeightSeamFixture):
    def test_rows_are_canonically_ordered_and_decimal_strings_normalized(self) -> None:
        target = self.target()
        self.assertEqual(
            tuple(value.instrument_id for value in target.rows),
            ("000001.SZ", "000002.SZ"),
        )
        self.assertEqual(
            tuple(value.target_weight for value in target.rows),
            ("0.5", "0.4"),
        )
        self.assertEqual(target.cash_weight, "0.1")
        self.assertEqual(normalize_weight_decimal("1E-2"), "0.01")
        self.assertEqual(normalize_weight_decimal("0.000000000001"), "0.000000000001")

    def test_duplicate_instrument_is_rejected(self) -> None:
        with self.assertRaisesRegex(WeightContractError, "unique"):
            self.target(
                rows=(
                    TargetWeightRow("000001.SZ", "0.4"),
                    TargetWeightRow("000001.SZ", "0.5"),
                )
            )

    def test_nonfinite_negative_zero_and_excess_precision_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(
                WeightContractError, "finite"
            ):
                TargetWeightRow("000001.SZ", value)
        for value in ("-0", "-0.0", "-0E-12"):
            with self.subTest(value=value), self.assertRaisesRegex(
                WeightContractError, "negative zero"
            ):
                TargetWeightRow("000001.SZ", value)
        with self.assertRaisesRegex(WeightContractError, "12-place"):
            TargetWeightRow("000001.SZ", "0.0000000000001")

    def test_long_only_budget_cash_and_bounds_fail_closed(self) -> None:
        target = self.target(
            rows=(TargetWeightRow("000001.SZ", "0.999999999998"),),
            cash_weight=str(WEIGHT_BUDGET_TOLERANCE),
        )
        self.assertEqual(target.cash_weight, "0.000000000001")
        with self.assertRaisesRegex(WeightContractError, "equal one"):
            self.target(
                rows=(TargetWeightRow("000001.SZ", "0.8"),),
                cash_weight="0.1",
            )
        with self.assertRaisesRegex(WeightContractError, "non-negative"):
            self.target(
                rows=(
                    TargetWeightRow("000001.SZ", "-0.1"),
                    TargetWeightRow("000002.SZ", "1"),
                )
            )

    def test_complete_absolute_scope_uses_zero_for_absent_universe_members(self) -> None:
        target = self.target()
        self.assertIs(target.target_kind, TargetKind.ABSOLUTE_COMPLETE)
        self.assertIs(target.absent_member_policy, AbsentMemberPolicy.ZERO)
        self.assertIs(target.exposure_profile, ExposureProfile.LONG_ONLY_UNLEVERED)
        self.assertIs(target.weight_basis, WeightBasis.NAV)
        absent = set(target.source.universe_instrument_ids) - {
            value.instrument_id for value in target.rows
        }
        self.assertEqual(absent, {"000003.SZ", "000004.SZ"})
        self.assertNotIn("UNCHANGED", str(target.to_wire()))
        with self.assertRaisesRegex(WeightContractError, "outside exact universe"):
            self.target(rows=(TargetWeightRow("999999.SZ", "0.9"),))

    def test_portfolio_intent_source_requires_exact_current_main_objects(self) -> None:
        wrong_intent = dataclasses.replace(
            self.intent,
            strategy_evaluation_binding_version_id="sebv_sha256_" + sha("0"),
        )
        with self.assertRaisesRegex(WeightContractError, "evaluation binding mismatch"):
            PortfolioIntentSource.create(
                intent=wrong_intent,
                definition=self.fixture.definition,
                binding=self.fixture.binding,
            )
        wrong_definition = dataclasses.replace(
            self.fixture.definition,
            canonical_ir_sha256=sha("0"),
        )
        with self.assertRaisesRegex(WeightContractError, "IR hash mismatch"):
            PortfolioIntentSource.create(
                intent=self.intent,
                definition=wrong_definition,
                binding=self.fixture.binding,
            )

    def test_target_identity_changes_for_each_semantic_input_class(self) -> None:
        base = self.target()
        changed_weights = self.target(
            rows=(
                TargetWeightRow("000001.SZ", "0.45"),
                TargetWeightRow("000002.SZ", "0.45"),
            )
        )
        changed_policy = self.target(
            construction_spec=self.reference(
                ReferenceKind.CONSTRUCTION_SPEC,
                "construction-spec-2",
                "9",
            )
        )
        changed_time = self.target(as_of=self.as_of - timedelta(minutes=1))

        other_universe_fixture = build_runtime_fixture(
            definition=self.fixture.definition,
            membership_character="e",
        )
        other_universe_result = DeterministicStrategyEvaluator().evaluate(
            definition=other_universe_fixture.definition,
            binding=other_universe_fixture.binding,
            inputs=(other_universe_fixture.runtime_input,),
        )
        assert other_universe_result.portfolio_intent is not None
        changed_universe_source = PortfolioIntentSource.create(
            intent=other_universe_result.portfolio_intent,
            definition=other_universe_fixture.definition,
            binding=other_universe_fixture.binding,
        )
        changed_universe = self.target(source=changed_universe_source)

        other_definition = StrategyCompiler(default_component_registry()).compile(
            build_strategy_ir(selection_count=1)
        )
        other_source_fixture = build_runtime_fixture(definition=other_definition)
        other_source_result = DeterministicStrategyEvaluator().evaluate(
            definition=other_source_fixture.definition,
            binding=other_source_fixture.binding,
            inputs=(other_source_fixture.runtime_input,),
        )
        assert other_source_result.portfolio_intent is not None
        changed_source = self.target(
            source=PortfolioIntentSource.create(
                intent=other_source_result.portfolio_intent,
                definition=other_source_fixture.definition,
                binding=other_source_fixture.binding,
            )
        )

        identities = {
            value.target_weight_vector_id
            for value in (
                base,
                changed_weights,
                changed_policy,
                changed_time,
                changed_universe,
                changed_source,
            )
        }
        self.assertEqual(len(identities), 6)

    def test_storage_metadata_is_outside_portfolio_intent_semantic_identity(self) -> None:
        first_storage = {"bucket": "local-a", "row_id": 1, "object": self.intent}
        second_storage = {"bucket": "remote-b", "row_id": 99, "object": self.intent}
        first = PortfolioIntentSource.create(
            intent=first_storage["object"],  # type: ignore[arg-type]
            definition=self.fixture.definition,
            binding=self.fixture.binding,
        )
        second = PortfolioIntentSource.create(
            intent=second_storage["object"],  # type: ignore[arg-type]
            definition=self.fixture.definition,
            binding=self.fixture.binding,
        )
        self.assertEqual(first, second)
        self.assertNotIn("bucket", first.to_wire())
        self.assertNotIn("row_id", first.to_wire())

    def test_deterministic_wire_hash_and_fixed_publisher_authority(self) -> None:
        first = self.target()
        second = self.target()
        self.assertEqual(first, second)
        self.assertEqual(first.to_wire(), second.to_wire())
        payload = {
            key: value
            for key, value in first.to_wire().items()
            if key not in {"artifact_type", "target_weight_vector_id", "content_sha256"}
        }
        self.assertEqual(canonical_sha256(payload), first.content_sha256)
        parameters = inspect.signature(TargetWeightVector.create).parameters
        self.assertNotIn("publisher_service", parameters)
        self.assertNotIn("target_kind", parameters)
        self.assertEqual(
            first.publisher_service,
            "PortfolioService/Portfolio Construction",
        )


class RiskAdjustedWeightContractTests(WeightSeamFixture):
    def test_exact_source_target_binding_rejects_tampered_target(self) -> None:
        target = self.target()
        tampered = dataclasses.replace(
            target,
            target_weight_vector_id="twv_sha256_" + sha("0"),
        )
        with self.assertRaisesRegex(WeightContractError, "TargetWeightVector"):
            RiskAdjustedWeightVector.create(
                source_target=tampered,
                risk_application=self.risk_receipt(),
                runtime_identity=self.runtime,
                cash_weight=tampered.cash_weight,
                rows=tampered.rows,
            )

    def test_pass_through_creates_distinct_derivative_with_equal_rows(self) -> None:
        target = self.target()
        adjusted = RiskAdjustedWeightVector.create(
            source_target=target,
            risk_application=self.risk_receipt(),
            runtime_identity=self.runtime,
            cash_weight=target.cash_weight,
            rows=tuple(reversed(target.rows)),
        )
        self.assertEqual(adjusted.rows, target.rows)
        self.assertEqual(adjusted.cash_weight, target.cash_weight)
        self.assertNotEqual(
            adjusted.risk_adjusted_weight_vector_id,
            target.target_weight_vector_id,
        )
        self.assertEqual(
            adjusted.to_wire()["source_target_weight_vector_id"],
            target.target_weight_vector_id,
        )
        self.assertEqual(
            adjusted.to_wire()["source_target_content_sha256"],
            target.content_sha256,
        )
        self.assertEqual(
            adjusted.to_wire()["risk_decision_reason"],
            "NO_ADDITIONAL_RISK_TRANSFORM",
        )

    def test_pass_through_cannot_change_rows_or_cash(self) -> None:
        target = self.target()
        with self.assertRaisesRegex(WeightContractError, "semantically equal"):
            RiskAdjustedWeightVector.create(
                source_target=target,
                risk_application=self.risk_receipt(),
                runtime_identity=self.runtime,
                cash_weight="0.2",
                rows=(
                    TargetWeightRow("000001.SZ", "0.4"),
                    TargetWeightRow("000002.SZ", "0.4"),
                ),
            )

    def test_risk_truth_is_bounded_by_source_and_cannot_promote(self) -> None:
        target = self.target()
        adjusted = RiskAdjustedWeightVector.create(
            source_target=target,
            risk_application=self.risk_receipt(),
            runtime_identity=self.runtime,
            cash_weight=target.cash_weight,
            rows=target.rows,
        )
        self.assertEqual(target.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(adjusted.truth_admission, PRE_ALPHA_CEILING)

    def test_unresolved_owner_refs_cannot_self_promote_formal(self) -> None:
        construction = self.reference(
            ReferenceKind.CONSTRUCTION_SPEC,
            "formal-looking-construction-owner",
            "a",
        )
        risk_policy = self.reference(
            ReferenceKind.RISK_POLICY_SET,
            "formal_looking_risk_owner",
            "b",
        )
        self.assertEqual(construction.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(risk_policy.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(construction.owner_receipt_resolution, "UNRESOLVED_CALLER_ASSERTED")
        with self.assertRaisesRegex(WeightContractError, "not caller-selectable"):
            UnresolvedExactReference(
                ReferenceKind.CONSTRUCTION_SPEC,
                "fake-resolved-owner",
                sha("e"),
                FORMAL_ADMITTED_CEILING,
                "RESOLVED_CANONICAL_OWNER",
            )

    def test_risk_stage_order_and_wire_identity_are_deterministic(self) -> None:
        first_receipt = self.risk_receipt()
        second_receipt = self.risk_receipt()
        self.assertEqual(first_receipt, second_receipt)
        self.assertEqual(first_receipt.to_wire(), second_receipt.to_wire())
        with self.assertRaisesRegex(WeightContractError, "contiguous"):
            RiskApplicationReceipt.create(
                risk_policy_set=self.reference(
                    ReferenceKind.RISK_POLICY_SET,
                    "risk_policy_set_ordered",
                    "c",
                ),
                decision=RiskDecision.PASS_THROUGH,
                decision_reason=RiskDecisionReason.NO_ADDITIONAL_RISK_TRANSFORM,
                stages=(RiskStageEvidence(2, "wrong-order", "pass", sha("d")),),
                supporting_refs=(),
                runtime_identity=self.runtime,
            )


if __name__ == "__main__":
    unittest.main()
