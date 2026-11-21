"""跨源互证：把「年报原件抽出来的数」和「第三方结构化数据的数」对撞。

为什么不是自评：
- 输入是巨潮的法定披露 PDF，抽取器只看 PDF；
- 参照值是另一家机构（东方财富）按自己的口径录入的结构化数据；
- 两边独立出错才会造成「假一致」，这比自建金标高一个量级的可信度。

比对规则（写死，不允许按结果调参）：
- 相差 0 → exact
- 相差 ≤1 元 → rounding（对方以元为单位四舍五入）
- 比值接近 1000 / 10000 → unit（单位换算错，属真实缺陷，单独计数）
- 其余 → mismatch
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..services import market
from ..storage import repo

D = Decimal

FIELDS = ("revenue", "operating_cost", "net_profit_parent", "total_assets",
          "total_liabilities", "total_equity", "operating_cashflow", "inventories", "receivables")

FIELD_LABEL = {k: v[2] for k, v in market.MARKET_FIELDS.items()}


def pdf_facts(entity_id: str, field_code: str, year: int) -> list[dict[str, Any]]:
    """取该 (公司, 字段, 年) 在**真实年报**里的合并口径事实。

    只读 dataset_tag='real_cninfo'：合成回归语料即使同库存在也不进入比对池。
    """
    cur = repo.get_conn().execute(
        """SELECT f.fact_id, f.value_text, f.raw_unit, f.audit_scope, l.page_index,
                  f.document_id, d.title, d.published_on, f.location_id,
                  l.cell_id, l.bbox, l.excerpt, l.row_label, l.col_label,
                  l.heading_path, l.table_type
             FROM facts f
             JOIN documents d ON d.document_id = f.document_id
             LEFT JOIN source_locations l ON l.location_id = f.location_id
            WHERE f.entity_id=? AND f.field_code=? AND f.consolidation='consolidated'
              AND substr(f.period_end,1,4)=? AND f.extract_status='OK'
              AND d.dataset_tag='real_cninfo'
            ORDER BY d.published_on DESC""",
        (entity_id, field_code, str(year)),
    )
    return [dict(r) for r in cur]


def _classify(pdf: Decimal, ref: Decimal) -> str:
    diff = pdf - ref
    if diff == 0:
        return "exact"
    if abs(diff) <= 1:
        return "rounding"
    for k in (1000, 10000, 1000000, 100000000):
        if ref and abs(abs(pdf / ref) - k) < D("0.001"):
            return "unit"
    if abs(diff) / max(abs(ref), D(1)) <= D("0.00002"):
        return "rounding"
    return "mismatch"


def _ratio(a: Decimal, b: int) -> float:
    return round(float(a) / b, 4) if b else 0.0


def crosscheck(years: list[int] | None = None) -> dict[str, Any]:
    years = years or [2023, 2024, 2025]
    rows: list[dict[str, Any]] = []
    by_field: dict[str, dict[str, int]] = {f: {"compared": 0, "ok": 0, "miss_pdf": 0, "miss_market": 0}
                                           for f in FIELDS}
    by_industry: dict[str, dict[str, int]] = {}
    restatements: list[dict[str, Any]] = []

    for comp in market.companies():
        eid, ind = comp["entity_id"], comp["industry_id"]
        by_industry.setdefault(ind, {"compared": 0, "ok": 0})
        for field in FIELDS:
            for year in years:
                ref = repo.market_fact(eid, field, year)
                facts = [f for f in pdf_facts(eid, field, year)
                         if f["audit_scope"] in ("primary_table", "summary_table", "parent_table")]
                if not ref:
                    if facts:
                        by_field[field]["miss_market"] += 1
                    continue
                if not facts:
                    by_field[field]["miss_pdf"] += 1
                    continue
                pdf_val = D(facts[0]["value_text"])
                ref_val = D(ref["value_text"])
                status = _classify(pdf_val, ref_val)
                # 同一指标在多份年报里出现过且数值不同 → 追溯重述，单独记账
                uniq = {D(f["value_text"]) for f in facts}
                if len(uniq) > 1:
                    restatements.append({
                        "entity_id": eid, "name": comp["name"], "field": field,
                        "year": year, "values": [str(v) for v in sorted(uniq)],
                        "docs": [f"{f['title'][:22]}({f['published_on']})" for f in facts[:3]],
                    })
                rows.append({
                    "entity_id": eid, "name": comp["name"], "industry": ind,
                    "field": field, "label": FIELD_LABEL.get(field, field), "year": year,
                    "pdf": str(pdf_val), "ref": str(ref_val),
                    "diff": str(pdf_val - ref_val), "status": status,
                    "page": facts[0]["page_index"], "doc": facts[0]["title"],
                    "published_on": facts[0]["published_on"],
                    # 失败样本故事卡要能直接回到原页与四层证据，所以把定位字段一起带出。
                    "fact_id": facts[0]["fact_id"], "doc_id": facts[0]["document_id"],
                    "location_id": facts[0]["location_id"], "cell_id": facts[0]["cell_id"],
                    "bbox": facts[0]["bbox"], "excerpt": facts[0]["excerpt"],
                    "row_label": facts[0]["row_label"], "col_label": facts[0]["col_label"],
                    "heading_path": facts[0]["heading_path"], "table_type": facts[0]["table_type"],
                })
                by_field[field]["compared"] += 1
                by_industry[ind]["compared"] += 1
                if status in ("exact", "rounding"):
                    by_field[field]["ok"] += 1
                    by_industry[ind]["ok"] += 1

    total = len(rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    ok = counts.get("exact", 0) + counts.get("rounding", 0)

    for f, v in by_field.items():
        v["rate"] = _ratio(v["ok"], v["compared"])
    for i, v in by_industry.items():
        v["rate"] = _ratio(v["ok"], v["compared"])
        v["name"] = (market.industry(i) or {}).get("name", i)

    failures = [r for r in rows if r["status"] in ("mismatch", "unit")]
    taxonomy = _taxonomy(failures)
    coverage = _coverage(by_field)
    return {
        "pairs": total,
        "ok": ok,
        "agreement": _ratio(ok, total),
        "counts": counts,
        "by_field": by_field,
        "by_industry": by_industry,
        "failures": sorted(failures, key=lambda r: (r["status"], r["entity_id"]))[:24],
        "failure_taxonomy": taxonomy,
        "coverage": coverage,
        "restatements": restatements[:12],
        "restatement_n": len(restatements),
        "years": years,
        "companies": len(market.companies()),
        "industries": len(market.industries()),
        "dataset_tag": "real_cninfo",
        "rule": "相差 0 记 exact；≤1 元记 rounding；整千/整万倍记 unit；其余 mismatch。"
                "参照值为第三方结构化数据，不是自建金标。",
    }


def _taxonomy(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把不一致按「差异量级」归类。只描述现象，不断言根因。"""
    buckets = {
        "unit": {"key": "unit", "label": "单位 / 量级", "hint": "两边相差整千或整万倍", "rows": []},
        "large": {"key": "large", "label": "大幅差异", "hint": "偏差 >50%，常见于取错行、列错位或口径不同", "rows": []},
        "medium": {"key": "medium", "label": "中等差异", "hint": "偏差 10%–50%，需回原页核对表头与期间", "rows": []},
        "small": {"key": "small", "label": "小幅差异", "hint": "偏差 <10%，可能是精度、四舍五入或口径微差", "rows": []},
    }
    for r in failures:
        if r["status"] == "unit":
            b = buckets["unit"]
        else:
            ref = abs(D(r["ref"])) or D(1)
            rel = float(abs(D(r["diff"])) / ref)
            b = buckets["large"] if rel > 0.5 else buckets["medium"] if rel >= 0.1 else buckets["small"]
        b["rows"].append(r)
    out = []
    for b in buckets.values():
        fields: dict[str, int] = {}
        for r in b["rows"]:
            fields[r["label"]] = fields.get(r["label"], 0) + 1
        out.append({"key": b["key"], "label": b["label"], "hint": b["hint"],
                    "count": len(b["rows"]),
                    "fields": [{"label": k, "count": v} for k, v in
                               sorted(fields.items(), key=lambda kv: -kv[1])]})
    return out


def _coverage(by_field: dict[str, dict[str, int]]) -> dict[str, Any]:
    conn = repo.get_conn()
    by_type = {r["source_type"]: r["n"] for r in conn.execute(
        "SELECT source_type, COUNT(*) n FROM documents WHERE dataset_tag='real_cninfo' "
        "GROUP BY source_type ORDER BY n DESC")}
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(period_end,1,4) y FROM documents "
        "WHERE dataset_tag='real_cninfo' AND source_type='annual_report' ORDER BY y")]
    total_compared = sum(v["compared"] for v in by_field.values())
    total_possible = sum(v["compared"] + v["miss_pdf"] + v["miss_market"] for v in by_field.values())
    return {
        "documents": sum(by_type.values()),
        "by_type": by_type,
        "years": years,
        "field_coverage": round(total_compared / max(total_possible, 1), 4),
        "compared": total_compared,
        "possible": total_possible,
        "note": "覆盖率按「字段 × 财年 × 公司」计：PDF 与第三方都有值才进入分母。",
    }
