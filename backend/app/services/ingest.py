"""入库：文档登记、快照、单元格与事实落库。

事实一经写入不再修改；同一文档重复入库按 (logical_doc_key, sha256) 去重，
内容变了就是新 document_id —— 这是“同公告镜像重新入库不产生新版本”的基础。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber

from ..domain.keys import FactKey, content_id, fact_version_id
from ..storage import repo
from ..storage.db import utcnow
from .extract import EXTRACTOR_VERSION, ParseResult, analyze, parse_number

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CORPUS = FIXTURES / "corpus"


def seed_entities() -> None:
    for ent in (
        {"entity_id": "SH:600600", "name": "青岛啤酒", "exchange": "SH", "ticker": "600600",
         "industry_id": "beer_cn_a", "role": "subject"},
        {"entity_id": "SH:600132", "name": "重庆啤酒", "exchange": "SH", "ticker": "600132",
         "industry_id": "beer_cn_a", "role": "peer"},
        {"entity_id": "SZ:002461", "name": "珠江啤酒", "exchange": "SZ", "ticker": "002461",
         "industry_id": "beer_cn_a", "role": "peer"},
    ):
        repo.upsert_entity(ent)
    for alias, eid in (("青岛啤酒", "SH:600600"), ("600600", "SH:600600"), ("青啤", "SH:600600"),
                       ("重庆啤酒", "SH:600132"), ("600132", "SH:600132"),
                       ("珠江啤酒", "SZ:002461"), ("002461", "SZ:002461")):
        repo.upsert_alias(alias, eid)


def manifest() -> list[dict[str, Any]]:
    data = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return data["documents"]


def register(entry: dict[str, Any], sha256: str) -> dict[str, Any]:
    logical = f"{entry.get('issuer') or 'industry'}:{entry['doc_type']}:{entry.get('fiscal_year') or entry.get('published_on')}"
    document_id = content_id("doc", {"lk": logical, "sha": sha256})
    path = CORPUS / entry["file"]
    doc = {
        "document_id": document_id,
        "logical_doc_key": logical,
        "sha256": sha256,
        "canonical_url": None,
        "title": entry["title"],
        "issuer": entry.get("issuer") or "industry",
        "source_type": entry["doc_type"],
        "published_on": entry.get("published_on"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period_start": f"{entry['fiscal_year']}-01-01" if entry.get("fiscal_year") else None,
        "period_end": f"{entry['fiscal_year']}-12-31" if entry.get("fiscal_year") else None,
        "content_type": "application/pdf",
        "page_count": 0,
        "local_path": str(path),
        "parser_version": EXTRACTOR_VERSION,
        "tier": entry.get("tier", "primary"),
        "demo_role": entry.get("demo_role"),
        # 合成语料只用于抽取器回归；跨源互证只读 real_cninfo。
        "dataset_tag": "synthetic_regression",
    }
    return doc


def ingest_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path = CORPUS / entry["file"]
    if not path.exists():
        return {"status": "missing_file", "file": entry["file"]}
    from ..services.extract import analyze as _analyze
    import hashlib

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = register(entry, sha)
    repo.upsert_document({**doc, "page_count": 0})

    doc_type = entry["doc_type"]
    if doc_type in ("annual_report", "correction") and entry.get("entity_id"):
        basis = "restated" if doc_type == "correction" else "original"
        parsed: ParseResult = analyze(path, entry["entity_id"], int(entry["fiscal_year"]),
                                      basis_tag=basis, doc_kind=doc_type)
        repo.get_conn().execute("UPDATE documents SET page_count=? WHERE document_id=?",
                                (parsed.page_count, doc["document_id"]))
        _store_page_locations(doc, parsed)
        n_facts = _store_facts(doc, parsed)
        _store_gaps(doc, parsed)
        return {"status": "ok", "document_id": doc["document_id"], "facts": n_facts,
                "pages": parsed.page_count, "gaps": parsed.gaps, "file": entry["file"]}
    if doc_type == "industry_stats":
        return _ingest_industry(doc, path)
    # 政策/观察类：登记文档与逐页定位，不产出数值事实
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        heads = [(i + 1, (p.extract_text() or "").replace("\n", " ")[:400]) for i, p in enumerate(pdf.pages)]
    repo.get_conn().execute("UPDATE documents SET page_count=? WHERE document_id=?", (pages, doc["document_id"]))
    for p_idx, head in heads:
        loc_id = content_id("loc", {"d": doc["document_id"], "p": p_idx, "k": "pdf_page"})
        repo.upsert_location({
            "location_id": loc_id, "document_id": doc["document_id"], "kind": "pdf_page", "page_index": p_idx,
            "printed_label": str(p_idx), "cell_id": None, "row_label": doc_type, "col_label": None,
            "table_id": None, "table_type": doc_type, "bbox": None, "heading_path": doc_type,
            "block_index": 0, "excerpt": head, "extractor_version": EXTRACTOR_VERSION,
        })
    return {"status": "ok", "document_id": doc["document_id"], "facts": 0, "pages": pages, "file": entry["file"]}


def _store_gaps(doc: dict[str, Any], parsed: ParseResult) -> None:
    """解析缺口落成 issue，进入数据质量章节与依赖图。"""
    for gap in parsed.gaps:
        kind = "SCANNED_UNSUPPORTED" if gap["type"] == "SCANNED_UNSUPPORTED" else "COVERAGE_GAP"
        severity = "WATCH" if kind == "SCANNED_UNSUPPORTED" else "INFO"
        repo.upsert_issue({
            "issue_id": content_id("issue", {"t": kind, "d": doc["document_id"], "p": gap.get("page"),
                                             "f": gap.get("field"), "y": gap.get("year")}),
            "type": kind, "severity": severity,
            "key": f"gap:{doc['document_id']}:{gap.get('page')}:{gap.get('field') or gap['type']}",
            "candidate_ids": [], "status": "OPEN",
            "context": {"document_id": doc["document_id"], "doc_title": doc["title"],
                        "page": gap.get("page"), "field": gap.get("field"), "year": gap.get("year"),
                        "detail": gap.get("detail"), "explanation": gap.get("detail", "")},
        })


def _store_page_locations(doc: dict[str, Any], parsed: ParseResult) -> None:
    """每页建一条 pdf_page 定位，供叙述性引用（产业链边、政策条款）挂靠。"""
    for page in parsed.pages:
        if not page.has_text:
            continue
        loc_id = content_id("loc", {"d": doc["document_id"], "p": page.page_index, "k": "pdf_page"})
        repo.upsert_location({
            "location_id": loc_id, "document_id": doc["document_id"], "kind": "pdf_page",
            "page_index": page.page_index, "printed_label": str(page.page_index),
            "cell_id": None, "row_label": page.kind, "col_label": None,
            "table_id": None, "table_type": page.kind, "bbox": None,
            "heading_path": f"第{page.page_index}页", "block_index": 0,
            "excerpt": page.text_head, "extractor_version": EXTRACTOR_VERSION,
        })


def _store_facts(doc: dict[str, Any], parsed: ParseResult) -> int:
    conn = repo.get_conn()
    n = 0
    for f in parsed.facts:
        key: FactKey = f["key"]
        loc_id = content_id("loc", {"d": doc["document_id"], "p": f["page_index"],
                                    "c": f["cell_id"], "t": f["table_id"]})
        repo.upsert_location({
            "location_id": loc_id, "document_id": doc["document_id"], "kind": "pdf_cell",
            "page_index": f["page_index"], "printed_label": str(f["page_index"]),
            "cell_id": f["cell_id"], "row_label": f["row_label"], "col_label": f["col_label"],
            "table_id": f["table_id"], "table_type": f["table_type"],
            "bbox": list(f["bbox"]) if f["bbox"] else None,
            "heading_path": f["heading_path"], "block_index": 0, "excerpt": f["excerpt"],
            "extractor_version": EXTRACTOR_VERSION,
        })
        fid = fact_version_id(key, doc["document_id"], doc["sha256"], loc_id, f["raw_value"], f["basis_tag"])
        inserted = repo.insert_fact({
            "fact_id": fid, "fact_key": f["fact_key"], "key_parts": f["key_parts"],
            "entity_id": f["entity_id"], "field_code": f["field_code"], "location_id": loc_id,
            "document_id": doc["document_id"], "raw_value": f["raw_value"], "value_text": f["value_text"],
            "raw_unit": f["raw_unit"], "unit_scale": f["unit_scale"], "currency": f["currency"],
            "precision_step": f["precision_step"], "extraction_method": f["extraction_method"],
            "audit_scope": f["audit_scope"], "basis_tag": f["basis_tag"], "lineage_group": "",
            "extract_status": f["extract_status"], "confidence_hint": f["confidence_hint"],
            "period_end": f["period_end"], "consolidation": f["consolidation"], "created_at": utcnow(),
        })
        n += 1 if inserted else 0
    return n


def _ingest_industry(doc: dict[str, Any], path: Path) -> dict[str, Any]:
    labels = {"啤酒产量": ("beer_output", "万千升"), "规模以上啤酒企业营业收入": ("beer_revenue_above_scale", "亿元")}
    rows_out = 0
    with pdfplumber.open(path) as pdf:
        pages = len(pdf.pages)
        for p_idx, page in enumerate(pdf.pages, start=1):
            head = (page.extract_text() or "").replace("\n", " ")[:400]
            repo.upsert_location({
                "location_id": content_id("loc", {"d": doc["document_id"], "p": p_idx, "k": "pdf_page"}),
                "document_id": doc["document_id"], "kind": "pdf_page", "page_index": p_idx,
                "printed_label": str(p_idx), "cell_id": None, "row_label": "industry_stats",
                "col_label": None, "table_id": None, "table_type": "industry_stats", "bbox": None,
                "heading_path": f"第{p_idx}页", "block_index": 0, "excerpt": head,
                "extractor_version": EXTRACTOR_VERSION,
            })
            for table in page.find_tables():
                data = table.extract()
                if not data or len(data) < 2:
                    continue
                header = [str(c or "").replace(" ", "") for c in data[0]]
                years: list[tuple[int, int]] = []
                for c_i, cell in enumerate(header):
                    m = __import__("re").search(r"(20\d{2})", cell)
                    if m:
                        years.append((c_i, int(m.group(1))))
                unit = "万千升" if "万千升" in (page.extract_text() or "")[:400] else "亿元"
                for r_i, row in enumerate(data[1:], start=1):
                    label = str(row[0] or "").replace(" ", "")
                    if label not in labels:
                        continue
                    code, unit = labels[label]
                    for c_i, year in years:
                        if c_i >= len(row):
                            continue
                        val, dec, note = parse_number(row[c_i])
                        if val is None:
                            continue
                        loc_id = content_id("loc", {"d": doc["document_id"], "p": p_idx, "c": f"r{r_i}c{c_i}"})
                        cell = table.rows[r_i].cells[c_i] if table.rows[r_i].cells else None
                        bbox = None
                        if cell:
                            bbox = [round(cell[0] / page.width, 5), round(cell[1] / page.height, 5),
                                    round(cell[2] / page.width, 5), round(cell[3] / page.height, 5)]
                        repo.upsert_location({
                            "location_id": loc_id, "document_id": doc["document_id"], "kind": "pdf_cell",
                            "page_index": p_idx, "printed_label": str(p_idx), "cell_id": f"r{r_i}c{c_i}",
                            "row_label": label, "col_label": f"{year}年", "table_id": f"p{p_idx}t1",
                            "table_type": "industry_stats", "bbox": bbox,
                            "heading_path": f"第{p_idx}页 / 行业统计", "block_index": 0,
                            "excerpt": f"{label} {row[c_i]}（{unit}）", "extractor_version": EXTRACTOR_VERSION,
                        })
                        repo.upsert_industry_fact({
                            "industry_fact_id": content_id("ind", {"e": "beer_cn_a", "c": code, "y": year,
                                                                   "d": doc["document_id"], "p": p_idx}),
                            "industry_id": "beer_cn_a", "code": code, "label": label,
                            "value_text": str(val), "unit": unit, "geography": "全国",
                            "period": str(year), "stat_scope": "规模以上啤酒制造企业",
                            "definition": "国家统计局工业统计快报口径",
                            "source_location": loc_id, "document_id": doc["document_id"],
                            "confidence": "HIGH", "created_at": utcnow(),
                        })
                        rows_out += 1
    repo.get_conn().execute("UPDATE documents SET page_count=? WHERE document_id=?", (pages, doc["document_id"]))
    return {"status": "ok", "document_id": doc["document_id"], "facts": rows_out, "pages": pages,
            "file": entry_file_name(path)}


def entry_file_name(path: Path) -> str:
    return path.name


def seed_corpus(force: bool = False) -> dict[str, Any]:
    """载入合成回归语料。

    合成语料与真实公开数据**不共用同一个库**：一旦检测到 real_cninfo 文档，
    直接拒绝并提示改用独立 DATA_DIR，避免跨源互证被污染。
    """
    from ..storage.db import db_path

    real_n = repo.get_conn().execute(
        "SELECT COUNT(*) FROM documents WHERE dataset_tag='real_cninfo'"
    ).fetchone()[0]
    if real_n:
        return {"documents": 0, "ok": 0, "details": [],
                "error": "DATASET_CONFLICT",
                "message": (f"当前库含 {real_n} 份真实公开年报（dataset_tag=real_cninfo），"
                            "不能再混入合成回归语料。请用独立目录运行："
                            "$env:DATA_DIR='data/regression'; python -m app.cli seed --pack beer-demo"),
                "db": str(db_path())}
    seed_entities()
    results = []
    for entry in manifest():
        results.append(ingest_entry(entry))
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"documents": len(results), "ok": ok, "details": results,
            "dataset_tag": "synthetic_regression", "db": str(db_path())}
