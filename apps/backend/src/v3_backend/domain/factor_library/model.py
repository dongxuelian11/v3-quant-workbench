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
class EvaluationEvidence:
    evaluation_ref: str
    factor_definition_version_id: str
    dataset_version_ref: str
    evaluation_context_ref: str
    result_refs: tuple[str, ...]
    reviewer_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "evaluation_ref",
            "factor_definition_version_id",
            "dataset_version_ref",
            "evaluation_context_ref",
        ):
            _text(getattr(self, name), name)
        _refs(self.result_refs, "result_refs")
        _refs(self.reviewer_refs, "reviewer_refs")
        _refs(self.provenance_refs, "provenance_refs")


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
    ) -> None:
        self._catalog = FactorAssetCatalogService(snapshot, assets)
        self._definitions = MappingProxyType(
            {value.factor_definition_version_id: value for value in definitions}
        )
        self._documents = MappingProxyType(
            {value.formula_document_version_id: value for value in formula_documents}
        )
        by_definition: dict[str, list[EvaluationEvidence]] = {}
        for evidence in evaluations:
            by_definition.setdefault(evidence.factor_definition_version_id, []).append(evidence)
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
class ConfirmedFactorApplication:
    confirmation_id: str
    preview_id: str
    definition: FactorDefinitionVersion
    import_receipt: FactorImportReceipt
    asset: FactorAssetVersion


class FactorApplicationCommand:
    """Explicit user application boundary. This class is deliberately not an Agent tool."""

    def apply_user_confirmation(
        self,
        *,
        proposal: FactorDraftProposal,
        preview: FactorTranslationPreview,
        confirmed_preview_id: str,
        output_name: str,
        asset_key: str,
        display_name: str,
        data_profile: TdxDataSemanticProfileVersion,
        lifecycle: FactorAssetLifecycle = FactorAssetLifecycle.DRAFT,
    ) -> ConfirmedFactorApplication:
        preview.assert_canonical()
        if preview.proposal_id != proposal.proposal_id or confirmed_preview_id != preview.preview_id:
            raise FactorLibraryError("USER_CONFIRMATION_BINDING_MISMATCH", proposal.proposal_id)
        if preview.status != "READY_FOR_USER_CONFIRMATION" or preview.translation is None:
            raise FactorLibraryError("USER_CONFIRMATION_NOT_APPLICABLE", preview.preview_id)
        translated = preview.translation.output(output_name)
        receipt = FactorImportReceipt.create_from_user_formula(
            translation=preview.translation,
            compatibility_profile=TdxTranslator(
                registry=_registry_from_translation(preview.translation)
            ).compatibility,
            data_profile=data_profile,
            definition=translated.definition,
        )
        asset = FactorAssetVersion.create(
            asset_key=asset_key,
            definition=translated.definition,
            source_family="AI_ASSISTED_TDX" if proposal.natural_language_intent else "TDX_USER_FORMULA",
            output_binding=translated.binding,
            display_name=display_name,
            tags=("ai-draft", "tdx"),
            categories=("user-confirmed",),
            frequency="1d",
            lifecycle=lifecycle,
            import_receipt=receipt,
            formula_document=preview.translation.document,
        )
        confirmation_payload = {
            "preview_id": preview.preview_id,
            "proposal_id": proposal.proposal_id,
            "factor_definition_version_id": translated.definition.factor_definition_version_id,
            "factor_asset_version_id": asset.factor_asset_version_id,
        }
        return ConfirmedFactorApplication(
            "fca_sha256_" + canonical_sha256(confirmation_payload),
            preview.preview_id,
            translated.definition,
            receipt,
            asset,
        )


def _registry_from_translation(translation: TdxTranslationResult):
    from v3_backend.domain.factors import signal_compatible_operator_registry

    registry = signal_compatible_operator_registry()
    if registry.registry_version != translation.outputs[0].definition.operator_registry_version:
        raise FactorLibraryError("FACTOR_DEFINITION_BINDING_MISMATCH", "operator registry")
    return registry


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
