from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from v3_backend.contracts.common.truth_admission import (
    UNKNOWN_CEILING,
    TruthAdmissionState,
    ValidationState,
    meet_all,
)
from v3_backend.provenance.canonical_hash import canonical_sha256


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be non-empty without edge whitespace")


def _require_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase sha256 digest")


class ReviewOutcome(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED"


class ReviewSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class OverallReviewStatus(StrEnum):
    CLEAR_WITHIN_CHECKED_SCOPE = "CLEAR_WITHIN_CHECKED_SCOPE"
    FINDINGS_PRESENT = "FINDINGS_PRESENT"
    INCOMPLETE_REVIEW = "INCOMPLETE_REVIEW"
    BLOCKED = "BLOCKED"


class FindingRelation(StrEnum):
    RESOLVES = "RESOLVES"
    SUPERSEDES = "SUPERSEDES"


@dataclass(frozen=True, slots=True)
class ReviewEvidenceRef:
    session_id: str
    object_kind: str
    object_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.session_id, "session_id")
        _require_text(self.object_kind, "object_kind")
        _require_text(self.object_id, "object_id")
        _require_digest(self.content_sha256, "content_sha256")

    @property
    def exact_key(self) -> tuple[str, str, str, str]:
        return (self.session_id, self.object_kind, self.object_id, self.content_sha256)

    @property
    def id_hash_matches(self) -> bool:
        return self.object_id.endswith(self.content_sha256)

    def to_wire(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "object_kind": self.object_kind,
            "object_id": self.object_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReviewFact:
    name: str
    value: str

    def __post_init__(self) -> None:
        _require_text(self.name, "fact name")
        _require_text(self.value, "fact value")

    def to_wire(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}


@dataclass(frozen=True, slots=True)
class ExactEvidenceBinding:
    relation: str
    target: ReviewEvidenceRef

    def __post_init__(self) -> None:
        _require_text(self.relation, "relation")
        if not isinstance(self.target, ReviewEvidenceRef):
            raise TypeError("binding target must be ReviewEvidenceRef")

    def to_wire(self) -> dict[str, object]:
        return {"relation": self.relation, "target": self.target.to_wire()}


@dataclass(frozen=True, slots=True)
class ReviewEvidenceRecord:
    ref: ReviewEvidenceRef
    validation_state: ValidationState
    truth_admission: TruthAdmissionState
    provenance_refs: tuple[ReviewEvidenceRef, ...]
    bindings: tuple[ExactEvidenceBinding, ...] = ()
    facts: tuple[ReviewFact, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ref, ReviewEvidenceRef):
            raise TypeError("ref must be ReviewEvidenceRef")
        if not isinstance(self.validation_state, ValidationState):
            raise TypeError("validation_state must be canonical ValidationState")
        if not isinstance(self.truth_admission, TruthAdmissionState):
            raise TypeError("truth_admission must be canonical TruthAdmissionState")
        if any(not isinstance(value, ReviewEvidenceRef) for value in self.provenance_refs):
            raise TypeError("provenance_refs must contain ReviewEvidenceRef values")
        if any(not isinstance(value, ExactEvidenceBinding) for value in self.bindings):
            raise TypeError("bindings must contain ExactEvidenceBinding values")
        if any(not isinstance(value, ReviewFact) for value in self.facts):
            raise TypeError("facts must contain ReviewFact values")
        if len({value.exact_key for value in self.provenance_refs}) != len(self.provenance_refs):
            raise ValueError("provenance refs must be exact and unique")
        if len({(value.relation, value.target.exact_key) for value in self.bindings}) != len(self.bindings):
            raise ValueError("exact bindings must be unique")
        if len({value.name for value in self.facts}) != len(self.facts):
            raise ValueError("fact names must be unique per evidence record")

    def fact_map(self) -> dict[str, str]:
        return {value.name: value.value for value in self.facts}

    def bindings_for(self, relation: str) -> tuple[ReviewEvidenceRef, ...]:
        return tuple(value.target for value in self.bindings if value.relation == relation)

    def to_wire(self) -> dict[str, object]:
        return {
            "ref": self.ref.to_wire(),
            "validation_state": self.validation_state.value,
            "truth_admission": self.truth_admission.to_wire(),
            "provenance_refs": [value.to_wire() for value in self.provenance_refs],
            "bindings": [value.to_wire() for value in self.bindings],
            "facts": [value.to_wire() for value in self.facts],
        }


@dataclass(frozen=True, slots=True)
class ResearchReviewScope:
    session_id: str
    target_refs: tuple[ReviewEvidenceRef, ...]
    evidence_records: tuple[ReviewEvidenceRecord, ...]

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        target_refs: tuple[ReviewEvidenceRef, ...],
        evidence_records: tuple[ReviewEvidenceRecord, ...],
    ) -> ResearchReviewScope:
        _require_text(session_id, "session_id")
        if not target_refs:
            raise ValueError("review scope requires at least one exact target")
        ordered_targets = tuple(sorted(target_refs, key=lambda value: value.exact_key))
        ordered_records = tuple(sorted(evidence_records, key=lambda value: value.ref.exact_key))
        if len({value.exact_key for value in ordered_targets}) != len(ordered_targets):
            raise ValueError("review targets must be unique")
        if len({value.ref.exact_key for value in ordered_records}) != len(ordered_records):
            raise ValueError("review evidence records must be unique")
        return cls(session_id, ordered_targets, ordered_records)

    def record_by_exact_ref(self, ref: ReviewEvidenceRef) -> ReviewEvidenceRecord | None:
        return next((value for value in self.evidence_records if value.ref == ref), None)

    def records_of_kind(self, kind: str) -> tuple[ReviewEvidenceRecord, ...]:
        return tuple(value for value in self.evidence_records if value.ref.object_kind == kind)


