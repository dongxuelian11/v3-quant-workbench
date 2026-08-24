from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from v3_backend.domain.factor_assets import (
    FormulaDocumentVersion,
    FormulaOutputBinding,
    FormulaParseStatus,
)
from v3_backend.domain.factors import (
    FactorDefinitionVersion,
    FactorNode,
    FeatureNode,
    NumericLiteralNode,
    OperatorNode,
    OperatorRegistry,
    ValueType,
    panel_operator_registry,
    signal_compatible_operator_registry,
)
from v3_backend.provenance.canonical_hash import canonical_sha256

from .parser import (
    BinaryExpression,
    CallExpression,
    FormulaStatement,
    IdentifierExpression,
    NumberExpression,
    ParsedTdxProgram,
    TdxExpression,
    TdxFormulaError,
    TdxParser,
    UnaryExpression,
)


class TdxFunctionStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_CANONICAL_OPERATOR = "UNSUPPORTED_CANONICAL_OPERATOR"
    SEMANTICS_UNRESOLVED = "SEMANTICS_UNRESOLVED"


@dataclass(frozen=True, slots=True)
class TdxFunctionCompatibility:
    tdx_function: str
    canonical_operator: str | None
    canonical_operator_version: str | None
    parameter_semantics: str
    warmup_semantics: str
    output_type: ValueType | None
    status: TdxFunctionStatus

    def __post_init__(self) -> None:
        if not self.tdx_function or self.tdx_function != self.tdx_function.upper():
            raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", "function names must be uppercase")
        if self.status is TdxFunctionStatus.SUPPORTED:
            if not self.canonical_operator or not self.canonical_operator_version or self.output_type is None:
                raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", self.tdx_function)
        elif any((self.canonical_operator, self.canonical_operator_version, self.output_type)):
            raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", "unsupported mappings cannot claim an operator")

    def to_wire(self) -> dict[str, object]:
        return {
            "tdx_function": self.tdx_function,
            "canonical_operator": self.canonical_operator,
            "canonical_operator_version": self.canonical_operator_version,
            "parameter_semantics": self.parameter_semantics,
            "warmup_semantics": self.warmup_semantics,
            "output_type": None if self.output_type is None else self.output_type.value,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class TdxCompatibilityProfileVersion:
    compatibility_profile_id: str
    operator_registry_version: str
    mappings: tuple[TdxFunctionCompatibility, ...]

    @classmethod
    def create_default(cls, registry: OperatorRegistry) -> TdxCompatibilityProfileVersion:
        supported = {
            "MA": ("SMA", "1.0.0", "MA(X,N): N integer 2..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "CROSS": ("CROSS", "1.0.0", "CROSS(left,right)", "one prior observation", ValueType.BOOLEAN_SERIES),
        }
        unresolved = {"SMA"}
        names = ("MA", "EMA", "SMA", "REF", "HHV", "LLV", "SUM", "STD", "CROSS", "COUNT", "EVERY", "EXIST", "IF", "MAX", "MIN", "ABS")
        mappings: list[TdxFunctionCompatibility] = []
        for name in names:
            if name in supported:
                operator, version, parameters, warmup, output = supported[name]
                mappings.append(TdxFunctionCompatibility(name, operator, version, parameters, warmup, output, TdxFunctionStatus.SUPPORTED))
            else:
                status = TdxFunctionStatus.SEMANTICS_UNRESOLVED if name in unresolved else TdxFunctionStatus.UNSUPPORTED_CANONICAL_OPERATOR
                mappings.append(TdxFunctionCompatibility(name, None, None, "NOT_ADMITTED", "LOOKBACK_UNRESOLVED", None, status))
        payload = {"operator_registry_version": registry.registry_version, "mappings": [value.to_wire() for value in mappings]}
        return cls("tdxcp_sha256_" + canonical_sha256(payload), registry.registry_version, tuple(mappings))

    @classmethod
    def create_panel_v1_1(cls, registry: OperatorRegistry) -> TdxCompatibilityProfileVersion:
        supported = {
            "MA": ("SMA", "1.0.0", "MA(X,N): N integer 2..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "EMA": ("EMA", "1.0.0", "EMA(X,N): N integer 2..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "REF": ("LAG", "1.0.0", "REF(X,N): N integer 0..250", "N observations", ValueType.FLOAT_SERIES),
            "HHV": ("HHV", "1.0.0", "HHV(X,N): N integer 1..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "LLV": ("LLV", "1.0.0", "LLV(X,N): N integer 1..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "SUM": ("SUM", "1.0.0", "SUM(X,N): N integer 1..250", "N-1 observations", ValueType.FLOAT_SERIES),
            "STD": ("STD", "1.0.0", "STD(X,N): population standard deviation", "N-1 observations", ValueType.FLOAT_SERIES),
            "CROSS": ("CROSS", "1.0.0", "CROSS(left,right)", "one prior observation", ValueType.BOOLEAN_SERIES),
            "IF": ("IF", "1.0.0", "IF(condition,true_value,false_value)", "propagated", ValueType.FLOAT_SERIES),
            "RANK": ("RANK", "1.0.0", "RANK(X): percentile within session date", "none", ValueType.FLOAT_SERIES),
        }
        unresolved = {"SMA"}
        names = (
            "MA", "EMA", "SMA", "REF", "HHV", "LLV", "SUM", "STD", "CROSS",
            "COUNT", "EVERY", "EXIST", "IF", "MAX", "MIN", "ABS", "RANK",
        )
        mappings: list[TdxFunctionCompatibility] = []
        for name in names:
            if name in supported:
                operator, version, parameters, warmup, output = supported[name]
                mappings.append(
                    TdxFunctionCompatibility(
                        name, operator, version, parameters, warmup, output,
                        TdxFunctionStatus.SUPPORTED,
                    )
                )
            else:
                status = (
                    TdxFunctionStatus.SEMANTICS_UNRESOLVED
                    if name in unresolved
                    else TdxFunctionStatus.UNSUPPORTED_CANONICAL_OPERATOR
                )
                mappings.append(
                    TdxFunctionCompatibility(
                        name, None, None, "NOT_ADMITTED", "LOOKBACK_UNRESOLVED", None, status
                    )
                )
        payload = {
            "operator_registry_version": registry.registry_version,
            "mappings": [value.to_wire() for value in mappings],
        }
        return cls(
            "tdxcp_sha256_" + canonical_sha256(payload),
            registry.registry_version,
            tuple(mappings),
        )

    def assert_canonical(self) -> None:
        legacy = ("MA", "EMA", "SMA", "REF", "HHV", "LLV", "SUM", "STD", "CROSS", "COUNT", "EVERY", "EXIST", "IF", "MAX", "MIN", "ABS")
        panel = (*legacy, "RANK")
        names = tuple(value.tdx_function for value in self.mappings)
        if names not in {legacy, panel} or len(names) != len(set(names)):
            raise TdxFormulaError("TDX_COMPATIBILITY_PROFILE_NOT_CANONICAL", "mapping coverage/order mismatch")
        payload = {"operator_registry_version": self.operator_registry_version, "mappings": [value.to_wire() for value in self.mappings]}
        if self.compatibility_profile_id != "tdxcp_sha256_" + canonical_sha256(payload):
            raise TdxFormulaError("TDX_COMPATIBILITY_PROFILE_NOT_CANONICAL", "profile ID/content mismatch")

    def resolve(self, name: str) -> TdxFunctionCompatibility:
        for mapping in self.mappings:
            if mapping.tdx_function == name.upper():
                return mapping
        raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", name)


@dataclass(frozen=True, slots=True)
class TdxDataFieldMapping:
    aliases: tuple[str, ...]
    canonical_field: str
    field_semantic_version: str
    canonical_unit: str
    tdx_unit: str
    canonical_to_tdx_multiplier: str
    dataset_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.aliases or not self.dataset_evidence_refs:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", self.canonical_field)
        aliases = {value.upper() for value in self.aliases}
        if any(not value or value != value.strip() for value in (*self.aliases, *self.dataset_evidence_refs)):
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "invalid alias/evidence ref")
        multiplier = Decimal(self.canonical_to_tdx_multiplier)
        if not multiplier.is_finite() or multiplier <= 0:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "invalid unit conversion")
        canonical_multiplier = format(multiplier.normalize(), "f")
        if "." in canonical_multiplier:
            canonical_multiplier = canonical_multiplier.rstrip("0").rstrip(".")
        if canonical_multiplier != self.canonical_to_tdx_multiplier:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "unit conversion must be canonical decimal text")
        unit_pair = (self.canonical_unit.upper(), self.tdx_unit.upper(), self.canonical_to_tdx_multiplier)
        ohlc = {"OPEN", "HIGH", "LOW", "CLOSE"}
        if aliases <= ohlc and len(aliases) == 1:
            admitted = {("CNY_PER_SHARE", "CNY_PER_SHARE", "1")}
        elif aliases == {"VOL"}:
            admitted = {
                ("SHARES", "HAND", "0.01"),
                ("HAND", "HAND", "1"),
            }
        elif aliases == {"AMOUNT", "AMO"}:
            admitted = {("CNY", "CNY", "1")}
        else:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "unknown TDX field family")
        if unit_pair not in admitted:
            raise TdxFormulaError(
                "TDX_DATA_SEMANTIC_UNRESOLVED",
                f"incompatible units for {sorted(aliases)}: {unit_pair}",
            )

    def to_wire(self) -> dict[str, object]:
        return {
            "aliases": list(self.aliases),
            "canonical_field": self.canonical_field,
            "field_semantic_version": self.field_semantic_version,
            "canonical_unit": self.canonical_unit,
            "tdx_unit": self.tdx_unit,
            "canonical_to_tdx_multiplier": self.canonical_to_tdx_multiplier,
            "dataset_evidence_refs": list(self.dataset_evidence_refs),
        }


