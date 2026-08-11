from __future__ import annotations

import copy
import dataclasses
import inspect
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from track_f_strategy_runtime.helpers import (
    build_runtime_fixture,
    build_strategy_ir,
    sha,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.portfolio_construction import (
    ConstructionMethod,
    ConstructionRejectionReason,
    DeterministicPortfolioConstruction,
    OptimizerCandidate,
    PortfolioConstructionRejected,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.strategies import (
    DeterministicStrategyEvaluator,
    PortfolioIntent,
    PortfolioIntentItem,
    SelectionArtifact,
    StrategyCompiler,
    default_component_registry,
)
from v3_backend.domain.weights import RuntimeIdentity, TargetWeightRow
from v3_backend.provenance.canonical_hash import canonical_sha256


class PortfolioConstructionFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_fixture()
        self.evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            inputs=(self.fixture.runtime_input,),
        )
        assert self.evaluation.portfolio_intent is not None
        assert self.evaluation.selection_artifact is not None
        self.intent = self.evaluation.portfolio_intent
        self.runtime_identity = RuntimeIdentity(
            code_version="git:track-h-runtime-v0",
            runtime_profile_id="v3.portfolio-construction-runtime/1.0.0",
            environment_fingerprint="cpython-3.14.5-windows-x64",
        )
        self.runtime = DeterministicPortfolioConstruction()
        self.as_of = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        self.decision_time = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)
        self.rebalance_time = datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)
        self.valid_until = datetime(2026, 1, 6, 7, 0, tzinfo=timezone.utc)

    def spec(
        self,
        method: ConstructionMethod = ConstructionMethod.EQUAL_WEIGHT_SELECTED,
        *,
        cash: str = "0.1",
        maximum: str = "1",
        method_version: str = "1.0.0",
    ) -> PortfolioConstructionSpecVersion:
        return PortfolioConstructionSpecVersion.create(
            method=method,
            method_version=method_version,
            target_cash_weight=cash,
            max_instrument_weight=maximum,
            runtime_identity=self.runtime_identity,
        )

    def construct(
        self,
        *,
        intent: PortfolioIntent | None = None,
        spec: PortfolioConstructionSpecVersion | None = None,
        optimizer_candidate: OptimizerCandidate | None = None,
        fixture: object | None = None,
    ):
        active_fixture = fixture or self.fixture
        return self.runtime.construct(
            intent=intent or self.intent,
            definition=active_fixture.definition,
            binding=active_fixture.binding,
            construction_spec=spec or self.spec(),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of,
            decision_time=self.decision_time,
            rebalance_time=self.rebalance_time,
            valid_until=self.valid_until,
            optimizer_candidate=optimizer_candidate,
        )

    def recreate_intent(
        self, items: tuple[PortfolioIntentItem, ...]
    ) -> PortfolioIntent:
        return PortfolioIntent.create(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            selection_artifact=self.evaluation.selection_artifact,
            signal_artifact=self.evaluation.signal_artifact,
            exposure_mode=self.intent.exposure_mode,
            cash_policy=self.intent.cash_policy,
            rebalance_intent=self.intent.rebalance_intent,
            items=items,
            constraints=dict(self.intent.constraints),
        )

    @staticmethod
    def recanonicalize_malformed_intent(
        intent: PortfolioIntent, items: tuple[PortfolioIntentItem, ...]
    ) -> PortfolioIntent:
        provisional = dataclasses.replace(
            intent,
            portfolio_intent_id="pint_sha256_" + sha("0"),
            items=items,
        )
        wire = provisional.to_wire()
        payload = {
            key: value
            for key, value in wire.items()
            if key not in {"artifact_type", "portfolio_intent_id"}
        }
        return dataclasses.replace(
            provisional,
            portfolio_intent_id="pint_sha256_" + canonical_sha256(payload),
        )


