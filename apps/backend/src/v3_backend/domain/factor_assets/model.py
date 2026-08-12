from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from v3_backend.domain.factors import FactorDefinitionVersion, ValueType
from v3_backend.provenance.canonical_hash import canonical_sha256


class FactorAssetError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _text(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise FactorAssetError("INVALID_FACTOR_ASSET_CONTRACT", f"{name} is required")
    return value


def _unique(values: tuple[str, ...], name: str, *, sort: bool = True) -> tuple[str, ...]:
    if any(not value or value != value.strip() for value in values):
        raise FactorAssetError("INVALID_FACTOR_ASSET_CONTRACT", f"{name} contains invalid text")
    if len(values) != len(set(values)):
        raise FactorAssetError("INVALID_FACTOR_ASSET_CONTRACT", f"{name} must be unique")
    return tuple(sorted(values)) if sort else values


class FormulaParseStatus(StrEnum):
    PARSED = "PARSED"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass(frozen=True, slots=True)
class FormulaDocumentVersion:
    formula_document_version_id: str
    language: str
    source_text: str
    source_sha256: str
    compatibility_profile_id: str
    parse_status: FormulaParseStatus
    ast_digest: str | None
    named_outputs: tuple[str, ...]
    provenance_ref: str

    @classmethod
    def create(
        cls,
        *,
        language: str,
        source_text: str,
        compatibility_profile_id: str,
        parse_status: FormulaParseStatus,
        ast_digest: str | None,
        named_outputs: tuple[str, ...],
        provenance_ref: str,
    ) -> FormulaDocumentVersion:
        if language != "TDX":
            raise FactorAssetError("UNSUPPORTED_FORMULA_LANGUAGE", language)
        if not source_text or not source_text.strip():
            raise FactorAssetError("INVALID_FACTOR_ASSET_CONTRACT", "source_text is required")
        _text(compatibility_profile_id, "compatibility_profile_id")
        _text(provenance_ref, "provenance_ref")
        outputs = _unique(named_outputs, "named_outputs", sort=False)
        if parse_status is FormulaParseStatus.PARSED:
            if ast_digest is None or not outputs:
                raise FactorAssetError("TDX_PARSE_ERROR", "parsed document requires AST and outputs")
        elif ast_digest is not None or outputs:
            raise FactorAssetError("TDX_PARSE_ERROR", "failed parse cannot claim AST or outputs")
        source_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        payload = {
            "language": language,
            "source_sha256": source_sha,
            "compatibility_profile_id": compatibility_profile_id,
            "parse_status": parse_status.value,
            "ast_digest": ast_digest,
            "named_outputs": list(outputs),
            "provenance_ref": provenance_ref,
        }
        return cls(
            "fdoc_sha256_" + canonical_sha256(payload),
            language,
            source_text,
            source_sha,
            compatibility_profile_id,
            parse_status,
            ast_digest,
            outputs,
            provenance_ref,
        )


@dataclass(frozen=True, slots=True)
class FormulaOutputBinding:
    binding_id: str
    formula_document_version_id: str
    output_name: str
    binding_kind: str
    factor_definition_version_id: str
    factor_definition_hash: str
    output_type: ValueType

    @classmethod
    def create(
        cls,
        document: FormulaDocumentVersion,
        output_name: str,
        binding_kind: str,
        definition: FactorDefinitionVersion,
    ) -> FormulaOutputBinding:
        if document.parse_status is not FormulaParseStatus.PARSED:
            raise FactorAssetError("TDX_PARSE_ERROR", "failed document cannot bind outputs")
        if output_name not in document.named_outputs:
            raise FactorAssetError("FACTOR_DEFINITION_BINDING_MISMATCH", output_name)
        payload = {
            "formula_document_version_id": document.formula_document_version_id,
            "output_name": _text(output_name, "output_name"),
            "binding_kind": _text(binding_kind, "binding_kind"),
            "factor_definition_version_id": definition.factor_definition_version_id,
            "factor_definition_hash": definition.factor_definition_version_id,
            "output_type": definition.metadata.output_type.value,
        }
        return cls(
            "fob_sha256_" + canonical_sha256(payload),
            document.formula_document_version_id,
            output_name,
            binding_kind,
            definition.factor_definition_version_id,
            definition.factor_definition_version_id,
            definition.metadata.output_type,
        )


class FactorPackItemStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"
    UNSUPPORTED_DATA = "UNSUPPORTED_DATA"
    LICENSE_BLOCKED = "LICENSE_BLOCKED"
    PIT_UNRESOLVED = "PIT_UNRESOLVED"
    REFERENCE_ONLY = "REFERENCE_ONLY"


@dataclass(frozen=True, slots=True)
class FactorPackItem:
    source_item_name: str
    source_item_digest: str
    operator_requirements: tuple[str, ...]
    data_requirements: tuple[str, ...]
    pit_notes: str
    compatibility_status: FactorPackItemStatus

    def to_wire(self) -> dict[str, object]:
        return {
            "source_item_name": self.source_item_name,
            "source_item_digest": self.source_item_digest,
            "operator_requirements": list(self.operator_requirements),
            "data_requirements": list(self.data_requirements),
            "pit_notes": self.pit_notes,
            "compatibility_status": self.compatibility_status.value,
        }


@dataclass(frozen=True, slots=True)
class FactorPackManifestVersion:
    factor_pack_manifest_version_id: str
    pack_name: str
    source_project_or_publication: str
    exact_source_revision: str
    license_identifier: str
    license_evidence_ref: str
    import_mode: str
    items: tuple[FactorPackItem, ...]

    @classmethod
    def create(cls, **values: object) -> FactorPackManifestVersion:
        items = values.get("items")
        if not isinstance(items, tuple) or not items or any(not isinstance(v, FactorPackItem) for v in items):
            raise FactorAssetError("INVALID_FACTOR_PACK_MANIFEST", "typed source items required")
        names = tuple(value.source_item_name for value in items)
        _unique(names, "source item names")
        exact_source_revision = str(values.get("exact_source_revision", ""))
        if not exact_source_revision or exact_source_revision != exact_source_revision.strip():
            raise FactorAssetError(
                "FACTOR_PACK_SOURCE_REVISION_MISSING", "exact_source_revision is required"
            )
        license_identifier = str(values.get("license_identifier", ""))
        license_evidence_ref = str(values.get("license_evidence_ref", ""))
        if not license_identifier or not license_evidence_ref:
            raise FactorAssetError(
                "FACTOR_PACK_LICENSE_BLOCKED", "license identifier and evidence are required"
            )
        payload = {
            "pack_name": _text(str(values.get("pack_name", "")), "pack_name"),
            "source_project_or_publication": _text(str(values.get("source_project_or_publication", "")), "source_project_or_publication"),
            "exact_source_revision": exact_source_revision,
            "license_identifier": _text(license_identifier, "license_identifier"),
            "license_evidence_ref": _text(license_evidence_ref, "license_evidence_ref"),
            "import_mode": _text(str(values.get("import_mode", "")), "import_mode"),
            "items": [value.to_wire() for value in items],
        }
        return cls(
            "fpm_sha256_" + canonical_sha256(payload),
            payload["pack_name"],
            payload["source_project_or_publication"],
            payload["exact_source_revision"],
            payload["license_identifier"],
            payload["license_evidence_ref"],
            payload["import_mode"],
            items,
        )


class FactorImportStatus(StrEnum):
    ADMITTED = "ADMITTED"
    IMPORT_NOT_ADMITTED = "IMPORT_NOT_ADMITTED"


@dataclass(frozen=True, slots=True)
class FactorImportReceipt:
    factor_import_receipt_id: str
    source_item_digest: str
    pack_manifest_version_id: str | None
    source_revision: str
    license_provenance_ref: str
    translator_version: str
    operator_registry_version: str
    data_semantic_profile_id: str
    resulting_factor_definition_version_id: str | None
    warnings: tuple[str, ...]
    status: FactorImportStatus

    @classmethod
    def create(
        cls,
        *,
        source_item_digest: str,
        pack_manifest_version_id: str | None,
        source_revision: str,
        license_provenance_ref: str,
        translator_version: str,
        operator_registry_version: str,
        data_semantic_profile_id: str,
        definition: FactorDefinitionVersion | None,
        warnings: tuple[str, ...] = (),
        status: FactorImportStatus,
    ) -> FactorImportReceipt:
        blocked = bool(warnings) or not source_revision or not license_provenance_ref
        if status is FactorImportStatus.ADMITTED and (blocked or definition is None):
            raise FactorAssetError("FACTOR_IMPORT_NOT_ADMITTED", "warnings or missing evidence/definition")
        if status is FactorImportStatus.IMPORT_NOT_ADMITTED and definition is not None:
            raise FactorAssetError("FACTOR_IMPORT_NOT_ADMITTED", "blocked import cannot produce a definition")
        payload = {
            "source_item_digest": _text(source_item_digest, "source_item_digest"),
            "pack_manifest_version_id": pack_manifest_version_id,
            "source_revision": source_revision,
            "license_provenance_ref": license_provenance_ref,
            "translator_version": _text(translator_version, "translator_version"),
            "operator_registry_version": _text(operator_registry_version, "operator_registry_version"),
            "data_semantic_profile_id": _text(data_semantic_profile_id, "data_semantic_profile_id"),
            "resulting_factor_definition_version_id": None if definition is None else definition.factor_definition_version_id,
            "warnings": list(_unique(warnings, "warnings")),
            "status": status.value,
        }
        return cls(
            "fir_sha256_" + canonical_sha256(payload),
            payload["source_item_digest"],
            pack_manifest_version_id,
            source_revision,
            license_provenance_ref,
            payload["translator_version"],
            payload["operator_registry_version"],
            payload["data_semantic_profile_id"],
            payload["resulting_factor_definition_version_id"],
            tuple(payload["warnings"]),
            status,
        )


class FactorAssetLifecycle(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    REVIEWED = "REVIEWED"
    PROMOTED = "PROMOTED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True)
class FactorAssetVersion:
    factor_asset_version_id: str
    asset_key: str
    factor_definition_version_id: str
    factor_definition_hash: str
    source_family: str
    import_receipt_id: str | None
    formula_document_version_id: str | None
    pack_manifest_version_id: str | None
    output_binding_id: str
    display_name: str
    tags: tuple[str, ...]
    categories: tuple[str, ...]
    frequency: str
    lifecycle: FactorAssetLifecycle
    output_type: ValueType
    required_data_fields: tuple[str, ...]
    operator_dependencies: tuple[str, ...]
    max_lookback: int
    compatibility_status: FactorPackItemStatus

    @classmethod
    def create(
        cls,
        *,
        asset_key: str,
        definition: FactorDefinitionVersion,
        source_family: str,
        output_binding: FormulaOutputBinding,
        display_name: str,
        tags: tuple[str, ...],
        categories: tuple[str, ...],
        frequency: str,
        lifecycle: FactorAssetLifecycle,
        compatibility_status: FactorPackItemStatus = FactorPackItemStatus.SUPPORTED,
        import_receipt: FactorImportReceipt | None = None,
        formula_document: FormulaDocumentVersion | None = None,
        pack_manifest: FactorPackManifestVersion | None = None,
    ) -> FactorAssetVersion:
        if output_binding.factor_definition_version_id != definition.factor_definition_version_id:
            raise FactorAssetError("FACTOR_DEFINITION_BINDING_MISMATCH", asset_key)
        if output_binding.factor_definition_hash != definition.factor_definition_version_id:
            raise FactorAssetError("FACTOR_DEFINITION_BINDING_MISMATCH", "stale hash")
        if import_receipt is not None and import_receipt.resulting_factor_definition_version_id != definition.factor_definition_version_id:
            raise FactorAssetError("FACTOR_DEFINITION_BINDING_MISMATCH", "import receipt")
        if (
            formula_document is not None
            and output_binding.formula_document_version_id
            != formula_document.formula_document_version_id
        ):
            raise FactorAssetError("FACTOR_DEFINITION_BINDING_MISMATCH", "formula document")
        payload = {
            "asset_key": _text(asset_key, "asset_key"),
            "factor_definition_version_id": definition.factor_definition_version_id,
            "factor_definition_hash": definition.factor_definition_version_id,
            "source_family": _text(source_family, "source_family"),
            "import_receipt_id": None if import_receipt is None else import_receipt.factor_import_receipt_id,
            "formula_document_version_id": None if formula_document is None else formula_document.formula_document_version_id,
            "pack_manifest_version_id": None if pack_manifest is None else pack_manifest.factor_pack_manifest_version_id,
            "output_binding_id": output_binding.binding_id,
            "display_name": _text(display_name, "display_name"),
            "tags": list(_unique(tags, "tags")),
            "categories": list(_unique(categories, "categories")),
            "frequency": _text(frequency, "frequency"),
            "lifecycle": lifecycle.value,
            "output_type": definition.metadata.output_type.value,
            "required_data_fields": list(definition.metadata.input_features),
            "operator_dependencies": list(definition.metadata.operator_keys),
            "max_lookback": definition.metadata.lookback,
            "compatibility_status": compatibility_status.value,
        }
        return cls(
            "fav_sha256_" + canonical_sha256(payload),
            payload["asset_key"],
            definition.factor_definition_version_id,
            definition.factor_definition_version_id,
            payload["source_family"],
            payload["import_receipt_id"],
            payload["formula_document_version_id"],
            payload["pack_manifest_version_id"],
            output_binding.binding_id,
            payload["display_name"],
            tuple(payload["tags"]),
            tuple(payload["categories"]),
            payload["frequency"],
            lifecycle,
            definition.metadata.output_type,
            definition.metadata.input_features,
            definition.metadata.operator_keys,
            definition.metadata.lookback,
            compatibility_status,
        )


@dataclass(frozen=True, slots=True)
class FactorCatalogSnapshotVersion:
    factor_catalog_snapshot_version_id: str
    asset_refs: tuple[tuple[str, str], ...]

    @classmethod
    def create(cls, assets: tuple[FactorAssetVersion, ...]) -> FactorCatalogSnapshotVersion:
        refs = tuple(sorted((value.asset_key, value.factor_asset_version_id) for value in assets))
        if len(refs) != len(set(key for key, _ in refs)):
            raise FactorAssetError("DUPLICATE_FACTOR_ASSET_KEY", "catalog asset keys")
        return cls("fcs_sha256_" + canonical_sha256([list(value) for value in refs]), refs)


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    asset_key: str | None = None
    source_family: str | None = None
    tag: str | None = None
    category: str | None = None
    output_type: ValueType | None = None
    max_lookback: int | None = None
    frequency: str | None = None
    lifecycle: FactorAssetLifecycle | None = None
    operator_dependency: str | None = None
    pack_manifest_version_id: str | None = None
    compatibility_status: FactorPackItemStatus | None = None


@dataclass(frozen=True, slots=True)
class CatalogQueryResult:
    assets: tuple[FactorAssetVersion, ...]
    performance_status: str = "NOT_EVALUATED"
    performance_context: None = None


class FactorAssetCatalogService:
    def __init__(self, snapshot: FactorCatalogSnapshotVersion, assets: tuple[FactorAssetVersion, ...]) -> None:
        by_id = {value.factor_asset_version_id: value for value in assets}
        if tuple(sorted((value.asset_key, value.factor_asset_version_id) for value in assets)) != snapshot.asset_refs:
            raise FactorAssetError("CATALOG_SNAPSHOT_BINDING_MISMATCH", snapshot.factor_catalog_snapshot_version_id)
        self._snapshot = snapshot
        self._assets = by_id

    def query(self, query: CatalogQuery) -> CatalogQueryResult:
        values = tuple(self._assets[value_id] for _, value_id in self._snapshot.asset_refs)
        def keep(value: FactorAssetVersion) -> bool:
            return all((
                query.asset_key is None or value.asset_key == query.asset_key,
                query.source_family is None or value.source_family == query.source_family,
                query.tag is None or query.tag in value.tags,
                query.category is None or query.category in value.categories,
                query.output_type is None or value.output_type is query.output_type,
                query.max_lookback is None or value.max_lookback <= query.max_lookback,
                query.frequency is None or value.frequency == query.frequency,
                query.lifecycle is None or value.lifecycle is query.lifecycle,
                query.operator_dependency is None or query.operator_dependency in value.operator_dependencies,
                query.pack_manifest_version_id is None or value.pack_manifest_version_id == query.pack_manifest_version_id,
                query.compatibility_status is None or value.compatibility_status is query.compatibility_status,
            ))
        return CatalogQueryResult(tuple(value for value in values if keep(value)))

    def get_factor_definition_ref(self, asset_key: str) -> str:
        result = self.query(CatalogQuery(asset_key=asset_key)).assets
        if len(result) != 1:
            raise FactorAssetError("FACTOR_ASSET_NOT_FOUND", asset_key)
        return result[0].factor_definition_version_id

    def require_evaluation_context(self, context: object | None) -> None:
        if context is None:
            raise FactorAssetError("EVALUATION_CONTEXT_REQUIRED", "performance is contextual")


@dataclass(frozen=True, slots=True)
class FactorDraftProposal:
    proposal_id: str
    natural_language_intent: str
    draft_kind: str
    draft_payload: str
    rationale: str
    expected_inputs: tuple[str, ...]
    expected_output: str
    authority_status: str = "NON_CANONICAL"
    lifecycle_state: str = "DRAFT"

    def __post_init__(self) -> None:
        if self.authority_status != "NON_CANONICAL" or self.lifecycle_state != "DRAFT":
            raise FactorAssetError(
                "INVALID_FACTOR_ASSET_CONTRACT",
                "AI factor drafts cannot set authority or lifecycle",
            )

    @classmethod
    def create(cls, **values: object) -> FactorDraftProposal:
        draft_payload = str(values.get("draft_payload", ""))
        if not draft_payload or not draft_payload.strip():
            raise FactorAssetError("INVALID_FACTOR_ASSET_CONTRACT", "draft_payload is required")
        payload = {
            "natural_language_intent": _text(str(values.get("natural_language_intent", "")), "natural_language_intent"),
            "draft_kind": _text(str(values.get("draft_kind", "")), "draft_kind"),
            "draft_payload": draft_payload,
            "rationale": _text(str(values.get("rationale", "")), "rationale"),
            "expected_inputs": list(_unique(values.get("expected_inputs", ()), "expected_inputs")),  # type: ignore[arg-type]
            "expected_output": _text(str(values.get("expected_output", "")), "expected_output"),
            "authority_status": "NON_CANONICAL",
            "lifecycle_state": "DRAFT",
        }
        return cls("fdp_sha256_" + canonical_sha256(payload), **{k: tuple(v) if k == "expected_inputs" else v for k, v in payload.items() if k not in {"authority_status", "lifecycle_state"}})


@dataclass(frozen=True, slots=True)
class MiningFactorCandidate:
    candidate_id: str
    expression_source: str
    source_digest: str
    authority_status: str = "NON_CANONICAL"
    lifecycle_state: str = "DRAFT"

    def __post_init__(self) -> None:
        if self.authority_status != "NON_CANONICAL" or self.lifecycle_state != "DRAFT":
            raise FactorAssetError(
                "INVALID_FACTOR_ASSET_CONTRACT",
                "mining candidates must use the canonical FactorDefinition path",
            )

    @classmethod
    def create(cls, expression_source: str) -> MiningFactorCandidate:
        if not expression_source or not expression_source.strip():
            raise FactorAssetError(
                "INVALID_FACTOR_ASSET_CONTRACT", "expression_source is required"
            )
        digest = hashlib.sha256(expression_source.encode("utf-8")).hexdigest()
        return cls("mfc_sha256_" + canonical_sha256({"source_digest": digest}), expression_source, digest)
