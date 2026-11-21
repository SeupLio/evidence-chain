"""真实年报 PDF 的行锚定抽取器。

为什么不复用表格抽取：
真实年报的三大报表是**规则的行**，不是规则的网格——合并/母公司并列、
表头分两行、标签跨行、负号用括号、附注列夹在中间。pdfplumber 的表格线检测
在这些页面上会把相邻列合并或错位。

做法：
1. 用 pdfium 快速定位（211 页只要 0.6s），只把报表那几页交给 pdfplumber；
2. 按 y 坐标聚行，按 x 坐标把数字归到「年份 + 合并/母公司」列；
3. 每个数字保留自身的 bbox，前端能精确框到那个单元格；
4. 抽不到就记缺口，**绝不猜**。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from ..domain.fields import FIELDS, match_field
from ..domain.keys import FactKey
from .extract import ParseResult, PageInfo, parse_number, precision_step

VERSION = "pdf-lines/2.0.0"

YEAR_RE = re.compile(r"(20\d{2})\s*年(?:\s*12\s*月\s*31\s*日|\s*度)?")
UNIT_RE = re.compile(r"人民币\s*(百万元|千元|万元|亿元|元)|单位[:：]\s*(?:人民币)?\s*(百万元|千元|万元|亿元|元)")
NOTE_RE = re.compile(r"^[\(（][一二三四五六七八九十百]+[\)）]\s*\d*$|^\d+$")
NUM_TOKEN_RE = re.compile(r"^[\(（]?[-－]?[\d,]+(?:\.\d+)?[\)）]?$")

UNIT_SCALE = {
    "元": Decimal(1), "千元": Decimal(1000), "万元": Decimal(10000),
    "百万元": Decimal(1000000), "亿元": Decimal(100000000),
}

#: 定位标记：任一命中即视为该类报表的候选页（资产负债表常常跨两页，不能要求同一页齐全）
STATEMENT_MARK = {
    "balance_sheet": ("资产总计", "负债和股东权益总计", "负债和所有者权益"),
    "income_statement": ("营业成本", "营业总收入"),
    "cash_flow": ("经营活动产生的现金流量", "经营活动现金流入小计", "销售商品、提供劳务收到的现金"),
}
STATEMENT_FIELDS = {
    "balance_sheet": ("total_assets", "total_liabilities", "total_equity", "liab_equity_total",
                      "inventories", "receivables"),
    "income_statement": ("revenue", "operating_cost", "net_profit_total", "net_profit_parent",
                         "minority_interest"),
    "cash_flow": ("operating_cashflow",),
}

TITLE_RE = {
    "balance_sheet": re.compile(r"合并(?:及公司)?资产负债表|^资产负债表$"),
    "income_statement": re.compile(r"合并(?:及公司)?利润表|^利润表$"),
    "cash_flow": re.compile(r"合并(?:及公司)?现金流量表|^现金流量表$"),
}

PREFIX_RE = re.compile(
    r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[）)]|\d+[、.．]"
    r"|减[:：]|加[:：]|其中[:：]|其他[:：])+")
#: 行名里夹带的附注编号，如「存货(五)6,(十七)3」；不剥掉会导致整行匹配失败
INLINE_NOTE_RE = re.compile(r"[\(（][一二三四五六七八九十百]+[\)）][\d,，、]*")


@dataclass
class Col:
    x: float
    period_start: str
    period_end: str
    period_kind: str
    consolidation: str


@dataclass
class Line:
    top: float
    words: list[dict[str, Any]]
    page: int
    label: str = ""
    numbers: list[tuple[dict[str, Any], Decimal, int]] = field(default_factory=list)


def clean_label(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").replace(" ", "")
    t = INLINE_NOTE_RE.sub("", t)
    t = PREFIX_RE.sub("", t)
    return t.strip("　:：")


def _group_lines(words: list[dict[str, Any]], page_no: int, tol: float = 3.2) -> list[Line]:
    buckets: list[Line] = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        placed = False
        for b in buckets[-3:]:
            if abs(b.top - w["top"]) <= tol:
                b.words.append(w)
                placed = True
                break
        if not placed:
            buckets.append(Line(top=w["top"], words=[w], page=page_no))
    for b in buckets:
        b.words.sort(key=lambda w: w["x0"])
    return buckets


def _columns(lines: list[Line]) -> list[Col]:
    """从「年份行 + 合并/母公司行」构造列定义。"""
    for i, line in enumerate(lines):
        years = [(m.group(1), w) for w in line.words for m in [YEAR_RE.search(w["text"])] if m]
        if len(years) < 2:
            continue
        # 表头行必须带「项目/附注」或紧跟其后有合并/母公司，否则可能是正文里的年份描述
        head = "".join(w["text"] for w in line.words)
        if not ("项目" in head or "附注" in head or i >= 1 and any(
                "项目" in "".join(w["text"] for w in ln.words) for ln in lines[max(0, i - 1):i + 2])):
            continue
        scopes: list[tuple[str, float]] = []
        for follow in lines[i:i + 4]:
            for w in follow.words:
                t = w["text"].replace(" ", "")
                if t in ("合并", "母公司", "公司"):
                    scopes.append((t, (w["x0"] + w["x1"]) / 2))
            if len(scopes) >= len(years):
                break
        cols: list[Col] = []
        for year, w in years:
            center = (w["x0"] + w["x1"]) / 2
            scope = min(scopes, key=lambda s: abs(s[1] - center)) if scopes else ("合并", center)
            consolidation = "consolidated" if scope[0] == "合并" else "parent"
            y = int(year)
            kind = "POINT" if ("31" in w["text"] or "12月" in w["text"] or "1月1日" in w["text"]) else "FY"
            # 「2025年1月1日」是期初余额，等价于 2024-12-31，不能记成 2025 年末
            end = f"{y - 1}-12-31" if "1月1日" in w["text"] else f"{y}-12-31"
            cols.append(Col(x=center, period_start=f"{y}-01-01", period_end=end,
                            period_kind=kind, consolidation=consolidation))
        # 去掉重复列（同一位置反复出现年份）
        uniq: list[Col] = []
        for c in cols:
            if not any(abs(c.x - u.x) < 12 and c.period_end == u.period_end
                       and c.consolidation == u.consolidation for u in uniq):
                uniq.append(c)
        if len(uniq) >= 2:
            return uniq
    return []


def _unit_scale(text: str) -> tuple[str, Decimal]:
    m = UNIT_RE.search(text or "")
    if not m:
        return "元", Decimal(1)
    unit = m.group(1) or m.group(2)
    return unit, UNIT_SCALE.get(unit, Decimal(1))


def _alignment(cols: list[Col], words: list[dict[str, Any]]) -> str:
    """判断数字是左对齐还是右对齐。

    年报里两种都常见：左对齐时数字左边缘贴列头，右对齐时右边缘贴列头。
    用中位数比较两种假设的偏差，选更小的那个。
    """
    if not cols or not words:
        return "left"
    d_left, d_right = [], []
    for w in words[:80]:
        d_left.append(min(abs(w["x0"] - c.x) for c in cols))
        d_right.append(min(abs(w["x1"] - c.x) for c in cols))
    d_left.sort()
    d_right.sort()
    return "left" if d_left[len(d_left) // 2] <= d_right[len(d_right) // 2] else "right"


def _assign(cols: list[Col], word: dict[str, Any], bounds: list[tuple[float, float]] | None = None,
            align: str = "left") -> Col | None:
    """按「列左边界的中点」分段归列。

    不能只看数字中心：真实报表的数字常常右对齐，位数越多中心越偏左。
    用中点分界 + 数字左边界，对左对齐和右对齐都稳定。
    """
    edge = word["x0"] if align == "left" else word["x1"]
    best = min(cols, key=lambda c: abs(c.x - edge))
    # 容差取列间距的一半，避免把相邻列的数吸过来
    gaps = sorted(abs(a.x - b.x) for i, a in enumerate(cols) for b in cols[i + 1:])
    tol = (gaps[0] * 0.55) if gaps else 40
    return best if abs(best.x - edge) <= tol else None


def _bounds(cols: list[Col]) -> list[tuple[float, float]]:
    xs = sorted(c.x for c in cols)
    mids = [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)]
    edges = [xs[0] - (mids[0] - xs[0]), *mids, xs[-1] + (xs[-1] - mids[-1])]
    order = sorted(range(len(cols)), key=lambda i: cols[i].x)
    out = [None] * len(cols)
    for pos, idx in enumerate(order):
        out[idx] = (edges[pos], edges[pos + 1])
    return out  # type: ignore[return-value]


def _parse_page(page: Any, kind: str, info: PageInfo, cols: list[Col], unit_scale: Decimal,
                sha: str, entity_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    words = [w for w in page.extract_words(use_text_flow=False, keep_blank_chars=False)
             if w["text"].strip()]
    lines = _group_lines(words, info.page_index)
    if not cols:
        return facts, gaps

    first_col = min(c.x for c in cols)
    all_nums = [w for w in words if NUM_TOKEN_RE.match(w["text"]) and len(w["text"]) >= 3]
    align = _alignment(cols, all_nums)
    allowed = set(STATEMENT_FIELDS[kind])

    def label_of(idx: int) -> str:
        if not (0 <= idx < len(lines)):
            return ""
        ws = [w for w in lines[idx].words if w["x1"] <= first_col - 26]
        return clean_label("".join(w["text"] for w in ws))

    def row_label(idx: int) -> str:
        """数字行没有行名时，取上下最近的「纯标签行」。

        真实报表存在两种排版：行名在上（常见）、行名在下（部分券商模板）。
        只看向上会漏掉后者，只看向下会错位到下一行，所以按距离取最近。
        """
        base = label_of(idx)
        if base:
            return base
        best: tuple[float, str] | None = None
        for step in (-1, 1):
            j = idx + step
            if not (0 <= j < len(lines)) or lines[j].numbers:
                continue
            cand = label_of(j)
            if not cand or cand.endswith(("：", ":")):
                continue
            gap = abs(lines[j].top - lines[idx].top)
            if gap > 18:
                continue
            if cand.count("（") + cand.count("(") > cand.count("）") + cand.count(")"):
                cand += label_of(j + step)
            if best is None or gap < best[0]:
                best = (gap, cand)
        return best[1] if best else ""

    for idx, ln in enumerate(lines):
        raw_label_words = [w for w in ln.words if w["x1"] <= first_col - 26 and not NOTE_RE.match(w["text"])]
        num_words = [w for w in ln.words if NUM_TOKEN_RE.match(w["text"])
                     and not NOTE_RE.match(w["text"]) and len(w["text"]) >= 3]
        label = clean_label("".join(w["text"] for w in raw_label_words))
        if not num_words:
            continue
        if not label:
            label = row_label(idx)
        code = match_field(label) if label else None
        # 被拆断的行名（括号没闭合）在后面一行续上，例如「所有者权益（或股东权」+「益）合计」
        if not code and label and (label.count("（") + label.count("(")
                                   > label.count("）") + label.count(")")):
            joined = label + label_of(idx + 1)
            if match_field(joined):
                label, code = joined, match_field(joined)
        if not code or code not in allowed:
            continue
        spec = FIELDS[code]

        for word in num_words:
            col = _assign(cols, word, align=align)
            if col is None:
                continue
            value, decimals, note = parse_number(word["text"])
            if value is None:
                continue
            key = FactKey(entity_id=entity_id, field_code=code, period_start=col.period_start,
                          period_end=col.period_end, period_kind=col.period_kind,
                          consolidation=col.consolidation, currency="CNY",
                          business_scope="total", definition_id=spec.definition_id)
            scaled = value * unit_scale
            pw, ph = page.width, page.height
            bbox = (round(word["x0"] / pw, 5), round(word["top"] / ph, 5),
                    round(word["x1"] / pw, 5), round(word["bottom"] / ph, 5))
            facts.append({
                "fact_key": key.canonical(), "key": key, "key_parts": key.describe(),
                "entity_id": entity_id, "field_code": code, "raw_value": word["text"],
                "value_text": str(scaled), "raw_unit": info.unit,
                "unit_scale": str(unit_scale), "currency": "CNY",
                "precision_step": str(precision_step(unit_scale, decimals)),
                "extraction_method": "line_anchor",
                "audit_scope": "primary_table" if col.consolidation == "consolidated" else "parent_table",
                "basis_tag": "original", "extract_status": "OK",
                "confidence_hint": "HIGH", "period_end": col.period_end,
                "consolidation": col.consolidation, "page_index": info.page_index,
                "cell_id": f"L{int(ln.top)}C{int(word['x0'])}",
                "row_label": label, "col_label": f"{col.period_end}·{col.consolidation}",
                "table_id": f"p{info.page_index}", "table_type": kind, "bbox": bbox,
                "excerpt": f"{label} · {word['text']}（单位：{info.unit}）",
                "document_sha256": sha,
                "heading_path": f"第{info.page_index}页 / {kind} / {col.consolidation}",
            })
    return facts, gaps


def _runs(pages: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for p in sorted(pages):
        if out and p - out[-1][-1] <= 1:
            out[-1].append(p)
        else:
            out.append([p])
    return out


def locate(pdf: pdfium.PdfDocument) -> tuple[dict[int, str], list[dict[str, Any]]]:
    """定位报表页，并按「连续页段」择优。

    真实年报里同一个标签会出现在管理层讨论、附注、母公司报表里。
    只取**命中核心字段最多、且连续**的那一段，其余整段丢弃并留痕，
    避免把附注里的明细当成主表。
    """
    texts: dict[int, str] = {}
    hits: dict[str, list[int]] = {}
    for i in range(len(pdf)):
        text = pdf[i].get_textpage().get_text_range()
        texts[i + 1] = text
        if not YEAR_RE.search(text):
            continue
        if not ("项目" in text or "附注" in text):
            continue
        for kind, marks in STATEMENT_MARK.items():
            if any(m in text for m in marks):
                hits.setdefault(kind, []).append(i + 1)
                break

    chosen: dict[int, str] = {}
    notes: list[dict[str, Any]] = []

    # 先给每一类算分；再用「资产负债表」定位报表区（三大表总是连着放），
    # 落在报表区之外的候选一律视为附注/管理层讨论，不参与。
    scored_all: dict[str, list[tuple[int, list[int]]]] = {}
    for kind, pages in hits.items():
        rows: list[tuple[int, list[int]]] = []
        for run in _runs(pages):
            blob = "".join(texts[p] for p in run)
            hit_n = sum(1 for code in STATEMENT_FIELDS[kind]
                        if any(alias in blob for alias in FIELDS[code].aliases))
            dense = sum(1 for tok in re.findall(r"\d[\d,]{6,}", blob))
            rows.append((hit_n * 10 + min(dense, 80), run))
        scored_all[kind] = rows

    anchor_pool = scored_all.get("balance_sheet") or [r for rows in scored_all.values() for r in rows]
    anchor = max(anchor_pool, key=lambda x: (x[0], -x[1][0]))[1] if anchor_pool else []
    lo, hi = (anchor[0] - 8, anchor[-1] + 16) if anchor else (0, len(pdf))

    for kind, rows in scored_all.items():
        inside = [(sc, run) for sc, run in rows if lo <= run[0] <= hi]
        outside = [(sc, run) for sc, run in rows if not (lo <= run[0] <= hi)]
        if outside:
            dropped = [p for _s, run in outside for p in run]
            notes.append({"type": "PAGE_RUN_IGNORED", "kind": kind,
                          "detail": f"{kind} 有 {len(dropped)} 页命中标签但不在报表区，"
                                    f"判为附注/摘要未抽取", "pages": dropped[:20]})
        if not inside:
            continue
        top = max(sc for sc, _ in inside)
        qualified = [run for sc, run in inside if sc >= top * 0.6]
        best_run = min(qualified, key=lambda r: r[0])
        for p in best_run:
            chosen[p] = kind
    return chosen, notes


def expand_blocks(pdf: pdfium.PdfDocument, hits: dict[int, str],
                  span: int = 4) -> dict[int, str]:
    """把命中页扩展成「报表区块」。

    真实年报里同一张报表常跨 2-4 页：首页有表头，续页只有行和数。
    做法是向两侧扩展，遇到另一张报表的标题或空页就停，保证不会把附注卷进来。
    """
    texts = {i + 1: pdf[i].get_textpage().get_text_range() for i in range(len(pdf))}
    chosen = dict(hits)
    for pno, kind in list(hits.items()):
        for direction in (-1, 1):
            cur = pno
            for _ in range(span):
                nxt = cur + direction
                if nxt < 1 or nxt > len(texts) or nxt in chosen:
                    break
                text = texts[nxt]
                if not text.strip():
                    break
                # 撞到别的报表标题 → 停
                if any(TITLE_RE[k].search(text) and k != kind for k in TITLE_RE):
                    break
                if "财务报表附注" in text[:120] or "审计报告" in text[:80]:
                    break
                chosen[nxt] = kind
                cur = nxt
    return chosen


def analyze_real(path: str | Path, entity_id: str, *, basis_tag: str = "original") -> ParseResult:
    path = Path(path)
    import hashlib
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    pdf = pdfium.PdfDocument(str(path))
    page_count = len(pdf)
    hits, notes = locate(pdf)

    facts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = list(notes)
    pages: list[PageInfo] = []
    carry: dict[str, list[Col]] = {}

    blocks = expand_blocks(pdf, hits)
    with pdfplumber.open(str(path)) as doc:
        for pno, kind in sorted(blocks.items()):
            page = doc.pages[pno - 1]
            text = page.extract_text() or ""
            unit, scale = _unit_scale(text)
            is_parent = bool(re.search(r"母公司(资产负债表|利润表|现金流量表)", text[:400]))
            info = PageInfo(page_index=pno, kind=kind,
                            consolidation="parent" if is_parent else "consolidated", unit=unit,
                            has_text=bool(text.strip()), text_head=text.replace("\n", " ")[:400])
            words = [w for w in page.extract_words(use_text_flow=False) if w["text"].strip()]
            header_cols = _columns(_group_lines(words, pno))
            if header_cols:
                carry[kind] = header_cols
            cols = carry.get(kind, [])
            if not cols:
                gaps.append({"page": pno, "type": "HEADER_UNRESOLVED",
                             "detail": f"{kind} 页未识别出「年份 + 合并/母公司」表头，未抽取"})
                pages.append(info)
                continue
            f, g = _parse_page(page, kind, info, cols, scale, sha, entity_id)
            facts.extend(f)
            gaps.extend(g)
            pages.append(info)

    # 同一份年报里同一个键只留**最先出现**的那条。
    # 报表顺序是「合并 → 母公司 → 附注」，先出现的才是主表；
    # 否则母公司数或附注明细会以同一键覆盖主表数。
    facts.sort(key=lambda f: (f["page_index"], f["bbox"][1] if f["bbox"] else 0))
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for f in facts:
        if f["fact_key"] in seen:
            continue
        seen.add(f["fact_key"])
        uniq.append(f)

    for kind in STATEMENT_FIELDS:
        if not any(p.kind == kind for p in pages):
            gaps.append({"page": 0, "type": "STATEMENT_NOT_FOUND",
                         "detail": f"全文未定位到 {kind} 报表页"})
    return ParseResult(pages=pages, facts=uniq, gaps=gaps, ambiguous=[], sha256=sha,
                       page_count=page_count)
