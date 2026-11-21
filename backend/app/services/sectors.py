"""行业视角：把 18 家公司的公开数据聚成「行业样本」。

必须守住的两条：
1. 样本合计 ≠ 行业总量。对外只说「样本 n=3 的合计/中位数」；
2. 聚合只用第三方结构化数据（覆盖全、口径统一），年报原件用于个案证据链。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..storage import repo
from . import market

D = Decimal


def _f(x: int | None, nd: int = 2) -> float | None:
    return None if x is None else round(x, nd)


def industries_overview() -> list[dict[str, Any]]:
    out = []
    for ind in market.industries():
        comps = market.companies(ind["id"])
        docs = 0
        facts = 0
        for c in comps:
            docs += repo.get_conn().execute(
                "SELECT COUNT(*) FROM documents WHERE issuer=? AND source_type='annual_report'",
                (c["entity_id"],)).fetchone()[0]
            facts += repo.get_conn().execute(
                "SELECT COUNT(*) FROM facts WHERE entity_id=?", (c["entity_id"],)).fetchone()[0]
        out.append({
            "id": ind["id"], "name": ind["name"], "short": ind["short"],
            "companies": [{"entity_id": c["entity_id"], "name": c["name"], "ticker": c["code"],
                           "role": c["role"], "tag": c.get("tag", "")} for c in comps],
            "documents": docs, "facts": facts,
            "years": repo.market_years(comps[0]["entity_id"])[-4:] if comps else [],
        })
    return out


def compare(field: str = "revenue", year: int = 2025) -> dict[str, Any]:
    """跨行业对比：每个行业给样本合计/中位数，并列出成员公司的值。"""
    label = market.MARKET_FIELDS.get(field, (None, None, field))[2]
    rows: list[dict[str, Any]] = []
    for ind in market.industries():
        agg = market.industry_aggregate(ind["id"], field, year)
        members = []
        for c in market.companies(ind["id"]):
            f = repo.market_fact(c["entity_id"], field, year)
            prev = repo.market_fact(c["entity_id"], field, year - 1)
            yoy = None
            if f and prev and int(prev["value_text"]):
                yoy = round((int(f["value_text"]) / int(prev["value_text"]) - 1) * 100, 2)
            members.append({"name": c["name"], "entity_id": c["entity_id"],
                            "value": int(D(f["value_text"])) if f else None, "yoy": yoy})
        rows.append({"industry": ind["id"], "name": ind["name"], "n": agg["n"],
                     "sum": agg["sum"], "median": agg["median"], "members": members})
    return {"field": field, "label": label, "year": year, "rows": rows,
            "note": "合计为样本合计（n=3），不是行业总量；中位数用于同业基准。"}


def industry_panel(industry_id: str, years: list[int] | None = None) -> dict[str, Any]:
    years = years or [2022, 2023, 2024, 2025]
    ind = market.industry(industry_id) or {"id": industry_id, "name": industry_id}
    summary = market.industry_summary(industry_id, years)
    members = []
    for c in market.companies(industry_id):
        rev = repo.market_series(c["entity_id"], "revenue")
        gm = {}
        for y in years:
            r, cost = repo.market_fact(c["entity_id"], "revenue", y), repo.market_fact(
                c["entity_id"], "operating_cost", y)
            if r and cost and D(r["value_text"]) != 0:
                gm[y] = round(float((1 - D(cost["value_text"]) / D(r["value_text"])) * 100), 2)
        members.append({
            "entity_id": c["entity_id"], "name": c["name"], "ticker": c["code"],
            "role": c["role"], "tag": c.get("tag", ""),
            "revenue": [{"year": y, "value": rev.get(y)} for y in years],
            "gross_margin": [{"year": y, "value": gm.get(y)} for y in years],
            "latest_revenue": rev.get(max(years)),
            "latest_gm": gm.get(max(years)),
        })
    return {"industry": ind, "years": years, "summary": summary, "members": members,
            "note": "样本口径；合计仅代表这 3 家公司，不代表行业总量。"}


def chain_with_metrics(industry_id: str, year: int = 2025) -> dict[str, Any]:
    g = repo.chain_graph(industry_id)
    metrics: dict[str, Any] = {}
    for n in g["nodes"]:
        if n.get("entity_id"):
            rev = repo.market_fact(n["entity_id"], "revenue", year)
            r = repo.market_fact(n["entity_id"], "revenue", year)
            cost = repo.market_fact(n["entity_id"], "operating_cost", year)
            gm = None
            if r and cost and D(r["value_text"]) != 0:
                gm = round(float((1 - D(cost["value_text"]) / D(r["value_text"])) * 100), 2)
            metrics[n["entity_id"]] = {"revenue": int(D(rev["value_text"])) if rev else None,
                                       "gross_margin": gm, "year": year}
    return {**g, "metrics": metrics,
            "note": "节点=产业链角色，边=交易/竞争关系；只有上市公司节点带财务数据。"}


def industry_matrix(year: int = 2025) -> dict[str, Any]:
    """跨行业对比矩阵：每个行业给样本层面的规模、增速、毛利率、杠杆、现金含量。

    全部由第三方结构化数据聚合，n 明确；不把样本合计当行业总量。
    """
    rows = []
    for ind in market.industries():
        cur = market.industry_summary(ind["id"], [year])[0]
        prev = market.industry_summary(ind["id"], [year - 1])[0]
        ocf = market.industry_aggregate(ind["id"], "operating_cashflow", year)
        npt = market.industry_aggregate(ind["id"], "net_profit_total", year)
        ocf_margin = (round(ocf["sum"] / cur["revenue_sum"] * 100, 2)
                      if ocf["sum"] is not None and cur["revenue_sum"] else None)
        cash_conv = (round(ocf["sum"] / npt["sum"] * 100, 2)
                     if ocf["sum"] is not None and npt["sum"] else None)
        members = []
        for c in market.companies(ind["id"]):
            rev = repo.market_fact(c["entity_id"], "revenue", year)
            rev_prev = repo.market_fact(c["entity_id"], "revenue", year - 1)
            cost = repo.market_fact(c["entity_id"], "operating_cost", year)
            liab = repo.market_fact(c["entity_id"], "total_liabilities", year)
            assets = repo.market_fact(c["entity_id"], "total_assets", year)
            gm = (round(float((1 - D(cost["value_text"]) / D(rev["value_text"])) * 100), 2)
                  if rev and cost and D(rev["value_text"]) else None)
            growth = (round(float(D(rev["value_text"]) / D(rev_prev["value_text"]) - 1) * 100, 2)
                      if rev and rev_prev and D(rev_prev["value_text"]) else None)
            lev = (round(float(D(liab["value_text"]) / D(assets["value_text"])) * 100, 2)
                   if liab and assets and D(assets["value_text"]) else None)
            members.append({"entity_id": c["entity_id"], "name": c["name"], "ticker": c["code"],
                            "role": c["role"], "revenue": int(D(rev["value_text"])) if rev else None,
                            "growth_pct": growth, "gross_margin_pct": gm, "debt_ratio_pct": lev})
        rows.append({
            "industry": ind["id"], "name": ind["name"], "short": ind.get("short", ind["name"]),
            "n": cur["n"], "revenue_sum": cur["revenue_sum"],
            "growth_pct": cur["growth_pct"], "gross_margin_pct": cur["gross_margin_pct"],
            "debt_ratio_pct": cur["debt_ratio_pct"], "net_margin_pct": cur["net_margin_pct"],
            "ocf_margin_pct": ocf_margin, "cash_conversion_pct": cash_conv,
            "prev_gross_margin_pct": prev["gross_margin_pct"],
            "members": members,
        })
    return {"year": year, "rows": rows,
            "note": "每格均为样本口径（n=3）；合计不代表行业总量，中位数不称行业均值。"}


def overview() -> dict[str, Any]:
    """首页与研究台共用的真实数据规模与评测摘要（30 秒缓存）。"""
    import time

    global _OVERVIEW_CACHE
    now = time.time()
    if _OVERVIEW_CACHE["data"] and now - _OVERVIEW_CACHE["at"] < 30:
        return _OVERVIEW_CACHE["data"]

    conn = repo.get_conn()
    counts = {
        "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "documents": conn.execute(
            "SELECT COUNT(*) FROM documents WHERE dataset_tag='real_cninfo'").fetchone()[0],
        "annual_reports": conn.execute(
            "SELECT COUNT(*) FROM documents WHERE dataset_tag='real_cninfo' "
            "AND source_type='annual_report'").fetchone()[0],
        "facts": conn.execute(
            "SELECT COUNT(*) FROM facts f JOIN documents d ON d.document_id=f.document_id "
            "WHERE d.dataset_tag='real_cninfo'").fetchone()[0],
        "market_facts": conn.execute("SELECT COUNT(*) FROM market_facts").fetchone()[0],
        "metrics": conn.execute("SELECT COUNT(*) FROM metric_results").fetchone()[0],
        "claims": conn.execute(
            "SELECT COUNT(*) FROM claims c JOIN version_objects v ON v.object_id=c.claim_version_id "
            "AND v.object_type='claim'").fetchone()[0],
        "reports": conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
        "issues": conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0],
        "source_locations": conn.execute("SELECT COUNT(*) FROM source_locations").fetchone()[0],
    }
    inds = industries_overview()
    from ..eval.crosscheck import crosscheck

    cross = crosscheck()
    data = {
        "counts": counts,
        "industries": inds,
        "industry_matrix": industry_matrix(2025),
        "cross_source": {k: cross[k] for k in ("pairs", "ok", "agreement", "counts",
                                               "restatement_n", "failure_taxonomy", "coverage")},
        "years": [2023, 2024, 2025],
        "note": "统计只读 dataset_tag=real_cninfo 的真实公开数据；合成语料不参与。",
    }
    _OVERVIEW_CACHE = {"at": now, "data": data}
    return data


_OVERVIEW_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
