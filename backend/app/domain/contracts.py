"""公共数据契约。

所有域对象 ``extra="forbid"``：拼错的字段必须立刻报错，而不是被静默吞掉。
金额、比率一律 Decimal；跨层传输用十进制字符串（``value_text``）。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #

class DocType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    ANNUAL_SUMMARY = "annual_summary"
    CORRECTION = "correction"
    INDUSTRY_STATS = "industry_stats"
    POLICY = "policy"
    MARKET_NOTE = "market_note"
    QUARTERLY = "quarterly"


class SourceMode(str, Enum):
    LIVE = "live"
    CACHED = "cached"
    REPLAY = "replay"


class ModelMode(str, Enum):
    LIVE = "live"
    MOCK = "mock"
    REPLAY = "replay"


class Decision(str, Enum):
    AGREED = "AGREED"
    ACCEPTED_WITH_CONFLICT = "ACCEPTED_WITH_CONFLICT"
    SUPERSEDED = "SUPERSEDED"
    BLOCKED = "BLOCKED"
    MISSING = "MISSING"
    PROVISIONAL = "PROVISIONAL"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

    @staticmethod
    def weakest(items: list["Confidence"]) -> "Confidence":
        order = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
        if not items:
            return Confidence.LOW
        return min(items, key=lambda c: order[c])


class IssueType(str, Enum):
    NUMERIC_CONFLICT = "NUMERIC_CONFLICT"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    ROUNDING_COMPATIBLE = "ROUNDING_COMPATIBLE"
    PRECISION_UNKNOWN = "PRECISION_UNKNOWN"
    RECONCILE_FAIL = "RECONCILE_FAIL"
    NOT_CHECKED = "NOT_CHECKED"
    DATE_UNRELIABLE = "DATE_UNRELIABLE"
    EXTRACT_AMBIGUOUS = "EXTRACT_AMBIGUOUS"
    SCANNED_UNSUPPORTED = "SCANNED_UNSUPPORTED"
    COVERAGE_GAP = "COVERAGE_GAP"
    CROSS_SOURCE_DIVERGENCE = "CROSS_SOURCE_DIVERGENCE"


class Severity(str, Enum):
    INFO = "INFO"
    WATCH = "WATCH"
    BLOCKING = "BLOCKING"


class MetricStatus(str, Enum):
    OK = "OK"
    MISSING_INPUT = "MISSING_INPUT"
    INVALID_BASE = "INVALID_BASE"
    BLOCKED_INPUT = "BLOCKED_INPUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RuleStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class ClaimKind(str, Enum):
    FACT = "fact"
    CALCULATION = "calculation"
    INTERPRETATION = "interpretation"
    HYPOTHESIS = "hypothesis"
    UNKNOWN = "unknown"


class Verdict(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


class Relation(str, Enum):
    USES_INPUT = "USES_INPUT"
    OPERATES_IN = "OPERATES_IN"
    SELLS_VIA = "SELLS_VIA"
    SUPPLIES_TO = "SUPPLIES_TO"
    PEER_OF = "PEER_OF"


class NodeType(str, Enum):
    COMPANY = "company"
    MATERIAL = "material"
    PROCESS = "process"
    CHANNEL = "channel"
    INDUSTRY = "industry"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL = {RunStatus.COMPLETE, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.INTERRUPTED}


# --------------------------------------------------------------------------- #
# 实体与文档
# --------------------------------------------------------------------------- #

class Entity(Strict):
    entity_id: str            # EX:600600 / SH:600600 / SZ:002461
    name: str
    exchange: str             # SH / SZ
    ticker: str
    industry_id: str
    role: Literal["subject", "peer"] = "peer"


class Alias(Strict):
    alias: str
    entity_id: str
    alias_type: Literal["short", "former", "english", "code"] = "short"


class Document(Strict):
    document_id: str
    logical_doc_key: str
    sha256: str
    canonical_url: str | None = None
    title: str
    issuer: str
    source_type: DocType
    published_on: date | None = None
    retrieved_at: datetime | None = None
    period_start: date | None = None
    period_end: date | None = None
    content_type: str = "application/pdf"
    page_count: int = 0
    local_path: str = ""
    parser_version: str = "pdfplumber/1"
    tier: Literal["primary", "secondary"] = "primary"
    demo_role: str | None = None


class SourceLocation(Strict):
    location_id: str
    document_id: str
    kind: Literal["pdf_cell", "pdf_page", "html_block"]
    page_index: int | None = None       # 物理页 1-based
    printed_label: str | None = None    # 印刷页标
    cell_id: str | None = None          # r{row}c{col}
    row_label: str | None = None
    col_label: str | None = None
    table_id: str | None = None
    table_type: str | None = None
    bbox: tuple[float, float, float, float] | None = None  # 归一化 左上原点
    heading_path: str | None = None
    block_index: int | None = None
    excerpt: str = ""
    extractor_version: str = "extract/1"


class Fact(Strict):
    fact_id: str
    fact_key: str                  # FactKey.canonical()
    key_parts: dict[str, str]
    entity_id: str
    field_code: str
    location_id: str
    document_id: str
    raw_value: str
    value_text: str                # 换算到基准单位后的数值
    raw_unit: str                  # 元 / 万元 / 亿元 / 万千升 / %
    unit_scale: str                # 换算倍数，避免除零歧义
    currency: str
    precision_step: str
    extraction_method: Literal["table_cell", "manual_candidate", "text_parse"]
    audit_scope: Literal["primary_table", "summary_table", "segment_table", "narrative"]
    basis_tag: Literal["original", "restated", "unknown"] = "original"
    lineage_group: str = ""
    extract_status: Literal["OK", "AMBIGUOUS", "SCANNED_UNSUPPORTED"] = "OK"
    confidence_hint: Confidence = Confidence.MEDIUM
    period_end: str = ""
    consolidation: str = "consolidated"


class Resolution(Strict):
    resolution_id: str
    fact_key: str
    field_code: str
    period_end: str
    chosen_fact_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    decision: Decision
    confidence: Confidence
    reason: str
    policy_version: str
    observed_values: list[dict[str, Any]] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)


class Issue(Strict):
    issue_id: str
    type: IssueType
    severity: Severity
    key: str
    candidate_ids: list[str] = Field(default_factory=list)
    status: Literal["OPEN", "RESOLVED", "WONTFIX"] = "OPEN"
    context: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 指标 / 图 / Claim
# --------------------------------------------------------------------------- #

class MetricInput(Strict):
    slot: str
    value_text: str | None
    fact_id: str | None
    metric_ref: str | None = None
    status: str = "OK"


class MetricResult(Strict):
    result_id: str
    metric_key: str
    metric_code: str
    formula_id: str
    formula_version: int
    entity_id: str
    fiscal_year: int
    value_text: str | None = None
    display: str | None = None
    unit: Literal["fraction", "pp", "cny", "days"]
    status: MetricStatus
    inputs: list[MetricInput] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    compare_scope: str = "single"
    confidence: Confidence = Confidence.LOW
    missing_reason: str | None = None
    computed_at: datetime | None = None


class GraphNode(Strict):
    node_id: str
    type: NodeType
    label: str
    entity_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(Strict):
    edge_id: str
    edge_key: str
    src: str
    dst: str
    relation: Relation
    scope: str
    evidence_refs: list[str] = Field(default_factory=list)
    effective_period: str
    status: Literal["VERIFIED", "STRUCTURAL", "UNVERIFIED"] = "VERIFIED"
    note: str | None = None


class Claim(Strict):
    claim_version_id: str
    claim_key: str
    kind: ClaimKind
    template: str
    slots: dict[str, str]
    reference_ids: list[str]
    verdict: Verdict = Verdict.PASS
    section_key: str
    text: str
    findings: list[dict[str, str]] = Field(default_factory=list)


class SectionVersion(Strict):
    section_version_id: str
    section_key: str
    report_id: str
    version_no: int
    content: dict[str, Any]
    content_hash: str
    claim_ids: list[str] = Field(default_factory=list)


class ReportVersion(Strict):
    report_id: str
    version_no: int
    base_version_id: str | None
    input_fingerprint: str
    as_of: str
    workflow_version: str
    state: Literal["draft", "published", "partial"]
    content_hash: str
    created_at: datetime
    label: str = ""


# --------------------------------------------------------------------------- #
# 运行与请求
# --------------------------------------------------------------------------- #

class RunRequest(Strict):
    entity_id: str
    fiscal_years: list[int]
    as_of: str
    peer_ids: list[str] = Field(default_factory=list)
    source_mode: SourceMode = SourceMode.REPLAY
    question: str | None = None


class StageEvent(Strict):
    seq: int
    node: str
    status: Literal["start", "ok", "skip", "fail", "partial", "info"]
    message: str = ""
    counts: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceRef(Strict):
    """引用解析结果：前端抽屉直接消费。"""

    ref: str
    kind: Literal["fact", "metric", "edge", "industry", "claim", "risk", "document"]
    title: str
    value_display: str | None = None
    unit: str | None = None
    formula: dict[str, Any] | None = None
    basis: dict[str, str] = Field(default_factory=dict)
    document: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    excerpt: str | None = None
    reasons: list[str] = Field(default_factory=list)