@dataclass(frozen=True, slots=True)
class TdxDataSemanticProfileVersion:
    data_semantic_profile_id: str
    mappings: tuple[TdxDataFieldMapping, ...]

    @classmethod
    def create(cls, mappings: tuple[TdxDataFieldMapping, ...]) -> TdxDataSemanticProfileVersion:
        if not mappings:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "empty profile")
        aliases = [alias.upper() for value in mappings for alias in value.aliases]
        if len(aliases) != len(set(aliases)):
            raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", "duplicate alias")
        required = {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "AMO"}
        if not required.issubset(aliases):
            raise TdxFormulaError(
                "TDX_DATA_SEMANTIC_UNRESOLVED",
                f"profile missing required fields {sorted(required - set(aliases))}",
            )
        ordered = tuple(
            sorted(mappings, key=lambda value: (value.canonical_field, value.aliases))
        )
        payload = [value.to_wire() for value in ordered]
        return cls("tdxds_sha256_" + canonical_sha256(payload), ordered)

    def assert_canonical(self) -> None:
        aliases = [alias.upper() for value in self.mappings for alias in value.aliases]
        required = {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "AMO"}
        ordered = tuple(sorted(self.mappings, key=lambda value: (value.canonical_field, value.aliases)))
        if self.mappings != ordered or len(aliases) != len(set(aliases)) or set(aliases) != required:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_PROFILE_NOT_CANONICAL", "coverage/order/alias mismatch")
        expected = "tdxds_sha256_" + canonical_sha256([value.to_wire() for value in ordered])
        if self.data_semantic_profile_id != expected:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_PROFILE_NOT_CANONICAL", "profile ID/content mismatch")

    def resolve(self, alias: str) -> TdxDataFieldMapping:
        normalized = alias.upper()
        for mapping in self.mappings:
            if normalized in {value.upper() for value in mapping.aliases}:
                return mapping
        raise TdxFormulaError("TDX_DATA_SEMANTIC_UNRESOLVED", alias)


