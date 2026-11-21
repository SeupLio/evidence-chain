"""生成一份**演练用**更正公告，并登记为一个受控候选文档。

为什么需要它：
真实语料里没有正好覆盖 600600 / 2025 / operating_cost 的正式更正公告，
而「补证 → 增量预览 → 只改命中章节」是赛题要求的能力。这里构造一份
明确标注「非真实披露」的一页 PDF，只用于演示流程；它不会伪装成巨潮原件。

用法：
    python -m app.scripts.add_demo_correction
幂等：重复执行会复用同一 document_id，不重复写事实。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..domain.keys import FactKey, content_id, fact_version_id
from ..storage import repo
from ..storage.db import init_db, utcnow

OUT = Path(__file__).resolve().parents[3] / "data" / "filings" / "600600_2025_correction_demo.pdf"
ENTITY = "SH:600600"
TITLE = "关于 2025 年年度报告营业成本更正的公告（演练材料 · 非真实披露）"
BEFORE = "18885149805.00"
AFTER = "18735149805.00"
PUBLISHED = "2026-06-18"


def build_pdf() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    doc = SimpleDocTemplate(str(OUT), pagesize=A4,
                            leftMargin=54, rightMargin=54, topMargin=64, bottomMargin=64,
                            title=TITLE, author="Evidence Chain Demo")
    h = ParagraphStyle("h", fontName="STSong-Light", fontSize=17, leading=26, spaceAfter=12,
                       alignment=1)
    b = ParagraphStyle("b", fontName="STSong-Light", fontSize=10.5, leading=20, spaceAfter=9)
    small = ParagraphStyle("s", fontName="STSong-Light", fontSize=8.5, leading=15, textColor="#666666")
    story = [
        Paragraph("青岛啤酒股份有限公司", h),
        Paragraph("关于 2025 年年度报告营业成本更正的公告", h),
        Paragraph("<b>（黑客松演练材料 · 非真实披露）</b>", ParagraphStyle(
            "w", parent=b, alignment=1, textColor="#b00020")),
        Spacer(1, 14),
        Paragraph("本公司于 2026 年 3 月 26 日披露《2025 年年度报告》。经复核，"
                  "合并利润表「营业成本」本期发生额应作如下更正：", b),
        Spacer(1, 6),
        Table(
            [["项目", "更正前（元）", "更正后（元）"],
             ["营业成本", "18,885,149,805.00", "18,735,149,805.00"]],
            colWidths=[150, 160, 160],
            style=TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, "#999999"),
                ("BACKGROUND", (0, 0), (-1, 0), "#eeeeee"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        Spacer(1, 12),
        Paragraph("本次更正仅影响营业成本及毛利相关指标，不改变营业收入、净利润与经营现金流。"
                  "更正后的数据以本公告为准。", b),
        Spacer(1, 16),
        Paragraph("说明：本文件由参赛项目构造，仅用于演示「更正公告 → 增量预览 → 版本提交」流程，"
                  "不对应任何真实公告，也不构成对上市公司的陈述。", small),
        Spacer(1, 8),
        Paragraph("青岛啤酒股份有限公司董事会　2026 年 6 月 18 日", small),
    ]
    doc.build(story)


def main() -> None:
    init_db()
    build_pdf()
    sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
    doc_id = content_id("doc", {"lk": f"{ENTITY}:correction:2025:demo", "sha": sha})
    repo.upsert_document({
        "document_id": doc_id,
        "logical_doc_key": f"{ENTITY}:correction:2025:demo",
        "sha256": sha,
        "canonical_url": None,
        "title": TITLE,
        "issuer": ENTITY,
        "source_type": "correction",
        "published_on": PUBLISHED,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "content_type": "application/pdf",
        "page_count": 1,
        "local_path": str(OUT),
        "parser_version": "demo/manual-1.0",
        "tier": "demo",
        "demo_role": "correction_demo",
        "dataset_tag": "demo_controlled",
    })

    key = FactKey(ENTITY, "operating_cost", "2025-01-01", "2025-12-31", "FY",
                  "consolidated", "CNY", "total", "cas_income_statement_cost_v1")
    cells = [
        ("before", BEFORE, "original", "r1c2", "更正前", [0.17, 0.40, 0.50, 0.445]),
        ("after", AFTER, "restated", "r1c3", "更正后", [0.53, 0.40, 0.86, 0.445]),
    ]
    for tag, value, basis, cell, col, bbox in cells:
        loc_id = content_id("loc", {"d": doc_id, "p": 1, "c": cell, "t": "demo_correction_t1"})
        repo.upsert_location({
            "location_id": loc_id, "document_id": doc_id, "kind": "pdf_cell", "page_index": 1,
            "printed_label": "1", "cell_id": cell, "row_label": "营业成本", "col_label": col,
            "table_id": "demo_correction_t1", "table_type": "income_statement", "bbox": bbox,
            "heading_path": "更正公告 / 营业成本更正表", "block_index": 0,
            "excerpt": f"营业成本｜{col}｜{value}", "extractor_version": "demo/manual-1.0",
        })
        fid = fact_version_id(key, doc_id, sha, loc_id, value, basis)
        repo.insert_fact({
            "fact_id": fid, "fact_key": key.canonical(), "key_parts": key.describe(),
            "entity_id": ENTITY, "field_code": "operating_cost", "location_id": loc_id,
            "document_id": doc_id, "raw_value": value, "value_text": str(Decimal(value)),
            "raw_unit": "元", "unit_scale": "1", "currency": "CNY", "precision_step": "0.01",
            "extraction_method": "manual_demo", "audit_scope": "primary_table",
            "basis_tag": basis, "lineage_group": "demo_correction", "extract_status": "OK",
            "confidence_hint": "演练材料", "period_end": "2025-12-31",
            "consolidation": "consolidated", "created_at": utcnow(),
        })
    print(f"document_id={doc_id}")
    print(f"title={TITLE}")
    print(f"published_on={PUBLISHED} dataset_tag=demo_controlled")
    print("下一步：在「版本与补证」选择这份更正公告，生成增量预览。")


if __name__ == "__main__":
    main()
