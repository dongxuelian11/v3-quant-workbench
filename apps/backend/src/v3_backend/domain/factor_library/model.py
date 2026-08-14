from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from v3_backend.adapters.tdx_formula import (
    TdxDataSemanticProfileVersion,
    TdxFormulaError,
    TdxTranslationResult,
    TdxTranslator,
)
from v3_backend.domain.factor_assets import (
    CatalogQuery,
    FactorAssetCatalogService,
    FactorAssetLifecycle,
    FactorAssetVersion,
    FactorCatalogSnapshotVersion,
    FactorDraftProposal,
    FactorImportReceipt,
    FactorPackItemStatus,
    FactorPackManifestVersion,
    FormulaDocumentVersion,
)
from v3_backend.domain.factors import FactorDefinitionVersion
from v3_backend.provenance.canonical_hash import canonical_sha256

from .evidence import (
    CanonicalEvaluationEvidenceResolver,
    EvaluationEvidence,
    ResolvedEvaluationEvidence,
)


class FactorLibraryError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _text(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise FactorLibraryError("INVALID_FACTOR_LIBRARY_CONTRACT", f"{name} is required")
    return value


def _refs(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if any(not value or value != value.strip() for value in values):
        raise FactorLibraryError("INVALID_FACTOR_LIBRARY_CONTRACT", f"{name} contains an invalid ref")
    if len(values) != len(set(values)):
        raise FactorLibraryError("INVALID_FACTOR_LIBRARY_CONTRACT", f"{name} must be unique")
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class FactorDetail:
    factor_asset_version_id: str
    asset_key: str
    factor_definition_version_id: str
    factor_definition_hash: str
    source_family: str
    pack_manifest_version_id: str | None
    source_formula: str | None
    source_language: str | None
    canonical_ir: Mapping[str, object]
    operators: tuple[str, ...]
    data_dependencies: tuple[str, ...]
    warmup_lookback: int
    output_type: str
    frequency: str
    lifecycle: str
    compatibility: str
    evaluation_refs: tuple[str, ...]
    reviewer_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    evaluation_status: str
    exact_evaluation_contexts: tuple[Mapping[str, object], ...]
    contextual_metrics: tuple[Mapping[str, float], ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "factor_asset_version_id": self.factor_asset_version_id,
            "asset_key": self.asset_key,
            "factor_definition_version_id": self.factor_definition_version_id,
            "factor_definition_hash": self.factor_definition_hash,
            "source_family": self.source_family,
            "pack_manifest_version_id": self.pack_manifest_version_id,
            "source_formula": self.source_formula,
            "source_language": self.source_language,
            "canonical_ir": dict(self.canonical_ir),
            "operators": list(self.operators),
            "data_dependencies": list(self.data_dependencies),
            "warmup_lookback": self.warmup_lookback,
            "output_type": self.output_type,
            "frequency": self.frequency,
            "lifecycle": self.lifecycle,
            "compatibility": self.compatibility,
            "evaluation_refs": list(self.evaluation_refs),
            "reviewer_refs": list(self.reviewer_refs),
            "provenance_refs": list(self.provenance_refs),
            "evaluation_status": self.evaluation_status,
            "exact_evaluation_contexts": [dict(value) for value in self.exact_evaluation_contexts],
            "contextual_metrics": [dict(value) for value in self.contextual_metrics],
        }


@dataclass(frozen=True, slots=True)
class FactorEvidenceExplanation:
    asset_key: str
    factor_definition_version_id: str
    evaluation_status: str
    exact_evaluation_refs: tuple[str, ...]
    exact_result_refs: tuple[str, ...]
    exact_reviewer_refs: tuple[str, ...]
    exact_provenance_refs: tuple[str, ...]
    exact_evaluation_contexts: tuple[Mapping[str, object], ...]
    contextual_metrics: tuple[Mapping[str, float], ...]
    statement: str


class FactorLibraryService:
    """Read-only business projection; assets never execute factor math."""

    def __init__(
        self,
        *,
        snapshot: FactorCatalogSnapshotVersion,
        assets: tuple[FactorAssetVersion, ...],
        definitions: tuple[FactorDefinitionVersion, ...],
        formula_documents: tuple[FormulaDocumentVersion, ...] = (),
        evaluations: tuple[EvaluationEvidence, ...] = (),
        evidence_resolver: CanonicalEvaluationEvidenceResolver | None = None,
    ) -> None:
        self._catalog = FactorAssetCatalogService(snapshot, assets)
        self._definitions = MappingProxyType(
            {value.factor_definition_version_id: value for value in definitions}
        )
        self._documents = MappingProxyType(
            {value.formula_document_version_id: value for value in formula_documents}
        )
        if evaluations and evidence_resolver is None:
            raise FactorLibraryError(
                "EVIDENCE_BINDING_UNAVAILABLE",
                "public EvaluationEvidence requires canonical owner resolution",
            )
        by_definition: dict[str, list[ResolvedEvaluationEvidence]] = {}
        for evidence in evaluations:
            assert evidence_resolver is not None
            resolved = evidence_resolver.resolve(evidence)
            by_definition.setdefault(resolved.factor_definition_version_id, []).append(resolved)
        self._evaluations = MappingProxyType(
            {key: tuple(sorted(values, key=lambda item: item.evaluation_ref)) for key, values in by_definition.items()}
        )
        unknown_evidence = tuple(sorted(set(self._evaluations) - set(self._definitions)))
        if unknown_evidence:
            raise FactorLibraryError("EVALUATION_DEFINITION_BINDING_MISMATCH", unknown_evidence[0])
        for asset in assets:
            definition = self._definitions.get(asset.factor_definition_version_id)
            if definition is None or definition.factor_definition_version_id != asset.factor_definition_hash:
                raise FactorLibraryError("FACTOR_DEFINITION_BINDING_MISMATCH", asset.asset_key)
            if asset.formula_document_version_id is not None and asset.formula_document_version_id not in self._documents:
                raise FactorLibraryError("FORMULA_DOCUMENT_BINDING_MISMATCH", asset.asset_key)

    def search(self, query: CatalogQuery) -> tuple[FactorDetail, ...]:
        return tuple(self._detail(asset) for asset in self._catalog.query(query).assets)

    def read(self, asset_key: str) -> FactorDetail:
        results = self.search(CatalogQuery(asset_key=asset_key))
        if len(results) != 1:
            raise FactorLibraryError("FACTOR_ASSET_NOT_FOUND", asset_key)
        return results[0]

    def explain_evidence(self, asset_key: str) -> FactorEvidenceExplanation:
        detail = self.read(asset_key)
        evidence = self._evaluations.get(detail.factor_definition_version_id, ())
        if not evidence:
            return FactorEvidenceExplanation(
                detail.asset_key,
                detail.factor_definition_version_id,
                "NOT_EVALUATED",
                (),
                (),
                (),
                detail.provenance_refs,
                (),
                (),
                "No exact Evaluation context is bound; performance is NOT_EVALUATED.",
            )
        return FactorEvidenceExplanation(
            detail.asset_key,
            detail.factor_definition_version_id,
            "EVALUATED_IN_EXACT_CONTEXTS",
            tuple(item.evaluation_ref for item in evidence),
            tuple(sorted({ref for item in evidence for ref in item.result_refs})),
            tuple(sorted({ref for item in evidence for ref in item.reviewer_refs})),
            tuple(sorted({ref for item in evidence for ref in item.provenance_refs})),
            tuple(item.exact_context for item in evidence),
            tuple(item.metrics for item in evidence),
            "Evidence is contextual and limited to the exact bound Evaluation references.",
        )

    def _detail(self, asset: FactorAssetVersion) -> FactorDetail:
        definition = self._definitions[asset.factor_definition_version_id]
        document = self._documents.get(asset.formula_document_version_id or "")
        evidence = self._evaluations.get(definition.factor_definition_version_id, ())
        provenance = () if document is None else (document.provenance_ref,)
        return FactorDetail(
            asset.factor_asset_version_id,
            asset.asset_key,
            definition.factor_definition_version_id,
            asset.factor_definition_hash,
            asset.source_family,
            asset.pack_manifest_version_id,
            None if document is None else document.source_text,
            None if document is None else document.language,
            MappingProxyType(definition.to_wire()),
            asset.operator_dependencies,
            asset.required_data_fields,
            asset.max_lookback,
            asset.output_type.value,
            asset.frequency,
            asset.lifecycle.value,
            asset.compatibility_status.value,
            tuple(item.evaluation_ref for item in evidence),
            tuple(sorted({ref for item in evidence for ref in item.reviewer_refs})),
            tuple(sorted({*provenance, *(ref for item in evidence for ref in item.provenance_refs)})),
            "NOT_EVALUATED" if not evidence else "EVALUATED_IN_EXACT_CONTEXTS",
            tuple(item.exact_context for item in evidence),
            tuple(item.metrics for item in evidence),
        )


@dataclass(frozen=True, slots=True)
class FactorTranslationPreview:
    preview_id: str
    proposal_id: str
    status: str
    translation: TdxTranslationResult | None
    diagnostics: tuple[str, ...]
    confirmation_required: bool

    def assert_canonical(self) -> None:
        if self.status == "READY_FOR_USER_CONFIRMATION":
            if self.translation is None or self.diagnostics or not self.confirmation_required:
                raise FactorLibraryError("INVALID_TRANSLATION_PREVIEW", self.preview_id)
            payload = {
                "proposal_id": self.proposal_id,
                "formula_document_version_id": self.translation.document.formula_document_version_id,
                "definition_refs": [
                    value.definition.factor_definition_version_id
                    for value in self.translation.outputs
                ],
                "data_semantic_profile_id": self.translation.static_analysis.data_semantic_profile_id,
                "status": "READY_FOR_USER_CONFIRMATION",
            }
        elif self.status == "NOT_ADMITTED":
            if self.translation is not None or not self.diagnostics or self.confirmation_required:
                raise FactorLibraryError("INVALID_TRANSLATION_PREVIEW", self.preview_id)
            payload = {
                "proposal_id": self.proposal_id,
                "status": "NOT_ADMITTED",
                "diagnostics": list(self.diagnostics),
            }
        else:
            raise FactorLibraryError("INVALID_TRANSLATION_PREVIEW", self.status)
        if self.preview_id != "ftp_sha256_" + canonical_sha256(payload):
            raise FactorLibraryError("INVALID_TRANSLATION_PREVIEW", "content-addressed ID mismatch")

    @classmethod
    def from_proposal(
        cls,
        proposal: FactorDraftProposal,
        *,
        translator: TdxTranslator,
        data_profile: TdxDataSemanticProfileVersion,
        provenance_ref: str,
    ) -> FactorTranslationPreview:
        if proposal.authority_status != "NON_CANONICAL" or proposal.lifecycle_state != "DRAFT":
            raise FactorLibraryError("AGENT_DRAFT_AUTHORITY_VIOLATION", proposal.proposal_id)
        if proposal.draft_kind != "TDX":
            return cls._failed(proposal, "UNSUPPORTED_DRAFT_KIND")
        try:
            translation = translator.translate(
                proposal.draft_payload,
                data_profile=data_profile,
                provenance_ref=provenance_ref,
            )
        except TdxFormulaError as exc:
            code = getattr(exc, "code", exc.__class__.__name__)
            return cls._failed(proposal, str(code))
        payload = {
            "proposal_id": proposal.proposal_id,
            "formula_document_version_id": translation.document.formula_document_version_id,
            "definition_refs": [value.definition.factor_definition_version_id for value in translation.outputs],
            "data_semantic_profile_id": translation.static_analysis.data_semantic_profile_id,
            "status": "READY_FOR_USER_CONFIRMATION",
        }
        return cls(
            "ftp_sha256_" + canonical_sha256(payload),
            proposal.proposal_id,
            "READY_FOR_USER_CONFIRMATION",
            translation,
            (),
            True,
        )

    @classmethod
    def _failed(cls, proposal: FactorDraftProposal, diagnostic: str) -> FactorTranslationPreview:
        payload = {
            "proposal_id": proposal.proposal_id,
            "status": "NOT_ADMITTED",
            "diagnostics": [diagnostic],
        }
        return cls(
            "ftp_sha256_" + canonical_sha256(payload),
            proposal.proposal_id,
            "NOT_ADMITTED",
            None,
            (diagnostic,),
            False,
        )


@dataclass(frozen=True, slots=True)
class FactorApplicationSpec:
    """Immutable full intent for a future canonical application authority."""

    application_spec_id: str
    content_hash: str
    proposal_id: str
    preview_id: str
    source_formula_sha256: str
    source_language: str
    formula_document_version_id: str
    source_provenance_ref: str
    selected_output_name: str
    factor_definition_version_id: str
    factor_definition_wire_sha256: str
    output_binding_id: str
    asset_key: str
    display_name: str
    data_semantic_profile_id: str
    lifecycle: FactorAssetLifecycle
    source_family: str
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    frequency: str
    compatibility_status: FactorPackItemStatus
    import_admission_options: tuple[str, ...]
    external_source_refs: tuple[str, ...]

    def _payload(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "preview_id": self.preview_id,
            "source_formula_sha256": self.source_formula_sha256,
            "source_language": self.source_language,
            "formula_document_version_id": self.formula_document_version_id,
            "source_provenance_ref": self.source_provenance_ref,
            "selected_output_name": self.selected_output_name,
            "factor_definition_version_id": self.factor_definition_version_id,
            "factor_definition_wire_sha256": self.factor_definition_wire_sha256,
            "output_binding_id": self.output_binding_id,
            "asset_key": self.asset_key,
            "display_name": self.display_name,
            "data_semantic_profile_id": self.data_semantic_profile_id,
            "lifecycle": self.lifecycle.value,
            "source_family": self.source_family,
            "tags": list(self.tags),
            "categories": list(self.categories),
            "frequency": self.frequency,
            "compatibility_status": self.compatibility_status.value,
            "import_admission_options": list(self.import_admission_options),
            "external_source_refs": list(self.external_source_refs),
        }

    def assert_canonical(self) -> None:
        if self.lifecycle is not FactorAssetLifecycle.DRAFT:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", "initial lifecycle must be DRAFT")
        for name in (
            "proposal_id",
            "preview_id",
            "source_formula_sha256",
            "source_language",
            "formula_document_version_id",
            "source_provenance_ref",
            "selected_output_name",
            "factor_definition_version_id",
            "factor_definition_wire_sha256",
            "output_binding_id",
            "asset_key",
            "display_name",
            "data_semantic_profile_id",
            "source_family",
            "frequency",
        ):
            _text(getattr(self, name), name)
        _refs(self.tags, "tags")
        _refs(self.categories, "categories")
        _refs(self.import_admission_options, "import_admission_options")
        _refs(self.external_source_refs, "external_source_refs")
        digest = canonical_sha256(self._payload())
        if self.content_hash != digest or self.application_spec_id != "fas_sha256_" + digest:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", "content-addressed spec mismatch")

    def assert_binding(
        self,
        *,
        proposal: FactorDraftProposal,
        preview: FactorTranslationPreview,
        data_profile: TdxDataSemanticProfileVersion,
    ) -> None:
        self.assert_canonical()
        preview.assert_canonical()
        data_profile.assert_canonical()
        if preview.translation is None:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", "translation is unavailable")
        translated = preview.translation.output(self.selected_output_name)
        observed = (
            proposal.proposal_id,
            preview.proposal_id,
            preview.preview_id,
            preview.translation.document.source_sha256,
            preview.translation.document.language,
            preview.translation.document.formula_document_version_id,
            preview.translation.document.provenance_ref,
            translated.definition.factor_definition_version_id,
            canonical_sha256(translated.definition.to_wire()),
            translated.binding.binding_id,
            preview.translation.static_analysis.data_semantic_profile_id,
            data_profile.data_semantic_profile_id,
        )
        expected = (
            self.proposal_id,
            self.proposal_id,
            self.preview_id,
            self.source_formula_sha256,
            self.source_language,
            self.formula_document_version_id,
            self.source_provenance_ref,
            self.factor_definition_version_id,
            self.factor_definition_wire_sha256,
            self.output_binding_id,
            self.data_semantic_profile_id,
            self.data_semantic_profile_id,
        )
        if observed != expected:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", self.application_spec_id)

    @classmethod
    def create(
        cls,
        *,
        proposal: FactorDraftProposal,
        preview: FactorTranslationPreview,
        selected_output_name: str,
        asset_key: str,
        display_name: str,
        data_profile: TdxDataSemanticProfileVersion,
        lifecycle: FactorAssetLifecycle = FactorAssetLifecycle.DRAFT,
        tags: tuple[str, ...] = ("ai-draft", "tdx"),
        categories: tuple[str, ...] = ("user-application-request",),
        frequency: str = "1d",
        compatibility_status: FactorPackItemStatus = FactorPackItemStatus.SUPPORTED,
        import_admission_options: tuple[str, ...] = ("EXACT_USER_FORMULA", "NO_WARNINGS"),
        external_source_refs: tuple[str, ...] = (),
    ) -> FactorApplicationSpec:
        preview.assert_canonical()
        data_profile.assert_canonical()
        if preview.proposal_id != proposal.proposal_id or preview.translation is None:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", proposal.proposal_id)
        if lifecycle is not FactorAssetLifecycle.DRAFT:
            raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", "initial lifecycle must be DRAFT")
        translated = preview.translation.output(selected_output_name)
        document = preview.translation.document
        source_family = "AI_ASSISTED_TDX" if proposal.natural_language_intent else "TDX_USER_FORMULA"
        values = {
            "proposal_id": proposal.proposal_id,
            "preview_id": preview.preview_id,
            "source_formula_sha256": document.source_sha256,
            "source_language": document.language,
            "formula_document_version_id": document.formula_document_version_id,
            "source_provenance_ref": document.provenance_ref,
            "selected_output_name": _text(selected_output_name, "selected_output_name"),
            "factor_definition_version_id": translated.definition.factor_definition_version_id,
            "factor_definition_wire_sha256": canonical_sha256(translated.definition.to_wire()),
            "output_binding_id": translated.binding.binding_id,
            "asset_key": _text(asset_key, "asset_key"),
            "display_name": _text(display_name, "display_name"),
            "data_semantic_profile_id": data_profile.data_semantic_profile_id,
            "lifecycle": lifecycle,
            "source_family": source_family,
            "tags": _refs(tags, "tags"),
            "categories": _refs(categories, "categories"),
            "frequency": _text(frequency, "frequency"),
            "compatibility_status": compatibility_status,
            "import_admission_options": _refs(import_admission_options, "import_admission_options"),
            "external_source_refs": _refs(external_source_refs, "external_source_refs"),
        }
        provisional = cls("", "", **values)
        digest = canonical_sha256(provisional._payload())
        result = cls("fas_sha256_" + digest, digest, **values)
        result.assert_binding(proposal=proposal, preview=preview, data_profile=data_profile)
        return result


class FactorApplicationCommand:
    """Retained seam that fails closed until a shared canonical authority exists."""

    def apply_user_confirmation(
        self,
        *,
        proposal: FactorDraftProposal,
        preview: FactorTranslationPreview,
        application_spec: FactorApplicationSpec | None = None,
        confirmed_application_spec_id: str | None = None,
        confirmed_preview_id: str | None = None,
        output_name: str | None = None,
        asset_key: str | None = None,
        display_name: str | None = None,
        data_profile: TdxDataSemanticProfileVersion | None = None,
        lifecycle: FactorAssetLifecycle = FactorAssetLifecycle.DRAFT,
        actor: str | None = None,
        confirmed_at: str | None = None,
    ) -> None:
        preview.assert_canonical()
        if preview.proposal_id != proposal.proposal_id:
            raise FactorLibraryError("USER_CONFIRMATION_BINDING_MISMATCH", proposal.proposal_id)
        if application_spec is not None:
            if data_profile is None:
                raise FactorLibraryError("APPLICATION_SPEC_BINDING_MISMATCH", "data profile is required")
            application_spec.assert_binding(
                proposal=proposal,
                preview=preview,
                data_profile=data_profile,
            )
            if confirmed_application_spec_id != application_spec.application_spec_id:
                raise FactorLibraryError("USER_CONFIRMATION_BINDING_MISMATCH", application_spec.application_spec_id)
        elif confirmed_preview_id != preview.preview_id:
            raise FactorLibraryError("USER_CONFIRMATION_BINDING_MISMATCH", preview.preview_id)
        for value, name in ((actor, "actor"), (confirmed_at, "confirmed_at")):
            if value is not None:
                _text(value, name)
        _ = (output_name, asset_key, display_name, lifecycle)
        raise FactorLibraryError(
            "USER_EXECUTION_AUTHORITY_NOT_AVAILABLE",
            "caller confirmation is not canonical application authority; production application is NOT_AVAILABLE / NOT_RUN",
        )


@dataclass(frozen=True, slots=True)
class PackCoverage:
    pack_name: str
    exact_source_revision: str
    total_known_items: int
    supported: int
    partially_supported: int
    unsupported_operator: int
    unsupported_data: int
    pit_unresolved: int
    license_blocked: int
    reference_only: int
    actually_imported_canonical_definitions: int
    manifest_version_id: str | None
    coverage_basis: str

    def __post_init__(self) -> None:
        counts = (
            self.supported,
            self.partially_supported,
            self.unsupported_operator,
            self.unsupported_data,
            self.pit_unresolved,
            self.license_blocked,
            self.reference_only,
        )
        if self.total_known_items < 1 or any(value < 0 for value in counts):
            raise FactorLibraryError("INVALID_PACK_COVERAGE", self.pack_name)
        if sum(counts) != self.total_known_items:
            raise FactorLibraryError("INVALID_PACK_COVERAGE", "status counts must equal total")
        if self.actually_imported_canonical_definitions > self.supported:
            raise FactorLibraryError("INVALID_PACK_COVERAGE", "imports exceed supported items")


class PackCoverageService:
    @staticmethod
    def from_manifest(
        manifest: FactorPackManifestVersion,
        *,
        import_receipts: tuple[FactorImportReceipt, ...] = (),
        coverage_basis: str = "EXACT_MANIFEST_MEMBERSHIP",
    ) -> PackCoverage:
        manifest.assert_canonical()
        counts = {status: 0 for status in FactorPackItemStatus}
        for item in manifest.items:
            counts[item.compatibility_status] += 1
        imported_definition_ids: list[str] = []
        manifest_digests = {item.source_item_digest for item in manifest.items if item.compatibility_status is FactorPackItemStatus.SUPPORTED}
        for receipt in import_receipts:
            if (
                receipt.status.value != "ADMITTED"
                or receipt.pack_manifest_version_id != manifest.factor_pack_manifest_version_id
                or receipt.source_item_digest not in manifest_digests
                or receipt.resulting_factor_definition_version_id is None
            ):
                raise FactorLibraryError("INVALID_PACK_IMPORT_EVIDENCE", receipt.factor_import_receipt_id)
            imported_definition_ids.append(receipt.resulting_factor_definition_version_id)
        if len(imported_definition_ids) != len(set(imported_definition_ids)):
            raise FactorLibraryError("INVALID_PACK_COVERAGE", "duplicate canonical imports")
        return PackCoverage(
            manifest.pack_name,
            manifest.exact_source_revision,
            len(manifest.items),
            counts[FactorPackItemStatus.SUPPORTED],
            counts[FactorPackItemStatus.PARTIALLY_SUPPORTED],
            counts[FactorPackItemStatus.UNSUPPORTED_OPERATOR],
            counts[FactorPackItemStatus.UNSUPPORTED_DATA],
            counts[FactorPackItemStatus.PIT_UNRESOLVED],
            counts[FactorPackItemStatus.LICENSE_BLOCKED],
            counts[FactorPackItemStatus.REFERENCE_ONLY],
            len(imported_definition_ids),
            manifest.factor_pack_manifest_version_id,
            coverage_basis,
        )
