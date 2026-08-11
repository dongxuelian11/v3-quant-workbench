from __future__ import annotations

import copy
import dataclasses
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from track_f_strategy_runtime.helpers import (
    build_runtime_fixture,
    build_strategy_ir,
    sha,
)
from v3_backend.contracts.common.truth_admission import PRE_ALPHA_CEILING
from v3_backend.domain.portfolio_construction import (
    ConstructionMethod,
    ConstructionRejectionReason,
    DesiredExposureMagnitudePolicy,
    DeterministicPortfolioConstruction,
    IntentConstraintNormalization,
    IntentExposureMode,
    IntentRebalancePolicy,
    OptimizerCandidate,
    PortfolioConstructionRejected,
    PortfolioConstructionSpecVersion,
)
from v3_backend.domain.strategies import (
    DeterministicStrategyEvaluator,
    EvaluationPeriod,
    PortfolioIntent,
    PortfolioIntentItem,
    SelectionArtifact,
    StrategyCompiler,
    StrategyEvaluationBindingVersion,
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
        as_of: datetime | None = None,
        decision_time: datetime | None = None,
        rebalance_time: datetime | None = None,
        valid_until: datetime | None = None,
    ):
        active_fixture = fixture or self.fixture
        return self.runtime.construct(
            intent=intent or self.intent,
            definition=active_fixture.definition,
            binding=active_fixture.binding,
            construction_spec=spec or self.spec(),
            runtime_identity=self.runtime_identity,
            base_currency="CNY",
            as_of=self.as_of if as_of is None else as_of,
            decision_time=(
                self.decision_time if decision_time is None else decision_time
            ),
            rebalance_time=(
                self.rebalance_time if rebalance_time is None else rebalance_time
            ),
            valid_until=self.valid_until if valid_until is None else valid_until,
            optimizer_candidate=optimizer_candidate,
        )

    def recreate_intent(
        self,
        items: tuple[PortfolioIntentItem, ...] | None = None,
        *,
        exposure_mode: str | None = None,
        cash_policy: str | None = None,
        rebalance_intent: str | None = None,
        constraints: dict[str, object] | None = None,
        fixture: object | None = None,
        evaluation: object | None = None,
    ) -> PortfolioIntent:
        active_fixture = fixture or self.fixture
        active_evaluation = evaluation or self.evaluation
        base_intent = active_evaluation.portfolio_intent or self.intent
        return PortfolioIntent.create(
            definition=active_fixture.definition,
            binding=active_fixture.binding,
            selection_artifact=active_evaluation.selection_artifact,
            signal_artifact=active_evaluation.signal_artifact,
            exposure_mode=exposure_mode or base_intent.exposure_mode,
            cash_policy=cash_policy or base_intent.cash_policy,
            rebalance_intent=rebalance_intent or base_intent.rebalance_intent,
            items=base_intent.items if items is None else items,
            constraints=(
                dict(base_intent.constraints) if constraints is None else constraints
            ),
        )

    def fixture_with_period_end(self, end: datetime):
        binding = StrategyEvaluationBindingVersion.create(
            definition=self.fixture.definition,
            dataset=self.fixture.dataset,
            factor_evaluations=(self.fixture.factor_evaluation,),
            feature_materializations=(self.fixture.materialization,),
            snapshot=self.fixture.binding.snapshot,
            universe=self.fixture.binding.universe,
            period=EvaluationPeriod(self.fixture.binding.period.start, end),
            knowledge_cutoff=self.fixture.binding.knowledge_cutoff,
            calendar=self.fixture.binding.calendar,
            compiler_version=self.fixture.binding.compiler_version,
            runtime_profile_id=self.fixture.binding.runtime_profile_id,
            environment_fingerprint=self.fixture.binding.environment_fingerprint,
            input_references=self.fixture.binding.input_references,
            generic_artifact_references=(
                self.fixture.binding.generic_artifact_references
            ),
        )
        fixture = dataclasses.replace(self.fixture, binding=binding)
        evaluation = DeterministicStrategyEvaluator().evaluate(
            definition=fixture.definition,
            binding=fixture.binding,
            inputs=(fixture.runtime_input,),
        )
        assert evaluation.portfolio_intent is not None
        return fixture, evaluation

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

    def test_arbitrary_exposure_mode_cannot_use_a_matching_arbitrary_spec(self) -> None:
        self.assertNotIn(
            "accepted_intent_exposure_mode",
            inspect.signature(PortfolioConstructionSpecVersion.create).parameters,
        )
        with self.assertRaises(TypeError):
            PortfolioConstructionSpecVersion.create(
                method=ConstructionMethod.EQUAL_WEIGHT_SELECTED,
                method_version="1.0.0",
                target_cash_weight="0.1",
                runtime_identity=self.runtime_identity,
                accepted_intent_exposure_mode="ARBITRARY_MODE",  # type: ignore[call-arg]
            )
        arbitrary = self.recreate_intent(exposure_mode="ARBITRARY_MODE")
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=arbitrary)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.EXPOSURE_MODE_MISMATCH,
        )

    def test_arbitrary_cash_and_rebalance_semantics_fail_closed(self) -> None:
        for field, value, reason in (
            (
                "cash_policy",
                "ARBITRARY_CASH",
                ConstructionRejectionReason.CASH_POLICY_MISMATCH,
            ),
            (
                "rebalance_intent",
                "ARBITRARY_REBALANCE",
                ConstructionRejectionReason.REBALANCE_INTENT_MISMATCH,
            ),
        ):
            with self.subTest(field=field):
                intent = self.recreate_intent(**{field: value})
                with self.assertRaises(PortfolioConstructionRejected) as raised:
                    self.construct(intent=intent)
                self.assertIs(raised.exception.reason, reason)

    def test_supported_rebalance_semantics_are_exactly_admitted(self) -> None:
        result = self.construct()
        self.assertIs(
            self.spec().accepted_intent_rebalance_intent,
            IntentRebalancePolicy.AT_BOUND_DECISION_TIME,
        )
        self.assertIs(
            result.diagnostics.intent_rebalance_intent,
            IntentRebalancePolicy.AT_BOUND_DECISION_TIME,
        )

    def test_required_constraint_flags_fail_closed(self) -> None:
        cases = (
            (
                {
                    "proposal_only": True,
                    "normalization": "EQUAL_DESIRED_EXPOSURE",
                },
                ConstructionRejectionReason.UNSUPPORTED_INTENT_CONSTRAINT,
            ),
            (
                {
                    "proposal_only": True,
                    "normalization": "EQUAL_DESIRED_EXPOSURE",
                    "portfolio_service_required": False,
                },
                ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
            ),
            (
                {
                    "proposal_only": False,
                    "normalization": "EQUAL_DESIRED_EXPOSURE",
                    "portfolio_service_required": True,
                },
                ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
            ),
        )
        for constraints, reason in cases:
            with self.subTest(constraints=constraints):
                with self.assertRaises(PortfolioConstructionRejected) as raised:
                    self.construct(intent=self.recreate_intent(constraints=constraints))
                self.assertIs(raised.exception.reason, reason)

    def test_unknown_constraint_and_normalization_marker_fail_closed(self) -> None:
        unknown = dict(self.intent.constraints)
        unknown["future_constraint"] = "ignored-nowhere"
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=self.recreate_intent(constraints=unknown))
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.UNSUPPORTED_INTENT_CONSTRAINT,
        )
        unsupported = dict(self.intent.constraints)
        unsupported["normalization"] = "ARBITRARY_NORMALIZATION"
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=self.recreate_intent(constraints=unsupported))
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.INTENT_CONSTRAINT_MISMATCH,
        )

    def test_equal_marker_rejects_incompatible_desired_exposures(self) -> None:
        incompatible = self.recreate_intent(
            (
                dataclasses.replace(self.intent.items[0], desired_exposure="0.8"),
                dataclasses.replace(self.intent.items[1], desired_exposure="0.2"),
            )
        )
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(intent=incompatible)
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.DESIRED_EXPOSURE_SEMANTICS_MISMATCH,
        )

    def test_equal_method_records_magnitude_and_selection_transform(self) -> None:
        result = self.construct()
        self.assertIs(
            result.diagnostics.desired_exposure_magnitude_policy,
            DesiredExposureMagnitudePolicy.NOT_PRESERVED,
        )
        self.assertEqual(
            result.diagnostics.selection_transform.value,
            "SELECTION_MEMBERSHIP_REWEIGHTED_EQUAL",
        )

    def test_method_semantic_policy_changes_spec_and_target_identity(self) -> None:
        equal_spec = self.spec(ConstructionMethod.EQUAL_WEIGHT_SELECTED)
        normalized_spec = self.spec(ConstructionMethod.NORMALIZED_DESIRED_EXPOSURE)
        self.assertNotEqual(
            equal_spec.portfolio_construction_spec_version_id,
            normalized_spec.portfolio_construction_spec_version_id,
        )
        normalized_intent = self.recreate_intent(
            exposure_mode=IntentExposureMode.RELATIVE_DESIRED_EXPOSURE.value,
            constraints={
                "proposal_only": True,
                "normalization": "RELATIVE_DESIRED_EXPOSURE",
                "portfolio_service_required": True,
            },
        )
        self.assertNotEqual(
            self.construct(spec=equal_spec).target.target_weight_vector_id,
            self.construct(
                intent=normalized_intent, spec=normalized_spec
            ).target.target_weight_vector_id,
        )

    def test_changing_portfolio_intent_changes_target_identity(self) -> None:
        changed_items = (
            dataclasses.replace(self.intent.items[0], source_score="2"),
            self.intent.items[1],
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
        intent = self.recreate_intent(
            items,
            exposure_mode=IntentExposureMode.RELATIVE_DESIRED_EXPOSURE.value,
            constraints={
                "proposal_only": True,
                "normalization": (
                    IntentConstraintNormalization.RELATIVE_DESIRED_EXPOSURE.value
                ),
                "portfolio_service_required": True,
            },
        )
        result = self.construct(
            intent=intent,
            spec=self.spec(ConstructionMethod.NORMALIZED_DESIRED_EXPOSURE),
        )
        self.assertEqual(
            tuple((row.instrument_id, row.target_weight) for row in result.target.rows),
            (("000001.SZ", "0.72"), ("000002.SZ", "0.18")),
        )
        self.assertEqual(result.diagnostics.normalization_input_total, "1")
        self.assertIs(
            result.diagnostics.intent_exposure_mode,
            IntentExposureMode.RELATIVE_DESIRED_EXPOSURE,
        )
        self.assertIs(
            result.diagnostics.desired_exposure_magnitude_policy,
            DesiredExposureMagnitudePolicy.RELATIVE_INPUTS,
        )

    def test_as_of_before_binding_period_is_rejected(self) -> None:
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(as_of=self.fixture.binding.period.start - timedelta(minutes=1))
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.AS_OF_OUTSIDE_BINDING_PERIOD,
        )

    def test_decision_time_before_binding_period_is_rejected(self) -> None:
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(
                as_of=self.fixture.binding.period.start + timedelta(minutes=1),
                decision_time=self.fixture.binding.period.start - timedelta(minutes=1),
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.DECISION_TIME_OUTSIDE_BINDING_PERIOD,
        )

    def test_decision_time_after_binding_period_is_rejected(self) -> None:
        decision = self.fixture.binding.period.end + timedelta(minutes=1)
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(
                decision_time=decision,
                rebalance_time=decision + timedelta(minutes=1),
                valid_until=decision + timedelta(minutes=2),
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.DECISION_TIME_OUTSIDE_BINDING_PERIOD,
        )

    def test_decision_time_after_knowledge_cutoff_is_rejected(self) -> None:
        cutoff = self.fixture.binding.knowledge_cutoff
        fixture, evaluation = self.fixture_with_period_end(cutoff + timedelta(hours=2))
        decision = cutoff + timedelta(minutes=10)
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(
                intent=evaluation.portfolio_intent,
                fixture=fixture,
                decision_time=decision,
                rebalance_time=decision + timedelta(minutes=10),
                valid_until=decision + timedelta(minutes=20),
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.DECISION_TIME_AFTER_KNOWLEDGE_CUTOFF,
        )

    def test_as_of_after_knowledge_cutoff_is_rejected(self) -> None:
        cutoff = self.fixture.binding.knowledge_cutoff
        fixture, evaluation = self.fixture_with_period_end(cutoff + timedelta(hours=2))
        as_of = cutoff + timedelta(minutes=5)
        decision = cutoff + timedelta(minutes=10)
        with self.assertRaises(PortfolioConstructionRejected) as raised:
            self.construct(
                intent=evaluation.portfolio_intent,
                fixture=fixture,
                as_of=as_of,
                decision_time=decision,
                rebalance_time=decision + timedelta(minutes=10),
                valid_until=decision + timedelta(minutes=20),
            )
        self.assertIs(
            raised.exception.reason,
            ConstructionRejectionReason.AS_OF_AFTER_KNOWLEDGE_CUTOFF,
        )

    def test_valid_in_period_timing_records_exact_evidence(self) -> None:
        result = self.construct()
        diagnostics = result.diagnostics.to_wire()
        provenance = result.provenance.to_wire()
        expected = {
            "as_of": "2026-01-05T14:30:00Z",
            "decision_time": "2026-01-05T15:00:00Z",
            "rebalance_time": "2026-01-06T01:30:00Z",
            "valid_until": "2026-01-06T07:00:00Z",
            "binding_period_start": "2026-01-05T08:00:00Z",
            "binding_period_end": "2026-01-05T16:00:00Z",
            "binding_knowledge_cutoff": "2026-01-05T16:00:00Z",
            "timing_validation_status": (
                "PASSED_EXACT_BINDING_PERIOD_AND_KNOWLEDGE_CUTOFF_V1"
            ),
            "intent_rebalance_intent": "AT_BOUND_DECISION_TIME",
        }
        for key, value in expected.items():
            with self.subTest(evidence=key):
                self.assertEqual(diagnostics[key], value)
        provenance_expected = dict(expected)
        provenance_expected["rebalance_intent"] = provenance_expected.pop(
            "intent_rebalance_intent"
        )
        for key, value in provenance_expected.items():
            with self.subTest(provenance=key):
                self.assertEqual(provenance[key], value)

    def test_changing_target_timing_changes_all_construction_identities(self) -> None:
        first = self.construct()
        second = self.construct(
            decision_time=self.decision_time - timedelta(minutes=15),
            rebalance_time=self.rebalance_time + timedelta(minutes=30),
            valid_until=self.valid_until + timedelta(minutes=30),
        )
        self.assertNotEqual(
            first.diagnostics.diagnostics_id, second.diagnostics.diagnostics_id
        )
        self.assertNotEqual(
            first.provenance.provenance_id, second.provenance.provenance_id
        )
        self.assertNotEqual(
            first.target.target_weight_vector_id,
            second.target.target_weight_vector_id,
        )

    def test_runtime_contract_disclaims_formal_decision_time_receipt(self) -> None:
        contract = (
            Path(__file__).resolve().parents[4]
            / "docs"
            / "portfolio-construction-runtime-v0"
            / "RUNTIME_CONTRACT.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "no owner-resolved exact Strategy evaluation decision-time receipt",
            contract,
        )

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
