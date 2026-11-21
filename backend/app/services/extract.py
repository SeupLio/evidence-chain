"""PDF 解析与单元格抽取。

真实链路：pdfplumber 读物理页 → 识别报表标题（排除目录/摘要）→ 定位表格与单元格坐标 →
行名词典映射字段 → 列头解析期间 → 单位证据定倍数。模型只在第二步做「候选映射」的复核，
永远不产生数字。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pdfplumber

from ..domain.fields import CORE_FIELDS, FIELDS, NOISE_MARKERS, STATEMENT_FIELDS, match_field
from ..domain.keys import FactKey

EXTRACTOR_VERSION = "extract/1.2.0"
CORE_FIELDS_SET = set(CORE_FIELDS)

UNIT_SCALE = {"元": Decimal(1), "千元": Decimal(1000), "万元": Decimal(10_000),
              "百万元": Decimal(1_000_000), "亿元": Decimal(100_000_000),
              "万千升": Decimal(10_000), "千升": Decimal(1000), "万吨": Decimal(10_000)}

YEAR_ONLY = re.compile(r"(20\d{2})\s*年度?")
DATE_FULL = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
UNIT_RE = re.compile(r"单位\s*[:：]\s*([元万千百亿升吨]+)")
NUM_RE = re.compile(r"[0-9]")


@dataclass
class CellRef:
    row: int
    col: int
    bbox: tuple[float, float, float, float]


@dataclass
class PageInfo:
    page_index: int
    kind: str = "unknown"          # cover | toc | summary | balance_sheet | income_statement | cash_flow | segment | parent_statement | other
    consolidation: str = "consolidated"
    unit: str = "元"
    titles: list[str] = field(default_factory=list)
    noise: bool = False
    has_text: bool = True
    text_head: str = ""


@dataclass
class ParseResult:
    pages: list[PageInfo]
    facts: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    ambiguous: list[dict[str, Any]]
    sha256: str
    page_count: int


# --------------------------------------------------------------------------- #
# 数值解析
# --------------------------------------------------------------------------- #

def parse_number(raw: str) -> tuple[Decimal | None, int, str]:
    """返回 (数值, 小数位数, 备注)。破折号/空白不默认为 0。"""
    if raw is None:
        return None, 0, "EMPTY"
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    if text in ("", "-", "—", "–", "－", "/", "不适用", "—　"):
        return None, 0, "EMPTY"
    negative = False
    if (text.startswith("(") and text.endswith(")")) or (text.startswith("（") and text.endswith("）")):
        negative, text = True, text[1:-1]
    if text.startswith("－") or text.startswith("−"):
        negative, text = True, text[1:]
    text = text.replace(",", "").replace("，", "").replace(" ", "").replace("%", "")
    if not NUM_RE.search(text):
        return None, 0, "NOT_NUMERIC"
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None, 0, "NOT_NUMERIC"
    decimals = len(text.split(".")[1]) if "." in text else 0
    return (-value if negative else value), decimals, "OK"


def precision_step(unit_scale: Decimal, decimals: int) -> Decimal:
    return unit_scale * (Decimal(10) ** -decimals)


# --------------------------------------------------------------------------- #
# 页分类
# --------------------------------------------------------------------------- #

TITLE_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"母公司\s*资产负债表"), "balance_sheet", "parent"),
    (re.compile(r"合并\s*资产负债表"), "balance_sheet", "consolidated"),
    (re.compile(r"母公司\s*利润表"), "income_statement", "parent"),
    (re.compile(r"合并\s*利润表"), "income_statement", "consolidated"),
    (re.compile(r"母公司\s*现金流量表"), "cash_flow", "parent"),
    (re.compile(r"合并\s*现金流量表"), "cash_flow", "consolidated"),
    (re.compile(r"主要会计数据"), "summary", "consolidated"),
    (re.compile(r"分行业|分部信息|主营业务分行业"), "segment", "consolidated"),
]


def _classify_page(page, index: int) -> PageInfo:
    text = page.extract_text() or ""
    info = PageInfo(page_index=index + 1, has_text=bool(text.strip()),
                    text_head=text.replace("\n", " ")[:400])
    head = text[:400]
    info.noise = any(m in head for m in NOISE_MARKERS if m != "主要会计数据") or (
        "目录" in head.split("\n")[0] if head else False
    )
    if info.noise:
        info.kind = "toc"
        return info
    for pattern, kind, consolidation in TITLE_RULES:
        if pattern.search(text):
            info.titles.append(pattern.pattern)
            info.kind = kind
            info.consolidation = consolidation
            break
    m = UNIT_RE.search(text)
    if m:
        unit = m.group(1)
        info.unit = unit if unit in UNIT_SCALE else "元"
    return info


def _valid_table(table: Any, page_kind: str = "") -> bool:
    """表头必须有年份列；分部表例外（其列为「营业收入/营业成本」）。"""
    rows = table.extract()
    if not rows or len(rows) < 2:
        return False
    header = [str(c or "").replace(" ", "") for c in rows[0]]
    if page_kind == "segment":
        return any("营业收入" in c for c in header) and any("营业成本" in c for c in header)
    year_cols = sum(1 for c in header if YEAR_ONLY.search(c) or DATE_FULL.search(c))
    return len(header) >= 3 and year_cols >= 1


def _period_from_header(cell: str) -> tuple[str, str, str, int] | None:
    """列头 → (period_start, period_end, period_kind, year)。"""
    c = (cell or "").replace(" ", "")
    m = DATE_FULL.search(c)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-01-01", f"{y:04d}-{mo:02d}-{d:02d}", "POINT", y
    m = YEAR_ONLY.search(c)
    if m:
        y = int(m.group(1))
        return f"{y:04d}-01-01", f"{y:04d}-12-31", "FY", y
    return None


def _col_basis(header: str, default: str) -> str:
    """更正公告里的「更正前/更正后」列决定 basis_tag，避免同一文档自相冲突。"""
    h = (header or "").replace(" ", "")
    if any(k in h for k in ("更正前", "调整前", "重述前", "原披露")):
        return "original"
    if any(k in h for k in ("更正后", "调整后", "重述后", "更正为")):
        return "restated"
    return default


# --------------------------------------------------------------------------- #
# 主解析
# --------------------------------------------------------------------------- #

def analyze(path: str | Path, entity_id: str, fiscal_year: int, *, basis_tag: str = "original",
            doc_kind: str = "annual_report") -> ParseResult:
    path = Path(path)
    blob = path.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    facts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    pages: list[PageInfo] = []

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for idx, page in enumerate(pdf.pages):
            info = _classify_page(page, idx)
            pages.append(info)
            if not info.has_text:
                gaps.append({"page": info.page_index, "type": "SCANNED_UNSUPPORTED",
                             "detail": "该页无原生文本层，未做 OCR；可在人工复核后录入候选值"})
                continue
            if info.kind in ("toc", "cover", "other", "unknown"):
                continue

            try:
                tables = page.find_tables()
            except Exception as exc:  # pragma: no cover
                gaps.append({"page": info.page_index, "type": "PARSE_ERROR", "detail": str(exc)})
                continue

            accepted = 0
            for table in tables:
                if not _valid_table(table, info.kind):
                    continue
                rows = table.extract()
                header = [str(c or "").replace(" ", "") for c in rows[0]]
                cols: list[tuple[int, tuple[str, str, str, int], str]] = []
                for c_i, cell in enumerate(header[1:], start=1):
                    period = _period_from_header(cell)
                    if period:
                        cols.append((c_i, period, _col_basis(cell, basis_tag)))
                if not cols and info.kind == "segment":
                    # 分部表无年份列，期间取自文档的报告期（记录在 excerpt 中）
                    p_start, p_end = f"{fiscal_year}-01-01", f"{fiscal_year}-12-31"
                    cols = [(None, (p_start, p_end, "FY", fiscal_year), basis_tag)]  # type: ignore[list-item]
                if not cols:
                    continue
                accepted += 1
                table_id = f"p{info.page_index}t{accepted}"
                unit_scale = UNIT_SCALE.get(info.unit, Decimal(1))

                if info.kind == "segment":
                    facts += _parse_segment_rows(rows, table, cols[0][1], info, unit_scale, sha,
                                                 entity_id, basis_tag, table_id)
                else:
                    facts += _parse_statement_rows(rows, table, cols, info, unit_scale, sha, entity_id,
                                                   doc_kind, table_id, gaps)
            if accepted == 0 and info.kind not in ("toc", "cover"):
                text = (page.extract_text() or "")
                if "未提供" in text or "不适用" in text:
                    gaps.append({"page": info.page_index, "type": "COVERAGE_NOTE",
                                 "detail": f"页面声明 {info.kind} 但未提供表格数据，记为覆盖缺口"})
                else:
                    gaps.append({"page": info.page_index, "type": "NO_TABLE",
                                 "detail": f"页类型判定为 {info.kind}，但未找到带年份表头的表格"})

    return ParseResult(pages=pages, facts=facts, gaps=gaps, ambiguous=ambiguous, sha256=sha, page_count=page_count)


def _cell_bbox(table: Any, r: int, c: int, page_w: float, page_h: float):
    try:
        cell = table.rows[r].cells[c]
    except (IndexError, AttributeError):
        return None
    if not cell:
        return None
    x0, top, x1, bottom = cell
    return (round(x0 / page_w, 5), round(top / page_h, 5), round(x1 / page_w, 5), round(bottom / page_h, 5))


def _parse_statement_rows(rows, table, cols, info: PageInfo, unit_scale: Decimal, sha: str,
                          entity_id: str, doc_kind: str, table_id: str, gaps: list) -> list[dict]:
    out: list[dict] = []
    page_w, page_h = table.page.width, table.page.height
    allowed = set(STATEMENT_FIELDS.get(info.kind, ()))
    if doc_kind == "correction":
        # 更正公告一张表里同时出现利润表与分部科目
        allowed |= set(STATEMENT_FIELDS["segment"]) | set(STATEMENT_FIELDS["income_statement"])
    for r_i, row in enumerate(rows[1:], start=1):
        label = str(row[0] or "")
        code = match_field(label)
        if not code or code not in allowed:
            continue
        spec = FIELDS[code]
        for c_i, (p_start, p_end, p_kind_hdr, year), col_basis in cols:
            if c_i >= len(row):
                continue
            # 期间形态由字段口径决定：流量用 FY，期末余额用 POINT。
            # 摘要表列头只写「2025年」，若按列头推会与资产负债表余额混为一谈。
            p_kind = spec.period_kind
            if p_kind == "POINT":
                p_start = p_end
            else:
                p_start = f"{year}-01-01"
                p_end = f"{year}-12-31"
            raw = row[c_i]
            value, decimals, note = parse_number(raw)
            if value is None:
                if code in CORE_FIELDS_SET:
                    gaps.append({"page": info.page_index, "type": "EMPTY_CELL", "field": code,
                                 "year": year, "note": note, "row": label,
                                 "detail": f"{label} 在 {year} 列为空（{note}），按要求不按 0 处理"})
                continue
            consolidation = info.consolidation
            scope = ("segment:beer" if code.endswith("_beer")
                     else "segment:other" if code.endswith("_other") else "total")
            key = FactKey(entity_id=entity_id, field_code=code, period_start=p_start, period_end=p_end,
                          period_kind=p_kind, consolidation=consolidation, currency="CNY",
                          business_scope=scope, definition_id=spec.definition_id)
            audit_scope = "summary_table" if info.kind == "summary" else "primary_table"
            bbox = _cell_bbox(table, r_i, c_i, page_w, page_h)
            out.append(_make_fact(key, spec, raw, value, decimals, unit_scale, info, sha, col_basis,
                                  table_id, r_i, c_i, label, bbox, audit_scope))
    return out


SEG_ROW = {"啤酒业务": ("seg_revenue_beer", "seg_cost_beer"), "其他业务": ("seg_revenue_other", "seg_cost_other")}
SEG_COL = {"营业收入": 0, "营业成本": 1}


def _parse_segment_rows(rows, table, period, info, unit_scale, sha, entity_id, basis_tag, table_id):
    out: list[dict] = []
    page_w, page_h = table.page.width, table.page.height
    header = [str(c or "").replace(" ", "") for c in rows[0]]
    rev_col = cost_col = None
    for c_i, name in enumerate(header):
        if rev_col is None and "营业收入" in name:
            rev_col = c_i
        elif cost_col is None and "营业成本" in name:
            cost_col = c_i
    if rev_col is None or cost_col is None:
        return out
    p_start, p_end, p_kind, year = period
    for r_i, row in enumerate(rows[1:], start=1):
        label = str(row[0] or "").replace(" ", "").strip()
        if label not in SEG_ROW:
            continue
        rev_code, cost_code = SEG_ROW[label]
        for code, c_i in ((rev_code, rev_col), (cost_code, cost_col)):
            spec = FIELDS[code]
            if c_i >= len(row):
                continue
            raw = row[c_i]
            value, decimals, note = parse_number(raw)
            if value is None:
                continue
            scope = "segment:beer" if "beer" in code else "segment:other"
            key = FactKey(entity_id=entity_id, field_code=code, period_start=p_start, period_end=p_end,
                          period_kind=p_kind, consolidation="consolidated", currency="CNY",
                          business_scope=scope, definition_id=spec.definition_id)
            bbox = _cell_bbox(table, r_i, c_i, page_w, page_h)
            out.append(_make_fact(key, spec, raw, value, decimals, unit_scale, info, sha, basis_tag,
                                  table_id, r_i, c_i, label, bbox, "segment_table"))
    return out


def _make_fact(key: FactKey, spec, raw: str, value: Decimal, decimals: int, unit_scale: Decimal,
               info: PageInfo, sha: str, basis_tag: str, table_id: str, r_i: int, c_i: int,
               label: str, bbox, audit_scope: str) -> dict[str, Any]:
    scaled = value * unit_scale
    step = precision_step(unit_scale, decimals)
    return {
        "fact_key": key.canonical(),
        "key": key,
        "key_parts": key.describe(),
        "entity_id": key.entity_id,
        "field_code": key.field_code,
        "raw_value": str(raw),
        "value_text": str(scaled),
        "raw_unit": info.unit,
        "unit_scale": str(unit_scale),
        "currency": "CNY",
        "precision_step": str(step),
        "extraction_method": "table_cell",
        "audit_scope": audit_scope,
        "basis_tag": basis_tag,
        "extract_status": "OK",
        "confidence_hint": "HIGH" if audit_scope == "primary_table" else "MEDIUM",
        "period_end": key.period_end,
        "consolidation": key.consolidation,
        "page_index": info.page_index,
        "cell_id": f"r{r_i}c{c_i}",
        "row_label": label.replace(" ", ""),
        "col_label": f"{key.period_end}",
        "table_id": table_id,
        "table_type": info.kind,
        "bbox": bbox,
        "excerpt": f"{label.replace(' ', '')} · {str(raw).strip()}（单位：{info.unit}）",
        "document_sha256": sha,
        "heading_path": f"第{info.page_index}页 / {info.kind}",
    }