@dataclass(frozen=True, slots=True)
class TranslatedTdxOutput:
    output_name: str
    binding_kind: str
    definition: FactorDefinitionVersion
    binding: FormulaOutputBinding


@dataclass(frozen=True, slots=True)
class TdxStaticAnalysis:
    input_data_dependencies: tuple[str, ...]
    operator_dependencies: tuple[str, ...]
    max_lookback: int
    named_outputs: tuple[tuple[str, ValueType], ...]
    unsupported_functions: tuple[str, ...]
    data_semantic_profile_id: str


@dataclass(frozen=True, slots=True)
class TdxTranslationResult:
    document: FormulaDocumentVersion
    program: ParsedTdxProgram
    outputs: tuple[TranslatedTdxOutput, ...]
    static_analysis: TdxStaticAnalysis
    drawing_metadata: tuple[tuple[str, tuple[str, ...]], ...]
    translator_version: str

    def output(self, name: str) -> TranslatedTdxOutput:
        for value in self.outputs:
            if value.output_name.upper() == name.upper():
                return value
        raise KeyError(name)


def _registered_data_profile(*, volume_in_hands: bool) -> TdxDataSemanticProfileVersion:
    prices = tuple(
        TdxDataFieldMapping(
            (name.upper(),), name, f"eod.{name}/1.0.0", "CNY_PER_SHARE", "CNY_PER_SHARE", "1",
            (f"dataset-profile:{name}:cny-per-share",),
        )
        for name in ("open", "high", "low", "close")
    )
    volume = TdxDataFieldMapping(
        ("VOL",),
        "volume_hands" if volume_in_hands else "volume",
        "eod.volume-hands/1.0.0" if volume_in_hands else "eod.volume-shares/1.0.0",
        "HAND" if volume_in_hands else "SHARES", "HAND", "1" if volume_in_hands else "0.01",
        ("dataset-profile:volume-unit-observed",),
    )
    amount = TdxDataFieldMapping(
        ("AMOUNT", "AMO"), "amount", "eod.amount-cny/1.0.0", "CNY", "CNY", "1",
        ("dataset-profile:amount-currency-cny",),
    )
    return TdxDataSemanticProfileVersion.create((*prices, volume, amount))