@dataclass(frozen=True, slots=True)
class ReviewRuleDefinition:
    rule_id: str
    version: str
    category: str
    required: bool
    description: str

    def __post_init__(self) -> None:
        for name in ("rule_id", "version", "category", "description"):
            _require_text(getattr(self, name), name)
        if not isinstance(self.required, bool):
            raise TypeError("required must be bool")

    def to_wire(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "category": self.category,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class ReviewerRuleSet:
    rule_set_id: str
    version: str
    content_sha256: str
    rules: tuple[ReviewRuleDefinition, ...]

    @classmethod
    def create(cls, version: str, rules: tuple[ReviewRuleDefinition, ...]) -> ReviewerRuleSet:
        _require_text(version, "ruleset version")
        ordered = tuple(sorted(rules, key=lambda value: value.rule_id))
        if not ordered or len({value.rule_id for value in ordered}) != len(ordered):
            raise ValueError("ruleset rules must be non-empty with unique rule IDs")
        payload = {"version": version, "rules": [value.to_wire() for value in ordered]}
        digest = canonical_sha256(payload)
        return cls("rrs_sha256_" + digest, version, digest, ordered)


@dataclass(frozen=True, slots=True)
class DeterministicReviewCheck:
    check_id: str
    rule_id: str
    rule_version: str
    required: bool
    outcome: ReviewOutcome
    severity: ReviewSeverity
    title: str
    explanation: str
    remediation_suggestion: str
    evidence_refs: tuple[ReviewEvidenceRef, ...]

    @classmethod
    def create(
        cls,
        *,
        rule: ReviewRuleDefinition,
        outcome: ReviewOutcome,
        severity: ReviewSeverity,
        title: str,
        explanation: str,
        remediation_suggestion: str,
        evidence_refs: tuple[ReviewEvidenceRef, ...] = (),
    ) -> DeterministicReviewCheck:
        if not isinstance(outcome, ReviewOutcome) or not isinstance(severity, ReviewSeverity):
            raise TypeError("review outcome and severity must use closed enums")
        for name, value in (
            ("title", title),
            ("explanation", explanation),
            ("remediation_suggestion", remediation_suggestion),
        ):
            _require_text(value, name)
        ordered_refs = tuple(sorted(evidence_refs, key=lambda value: value.exact_key))
        if len({value.exact_key for value in ordered_refs}) != len(ordered_refs):
            raise ValueError("check evidence refs must be exact and unique")
        if outcome in {ReviewOutcome.FINDING, ReviewOutcome.BLOCKED} and not ordered_refs:
            raise ValueError("finding/blocking checks require factual evidence refs")
        payload = {
            "rule_id": rule.rule_id,
            "rule_version": rule.version,
            "required": rule.required,
            "outcome": outcome.value,
            "severity": severity.value,
            "title": title,
            "explanation": explanation,
            "remediation_suggestion": remediation_suggestion,
            "evidence_refs": [value.to_wire() for value in ordered_refs],
        }
        return cls(
            check_id="rrc_sha256_" + canonical_sha256(payload),
            rule_id=rule.rule_id,
            rule_version=rule.version,
            required=rule.required,
            outcome=outcome,
            severity=severity,
            title=title,
            explanation=explanation,
            remediation_suggestion=remediation_suggestion,
            evidence_refs=ordered_refs,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "required": self.required,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "title": self.title,
            "explanation": self.explanation,
            "remediation_suggestion": self.remediation_suggestion,
            "evidence_refs": [value.to_wire() for value in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class ReviewerFinding:
    finding_id: str
    review_report_id: str
    check_id: str
    rule_id: str
    rule_version: str
    severity: ReviewSeverity
    outcome: ReviewOutcome
    title: str
    factual_evidence_refs: tuple[ReviewEvidenceRef, ...]
    explanation: str
    remediation_suggestion: str

    @classmethod
    def create(cls, review_report_id: str, check: DeterministicReviewCheck) -> ReviewerFinding:
        _require_text(review_report_id, "review_report_id")
        if check.outcome not in {ReviewOutcome.FINDING, ReviewOutcome.BLOCKED}:
            raise ValueError("only FINDING/BLOCKED deterministic checks create findings")
        payload = {
            "review_report_id": review_report_id,
            "check_id": check.check_id,
            "rule_id": check.rule_id,
            "rule_version": check.rule_version,
            "severity": check.severity.value,
            "outcome": check.outcome.value,
            "title": check.title,
            "factual_evidence_refs": [value.to_wire() for value in check.evidence_refs],
            "explanation": check.explanation,
            "remediation_suggestion": check.remediation_suggestion,
        }
        return cls(
            finding_id="rvf_sha256_" + canonical_sha256(payload),
            review_report_id=review_report_id,
            check_id=check.check_id,
            rule_id=check.rule_id,
            rule_version=check.rule_version,
            severity=check.severity,
            outcome=check.outcome,
            title=check.title,
            factual_evidence_refs=check.evidence_refs,
            explanation=check.explanation,
            remediation_suggestion=check.remediation_suggestion,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "review_report_id": self.review_report_id,
            "check_id": self.check_id,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "severity": self.severity.value,
            "outcome": self.outcome.value,
            "title": self.title,
            "factual_evidence_refs": [value.to_wire() for value in self.factual_evidence_refs],
            "explanation": self.explanation,
            "remediation_suggestion": self.remediation_suggestion,
        }


@dataclass(frozen=True, slots=True)
class ReviewCoverage:
    checked_rules: int
    PASS: int
    FINDING: int
    NOT_RUN: int
    NOT_APPLICABLE: int
    BLOCKED: int

    @classmethod
    def from_checks(cls, checks: tuple[DeterministicReviewCheck, ...]) -> ReviewCoverage:
        counts = {value: 0 for value in ReviewOutcome}
        for check in checks:
            counts[check.outcome] += 1
        return cls(
            checked_rules=len(checks),
            PASS=counts[ReviewOutcome.PASS],
            FINDING=counts[ReviewOutcome.FINDING],
            NOT_RUN=counts[ReviewOutcome.NOT_RUN],
            NOT_APPLICABLE=counts[ReviewOutcome.NOT_APPLICABLE],
            BLOCKED=counts[ReviewOutcome.BLOCKED],
        )

    def to_wire(self) -> dict[str, int]:
        return {
            "checked_rules": self.checked_rules,
            "PASS": self.PASS,
            "FINDING": self.FINDING,
            "NOT_RUN": self.NOT_RUN,
            "NOT_APPLICABLE": self.NOT_APPLICABLE,
            "BLOCKED": self.BLOCKED,
        }


@dataclass(frozen=True, slots=True)
class ResearchReviewReport:
    review_report_id: str
    session_id: str
    target_refs: tuple[ReviewEvidenceRef, ...]
    rule_set_id: str
    rule_set_content_sha256: str
    deterministic_checks: tuple[DeterministicReviewCheck, ...]
    source_evidence_refs: tuple[ReviewEvidenceRef, ...]
    findings: tuple[ReviewerFinding, ...]
    coverage: ReviewCoverage
    overall_status: OverallReviewStatus
    truth_ceiling: TruthAdmissionState

    @classmethod
    def create(
        cls,
        *,
        scope: ResearchReviewScope,
        rule_set: ReviewerRuleSet,
        checks: tuple[DeterministicReviewCheck, ...],
    ) -> ResearchReviewReport:
        ordered_checks = tuple(sorted(checks, key=lambda value: value.rule_id))
        if tuple(value.rule_id for value in ordered_checks) != tuple(value.rule_id for value in rule_set.rules):
            raise ValueError("report checks must exactly cover the versioned ruleset")
        source_refs = tuple(value.ref for value in scope.evidence_records)
        truth_ceiling = (
            meet_all(value.truth_admission for value in scope.evidence_records)
            if scope.evidence_records
            else UNKNOWN_CEILING
        )
        basis = {
            "session_id": scope.session_id,
            "target_refs": [value.to_wire() for value in scope.target_refs],
            "rule_set_id": rule_set.rule_set_id,
            "rule_set_content_sha256": rule_set.content_sha256,
            "deterministic_checks": [value.to_wire() for value in ordered_checks],
            "source_evidence_refs": [value.to_wire() for value in source_refs],
            "truth_ceiling": truth_ceiling.to_wire(),
        }
        report_id = "rrp_sha256_" + canonical_sha256(basis)
        findings = tuple(
            ReviewerFinding.create(report_id, value)
            for value in ordered_checks
            if value.outcome in {ReviewOutcome.FINDING, ReviewOutcome.BLOCKED}
        )
        coverage = ReviewCoverage.from_checks(ordered_checks)
        if coverage.BLOCKED:
            overall = OverallReviewStatus.BLOCKED
        elif coverage.FINDING:
            overall = OverallReviewStatus.FINDINGS_PRESENT
        elif any(value.required and value.outcome is ReviewOutcome.NOT_RUN for value in ordered_checks):
            overall = OverallReviewStatus.INCOMPLETE_REVIEW
        else:
            overall = OverallReviewStatus.CLEAR_WITHIN_CHECKED_SCOPE
        return cls(
            report_id,
            scope.session_id,
            scope.target_refs,
            rule_set.rule_set_id,
            rule_set.content_sha256,
            ordered_checks,
            source_refs,
            findings,
            coverage,
            overall,
            truth_ceiling,
        )

    def to_wire(self) -> dict[str, object]:
        return {
            "review_report_id": self.review_report_id,
            "session_id": self.session_id,
            "target_refs": [value.to_wire() for value in self.target_refs],
            "rule_set_id": self.rule_set_id,
            "rule_set_content_sha256": self.rule_set_content_sha256,
            "deterministic_checks": [value.to_wire() for value in self.deterministic_checks],
            "source_evidence_refs": [value.to_wire() for value in self.source_evidence_refs],
            "findings": [value.to_wire() for value in self.findings],
            "coverage": self.coverage.to_wire(),
            "overall_status": self.overall_status.value,
            "truth_ceiling": self.truth_ceiling.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class FindingLifecycleLink:
    lifecycle_link_id: str
    relation: FindingRelation
    current_review_report_id: str
    current_finding_id: str | None
    prior_review_report_id: str
    prior_finding_id: str

    @classmethod
    def create(
        cls,
        *,
        relation: FindingRelation,
        current_report: ResearchReviewReport,
        current_finding: ReviewerFinding | None,
        prior_report: ResearchReviewReport,
        prior_finding: ReviewerFinding,
    ) -> FindingLifecycleLink:
        if not isinstance(relation, FindingRelation):
            raise TypeError("finding lifecycle relation must use the closed enum")
        if current_finding is not None and current_finding.review_report_id != current_report.review_report_id:
            raise ValueError("current finding must bind the exact current report")
        if prior_finding.review_report_id != prior_report.review_report_id:
            raise ValueError("prior finding must bind the exact prior report")
        if current_report.review_report_id == prior_report.review_report_id:
            raise ValueError("re-review lifecycle must link distinct immutable reports")
        payload = {
            "relation": relation.value,
            "current_review_report_id": current_report.review_report_id,
            "current_finding_id": current_finding.finding_id if current_finding else None,
            "prior_review_report_id": prior_report.review_report_id,
            "prior_finding_id": prior_finding.finding_id,
        }
        return cls("rfl_sha256_" + canonical_sha256(payload), relation, **{key: value for key, value in payload.items() if key != "relation"})


@dataclass(frozen=True, slots=True)
class ReviewerAgentDraft:
    draft_id: str
    review_report_id: str
    permission: str
    authority_status: str
    summary: str
    prioritized_risks: tuple[str, ...]
    research_suggestions: tuple[str, ...]
    cited_evidence_refs: tuple[ReviewEvidenceRef, ...]

    @classmethod
    def create(
        cls,
        *,
        report: ResearchReviewReport,
        summary: str,
        prioritized_risks: tuple[str, ...],
        research_suggestions: tuple[str, ...],
        cited_evidence_refs: tuple[ReviewEvidenceRef, ...],
    ) -> ReviewerAgentDraft:
        _require_text(summary, "summary")
        for value in (*prioritized_risks, *research_suggestions):
            _require_text(value, "agent draft item")
        ordered_refs = tuple(sorted(cited_evidence_refs, key=lambda value: value.exact_key))
        allowed = {value.exact_key for value in report.source_evidence_refs}
        if not ordered_refs or any(value.exact_key not in allowed for value in ordered_refs):
            raise ValueError("Reviewer Agent citations must be exact report evidence")
        payload = {
            "review_report_id": report.review_report_id,
            "permission": "L1_DRAFT",
            "authority_status": "NON_CANONICAL",
            "summary": summary,
            "prioritized_risks": list(prioritized_risks),
            "research_suggestions": list(research_suggestions),
            "cited_evidence_refs": [value.to_wire() for value in ordered_refs],
        }
        return cls("rad_sha256_" + canonical_sha256(payload), report.review_report_id, "L1_DRAFT", "NON_CANONICAL", summary, prioritized_risks, research_suggestions, ordered_refs)


__all__ = [
    "DeterministicReviewCheck",
    "ExactEvidenceBinding",
    "FindingLifecycleLink",
    "FindingRelation",
    "OverallReviewStatus",
    "ResearchReviewReport",
    "ResearchReviewScope",
    "ReviewCoverage",
    "ReviewEvidenceRecord",
    "ReviewEvidenceRef",
    "ReviewerAgentDraft",
    "ReviewerFinding",
    "ReviewerRuleSet",
    "ReviewFact",
    "ReviewOutcome",
    "ReviewRuleDefinition",
    "ReviewSeverity",
]
