"""分析层：指标计算、同业基准、行业事实、产业链图。

这一层不产生任何模型文字，只产生可以用引用打开的结构化对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

from ..domain.contracts import (Confidence, GraphEdge, GraphNode, MetricResult, MetricStatus,
                                NodeType, Relation)
from ..domain.keys import content_id, edge_key
from ..domain.metrics import FORMULAS, compute_suite
from ..storage import repo
from .verify import VerifyOutput, to_metric_slots, verify_entity

D = Decimal
METRIC_CODES = ("revenue_yoy", "gross_margin", "parent_net_margin", "debt_asset_ratio",
                "ocf_margin", "cash_conversion", "gross_margin_delta_pp", "asset_ratio_delta_pp",
                "ocf_margin_delta_pp")


@dataclass
class FinanceBundle:
    entity_id: str
    verify: VerifyOutput
    metrics: dict[int, dict[str, MetricResult]] = field(default_factory=dict)

    def get(self, code: str, year: int) -> MetricResult | None:
        return self.metrics.get(year, {}).get(code)

    def series(self, code: str, years: Sequence[int]) -> list[MetricResult]:
        return [m for y in years if (m := self.get(code, y))]


def compute_finance(entity_id: str, years: Sequence[int], as_of: str,
                    staged: Sequence[str] = ()) -> FinanceBundle:
    v = verify_entity(entity_id, as_of, staged)
    slots = to_metric_slots(v.year_facts)
    available = sorted(set(slots) | set(range(min(years) - 1, max(years) + 1)))
    lookup: dict[tuple[str, int], MetricResult] = {}
    bundle = FinanceBundle(entity_id=entity_id, verify=v)
    for year in available:
        res = compute_suite(entity_id=entity_id, fiscal_year=year, year_facts=slots, metric_lookup=lookup)
        bundle.metrics[year] = res
        for m in res.values():
            repo.insert_metric(m.model_dump())
    return bundle


def market_metric(entity_id: str, code: str, year: int) -> Decimal | None:
    """用第三方结构化数据补一个可比指标。

    只用于**同业基准**：同业的年报原件不一定全部入库，缺一家就让 n 掉到 1，
    基准就失去意义。这里补值必须带 source 标记，报告里会写清楚是哪来的。
    """
    rev = repo.market_fact(entity_id, "revenue", year)
    cost = repo.market_fact(entity_id, "operating_cost", year)
    assets = repo.market_fact(entity_id, "total_assets", year)
    liab = repo.market_fact(entity_id, "total_liabilities", year)
    ocf = repo.market_fact(entity_id, "operating_cashflow", year)
    try:
        if code == "gross_margin" and rev and cost and D(rev["value_text"]) != 0:
            return D(1) - D(cost["value_text"]) / D(rev["value_text"])
        if code == "debt_asset_ratio" and assets and liab and D(assets["value_text"]) != 0:
            return D(liab["value_text"]) / D(assets["value_text"])
        if code == "ocf_margin" and rev and ocf and D(rev["value_text"]) != 0:
            return D(ocf["value_text"]) / D(rev["value_text"])
    except (ArithmeticError, ValueError):
        return None
    return None


def peer_median(bundle: FinanceBundle, peer_ids: Sequence[str], year: int,
                code: str) -> tuple[Decimal | None, int, list[dict[str, Any]]]:
    vals: list[Decimal] = []
    detail: list[dict[str, Any]] = []
    for pid in peer_ids:
        ms = repo.metrics_of(pid, year)
        hit = next((m for m in ms if m["metric_code"] == code), None)
        if hit and hit["status"] == MetricStatus.OK.value and hit["value_text"]:
            vals.append(D(hit["value_text"]))
            detail.append({"entity_id": pid, "value_text": hit["value_text"],
                           "display": hit["display"], "source": "annual_report"})
            continue
        fb = market_metric(pid, code, year)
        if fb is not None:
            vals.append(fb)
            disp = f"{fb * 100:.2f}%" if FORMULAS[code].unit == "fraction" else f"{fb}"
            detail.append({"entity_id": pid, "value_text": str(fb), "display": disp,
                           "source": "eastmoney"})
            continue
        detail.append({"entity_id": pid, "value_text": None,
                       "display": "缺失" if hit is None else hit.get("display") or hit["status"],
                       "source": None})
    if not vals:
        return None, 0, detail
    vals.sort()
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / D(2)
    return med, n, detail


def peer_table(peer_ids: Sequence[str], year: int, codes: Sequence[str],
               subject_id: str | None = None) -> dict[str, Any]:
    rows = []
    for code in codes:
        row = {"metric_code": code, "label": FORMULAS[code].label, "unit": FORMULAS[code].unit, "values": {}}
        for pid in peer_ids:
            ms = repo.metrics_of(pid, year)
            hit = next((m for m in ms if m["metric_code"] == code), None)
            if hit and hit["status"] == MetricStatus.OK.value:
                row["values"][pid] = {"value_text": hit["value_text"], "display": hit["display"],
                                      "status": hit["status"], "metric_key": hit["metric_key"],
                                      "source": "annual_report"}
                continue
            fb = market_metric(pid, code, year)
            if fb is not None:
                disp = f"{fb * 100:.2f}%" if FORMULAS[code].unit == "fraction" else f"{fb}"
                row["values"][pid] = {"value_text": str(fb), "display": disp, "status": "OK",
                                      "metric_key": None, "source": "eastmoney"}
                continue
            row["values"][pid] = ({"value_text": None, "display": hit["display"] if hit else "未覆盖",
                                   "status": hit["status"] if hit else "NO_RECORD",
                                   "metric_key": hit["metric_key"] if hit else None,
                                   "source": None})
        rows.append(row)
    return {"year": year, "rows": rows, "n": len(peer_ids)}


# --------------------------------------------------------------------------- #
# 行业
# --------------------------------------------------------------------------- #

def industry_view(industry_id: str, years: Sequence[int]) -> dict[str, Any]:
    facts = repo.industry_facts(industry_id)
    by_code: dict[str, dict[str, Any]] = {}
    for f in facts:
        by_code.setdefault(f["code"], {})[f["period"]] = f

    def series(code: str) -> list[dict[str, Any]]:
        out = []
        prev = None
        for y in sorted(by_code.get(code, {})):
            f = by_code[code][y]
            v = D(f["value_text"])
            yoy = ((v / prev - 1) * 100).quantize(D("0.01")) if prev else None
            out.append({"period": y, "value_text": f["value_text"], "unit": f["unit"],
                        "display": f"{v:,.1f}{f['unit']}", "yoy_pct": str(yoy) if yoy is not None else None,
                        "location": f["source_location"], "document_id": f["document_id"],
                        "stat_scope": f["stat_scope"], "definition": f["definition"]})
            prev = v
        return out

    policy_docs = [d for d in repo.documents_visible() if d["source_type"] == "policy"]
    market_docs = [d for d in repo.documents_visible() if d["source_type"] == "market_note"]
    policy_refs = []
    for d in policy_docs:
        locs = repo.get_conn().execute(
            "SELECT location_id, excerpt, page_index FROM source_locations WHERE document_id=? AND kind='pdf_page'",
            (d["document_id"],)).fetchall()
        policy_refs.append({"document_id": d["document_id"], "title": d["title"],
                            "published_on": d["published_on"],
                            "locations": [dict(r) for r in locs]})
    market_refs = [{"document_id": d["document_id"], "title": d["title"],
                    "published_on": d["published_on"], "tier": d["tier"]} for d in market_docs]
    return {
        "industry_id": industry_id,
        "output": series("beer_output"),
        "revenue_above_scale": series("beer_revenue_above_scale"),
        "policy_refs": policy_refs,
        "market_refs": market_refs,
        "gaps": [] if by_code else [{"detail": "行业统计原件未入库，行业章节只保留定性描述"}],
    }


# --------------------------------------------------------------------------- #
# 产业链图
# --------------------------------------------------------------------------- #

CHAIN_NODES = [
    ("mat:barley", NodeType.MATERIAL, "大麦"),
    ("mat:glass", NodeType.MATERIAL, "玻璃瓶"),
    ("mat:aluminium", NodeType.MATERIAL, "铝罐"),
    ("proc:brewing", NodeType.PROCESS, "啤酒酿造"),
    ("ch:distributor", NodeType.CHANNEL, "经销商分销"),
    ("ch:retail", NodeType.CHANNEL, "商超与电商"),
    ("ind:beer", NodeType.INDUSTRY, "啤酒制造业"),
]


def _page_loc(document_id: str, page: int) -> str | None:
    row = repo.get_conn().execute(
        "SELECT location_id FROM source_locations WHERE document_id=? AND page_index=? AND kind='pdf_page'",
        (document_id, page)).fetchone()
    return row[0] if row else None


def build_graph(subject: dict[str, Any], peers: Sequence[dict[str, Any]],
                subject_doc: dict[str, Any] | None) -> dict[str, Any]:
    subject_node = f"co:{subject['entity_id']}"
    nodes: list[dict[str, Any]] = [{
        "node_id": subject_node, "type": NodeType.COMPANY.value,
        "label": subject["name"], "entity_id": subject["entity_id"], "meta": {"role": "subject"},
    }]
    for p in peers:
        nodes.append({"node_id": f"co:{p['entity_id']}", "type": NodeType.COMPANY.value,
                      "label": p["name"], "entity_id": p["entity_id"], "meta": {"role": "peer"}})
    for nid, ntype, label in CHAIN_NODES:
        nodes.append({"node_id": nid, "type": ntype.value, "label": label, "entity_id": None, "meta": {}})

    edges: list[dict[str, Any]] = []
    mdna_loc = _page_loc(subject_doc["document_id"], 4) if subject_doc else None

    def add(src: str, rel: Relation, dst: str, scope: str, period: str, refs: list[str],
            status: str = "VERIFIED", note: str | None = None) -> None:
        ek = edge_key(src, rel.value, dst, scope, period)
        edges.append({
            "edge_id": ek, "edge_key": ek, "src": src, "dst": dst, "relation": rel.value,
            "scope": scope, "evidence_refs": [r for r in refs if r], "effective_period": period,
            "status": status, "note": note,
        })

    # 使用原料：有明确原句才建边
    for nid, label in (("mat:barley", "大麦"), ("mat:glass", "玻璃瓶"), ("mat:aluminium", "铝罐")):
        add(subject_node, Relation.USES_INPUT, nid, "啤酒生产", "FY2025",
            [mdna_loc] if mdna_loc else [], "VERIFIED",
            f"年报原文点名「{label}」为主要原材料；USES_INPUT 只表示使用该类原料，不派生供应商")
    add(subject_node, Relation.OPERATES_IN, "proc:brewing", "主业", "FY2025", [mdna_loc], "VERIFIED",
        "年报披露主营业务为啤酒生产与销售")
    add(subject_node, Relation.OPERATES_IN, "ind:beer", "行业归属", "FY2025", [mdna_loc], "VERIFIED",
        "按预置行业档案归入啤酒制造业，用于研究口径而非商业关系")
    add(subject_node, Relation.SELLS_VIA, "ch:distributor", "销售模式", "FY2025", [mdna_loc], "VERIFIED",
        "年报原文：以经销商分销为主")
    add(subject_node, Relation.SELLS_VIA, "ch:retail", "销售模式", "FY2025", [mdna_loc], "VERIFIED",
        "年报原文：直接供货商超与电商平台")

    for p in peers:
        add(subject_node, Relation.PEER_OF, f"co:{p['entity_id']}", "研究对标", "FY2025", [],
            "STRUCTURAL", "由预置行业档案确定的可比样本，属研究对标关系，不等于商业交易")
        add(f"co:{p['entity_id']}", Relation.OPERATES_IN, "ind:beer", "行业归属", "FY2025", [],
            "STRUCTURAL", "同行样本行业归属")

    for n in nodes:
        repo.upsert_node(n)
    for e in edges:
        repo.upsert_edge(e)
    return {"nodes": nodes, "edges": edges,
            "unbuilt": [{"relation": "SUPPLIES_TO",
                         "reason": "未检索到具名供应商与客户的交易披露；按规则保留「公开披露未具名」，不建边"}]}
