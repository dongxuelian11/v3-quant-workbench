from __future__ import annotations

import dataclasses
import platform
import unittest
from decimal import Decimal

from round3_w0_weight_seam.test_weight_seam import WeightSeamFixture
from v3_backend.contracts.common.truth_admission import (
    FORMAL_ADMITTED_CEILING,
    PRE_ALPHA_CEILING,
)
from v3_backend.domain.risk_runtime import (
    DecisionStatus,
    ExternalSolverAuthorityError,
    PitRequirement,
    PolicyMode,
    PolicyType,
    RISK_V0_BACKEND,
    ResidualCashRule,
    RiskPolicyDefinition,
    RiskPolicyRejected,
    RiskPolicySetVersion,
    RiskRuntimeError,
    RiskStateInput,
    RiskStateRequirement,
    StageStatus,
    apply_risk,
)
from v3_backend.domain.weights import (
    ReferenceKind,
    RiskAdjustedWeightVector,
    RiskDecision,
    RiskDecisionReason,
    RuntimeIdentity,
    TargetWeightRow,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


class RiskRuntimeFixture(WeightSeamFixture):
    def setUp(self) -> None:
        super().setUp()
        self.risk_runtime = RuntimeIdentity(
            code_version="git:round3-track-i-test",
            runtime_profile_id="v3.risk-runtime/1.0.0",
            environment_fingerprint=(
                f"cpython-{platform.python_version()}-"
                f"{platform.system().lower()}-{platform.machine().lower()}"
            ),
        )

    def pass_policy(self) -> RiskPolicyDefinition:
        return RiskPolicyDefinition.pass_through(
            code_version=self.risk_runtime.code_version,
            runtime_profile_id=self.risk_runtime.runtime_profile_id,
        )

    def max_policy(
        self,
        max_weight: str = "0.45",
        *,
        required_state_inputs: tuple[RiskStateRequirement, ...] = (),
    ) -> RiskPolicyDefinition:
        return RiskPolicyDefinition.max_single_name(
            max_weight=max_weight,
            required_state_inputs=required_state_inputs,
            code_version=self.risk_runtime.code_version,
            runtime_profile_id=self.risk_runtime.runtime_profile_id,
        )

    def exposure_policy(
        self,
        *,
        max_gross: str = "1",
        min_net: str = "0",
        max_net: str = "1",
        required_state_inputs: tuple[RiskStateRequirement, ...] = (),
    ) -> RiskPolicyDefinition:
        return RiskPolicyDefinition.gross_net_exposure_validate(
            max_gross=max_gross,
            min_net=min_net,
            max_net=max_net,
            required_state_inputs=required_state_inputs,
            code_version=self.risk_runtime.code_version,
            runtime_profile_id=self.risk_runtime.runtime_profile_id,
        )

    def apply(
        self,
        policies: tuple[RiskPolicyDefinition, ...],
        *,
        target=None,
        state_inputs: tuple[RiskStateInput, ...] = (),
    ):
        return apply_risk(
            source_target=target or self.target(),
            policy_set=RiskPolicySetVersion.create(policies),
            runtime_identity=self.risk_runtime,
            state_inputs=state_inputs,
        )

    def rehash_policy(
        self,
        policy: RiskPolicyDefinition,
        **changes: object,
    ) -> RiskPolicyDefinition:
        candidate = dataclasses.replace(policy, **changes)
        payload = {
            key: value
            for key, value in candidate.to_wire().items()
            if key not in {"policy_id", "content_sha256"}
        }
        digest = canonical_sha256(payload)
        return dataclasses.replace(
            candidate,
            policy_id="rpd_sha256_" + digest,
            content_sha256=digest,
        )

    def rehash_policy_set(
        self,
        policies: tuple[RiskPolicyDefinition, ...],
    ) -> RiskPolicySetVersion:
        payload = RiskPolicySetVersion._payload(policies, PRE_ALPHA_CEILING)
        digest = canonical_sha256(payload)
        return RiskPolicySetVersion(
            risk_policy_set_version_id="rpsv_sha256_" + digest,
            content_sha256=digest,
            policies=policies,
            truth_admission=PRE_ALPHA_CEILING,
        )


class RiskPolicySetTests(RiskRuntimeFixture):
    def test_normal_policy_factories_are_semantically_canonical(self) -> None:
        policies = (
            self.pass_policy(),
            self.max_policy(),
            self.exposure_policy(),
        )
        for policy in policies:
            with self.subTest(policy_type=policy.policy_type):
                policy.assert_canonical()
                self.assertEqual(policy.backend, RISK_V0_BACKEND)

    def test_public_factory_rejects_non_native_backend(self) -> None:
        common = {
            "code_version": self.risk_runtime.code_version,
            "runtime_profile_id": self.risk_runtime.runtime_profile_id,
            "backend": "cvxpy-worker",
        }
        factories = (
            lambda: RiskPolicyDefinition.pass_through(**common),
            lambda: RiskPolicyDefinition.max_single_name(
                max_weight="0.45",
                **common,
            ),
            lambda: RiskPolicyDefinition.gross_net_exposure_validate(
                max_gross="1",
                min_net="0",
                max_net="1",
                **common,
            ),
        )
        for factory in factories:
            with self.subTest(factory=factory):
                with self.assertRaisesRegex(RiskRuntimeError, "backend must be exactly"):
                    factory()

    def test_hash_consistent_pass_through_with_wrong_mode_is_rejected(self) -> None:
        forged = self.rehash_policy(
            self.pass_policy(),
            mode=PolicyMode.VALIDATE,
        )
        with self.assertRaisesRegex(RiskRuntimeError, "PASS_THROUGH mode"):
            forged.assert_canonical()

    def test_hash_consistent_max_single_name_with_wrong_cash_rule_is_rejected(
        self,
    ) -> None:
        forged = self.rehash_policy(
            self.max_policy(),
            residual_cash_rule=ResidualCashRule.PRESERVE,
        )
        with self.assertRaisesRegex(RiskRuntimeError, "ADD_REDUCTION_TO_CASH"):
            forged.assert_canonical()

    def test_hash_consistent_gross_net_with_invalid_parameters_is_rejected(
        self,
    ) -> None:
        forged = self.rehash_policy(
            self.exposure_policy(),
            parameters=(("max_gross", "1"), ("min_net", "0")),
        )
        with self.assertRaisesRegex(RiskRuntimeError, "exact gross/net limits"):
            forged.assert_canonical()

    def test_hash_consistent_policy_above_pre_alpha_is_rejected(self) -> None:
        forged = self.rehash_policy(
            self.pass_policy(),
            truth_admission=FORMAL_ADMITTED_CEILING,
        )
        with self.assertRaisesRegex(RiskRuntimeError, "cannot exceed PRE_ALPHA"):
            forged.assert_canonical()

    def test_hash_consistent_policy_with_wrong_pit_or_truth_requirement_is_rejected(
        self,
    ) -> None:
        cases = (
            (
                self.rehash_policy(
                    self.pass_policy(),
                    pit_requirement=PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION,
                ),
                "TARGET_ONLY",
            ),
            (
                self.rehash_policy(
                    self.pass_policy(),
                    truth_requirement="PROMOTE_AFTER_VALIDATION",
                ),
                "upstream truth ceiling",
            ),
        )
        for policy, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RiskRuntimeError, message):
                    policy.assert_canonical()

    def test_unsupported_backend_cannot_enter_policy_set(self) -> None:
        forged = self.rehash_policy(
            self.pass_policy(),
            backend="cvxpy-worker",
        )
        with self.assertRaisesRegex(RiskRuntimeError, "backend must be exactly"):
            RiskPolicySetVersion.create((forged,))

    def test_repeated_state_key_with_identical_kind_and_pit_is_allowed(self) -> None:
        requirement = RiskStateRequirement(
            "shared-risk-state",
            ReferenceKind.RISK_STATE,
            PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION,
        )
        policy_set = RiskPolicySetVersion.create(
            (
                self.max_policy(required_state_inputs=(requirement,)),
                self.exposure_policy(required_state_inputs=(requirement,)),
            )
        )
        self.assertEqual(len(policy_set.policies), 2)

    def test_repeated_state_key_with_conflicting_reference_kind_is_rejected(
        self,
    ) -> None:
        first = RiskStateRequirement("shared-risk-state", ReferenceKind.RISK_STATE)
        second = RiskStateRequirement("shared-risk-state", ReferenceKind.RISK_MODEL)
        with self.assertRaisesRegex(RiskRuntimeError, "reference_kind"):
            RiskPolicySetVersion.create(
                (
                    self.max_policy(required_state_inputs=(first,)),
                    self.exposure_policy(required_state_inputs=(second,)),
                )
            )

    def test_repeated_state_key_with_conflicting_pit_requirement_is_rejected(
        self,
    ) -> None:
        first = RiskStateRequirement(
            "shared-risk-state",
            ReferenceKind.RISK_STATE,
            PitRequirement.AS_OF_NOT_AFTER_TARGET_DECISION,
        )
        second = RiskStateRequirement(
            "shared-risk-state",
            ReferenceKind.RISK_STATE,
            PitRequirement.TARGET_ONLY,
        )
        with self.assertRaisesRegex(RiskRuntimeError, "pit_requirement"):
            RiskPolicySetVersion.create(
                (
                    self.max_policy(required_state_inputs=(first,)),
                    self.exposure_policy(required_state_inputs=(second,)),
                )
            )

    def test_policy_set_is_immutable_content_addressed_and_ordered(self) -> None:
        pass_policy = self.pass_policy()
        validate = self.exposure_policy()
        first = RiskPolicySetVersion.create((pass_policy, validate))
        second = RiskPolicySetVersion.create((validate, pass_policy))

        self.assertNotEqual(first.risk_policy_set_version_id, second.risk_policy_set_version_id)
        self.assertNotEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(first, RiskPolicySetVersion.create((pass_policy, validate)))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            first.content_sha256 = "0" * 64  # type: ignore[misc]

    def test_policy_parameter_change_changes_identity(self) -> None:
        first = self.max_policy("0.45")
        second = self.max_policy("0.44")
        self.assertNotEqual(first.policy_id, second.policy_id)
        self.assertNotEqual(
            RiskPolicySetVersion.create((first,)).risk_policy_set_version_id,
            RiskPolicySetVersion.create((second,)).risk_policy_set_version_id,
        )

    def test_non_transforming_set_requires_explicit_pass_through(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit PASS_THROUGH"):
            RiskPolicySetVersion.create((self.exposure_policy(),))

    def test_policy_contract_declares_required_semantics(self) -> None:
        policy = self.max_policy()
        wire = policy.to_wire()
        self.assertEqual(wire["policy_type"], "MAX_SINGLE_NAME")
        self.assertEqual(wire["mode"], "CLIP")
        self.assertEqual(wire["failure_behavior"], "REJECT")
        self.assertEqual(wire["residual_cash_rule"], "ADD_REDUCTION_TO_CASH")
        self.assertEqual(wire["risk_model_requirement"], "NOT_REQUIRED")
        self.assertEqual(wire["backend"], "v3-native-decimal")
        self.assertIn("truth_requirement", wire)
        self.assertIn("pit_requirement", wire)


class RiskRuntimeTests(RiskRuntimeFixture):
    def test_native_backend_executes_and_manual_non_native_set_cannot(self) -> None:
        native = self.apply((self.pass_policy(),))
        self.assertEqual(native.policy_set.policies[0].backend, RISK_V0_BACKEND)

        non_native = self.rehash_policy(
            self.pass_policy(),
            backend="cvxpy-worker",
        )
        with self.assertRaisesRegex(RiskRuntimeError, "backend must be exactly"):
            apply_risk(
                source_target=self.target(),
                policy_set=self.rehash_policy_set((non_native,)),
                runtime_identity=self.risk_runtime,
            )

    def test_policy_code_and_runtime_profile_must_match_execution_runtime(
        self,
    ) -> None:
        wrong_runtime = dataclasses.replace(
            self.risk_runtime,
            runtime_profile_id="v3.risk-runtime/wrong-profile",
        )
        with self.assertRaisesRegex(RiskRuntimeError, "match exactly"):
            apply_risk(
                source_target=self.target(),
                policy_set=RiskPolicySetVersion.create((self.pass_policy(),)),
                runtime_identity=wrong_runtime,
            )

    def test_exact_canonical_target_object_is_required(self) -> None:
        with self.assertRaisesRegex(TypeError, "canonical W0 TargetWeightVector object"):
            apply_risk(
                source_target="twv_sha256_" + "1" * 64,  # type: ignore[arg-type]
                policy_set=RiskPolicySetVersion.create((self.pass_policy(),)),
                runtime_identity=self.risk_runtime,
            )

    def test_source_target_is_never_mutated(self) -> None:
        target = self.target()
        before = target.to_wire()
        result = self.apply((self.max_policy(),), target=target)
        self.assertEqual(target.to_wire(), before)
        self.assertEqual(target.rows[0].target_weight, "0.5")
        self.assertNotEqual(result.adjusted_weights.rows, target.rows)

    def test_explicit_pass_through_has_equal_rows_and_new_identity(self) -> None:
        target = self.target()
        result = self.apply((self.pass_policy(),), target=target)
        adjusted = result.adjusted_weights

        self.assertIsInstance(adjusted, RiskAdjustedWeightVector)
        self.assertEqual(adjusted.rows, target.rows)
        self.assertEqual(adjusted.cash_weight, target.cash_weight)
        self.assertNotEqual(adjusted.risk_adjusted_weight_vector_id, target.target_weight_vector_id)
        self.assertEqual(result.decision_report.decision, DecisionStatus.PASS_THROUGH)
        self.assertEqual(result.decision_report.stages[0].reason, "NO_ADDITIONAL_RISK_TRANSFORM")
        self.assertEqual(result.application_receipt.decision, RiskDecision.PASS_THROUGH)
        self.assertEqual(
            result.application_receipt.decision_reason,
            RiskDecisionReason.NO_ADDITIONAL_RISK_TRANSFORM,
        )

    def test_policy_order_changes_published_identity(self) -> None:
        pass_policy = self.pass_policy()
        validate = self.exposure_policy()
        first = self.apply((pass_policy, validate))
        second = self.apply((validate, pass_policy))
        self.assertNotEqual(
            first.adjusted_weights.risk_adjusted_weight_vector_id,
            second.adjusted_weights.risk_adjusted_weight_vector_id,
        )
        self.assertNotEqual(
            first.application_receipt.ordered_stage_evidence_sha256,
            second.application_receipt.ordered_stage_evidence_sha256,
        )

    def test_max_single_name_is_deterministic(self) -> None:
        first = self.apply((self.max_policy(),))
        second = self.apply((self.max_policy(),))
        self.assertEqual(first, second)
        self.assertEqual(
            tuple((value.instrument_id, value.target_weight) for value in first.adjusted_weights.rows),
            (("000001.SZ", "0.45"), ("000002.SZ", "0.4")),
        )
        self.assertEqual(first.adjusted_weights.cash_weight, "0.15")
        self.assertEqual(first.decision_report.decision, DecisionStatus.ADJUSTED)

    def test_max_single_name_declares_and_satisfies_residual_cash_equation(self) -> None:
        target = self.target()
        result = self.apply((self.max_policy(),), target=target)
        reduction = sum(
            (Decimal(before.target_weight) - Decimal(after.target_weight))
            for before, after in zip(target.rows, result.adjusted_weights.rows, strict=True)
        )
        cash_increase = Decimal(result.adjusted_weights.cash_weight) - Decimal(target.cash_weight)
        self.assertEqual(reduction, cash_increase)
        stage = result.decision_report.stages[0]
        self.assertEqual(stage.residual_cash_handling, ResidualCashRule.ADD_REDUCTION_TO_CASH)
        self.assertEqual(stage.reason, "MAX_SINGLE_NAME_CLIPPED")

    def test_gross_net_exposure_validation_has_typed_rejection(self) -> None:
        with self.assertRaises(RiskPolicyRejected) as captured:
            self.apply((self.pass_policy(), self.exposure_policy(max_gross="0.8")))
        report = captured.exception.report
        self.assertEqual(report.decision, DecisionStatus.REJECTED)
        self.assertEqual(report.rejection_reason, "GROSS_EXPOSURE_LIMIT_EXCEEDED")
        self.assertEqual(report.stages[-1].status, StageStatus.REJECTED)

    def test_missing_required_state_fails_closed_without_fallback(self) -> None:
        requirement = RiskStateRequirement("exposure-limit-state", ReferenceKind.RISK_STATE)
        target = self.target()
        with self.assertRaises(RiskPolicyRejected) as captured:
            self.apply(
                (
                    self.exposure_policy(required_state_inputs=(requirement,)),
                    self.pass_policy(),
                ),
                target=target,
            )
        report = captured.exception.report
        self.assertEqual(
            report.rejection_reason,
            "MISSING_REQUIRED_RISK_STATE:exposure-limit-state",
        )
        self.assertEqual(report.final_rows, target.rows)
        self.assertEqual(report.final_cash_weight, target.cash_weight)
        self.assertFalse(hasattr(captured.exception, "adjusted_weights"))

    def test_required_state_is_exact_and_pit_safe(self) -> None:
        requirement = RiskStateRequirement("exposure-limit-state", ReferenceKind.RISK_STATE)
        policy = self.exposure_policy(required_state_inputs=(requirement,))
        state = RiskStateInput(
            "exposure-limit-state",
            self.reference(ReferenceKind.RISK_STATE, "risk-state-1", "9"),
            self.decision_time,
        )
        result = self.apply((policy, self.pass_policy()), state_inputs=(state,))
        self.assertEqual(result.decision_report.state_inputs, (state,))
        self.assertIn(state.reference, result.application_receipt.supporting_refs)

        future_state = dataclasses.replace(state, as_of=self.valid_until)
        with self.assertRaises(RiskPolicyRejected) as captured:
            self.apply((policy, self.pass_policy()), state_inputs=(future_state,))
        self.assertEqual(
            captured.exception.report.rejection_reason,
            "RISK_STATE_PIT_VIOLATION:exposure-limit-state",
        )

    def test_source_target_change_changes_output_identity(self) -> None:
        target_a = self.target()
        target_b = self.target(
            rows=(
                TargetWeightRow("000001.SZ", "0.4"),
                TargetWeightRow("000002.SZ", "0.4"),
            ),
            cash_weight="0.2",
        )
        first = self.apply((self.pass_policy(),), target=target_a)
        second = self.apply((self.pass_policy(),), target=target_b)
        self.assertNotEqual(
            first.adjusted_weights.risk_adjusted_weight_vector_id,
            second.adjusted_weights.risk_adjusted_weight_vector_id,
        )

    def test_pre_alpha_truth_ceiling_is_preserved(self) -> None:
        result = self.apply((self.max_policy(),))
        self.assertEqual(result.policy_set.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.decision_report.truth_admission, PRE_ALPHA_CEILING)
        self.assertEqual(result.adjusted_weights.truth_admission, PRE_ALPHA_CEILING)

    def test_external_solver_candidate_cannot_publish_canonical_output(self) -> None:
        with self.assertRaisesRegex(
            ExternalSolverAuthorityError,
            "cannot assign canonical Risk V0 output",
        ):
            apply_risk(
                source_target=self.target(),
                policy_set=RiskPolicySetVersion.create((self.pass_policy(),)),
                runtime_identity=self.risk_runtime,
                external_solver_candidate={"weights": {"000001.SZ": "1"}},
            )

    def test_stage_evidence_is_complete_and_deterministic(self) -> None:
        policies = (self.max_policy(), self.exposure_policy(), self.pass_policy())
        first = self.apply(policies)
        second = self.apply(policies)
        self.assertEqual(first.decision_report.to_wire(), second.decision_report.to_wire())
        expected = {
            "schema_version",
            "risk_stage_report_id",
            "content_sha256",
            "stage_index",
            "policy_id",
            "policy_type",
            "input_vector_sha256",
            "output_vector_sha256",
            "input_rows",
            "output_rows",
            "before",
            "after",
            "limits",
            "reason",
            "status",
            "residual_cash_handling",
            "required_state_refs",
            "external_solver_evidence",
        }
        for index, stage in enumerate(first.decision_report.stages, start=1):
            self.assertEqual(set(stage.to_wire()), expected)
            self.assertEqual(stage.stage_index, index)
            self.assertEqual(stage.external_solver_evidence, "NOT_USED_V0")

    def test_tampered_report_or_stage_cannot_become_w0_evidence(self) -> None:
        result = self.apply((self.max_policy(), self.pass_policy()))
        tampered_report = dataclasses.replace(
            result.decision_report,
            final_vector_sha256="0" * 64,
        )
        with self.assertRaisesRegex(RiskRuntimeError, "content identity mismatch"):
            tampered_report.as_w0_reference()

        tampered_stage = dataclasses.replace(
            result.decision_report.stages[0],
            reason="TAMPERED_REASON",
        )
        tampered_chain = dataclasses.replace(
            result.decision_report,
            stages=(tampered_stage, *result.decision_report.stages[1:]),
        )
        with self.assertRaisesRegex(RiskRuntimeError, "content identity mismatch"):
            tampered_chain.as_w0_reference()

    def test_policy_types_and_modes_are_closed_not_callbacks(self) -> None:
        self.assertEqual(
            set(PolicyType),
            {
                PolicyType.PASS_THROUGH,
                PolicyType.MAX_SINGLE_NAME,
                PolicyType.GROSS_NET_EXPOSURE_VALIDATE,
            },
        )
        self.assertEqual(self.pass_policy().mode, PolicyMode.PASS_THROUGH)
        self.assertEqual(self.max_policy().mode, PolicyMode.CLIP)
        self.assertEqual(self.exposure_policy().mode, PolicyMode.VALIDATE)


if __name__ == "__main__":
    unittest.main()