REGISTERED_TDX_DATA_SEMANTIC_PROFILES: Mapping[str, TdxDataSemanticProfileVersion] = MappingProxyType(
    {value.data_semantic_profile_id: value for value in (_registered_data_profile(volume_in_hands=False), _registered_data_profile(volume_in_hands=True))}
)


def registered_tdx_data_semantic_profile(*, volume_in_hands: bool = False) -> TdxDataSemanticProfileVersion:
    expected = _registered_data_profile(volume_in_hands=volume_in_hands)
    return REGISTERED_TDX_DATA_SEMANTIC_PROFILES[expected.data_semantic_profile_id]


class TdxTranslator:
    translator_version = "v3-tdx-to-factor-ir/1.0.0"

    def __init__(self, registry: OperatorRegistry, compatibility: TdxCompatibilityProfileVersion | None = None) -> None:
        self.registry = registry
        if registry.to_wire() == signal_compatible_operator_registry().to_wire():
            registered = TdxCompatibilityProfileVersion.create_default(registry)
        elif registry.to_wire() == panel_operator_registry().to_wire():
            registered = TdxCompatibilityProfileVersion.create_panel_v1_1(registry)
        else:
            raise TdxFormulaError(
                "TDX_COMPATIBILITY_PROFILE_NOT_REGISTERED",
                "TDX execution requires an exact registered V3 operator registry",
            )
        self.compatibility = compatibility or registered
        self.compatibility.assert_canonical()
        if self.compatibility != registered:
            raise TdxFormulaError("TDX_COMPATIBILITY_PROFILE_NOT_REGISTERED", self.compatibility.compatibility_profile_id)
        if self.compatibility.operator_registry_version != registry.registry_version:
            raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", "compatibility/registry version mismatch")
        self.parser = TdxParser()

    def translate(self, source: str, *, data_profile: TdxDataSemanticProfileVersion, provenance_ref: str) -> TdxTranslationResult:
        data_profile.assert_canonical()
        registered_data = REGISTERED_TDX_DATA_SEMANTIC_PROFILES.get(data_profile.data_semantic_profile_id)
        if registered_data is None or registered_data != data_profile:
            raise TdxFormulaError("TDX_DATA_SEMANTIC_PROFILE_NOT_REGISTERED", data_profile.data_semantic_profile_id)
        program = self.parser.parse(source)
        document = FormulaDocumentVersion.create(
            language="TDX",
            source_text=source,
            compatibility_profile_id=self.compatibility.compatibility_profile_id,
            parse_status=FormulaParseStatus.PARSED,
            ast_digest=program.ast_digest,
            named_outputs=program.declared_names,
            provenance_ref=provenance_ref,
        )
        environment: dict[str, FactorNode] = {}
        outputs: list[TranslatedTdxOutput] = []
        drawing: list[tuple[str, tuple[str, ...]]] = []
        for statement in program.statements:
            if statement.statement_kind == "EXPRESSION":
                if (
                    isinstance(statement.expression, CallExpression)
                    and statement.expression.function_name
                    in {"DRAWTEXT", "DRAWLINE", "STICKLINE"}
                ):
                    drawing.append((statement.expression.function_name, ("UNSUPPORTED_NON_COMPUTATIONAL_STATEMENT",)))
                    continue
                raise TdxFormulaError("TDX_PARSE_ERROR", "top-level computational expression requires a name")
            assert statement.name is not None
            node = self._translate_expression(statement.expression, environment, data_profile)
            normalized_name = statement.name.upper()
            environment[normalized_name] = node
            definition = FactorDefinitionVersion.create(
                f"tdx.{document.formula_document_version_id}.{statement.name}", node, self.registry
            )
            binding = FormulaOutputBinding.create(document, statement.name, statement.statement_kind, definition)
            outputs.append(TranslatedTdxOutput(statement.name, statement.statement_kind, definition, binding))
            if statement.drawing_metadata:
                drawing.append((statement.name, statement.drawing_metadata))
        if not outputs:
            raise TdxFormulaError("TDX_PARSE_ERROR", "script has no factor outputs")
        dependencies = tuple(sorted({name for value in outputs for name in value.definition.metadata.input_features}))
        operators = tuple(sorted({name for value in outputs for name in value.definition.metadata.operator_keys}))
        analysis = TdxStaticAnalysis(
            dependencies,
            operators,
            max(value.definition.metadata.lookback for value in outputs),
            tuple((value.output_name, value.definition.metadata.output_type) for value in outputs),
            (),
            data_profile.data_semantic_profile_id,
        )
        return TdxTranslationResult(document, program, tuple(outputs), analysis, tuple(drawing), self.translator_version)

    def _translate_expression(self, expression: TdxExpression, environment: dict[str, FactorNode], data_profile: TdxDataSemanticProfileVersion) -> FactorNode:
        if isinstance(expression, NumberExpression):
            return NumericLiteralNode.create(expression.text)
        if isinstance(expression, IdentifierExpression):
            normalized = expression.name.upper()
            if normalized in environment:
                return environment[normalized]
            mapping = data_profile.resolve(normalized)
            feature: FactorNode = FeatureNode(mapping.canonical_field, mapping.field_semantic_version)
            if Decimal(mapping.canonical_to_tdx_multiplier) != Decimal(1):
                feature = OperatorNode("MULTIPLY", "1.0.0", (feature, NumericLiteralNode.create(mapping.canonical_to_tdx_multiplier)), {})
            return feature
        if isinstance(expression, UnaryExpression):
            operand = self._translate_expression(expression.operand, environment, data_profile)
            if expression.operator == "NOT":
                return OperatorNode("NOT", "1.0.0", (operand,), {})
            if expression.operator == "-":
                return OperatorNode("SUBTRACT", "1.0.0", (NumericLiteralNode.create(0), operand), {})
            raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", expression.operator)
        if isinstance(expression, BinaryExpression):
            left = self._translate_expression(expression.left, environment, data_profile)
            right = self._translate_expression(expression.right, environment, data_profile)
            mapping = {
                "+": "ADD", "-": "SUBTRACT", "*": "MULTIPLY", "/": "DIVIDE",
                "GT": "GT", "GTE": "GTE", "LT": "LT", "LTE": "LTE", "EQ": "EQ", "NE": "NE",
                "AND": "AND", "OR": "OR",
            }
            try:
                operator = mapping[expression.operator]
            except KeyError as error:
                raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", expression.operator) from error
            return OperatorNode(operator, "1.0.0", (left, right), {})
        if isinstance(expression, CallExpression):
            compatibility = self.compatibility.resolve(expression.function_name)
            if compatibility.status is not TdxFunctionStatus.SUPPORTED:
                raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", f"{expression.function_name}:{compatibility.status.value}")
            if expression.function_name == "CROSS":
                if len(expression.arguments) != 2:
                    raise TdxFormulaError("TDX_PARSE_ERROR", "CROSS requires two arguments")
                values = tuple(self._translate_expression(value, environment, data_profile) for value in expression.arguments)
                return OperatorNode(compatibility.canonical_operator, compatibility.canonical_operator_version, values, {})  # type: ignore[arg-type]
            if expression.function_name in {"MA", "EMA", "REF", "HHV", "LLV", "SUM", "STD"}:
                if len(expression.arguments) != 2 or not isinstance(expression.arguments[1], NumberExpression):
                    raise TdxFormulaError(
                        "LOOKBACK_UNRESOLVED",
                        f"{expression.function_name} period must be a non-negative numeric literal",
                    )
                period_decimal = Decimal(expression.arguments[1].text)
                if period_decimal != period_decimal.to_integral_value():
                    raise TdxFormulaError("LOOKBACK_UNRESOLVED", f"{expression.function_name} period must be an integer")
                source = self._translate_expression(expression.arguments[0], environment, data_profile)
                parameter = "periods" if expression.function_name == "REF" else "timeperiod"
                return OperatorNode(compatibility.canonical_operator, compatibility.canonical_operator_version, (source,), {parameter: int(period_decimal)})  # type: ignore[arg-type]
            if expression.function_name == "IF":
                if len(expression.arguments) != 3:
                    raise TdxFormulaError("TDX_PARSE_ERROR", "IF requires three arguments")
                values = tuple(
                    self._translate_expression(value, environment, data_profile)
                    for value in expression.arguments
                )
                return OperatorNode(compatibility.canonical_operator, compatibility.canonical_operator_version, values, {})  # type: ignore[arg-type]
            if expression.function_name == "RANK":
                if len(expression.arguments) != 1:
                    raise TdxFormulaError("TDX_PARSE_ERROR", "RANK requires one argument")
                source = self._translate_expression(expression.arguments[0], environment, data_profile)
                return OperatorNode(compatibility.canonical_operator, compatibility.canonical_operator_version, (source,), {})  # type: ignore[arg-type]
            raise TdxFormulaError("UNSUPPORTED_TDX_OPERATOR", expression.function_name)
        raise TdxFormulaError("TDX_PARSE_ERROR", "unknown AST expression")