class PortfolioConstructionRuntimeTests(PortfolioConstructionFixture):
    def test_exact_canonical_portfolio_intent_object_is_required(self) -> None:
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.runtime.construct(
                intent="pint_sha256_not_an_object",  # type: ignore[arg-type]
                definition=self.fixture.definition,
                binding=self.fixture.binding,
                construction_spec=self.spec(),
                runtime_identity=self.runtime_identity,
                base_currency="CNY",
                as_of=self.as_of,
                decision_time=self.decision_time,
                rebalance_time=self.rebalance_time,
                valid_until=self.valid_until,
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.INVALID_PORTFOLIO_INTENT,
        )

    def test_equal_weight_is_deterministic_and_uses_explicit_cash(self) -> None:
        first = self.construct()
        second = self.construct()
        self.assertEqual(first, second)
        self.assertEqual(first.target.cash_weight, "0.1")
        self.assertEqual(
            tuple((row.instrument_id, row.target_weight) for row in first.target.rows),
            (("000001.SZ", "0.45"), ("000002.SZ", "0.45")),
        )

    def test_input_order_does_not_change_intent_or_target_identity(self) -> None:
        reversed_intent = self.recreate_intent(tuple(reversed(self.intent.items)))
        self.assertEqual(reversed_intent, self.intent)
        self.assertEqual(
            self.construct(intent=reversed_intent).target.target_weight_vector_id,
            self.construct().target.target_weight_vector_id,
        )

    def test_rounding_residual_uses_largest_remainder_then_canonical_id(self) -> None:
        definition = StrategyCompiler(default_component_registry()).compile(
            build_strategy_ir(selection_count=3)
        )
        fixture = build_runtime_fixture(definition=definition)
        evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=fixture.definition,
            binding=fixture.binding,
            inputs=(fixture.runtime_input,),
        )
        assert evaluation.portfolio_intent is not None
        result = self.construct(
            intent=evaluation.portfolio_intent,
            spec=self.spec(cash="0"),
            fixture=fixture,
        )
        self.assertEqual(
            tuple((row.instrument_id, row.target_weight) for row in result.target.rows),
            (
                ("000001.SZ", "0.333333333334"),
                ("000002.SZ", "0.333333333333"),
                ("000003.SZ", "0.333333333333"),
            ),
        )
        self.assertEqual(
            result.diagnostics.rounding_residual_allocated,
            "0.000000000001",
        )

    def test_empty_selection_is_explicit_all_cash_or_typed_rejection(self) -> None:
        empty_selection = SelectionArtifact.create(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            entries=(),
            excluded_instrument_ids=self.fixture.binding.universe.instrument_ids,
            input_artifacts=self.evaluation.selection_artifact.input_artifacts,
        )
        empty_intent = PortfolioIntent.create(
            definition=self.fixture.definition,
            binding=self.fixture.binding,
            selection_artifact=empty_selection,
            signal_artifact=None,
            exposure_mode=self.intent.exposure_mode,
            cash_policy=self.intent.cash_policy,
            rebalance_intent=self.intent.rebalance_intent,
            items=(),
            constraints=dict(self.intent.constraints),
        )
        all_cash = self.construct(
            intent=empty_intent,
            spec=self.spec(cash="1"),
        )
        self.assertEqual(all_cash.target.rows, ())
        self.assertEqual(all_cash.target.cash_weight, "1")
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(
                intent=empty_intent,
                spec=self.spec(cash="0"),
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.EMPTY_SELECTION_INFEASIBLE,
        )

    def test_negative_and_nonfinite_desired_exposure_are_typed_rejections(self) -> None:
        negative = dataclasses.replace(self.intent.items[0], desired_exposure="-0.1")
        negative_intent = self.recreate_intent((negative, self.intent.items[1]))
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=negative_intent)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.INVALID_DESIRED_EXPOSURE,
        )

        nonfinite = copy.copy(self.intent.items[0])
        object.__setattr__(nonfinite, "desired_exposure", "NaN")
        nonfinite_intent = self.recanonicalize_malformed_intent(
            self.intent,
            (nonfinite, self.intent.items[1]),
        )
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=nonfinite_intent)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.INVALID_DESIRED_EXPOSURE,
        )

    def test_outside_universe_is_rejected_even_for_rehashed_input(self) -> None:
        outside = PortfolioIntentItem(
            "999999.SZ",
            "0.5",
            "1",
            ("malformed.external",),
        )
        malformed = self.recanonicalize_malformed_intent(
            self.intent,
            (self.intent.items[0], outside),
        )
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=malformed)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.OUTSIDE_EXACT_UNIVERSE,
        )

    def test_duplicate_instrument_is_rejected_even_for_rehashed_input(self) -> None:
        duplicate = dataclasses.replace(
            self.intent.items[1], instrument_id=self.intent.items[0].instrument_id
        )
        malformed = self.recanonicalize_malformed_intent(
            self.intent,
            (self.intent.items[0], duplicate),
        )
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=malformed)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.DUPLICATE_INSTRUMENT,
        )

    def test_budget_equation_and_complete_zero_absence_semantics(self) -> None:
        target = self.construct().target
        total = sum((Decimal(row.target_weight) for row in target.rows), Decimal(0))
        total += Decimal(target.cash_weight)
        self.assertEqual(total, Decimal(1))
        self.assertEqual(
            set(target.source.universe_instrument_ids)
            - {row.instrument_id for row in target.rows},
            {"000003.SZ", "000004.SZ"},
        )
        self.assertEqual(target.absent_member_policy.value, "ZERO")

    def test_changing_construction_spec_changes_target_identity(self) -> None:
        first = self.construct(spec=self.spec(method_version="1.0.0")).target
        second = self.construct(spec=self.spec(method_version="1.0.1")).target
        self.assertNotEqual(first.target_weight_vector_id, second.target_weight_vector_id)

    def test_changing_portfolio_intent_changes_target_identity(self) -> None:
        changed_items = (
            dataclasses.replace(self.intent.items[0], desired_exposure="0.8"),
            dataclasses.replace(self.intent.items[1], desired_exposure="0.2"),
        )
        changed = self.recreate_intent(changed_items)
        self.assertNotEqual(changed.portfolio_intent_id, self.intent.portfolio_intent_id)
        self.assertNotEqual(
            self.construct(intent=changed).target.target_weight_vector_id,
            self.construct().target.target_weight_vector_id,
        )

    def test_pre_alpha_truth_ceiling_is_preserved(self) -> None:
        result = self.construct()
        self.assertEqual(result.target.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.diagnostics.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.provenance.truth_admission, PRE_ALPHA_CEILING)

    def test_optimizer_candidate_cannot_assign_target_identity_or_enter_v0(self) -> None:
        self.assertNotIn(
            "target_weight_vector_id",
            {field.name for field in dataclasses.fields(OptimizerCandidate)},
        )
        self.assertNotIn(
            "target_weight_vector_id",
            inspect.signature(OptimizerCandidate.create).parameters,
        )
        candidate = OptimizerCandidate.create(
            backend="cvxpy",
            backend_version="1.9.2",
            objective="MIN_VARIANCE",
            constraints_sha256=sha("a"),
            tolerance="0.000001",
            status="SUCCESS",
            seed=None,
            rows=(TargetWeightRow("000001.SZ", "1"),),
        )
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(optimizer_candidate=candidate)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.OPTIMIZER_NOT_CONFIGURED,
        )

    def test_infeasible_constraints_are_typed_rejections(self) -> None:
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(spec=self.spec(cash="0", maximum="0.4"))
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.INSTRUMENT_WEIGHT_BOUND,
        )

    def test_normalized_desired_exposure_is_deterministic(self) -> None:
        items = (
            dataclasses.replace(self.intent.items[0], desired_exposure="0.8"),
            dataclasses.replace(self.intent.items[1], desired_exposure="0.2"),
        )
        intent = self.recreate_intent(items)
        result = self.construct(
            intent=intent,
            spec=self.spec(ConstructionMethod.NORMALIZED_DESIRED_EXPOSURE),
        )
        self.assertEqual(
            tuple((row.instrument_id, row.target_weight) for row in result.target.rows),
            (("000001.SZ", "0.72"), ("000002.SZ", "0.18")),
        )
        self.assertEqual(result.diagnostics.normalization_input_total, "1")

    def test_target_contains_no_execution_or_account_fields(self) -> None:
        wire = str(self.construct().target.to_wire()).lower()
        for forbidden in (
            "current_price",
            "current_holdings",
            "account",
            "order_status",
            "orders",
            "fills",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, wire)


if __name__ == "__main__":
    unittest.main()
