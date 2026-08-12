from __future__ import annotations

import hashlib
from dataclasses import dataclass

from v3_backend.adapters.tdx_formula import (
    TdxDataSemanticProfileVersion,
    TdxTranslator,
)
from v3_backend.domain.factor_assets import (
    FactorAssetLifecycle,
    FactorAssetVersion,
    FactorImportReceipt,
    FactorPackItem,
    FactorPackItemStatus,
    FactorPackManifestVersion,
)
from v3_backend.domain.factor_library import PackCoverage, PackCoverageService


QLIB_REVISION = "git:79633dd9506ea689e5400dea0197717b5b3d74b7"
PANDAS_TA_CLASSIC_REVISION = "git:33c855e853c5ae235abb2a0b010e62abf4e14cf1"
TALIB_CORE_REVISION = "git:c83a2852335ebf21668f94ebe2237cd9a0ad599d"
ALPHA101_REFERENCE_REVISION = "publication:101-formulaic-alphas+yli188:3bb9918dd7b62039f41a585a9e37bfd67ce3719f"
ALPHA191_REFERENCE_REVISION = "publication:gtja-191+aurumq-rl:5cf7e83637b85e4f855daec16099148b358b89b3"


def _digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _alpha360_formula(field: str, lag: int) -> str:
    name = f"{field.upper()}{lag}"
    numerator = field.upper() if lag == 0 else f"REF({field.upper()},{lag})"
    denominator = "VOL" if field == "volume" else "CLOSE"
    return f"{name}:{numerator}/{denominator};"


def alpha360_manifest() -> FactorPackManifestVersion:
    """Exact Alpha360 6 fields x 60 lags membership; no Qlib code is executed."""

    items: list[FactorPackItem] = []
    for field in ("close", "open", "high", "low", "volume", "vwap"):
        for lag in range(60):
            formula = _alpha360_formula(field, lag)
            name = f"{field.upper()}{lag}"
            if lag > 0:
                status = FactorPackItemStatus.UNSUPPORTED_OPERATOR
                operators = ("REF",)
                pit = "Historical lag is PIT-safe in principle; current W0 TDX REF is unsupported."
            elif field == "volume":
                status = FactorPackItemStatus.PIT_UNRESOLVED
                operators = ()
                pit = "Qlib volume normalization and V3 VOL unit/normalization parity are unresolved."
            elif field == "vwap":
                status = FactorPackItemStatus.UNSUPPORTED_DATA
                operators = ()
                pit = "Exact Qlib VWAP source/adjustment semantic is unavailable in the current V3 TDX data profile."
            else:
                status = FactorPackItemStatus.SUPPORTED
                operators = ()
                pit = "Current daily OHLC ratio to CLOSE with observation available-time semantics; exact registered V3 data profile required."
            items.append(
                FactorPackItem(
                    name,
                    _digest(formula),
                    operators,
                    (field,),
                    pit,
                    status,
                )
            )
    return FactorPackManifestVersion.create(
        pack_name="Qlib Alpha360",
        source_project_or_publication="microsoft/qlib Alpha360",
        exact_source_revision=QLIB_REVISION,
        license_identifier="MIT",
        license_evidence_ref="https://github.com/microsoft/qlib/blob/79633dd9506ea689e5400dea0197717b5b3d74b7/LICENSE",
        import_mode="SELECTIVE_MODULE_REUSE",
        items=tuple(items),
    )


def _numbered_reference_manifest(
    *,
    count: int,
    prefix: str,
    pack_name: str,
    source: str,
    revision: str,
    status: FactorPackItemStatus,
    license_identifier: str,
    license_ref: str,
    pit_notes: str,
) -> FactorPackManifestVersion:
    return FactorPackManifestVersion.create(
        pack_name=pack_name,
        source_project_or_publication=source,
        exact_source_revision=revision,
        license_identifier=license_identifier,
        license_evidence_ref=license_ref,
        import_mode="REFERENCE_ONLY",
        items=tuple(
            FactorPackItem(
                f"{prefix}{index:03d}",
                _digest(f"{revision}:{prefix}{index:03d}:FORMULA_NOT_COPIED"),
                (),
                (),
                pit_notes,
                status,
            )
            for index in range(1, count + 1)
        ),
    )


def alpha101_reference_manifest() -> FactorPackManifestVersion:
    return _numbered_reference_manifest(
        count=101,
        prefix="WQ_ALPHA",
        pack_name="WorldQuant Alpha101 publication reference",
        source="101 Formulaic Alphas publication; unlicensed yli188 implementation not copied",
        revision=ALPHA101_REFERENCE_REVISION,
        status=FactorPackItemStatus.LICENSE_BLOCKED,
        license_identifier="PUBLICATION_REFERENCE_ONLY_NO_CODE_LICENSE",
        license_ref="docs/research/round5-p/REUSE_ADOPTION_MATRIX.md#pack-and-reference-candidates",
        pit_notes="Formula publication and repository-code license are distinct; data/rank/industry semantics require per-item admission.",
    )


