from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..contracts import StrictAgentModel


BoundedText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)]
ShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
EvidenceId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"[a-z][a-z0-9_]*_sha256_[0-9a-f]{64}"),
]
DisplayNormalization = Literal["NONE", "NUMBER", "PERCENT", "ISO_DATE"]
EvidenceField = Literal[
    "objectId",
    "kind",
    "title",
    "summary",
    "canonicalTruthState",
    "canonicalAdmissionState",
    "validationState",
    "reviewerFinding",
    "openInLab",
    "artifactId",
]


def reject_markup(value: str) -> str:
    lowered = value.lower()
    if "<script" in lowered or "<iframe" in lowered or "javascript:" in lowered:
        raise ValueError("Agent-authored markup or script is forbidden")
    if "<" in value and ">" in value:
        raise ValueError("Agent-authored HTML is forbidden")
    return value


class EvidenceFieldSelector(StrictAgentModel):
    kind: Literal["EVIDENCE_FIELD"]
    field: EvidenceField
    normalization: DisplayNormalization


class FactSelector(StrictAgentModel):
    kind: Literal["FACT"]
    label: ShortText
    normalization: DisplayNormalization

    _safe_label = field_validator("label")(reject_markup)


ResearchViewSelector = Annotated[
    EvidenceFieldSelector | FactSelector,
    Field(discriminator="kind"),
]


