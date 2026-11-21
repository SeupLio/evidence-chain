"""公开市场数据接入（真实数据，非合成）。

数据源：东方财富公开财报接口（年报口径）。定位是**第三方结构化数据**，
与「从巨潮年报 PDF 抽出来的事实」互为独立来源，用于跨源互证。

三条硬约束：
1. 只取 `REPORT_TYPE=年报`，避免把季报当年度值；
2. 原始响应落盘缓存，`replay` 模式只读缓存，保证演示时无网也能跑；
3. 抓取时间与接口地址随事实一起入库，报告里可点回来源。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import yaml

from ..domain.keys import content_id
from ..storage import repo
from ..storage.db import utcnow

ROOT = Path(__file__).resolve().parents[2]      # backend/
CONFIG = ROOT / "config"
CACHE = ROOT.parent / "data" / "cache"

API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
SOURCE = "eastmoney"

REPORTS = {
    "income": "RPT_F10_FINANCE_GINCOME",
    "balance": "RPT_F10_FINANCE_GBALANCE",
    "cashflow": "RPT_F10_FINANCE_GCASHFLOW",
}

#: field_code → (报表, 接口字段, 中文名)
MARKET_FIELDS: dict[str, tuple[str, str, str]] = {
    "revenue":            ("income",   "OPERATE_INCOME",   "营业收入"),
    "operating_cost":     ("income",   "OPERATE_COST",     "营业成本"),
    "net_profit_parent":  ("income",   "PARENT_NETPROFIT", "归母净利润"),
    "net_profit_total":   ("income",   "NETPROFIT",        "净利润"),
    "total_assets":       ("balance",  "TOTAL_ASSETS",     "资产总计"),
    "total_liabilities":  ("balance",  "TOTAL_LIABILITIES", "负债合计"),
    "total_equity":       ("balance",  "TOTAL_EQUITY",     "所有者权益合计"),
    "inventories":        ("balance",  "INVENTORY",        "存货"),
    "receivables":        ("balance",  "ACCOUNTS_RECE",    "应收账款"),
    "operating_cashflow": ("cashflow", "NETCASH_OPERATE",  "经营活动现金流量净额"),
}

UNIVERSE_FILE = "universe.yaml"


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #


def load_universe() -> dict[str, Any]:
    return yaml.safe_load((CONFIG / UNIVERSE_FILE).read_text(encoding="utf-8"))


def industries() -> list[dict[str, Any]]:
    return load_universe()["industries"]


def industry(industry_id: str) -> dict[str, Any] | None:
    return next((i for i in industries() if i["id"] == industry_id), None)


def companies(industry_id: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ind in industries():
        if industry_id and ind["id"] != industry_id:
            continue
        for c in ind["companies"]:
            out.append({**c, "industry_id": ind["id"], "industry_name": ind["name"],
                        "entity_id": entity_id_of(c["code"]), "market": market_of(c["code"])})
    return out


def market_of(code: str) -> str:
    return "SH" if code.startswith(("6", "9")) else "SZ" if code.startswith(("0", "3")) else "BJ"


def entity_id_of(code: str) -> str:
    return f"{market_of(code)}:{code}"


def secucode(code: str) -> str:
    return f"{code}.{market_of(code)}"


# --------------------------------------------------------------------------- #
# 抓取（带缓存）
# --------------------------------------------------------------------------- #


def _cache_path(report: str, code: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{report}_{code}.json"


def _fetch(report_name: str, code: str, *, mode: str = "live", retries: int = 3) -> list[dict[str, Any]]:
    """抓一份报表的全部年度记录。replay 模式只读缓存，缺失即报错而不是静默跳过。"""
    key = "income" if report_name == REPORTS["income"] else (
        "balance" if report_name == REPORTS["balance"] else "cashflow")
    path = _cache_path(key, code)
    if mode == "replay" or (mode == "cached" and path.exists()):
        if not path.exists():
            raise FileNotFoundError(f"replay 模式缺少缓存：{path.name}")
        return json.loads(path.read_text(encoding="utf-8"))["data"]

    flt = f'(SECUCODE="{secucode(code)}")(REPORT_TYPE="年报")'
    query = urllib.parse.urlencode({
        "reportName": report_name, "columns": "ALL", "filter": flt,
        "pageSize": 30, "sortColumns": "REPORT_DATE", "sortTypes": -1,
        "source": "HSF10", "client": "PC",
    })
    url = f"{API}?{query}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://emweb.securities.eastmoney.com/",
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            data = (payload.get("result") or {}).get("data") or []
            path.write_text(json.dumps({"url": url, "fetched_at": utcnow(), "data": data},
                                       ensure_ascii=False), encoding="utf-8")
            return data
        except Exception as exc:            # 网络抖动重试，三次仍失败则抛出
            last = exc
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"{code} {report_name} 抓取失败：{last}")


def _value(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        return str(int(raw)) if float(raw).is_integer() else str(raw)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 入库
# --------------------------------------------------------------------------- #


def sync_entities() -> int:
    n = 0
    for c in companies():
        repo.upsert_entity({
            "entity_id": c["entity_id"], "name": c["name"], "exchange": c["market"],
            "ticker": c["code"], "industry_id": c["industry_id"], "role": c["role"],
            "tag": c.get("tag", ""), "market": "A",
        })
        repo.upsert_alias(c["name"], c["entity_id"], "short")
        repo.upsert_alias(c["code"], c["entity_id"], "ticker")
        if c.get("alias"):
            repo.upsert_alias(c["alias"], c["entity_id"], "short")
        n += 1
    return n


def sync_market_facts(*, mode: str = "live", codes: Iterable[str] | None = None,
                      years: Iterable[int] | None = None, log=print) -> dict[str, Any]:
    """拉取全部样本公司的年度三大报表，写入 market_facts。"""
    wanted = set(years) if years else None
    targets = [c for c in companies() if not codes or c["code"] in set(codes)]
    stats = {"companies": 0, "records": 0, "facts": 0, "empty": [], "errors": []}
    for c in targets:
        rows: dict[str, dict[str, Any]] = {}
        try:
            for key, report_name in REPORTS.items():
                for rec in _fetch(report_name, c["code"], mode=mode):
                    date = str(rec.get("REPORT_DATE") or "")[:10]
                    if not date.endswith("12-31"):
                        continue
                    year = int(date[:4])
                    if wanted and year not in wanted:
                        continue
                    rows.setdefault(str(year), {})[key] = rec
        except Exception as exc:
            stats["errors"].append({"code": c["code"], "error": str(exc)[:160]})
            continue

        if not rows:
            stats["empty"].append(c["code"])
            continue
        stats["companies"] += 1
        for year_s, recs in sorted(rows.items()):
            year = int(year_s)
            for field_code, (key, src_field, _label) in MARKET_FIELDS.items():
                rec = recs.get(key)
                if not rec:
                    continue
                value = _value(rec.get(src_field))
                if value is None:
                    continue
                stats["facts"] += 1
                repo.upsert_market_fact({
                    "market_fact_id": content_id("mf", {"e": c["entity_id"], "f": field_code,
                                                        "y": year, "s": SOURCE}),
                    "entity_id": c["entity_id"], "field_code": field_code, "fiscal_year": year,
                    "period_end": f"{year}-12-31", "consolidation": "consolidated",
                    "currency": rec.get("CURRENCY") or "CNY", "value_text": value, "unit": "cny",
                    "source": SOURCE, "source_field": src_field,
                    "source_url": f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code={c['market']}{c['code']}",
                    "report_type": rec.get("REPORT_TYPE") or "年报",
                    "notice_date": str(rec.get("NOTICE_DATE") or "")[:10] or None,
                    "fetched_at": utcnow(),
                    "raw": json.dumps({src_field: rec.get(src_field),
                                       "REPORT_DATE": rec.get("REPORT_DATE")}, ensure_ascii=False),
                })
            stats["records"] += 1
        log(f"  {c['entity_id']:<12} {c['name']:<8} 年度 {len(rows)} 个")
    return stats


# --------------------------------------------------------------------------- #
# 行业视角（样本口径，必须标注 n，不冒充行业总量）
# --------------------------------------------------------------------------- #


def industry_aggregate(industry_id: str, field_code: str, year: int) -> dict[str, Any]:
    """样本合计 + 中位数。只对「可加总」的字段给合计（金额类）。"""
    cs = companies(industry_id)
    vals: list[Decimal] = []
    for c in cs:
        f = repo.market_fact(c["entity_id"], field_code, year)
        if f:
            vals.append(Decimal(f["value_text"]))
    vals.sort()
    if not vals:
        return {"n": 0, "sum": None, "median": None}
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    # 金额用到「元」为止；保留整数避免 JSON 精度问题
    return {"n": len(vals), "sum": int(sum(vals)), "median": int(median),
            "values": [int(v) for v in vals]}


def industry_summary(industry_id: str, years: list[int]) -> list[dict[str, Any]]:
    """行业样本层面：规模、增速、盈利能力、杠杆。全部由公司数据聚合，n 明确。"""
    out: list[dict[str, Any]] = []
    for year in years:
        rev = industry_aggregate(industry_id, "revenue", year)
        prev = industry_aggregate(industry_id, "revenue", year - 1)
        cost = industry_aggregate(industry_id, "operating_cost", year)
        assets = industry_aggregate(industry_id, "total_assets", year)
        liab = industry_aggregate(industry_id, "total_liabilities", year)
        np_ = industry_aggregate(industry_id, "net_profit_parent", year)
        growth = None
        if rev["sum"] and prev["sum"]:
            growth = round((rev["sum"] / prev["sum"] - 1) * 100, 2)
        gm = round((rev["sum"] - cost["sum"]) / rev["sum"] * 100, 2) if rev["sum"] and cost["sum"] else None
        lev = round(liab["sum"] / assets["sum"] * 100, 2) if assets["sum"] and liab["sum"] else None
        npm = round(np_["sum"] / rev["sum"] * 100, 2) if rev["sum"] and np_["sum"] else None
        out.append({"year": year, "n": rev["n"], "revenue_sum": rev["sum"], "growth_pct": growth,
                    "gross_margin_pct": gm, "debt_ratio_pct": lev, "net_margin_pct": npm,
                    "revenue_median": rev["median"]})
    return out


# --------------------------------------------------------------------------- #
# 产业链知识落库
# --------------------------------------------------------------------------- #


def sync_chains() -> dict[str, int]:
    """把 config/chains/*.yaml 落库；core 节点展开为样本公司节点。"""
    nodes_n = edges_n = 0
    for ind in industries():
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        spec = yaml.safe_load((CONFIG / ind["chain"]).read_text(encoding="utf-8"))
        core = spec["core"]
        deg: dict[str, int] = {}

        for n in spec["nodes"]:
            if n["id"] == core:
                continue
            node = {"node_id": f"{ind['id']}:{n['id']}", "industry_id": ind["id"], "name": n["name"],
                    "role": n.get("role", "upstream"), "note": n.get("note", ""),
                    "entity_id": None, "ticker": None, "degree": 0}
            nodes.append(node)
        for c in ind["companies"]:
            nodes.append({"node_id": f"{ind['id']}:{c['code']}", "industry_id": ind["id"],
                          "name": c["name"], "role": "core", "note": c.get("tag", ""),
                          "entity_id": entity_id_of(c["code"]), "ticker": c["code"], "degree": 0})

        for e in spec["edges"]:
            src, dst = e["from"], e["to"]
            if src == core or dst == core:
                for c in ind["companies"]:
                    s = f"{ind['id']}:{c['code']}" if src == core else f"{ind['id']}:{src}"
                    d = f"{ind['id']}:{c['code']}" if dst == core else f"{ind['id']}:{dst}"
                    edges.append({"edge_id": f"{ind['id']}:{s}->{d}", "industry_id": ind["id"],
                                  "src": s, "dst": d, "relation": e["relation"],
                                  "basis": e.get("basis", "")})
            else:
                s, d = f"{ind['id']}:{src}", f"{ind['id']}:{dst}"
                edges.append({"edge_id": f"{ind['id']}:{s}->{d}", "industry_id": ind["id"],
                              "src": s, "dst": d, "relation": e["relation"],
                              "basis": e.get("basis", "")})

        # 同业关系：样本公司两两相连，标注为竞争而非供货
        cs = ind["companies"]
        for i in range(len(cs)):
            for j in range(i + 1, len(cs)):
                a, b = f"{ind['id']}:{cs[i]['code']}", f"{ind['id']}:{cs[j]['code']}"
                edges.append({"edge_id": f"{ind['id']}:{a}<->{b}", "industry_id": ind["id"],
                              "src": a, "dst": b, "relation": "同业竞争",
                              "basis": "同属一个行业分类，收入口径可比"})

        for e in edges:
            deg[e["src"]] = deg.get(e["src"], 0) + 1
            deg[e["dst"]] = deg.get(e["dst"], 0) + 1
        for n in nodes:
            n["degree"] = deg.get(n["node_id"], 0)
            repo.upsert_chain_node(n)
            nodes_n += 1
        for e in edges:
            repo.upsert_chain_edge(e)
            edges_n += 1
    return {"nodes": nodes_n, "edges": edges_n}
