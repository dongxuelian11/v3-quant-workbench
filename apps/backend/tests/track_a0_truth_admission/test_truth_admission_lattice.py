from __future__ import annotations

import itertools
import unittest

from v3_backend.contracts.common.capability_state import (
    CapabilityTruthState,
    CapabilityTruthV1,
    OperationalTruthState,
)
from v3_backend.contracts.common.truth_admission import (
    AdmissionState,
    CanonicalClaimKind,
    FORMAL_ADMITTED_CEILING,
    InvalidTruthAdmissionState,
    LegacyTruthCompatibilityReason,
    LegacyTruthVocabulary,
    NOT_FORMAL_CEILING,
    OrderRelation,
    PRE_ALPHA_CEILING,
    PublicationState,
    TruthAdmissionClaim,
    TruthAdmissionState,
    TruthState,
    UNKNOWN_CEILING,
    UnsupportedTruthAdmissionState,
    UpstreamRequirement,
    ValidationState,
    aggregate_upstream_requirements,
    compare_states,
    is_at_most,
    meet_all,
    meet_pair,
    propagate_downstream_ceiling,
    reconcile_capability_truth_ceiling,
    reconcile_operational_truth_ceiling,
)


class TruthAdmissionLatticeTests(unittest.TestCase):
    def test_identical_state_meet_is_idempotent(self) -> None:
        for state in (
            UNKNOWN_CEILING,
            NOT_FORMAL_CEILING,
            PRE_ALPHA_CEILING,
            FORMAL_ADMITTED_CEILING,
        ):
            self.assertEqual(meet_pair(state, state), state)

    def test_mixed_state_meet_returns_greatest_common_ceiling(self) -> None:
        formal_not_admitted = TruthAdmissionState(
            TruthState.FORMAL, AdmissionState.PRE_ALPHA
        )
        self.assertEqual(
            meet_pair(formal_not_admitted, PRE_ALPHA_CEILING), PRE_ALPHA_CEILING
        )

    def test_multi_upstream_aggregation_is_sorted_and_deterministic(self) -> None:
        aggregate = aggregate_upstream_requirements(
            (
                UpstreamRequirement("universe", FORMAL_ADMITTED_CEILING),
                UpstreamRequirement("dataset", PRE_ALPHA_CEILING),
                UpstreamRequirement("snapshot", FORMAL_ADMITTED_CEILING),
            )
        )
        self.assertEqual(
            tuple(item.source_id for item in aggregate.requirements),
            ("dataset", "snapshot", "universe"),
        )
        self.assertEqual(aggregate.ceiling, PRE_ALPHA_CEILING)

    def test_pre_alpha_upstream_prevents_formal_downstream(self) -> None:
        ceiling = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement("snapshot", PRE_ALPHA_CEILING),
                UpstreamRequirement("factor-proof", FORMAL_ADMITTED_CEILING),
            ),
        )
        self.assertEqual(ceiling, PRE_ALPHA_CEILING)
        self.assertFalse(is_at_most(FORMAL_ADMITTED_CEILING, ceiling))

    def test_unknown_upstream_fails_closed(self) -> None:
        ceiling = propagate_downstream_ceiling(
            FORMAL_ADMITTED_CEILING,
            (
                UpstreamRequirement("known", FORMAL_ADMITTED_CEILING),
                UpstreamRequirement("unknown", UNKNOWN_CEILING),
            ),
        )
        self.assertEqual(ceiling, UNKNOWN_CEILING)

    def test_invalid_or_unsupported_state_fails_closed(self) -> None:
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionState(
                TruthState.NOT_FORMAL, AdmissionState.FORMAL_ADMITTED
            )
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionState.from_wire(
                {
                    "canonical_truth_state": "CERTAIN",
                    "canonical_admission_state": "FORMAL_ADMITTED",
                }
            )
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionState.from_wire(
                {
                    "canonical_truth_state": "FORMAL",
                    "canonical_admission_state": "FORMAL_ADMITTED",
                    "fallback": True,
                }
            )

    def test_publication_and_validation_do_not_promote_admission(self) -> None:
        claim = TruthAdmissionClaim(
            state=PRE_ALPHA_CEILING,
            publication=PublicationState.PUBLISHED,
            validation=ValidationState.PASSED,
            kind=CanonicalClaimKind.PROPOSAL,
        )
        self.assertEqual(claim.state, PRE_ALPHA_CEILING)
        self.assertIs(claim.kind, CanonicalClaimKind.PROPOSAL)
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionClaim(
                state=PRE_ALPHA_CEILING,
                publication=PublicationState.PUBLISHED,
                validation=ValidationState.PASSED,
                kind=CanonicalClaimKind.ADMITTED_CANONICAL_TRUTH,
            )

    def test_strong_downstream_proof_cannot_exceed_upstream_ceiling(self) -> None:
        proposed = FORMAL_ADMITTED_CEILING
        actual = propagate_downstream_ceiling(
            proposed,
            (UpstreamRequirement("dataset", NOT_FORMAL_CEILING),),
        )
        self.assertEqual(actual, NOT_FORMAL_CEILING)
        self.assertTrue(is_at_most(actual, proposed))

    def test_ordering_and_meet_are_deterministic_for_all_permutations(self) -> None:
        states = (
            FORMAL_ADMITTED_CEILING,
            PRE_ALPHA_CEILING,
            UNKNOWN_CEILING,
        )
        observed = {meet_all(permutation) for permutation in itertools.permutations(states)}
        self.assertEqual(observed, {UNKNOWN_CEILING})
        for left, right in itertools.product(states, repeat=2):
            self.assertEqual(meet_pair(left, right), meet_pair(right, left))

    def test_meet_is_the_greatest_lower_bound_for_every_valid_pair(self) -> None:
        valid_states = tuple(
            TruthAdmissionState(truth, admission)
            for truth in TruthState
            for admission in AdmissionState
            if admission
            in {
                TruthState.UNKNOWN: {AdmissionState.UNKNOWN},
                TruthState.NOT_FORMAL: {
                    AdmissionState.UNKNOWN,
                    AdmissionState.PRE_ALPHA,
                },
                TruthState.FORMAL: set(AdmissionState),
            }[truth]
        )
        for left, right in itertools.product(valid_states, repeat=2):
            result = meet_pair(left, right)
            self.assertTrue(is_at_most(result, left))
            self.assertTrue(is_at_most(result, right))
            for candidate in valid_states:
                if is_at_most(candidate, left) and is_at_most(candidate, right):
                    self.assertTrue(is_at_most(candidate, result))

    def test_incomparable_state_is_explicit(self) -> None:
        formal_unknown = TruthAdmissionState(
            TruthState.FORMAL, AdmissionState.UNKNOWN
        )
        nonformal_pre_alpha = PRE_ALPHA_CEILING
        self.assertEqual(
            compare_states(formal_unknown, nonformal_pre_alpha),
            OrderRelation.INCOMPARABLE,
        )
        self.assertEqual(
            meet_pair(formal_unknown, nonformal_pre_alpha), NOT_FORMAL_CEILING
        )

    def test_no_silent_coercion(self) -> None:
        with self.assertRaises(UnsupportedTruthAdmissionState):
            TruthAdmissionState("FORMAL", AdmissionState.FORMAL_ADMITTED)  # type: ignore[arg-type]
        with self.assertRaises(UnsupportedTruthAdmissionState):
            meet_pair("FORMAL", FORMAL_ADMITTED_CEILING)  # type: ignore[arg-type]
        with self.assertRaises(UnsupportedTruthAdmissionState):
            UpstreamRequirement("snapshot", "FORMAL")  # type: ignore[arg-type]

    def test_proposal_is_not_admitted_canonical_truth(self) -> None:
        proposal = TruthAdmissionClaim(
            state=FORMAL_ADMITTED_CEILING,
            publication=PublicationState.PUBLISHED,
            validation=ValidationState.PASSED,
            kind=CanonicalClaimKind.PROPOSAL,
        )
        admitted = TruthAdmissionClaim(
            state=FORMAL_ADMITTED_CEILING,
            publication=PublicationState.PUBLISHED,
            validation=ValidationState.PASSED,
            kind=CanonicalClaimKind.ADMITTED_CANONICAL_TRUTH,
        )
        self.assertNotEqual(proposal.kind, admitted.kind)

    def test_empty_or_duplicate_upstream_requirements_fail_closed(self) -> None:
        with self.assertRaises(InvalidTruthAdmissionState):
            aggregate_upstream_requirements(())
        with self.assertRaises(InvalidTruthAdmissionState):
            aggregate_upstream_requirements(
                (
                    UpstreamRequirement("snapshot", PRE_ALPHA_CEILING),
                    UpstreamRequirement("snapshot", FORMAL_ADMITTED_CEILING),
                )
            )

    def test_canonical_wire_is_explicitly_separate_from_capability_wire(self) -> None:
        canonical_wire = FORMAL_ADMITTED_CEILING.to_wire()
        self.assertEqual(
            canonical_wire,
            {
                "canonical_truth_state": "FORMAL",
                "canonical_admission_state": "FORMAL_ADMITTED",
            },
        )
        self.assertEqual(
            TruthAdmissionState.from_wire(canonical_wire), FORMAL_ADMITTED_CEILING
        )
        capability_wire = CapabilityTruthV1(CapabilityTruthState.FORMAL).to_wire()
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionState.from_wire(capability_wire)
        with self.assertRaises(InvalidTruthAdmissionState):
            TruthAdmissionState.from_wire(
                {"truth_state": "FORMAL", "admission_state": "FORMAL_ADMITTED"}
            )

    def test_capability_formal_is_not_canonical_truth_or_admission(self) -> None:
        decision = reconcile_capability_truth_ceiling(
            CapabilityTruthState.FORMAL, FORMAL_ADMITTED_CEILING
        )
        self.assertIs(decision.source_vocabulary, LegacyTruthVocabulary.CAPABILITY)
        self.assertIs(decision.source_state, CapabilityTruthState.FORMAL)
        self.assertEqual(decision.canonical_ceiling, NOT_FORMAL_CEILING)
        self.assertIs(
            decision.reason,
            LegacyTruthCompatibilityReason.CAPABILITY_FORMAL_IS_NOT_CANONICAL_TRUTH,
        )
        self.assertNotEqual(decision.canonical_ceiling, FORMAL_ADMITTED_CEILING)
        self.assertIs(decision.canonical_ceiling.truth, TruthState.NOT_FORMAL)
        self.assertIs(decision.canonical_ceiling.admission, AdmissionState.UNKNOWN)

    def test_capability_demo_and_unavailable_fail_closed(self) -> None:
        for source_state, expected_reason in (
            (
                CapabilityTruthState.DEMO,
                LegacyTruthCompatibilityReason.CAPABILITY_DEMO_FAILS_CLOSED,
            ),
            (
                CapabilityTruthState.UNAVAILABLE,
                LegacyTruthCompatibilityReason.CAPABILITY_UNAVAILABLE_FAILS_CLOSED,
            ),
        ):
            decision = reconcile_capability_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            self.assertEqual(decision.canonical_ceiling, UNKNOWN_CEILING)
            self.assertIs(decision.reason, expected_reason)

    def test_operational_nonformal_states_fail_closed(self) -> None:
        for source_state in (
            OperationalTruthState.DEMO,
            OperationalTruthState.UNAVAILABLE,
            OperationalTruthState.DEGRADED,
        ):
            decision = reconcile_operational_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            self.assertEqual(decision.canonical_ceiling, UNKNOWN_CEILING)
            self.assertIs(
                decision.source_vocabulary, LegacyTruthVocabulary.OPERATIONAL
            )

    def test_operational_formal_is_not_canonical_truth_or_admission(self) -> None:
        decision = reconcile_operational_truth_ceiling(
            OperationalTruthState.FORMAL, FORMAL_ADMITTED_CEILING
        )
        self.assertEqual(decision.canonical_ceiling, NOT_FORMAL_CEILING)
        self.assertIs(
            decision.reason,
            LegacyTruthCompatibilityReason.OPERATIONAL_FORMAL_IS_NOT_CANONICAL_TRUTH,
        )

    def test_compatibility_mapping_is_deterministic(self) -> None:
        for source_state in CapabilityTruthState:
            first = reconcile_capability_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            second = reconcile_capability_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            self.assertEqual(first, second)
        for source_state in OperationalTruthState:
            first = reconcile_operational_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            second = reconcile_operational_truth_ceiling(
                source_state, FORMAL_ADMITTED_CEILING
            )
            self.assertEqual(first, second)

    def test_compatibility_mapping_cannot_exceed_canonical_upstream(self) -> None:
        decision = reconcile_capability_truth_ceiling(
            CapabilityTruthState.FORMAL, UNKNOWN_CEILING
        )
        self.assertEqual(decision.canonical_ceiling, UNKNOWN_CEILING)
        self.assertTrue(
            is_at_most(decision.canonical_ceiling, UNKNOWN_CEILING)
        )

    def test_compatibility_boundary_rejects_strings_and_other_enum_types(self) -> None:
        with self.assertRaises(UnsupportedTruthAdmissionState):
            reconcile_capability_truth_ceiling(  # type: ignore[arg-type]
                "FORMAL", FORMAL_ADMITTED_CEILING
            )
        with self.assertRaises(UnsupportedTruthAdmissionState):
            reconcile_capability_truth_ceiling(  # type: ignore[arg-type]
                OperationalTruthState.FORMAL, FORMAL_ADMITTED_CEILING
            )
        with self.assertRaises(UnsupportedTruthAdmissionState):
            reconcile_operational_truth_ceiling(  # type: ignore[arg-type]
                CapabilityTruthState.FORMAL, FORMAL_ADMITTED_CEILING
            )


if __name__ == "__main__":
    unittest.main()