def as_tuple(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def exact_evidence_binding(declared_values: tuple[str, ...], referenced_values: tuple[str, ...]) -> None:
    declared = set(declared_values)
    if len(declared) != len(declared_values):
        raise ValueError("evidence_ids must not contain duplicates")
    if any(evidence_id not in declared for evidence_id in referenced_values):
        raise ValueError("child evidence_id must be declared by its block")


class NarrativeBlock(StrictAgentModel):
    type: Literal["Narrative"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["AGENT_DRAFT_DERIVED"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    text: BoundedText

    _arrays = field_validator("evidence_ids", mode="before")(as_tuple)
    _safe_title = field_validator("title")(reject_markup)
    _safe_text = field_validator("text")(reject_markup)

    @model_validator(mode="after")
    def validate_evidence(self) -> NarrativeBlock:
        exact_evidence_binding(self.evidence_ids, ())
        return self


class ResearchViewMetric(StrictAgentModel):
    label: ShortText
    evidence_id: EvidenceId
    selector: ResearchViewSelector

    _safe_label = field_validator("label")(reject_markup)


class MetricGroupBlock(StrictAgentModel):
    type: Literal["MetricGroup"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["CANONICAL_EVIDENCE"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    metrics: tuple[ResearchViewMetric, ...] = Field(min_length=1, max_length=32)

    _safe_title = field_validator("title")(reject_markup)

    @field_validator("evidence_ids", "metrics", mode="before")
    @classmethod
    def accept_json_arrays(cls, value: object) -> object:
        return as_tuple(value)

    @model_validator(mode="after")
    def enforce_exact_evidence_binding(self) -> MetricGroupBlock:
        exact_evidence_binding(self.evidence_ids, tuple(metric.evidence_id for metric in self.metrics))
        return self


class DataTableColumn(StrictAgentModel):
    key: ShortText
    header: ShortText
    selector: ResearchViewSelector

    _safe_header = field_validator("header")(reject_markup)


class EvidenceRow(StrictAgentModel):
    evidence_id: EvidenceId


class TableSort(StrictAgentModel):
    column_key: ShortText
    direction: Literal["ASC", "DESC"]


class DataTableBlock(StrictAgentModel):
    type: Literal["DataTable"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["CANONICAL_EVIDENCE"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    columns: tuple[DataTableColumn, ...] = Field(min_length=1, max_length=20)
    rows: tuple[EvidenceRow, ...] = Field(min_length=1, max_length=500)
    sort: TableSort | None
    top_n: Annotated[int, Field(strict=True, ge=1, le=100)] | None

    _arrays = field_validator("evidence_ids", "columns", "rows", mode="before")(as_tuple)
    _safe_title = field_validator("title")(reject_markup)

    @model_validator(mode="after")
    def validate_table(self) -> DataTableBlock:
        exact_evidence_binding(self.evidence_ids, tuple(row.evidence_id for row in self.rows))
        keys = tuple(column.key for column in self.columns)
        if len(set(keys)) != len(keys):
            raise ValueError("DataTable column keys must be unique")
        if self.sort is not None and self.sort.column_key not in set(keys):
            raise ValueError("DataTable sort references an unknown column")
        return self


class TimeSeriesPoint(StrictAgentModel):
    evidence_id: EvidenceId
    x_selector: ResearchViewSelector
    y_selector: ResearchViewSelector

    @model_validator(mode="after")
    def require_numeric_axis_types(self) -> TimeSeriesPoint:
        if self.x_selector.normalization != "ISO_DATE":
            raise ValueError("TimeSeriesChart x selector requires ISO_DATE")
        if self.y_selector.normalization != "NUMBER":
            raise ValueError("TimeSeriesChart y selector requires NUMBER")
        return self


class DateWindow(StrictAgentModel):
    start: ShortText
    end: ShortText


class TimeSeriesChartBlock(StrictAgentModel):
    type: Literal["TimeSeriesChart"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["CANONICAL_EVIDENCE"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    x_label: ShortText
    y_label: ShortText
    points: tuple[TimeSeriesPoint, ...] = Field(min_length=1, max_length=200)
    date_window: DateWindow | None

    _arrays = field_validator("evidence_ids", "points", mode="before")(as_tuple)
    _safe_text = field_validator("title", "x_label", "y_label")(reject_markup)

    @model_validator(mode="after")
    def validate_points(self) -> TimeSeriesChartBlock:
        exact_evidence_binding(self.evidence_ids, tuple(point.evidence_id for point in self.points))
        return self


class BarPoint(StrictAgentModel):
    evidence_id: EvidenceId
    category_selector: ResearchViewSelector
    value_selector: ResearchViewSelector

    @model_validator(mode="after")
    def require_numeric_values(self) -> BarPoint:
        if self.value_selector.normalization != "NUMBER":
            raise ValueError("BarChart value selector requires NUMBER")
        return self


class BarChartBlock(StrictAgentModel):
    type: Literal["BarChart"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["CANONICAL_EVIDENCE"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    category_label: ShortText
    value_label: ShortText
    bars: tuple[BarPoint, ...] = Field(min_length=1, max_length=100)
    sort: Literal["INPUT", "VALUE_ASC", "VALUE_DESC"]
    top_n: Annotated[int, Field(strict=True, ge=1, le=50)] | None

    _arrays = field_validator("evidence_ids", "bars", mode="before")(as_tuple)
    _safe_text = field_validator("title", "category_label", "value_label")(reject_markup)

    @model_validator(mode="after")
    def validate_bars(self) -> BarChartBlock:
        exact_evidence_binding(self.evidence_ids, tuple(bar.evidence_id for bar in self.bars))
        return self


class EvidenceListField(StrictAgentModel):
    key: ShortText
    label: ShortText
    selector: ResearchViewSelector

    _safe_label = field_validator("label")(reject_markup)


class EvidenceListBlock(StrictAgentModel):
    type: Literal["EvidenceList"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["CANONICAL_EVIDENCE"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    fields: tuple[EvidenceListField, ...] = Field(min_length=1, max_length=10)

    _arrays = field_validator("evidence_ids", "fields", mode="before")(as_tuple)
    _safe_title = field_validator("title")(reject_markup)

    @model_validator(mode="after")
    def validate_fields(self) -> EvidenceListBlock:
        exact_evidence_binding(self.evidence_ids, ())
        keys = tuple(field.key for field in self.fields)
        if len(set(keys)) != len(keys):
            raise ValueError("EvidenceList field keys must be unique")
        return self


class CalloutBlock(StrictAgentModel):
    type: Literal["Callout"]
    block_id: ShortText
    title: ShortText
    data_authority: Literal["AGENT_DRAFT_DERIVED"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1, max_length=128)
    tone: Literal["INFO", "WARNING", "BLOCKED"]
    text: BoundedText

    _arrays = field_validator("evidence_ids", mode="before")(as_tuple)
    _safe_title = field_validator("title")(reject_markup)
    _safe_text = field_validator("text")(reject_markup)

    @model_validator(mode="after")
    def validate_evidence(self) -> CalloutBlock:
        exact_evidence_binding(self.evidence_ids, ())
        return self


ResearchViewBlock = Annotated[
    NarrativeBlock
    | MetricGroupBlock
    | DataTableBlock
    | TimeSeriesChartBlock
    | BarChartBlock
    | EvidenceListBlock
    | CalloutBlock,
    Field(discriminator="type"),
]


class ResearchViewSpecV1(StrictAgentModel):
    schema_version: Literal["v3.generative_research_view/1.0.0"]
    spec_id: ShortText
    session_view_id: ShortText
    permission: Literal["L1_DRAFT"]
    authority: Literal["AGENT_DRAFT_PROPOSAL"]
    title: ShortText
    blocks: tuple[ResearchViewBlock, ...] = Field(min_length=1, max_length=64)

    _safe_title = field_validator("title")(reject_markup)

    @field_validator("blocks", mode="before")
    @classmethod
    def accept_json_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class StructuredResearchViewResult(StrictAgentModel):
    status: Literal["VALID", "INVALID"]
    view_spec: ResearchViewSpecV1 | None
    error: ShortText | None
    text_draft: BoundedText | None

    @model_validator(mode="after")
    def enforce_explicit_result(self) -> StructuredResearchViewResult:
        if self.status == "VALID" and (self.view_spec is None or self.error is not None):
            raise ValueError("VALID result requires a view_spec and no error")
        if self.status == "INVALID" and (self.view_spec is not None or self.error is None):
            raise ValueError("INVALID result requires an error and no view_spec")
        return self