def alpha191_reference_manifest() -> FactorPackManifestVersion:
    return _numbered_reference_manifest(
        count=191,
        prefix="GTJA_ALPHA",
        pack_name="GTJA Alpha191 publication reference",
        source="GTJA Alpha191 publication family; AurumQ-RL is design reference only",
        revision=ALPHA191_REFERENCE_REVISION,
        status=FactorPackItemStatus.REFERENCE_ONLY,
        license_identifier="PUBLICATION_REFERENCE_ONLY_IMPLEMENTATION_LICENSE_UNRESOLVED",
        license_ref="docs/research/round5-p/REUSE_ADOPTION_MATRIX.md#pack-and-reference-candidates",
        pit_notes="Per-item formula provenance, implementation license, A-share fields and available-time semantics are unresolved.",
    )


@dataclass(frozen=True, slots=True)
class ImportedPackItem:
    source_item_name: str
    receipt: FactorImportReceipt
    asset: FactorAssetVersion


def import_supported_alpha360(
    *,
    translator: TdxTranslator,
    data_profile: TdxDataSemanticProfileVersion,
) -> tuple[ImportedPackItem, ...]:
    manifest = alpha360_manifest()
    imported: list[ImportedPackItem] = []
    for item in manifest.items:
        if item.compatibility_status is not FactorPackItemStatus.SUPPORTED:
            continue
        field = item.source_item_name[:-1].lower()
        formula = _alpha360_formula(field, 0)
        translation = translator.translate(
            formula,
            data_profile=data_profile,
            provenance_ref=f"pack:{manifest.factor_pack_manifest_version_id}:{item.source_item_name}",
        )
        output = translation.output(item.source_item_name)
        receipt = FactorImportReceipt.create_from_pack_item(
            manifest=manifest,
            item=item,
            translation=translation,
            compatibility_profile=translator.compatibility,
            data_profile=data_profile,
            definition=output.definition,
        )
        asset = FactorAssetVersion.create(
            asset_key=f"qlib.alpha360.{item.source_item_name.lower()}",
            definition=output.definition,
            source_family="QLIB_ALPHA360",
            output_binding=output.binding,
            display_name=f"Qlib Alpha360 {item.source_item_name}",
            tags=("alpha360", "qlib"),
            categories=("price-feature",),
            frequency="1d",
            lifecycle=FactorAssetLifecycle.CANDIDATE,
            import_receipt=receipt,
            formula_document=translation.document,
            pack_manifest=manifest,
        )
        imported.append(ImportedPackItem(item.source_item_name, receipt, asset))
    return tuple(imported)


def alpha158_coverage() -> PackCoverage:
    # Qlib documents 158 as the pack's exact feature count, but exact per-item
    # formulas are intentionally not copied into P. Current IR/TDX cannot prove
    # per-member parity, so all membership remains reference-only.
    return PackCoverage(
        "Qlib Alpha158",
        QLIB_REVISION,
        158,
        0,
        0,
        0,
        0,
        0,
        0,
        158,
        0,
        None,
        "DOCUMENTED_TOTAL_ONLY_MEMBERSHIP_NOT_COPIED",
    )


def talib_v3_coverage() -> PackCoverage:
    return PackCoverage(
        "TA-Lib current V3 adapter",
        TALIB_CORE_REVISION,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        None,
        "EXISTING_V3_ADAPTER_SMA_ONLY; RUNTIME_AVAILABILITY_MAY_SKIP",
    )


def pandas_ta_classic_coverage() -> PackCoverage:
    return PackCoverage(
        "pandas-ta-classic",
        PANDAS_TA_CLASSIC_REVISION,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        None,
        "LIBRARY_REFERENCE_RECORD_ONLY; COMPLETE_CURRENT_INDICATOR_MEMBERSHIP_PENDING_NETWORK_RECHECK",
    )


def a_share_extended_coverage() -> PackCoverage:
    # Seven explicit semantic families, not invented individual factor formulas.
    return PackCoverage(
        "A-share extended data families",
        "v3-data-truth:f2cd80ee377d213a1bc1e78fb9812d2192b10cf9",
        7,
        0,
        0,
        0,
        3,
        4,
        0,
        0,
        0,
        None,
        "EXPLICIT_DATA_FAMILY_GATE: northbound, large-order, chip, shareholder, financial, sentiment, membership",
    )


def all_pack_coverages() -> tuple[PackCoverage, ...]:
    alpha360 = alpha360_manifest()
    imports = import_supported_alpha360(
        translator=_translator(),
        data_profile=_data_profile(),
    )
    return (
        alpha158_coverage(),
        PackCoverageService.from_manifest(
            alpha360,
            import_receipts=tuple(value.receipt for value in imports),
        ),
        PackCoverageService.from_manifest(alpha101_reference_manifest()),
        PackCoverageService.from_manifest(alpha191_reference_manifest()),
        talib_v3_coverage(),
        pandas_ta_classic_coverage(),
        a_share_extended_coverage(),
    )


def _translator() -> TdxTranslator:
    from v3_backend.domain.factors import signal_compatible_operator_registry

    return TdxTranslator(signal_compatible_operator_registry())


def _data_profile() -> TdxDataSemanticProfileVersion:
    from v3_backend.adapters.tdx_formula import registered_tdx_data_semantic_profile

    return registered_tdx_data_semantic_profile(volume_in_hands=False)
