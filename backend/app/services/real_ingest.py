"""真实年报入库：把行锚定抽取的结果写成 location + fact。

与合成语料入库共用同一套 FactKey 规则，因此下游（核验、指标、报告）
不需要区分数据来自真实年报还是模板语料。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.keys import content_id, fact_version_id
from ..storage import repo
from ..storage.db import utcnow
from . import pdf_lines
from .extract import ParseResult


def _store_page_locations(doc: dict[str, Any], parsed: ParseResult) -> None:
    for info in parsed.pages:
        repo.upsert_location({
            "location_id": content_id("loc", {"d": doc["document_id"], "p": info.page_index, "k": "pdf_page"}),
            "document_id": doc["document_id"], "kind": "pdf_page", "page_index": info.page_index,
            "printed_label": str(info.page_index), "cell_id": None, "row_label": info.kind,
            "col_label": None, "table_id": None, "table_type": info.kind, "bbox": None,
            "heading_path": f"第{info.page_index}页 / {info.kind}", "block_index": 0,
            "excerpt": info.text_head, "extractor_version": pdf_lines.VERSION,
        })


def store_facts(doc: dict[str, Any], parsed: ParseResult) -> int:
    n = 0
    for f in parsed.facts:
        key = f["key"]
        loc_id = content_id("loc", {"d": doc["document_id"], "p": f["page_index"],
                                    "c": f["cell_id"], "t": f["table_id"]})
        repo.upsert_location({
            "location_id": loc_id, "document_id": doc["document_id"], "kind": "pdf_cell",
            "page_index": f["page_index"], "printed_label": str(f["page_index"]),
            "cell_id": f["cell_id"], "row_label": f["row_label"], "col_label": f["col_label"],
            "table_id": f["table_id"], "table_type": f["table_type"],
            "bbox": list(f["bbox"]) if f["bbox"] else None,
            "heading_path": f["heading_path"], "block_index": 0, "excerpt": f["excerpt"],
            "extractor_version": pdf_lines.VERSION,
        })
        fid = fact_version_id(key, doc["document_id"], doc["sha256"], loc_id,
                              f["raw_value"], f["basis_tag"])
        inserted = repo.insert_fact({
            "fact_id": fid, "fact_key": f["fact_key"], "key_parts": f["key_parts"],
            "entity_id": f["entity_id"], "field_code": f["field_code"], "location_id": loc_id,
            "document_id": doc["document_id"], "raw_value": f["raw_value"],
            "value_text": f["value_text"], "raw_unit": f["raw_unit"],
            "unit_scale": f["unit_scale"], "currency": f["currency"],
            "precision_step": f["precision_step"], "extraction_method": f["extraction_method"],
            "audit_scope": f["audit_scope"], "basis_tag": f["basis_tag"], "lineage_group": "",
            "extract_status": f["extract_status"], "confidence_hint": f["confidence_hint"],
            "period_end": f["period_end"], "consolidation": f["consolidation"],
            "created_at": utcnow(),
        })
        n += 1 if inserted else 0
    return n


def ingest_filing(doc: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """解析并入库一份年报；已解析过（同 sha + 同版本）直接跳过。"""
    path = Path(doc["local_path"])
    if not path.exists():
        return {"document_id": doc["document_id"], "status": "MISSING_FILE", "facts": 0}

    existing = repo.get_conn().execute(
        "SELECT COUNT(*) FROM facts WHERE document_id=?", (doc["document_id"],)).fetchone()[0]
    if existing and not force:
        return {"document_id": doc["document_id"], "status": "ok", "facts": existing,
                "pages": doc["page_count"], "skipped": True}

    parsed = pdf_lines.analyze_real(path, doc["issuer"], basis_tag=doc.get("basis_tag") or "original")
    _store_page_locations(doc, parsed)
    n = store_facts(doc, parsed)
    repo.get_conn().execute(
        "UPDATE documents SET page_count=?, parser_version=? WHERE document_id=?",
        (parsed.page_count, pdf_lines.VERSION, doc["document_id"]))
    return {"document_id": doc["document_id"], "status": "ok", "facts": n,
            "pages": parsed.page_count, "found": len(parsed.pages), "gaps": parsed.gaps[:6],
            "title": doc["title"], "sha256": doc["sha256"][:12]}


def ingest_all(*, force: bool = False, codes: list[str] | None = None,
               years: list[int] | None = None, log=print) -> dict[str, Any]:
    docs = [d for d in repo.documents_visible() if d["source_type"] == "annual_report"
            and (not codes or any(c in d["issuer"] for c in codes))
            and (not years or int((d["period_end"] or "0000")[:4]) in set(years))]
    out = {"documents": len(docs), "facts": 0, "empty": [], "details": []}
    for d in sorted(docs, key=lambda x: (x["issuer"], x["period_end"])):
        r = ingest_filing(d, force=force)
        out["facts"] += r.get("facts", 0)
        if not r.get("facts"):
            out["empty"].append(r)
        out["details"].append(r)
        log(f"  {r.get('title','?')[:34]:<36} facts={r.get('facts',0):<4} p{r.get('pages',0)} {r['status']}")
    return out
