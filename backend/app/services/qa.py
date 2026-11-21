"""版本内答疑（自由文本）。

三条设计原则：
1. **钉住版本**：只检索该快照的事实、指标与结论，不把最新证据混进历史版本；
2. **分清口径**：本报告口径的回答必须给内部引用；引用第三方结构化数据时必须
   标明来源并给链接，不能和年报原件混为一谈；
3. **不知道就说不知道**：没有命中时给出「能查到什么」与「缺哪份材料」，
   而不是编一段像模像样的话。
"""

from __future__ import annotations

import re
from decimal import Decimal as D
from typing import Any, Iterable, Sequence

from ..domain.keys import content_id
from ..storage import repo
from ..storage.db import utcnow
from . import market

# --------------------------------------------------------------------------- #
# 语言解析
# --------------------------------------------------------------------------- #

METRIC_WORDS: dict[str, tuple[str, ...]] = {
    "gross_margin": ("毛利率", "毛利", "成本率"),
    "net_margin": ("净利率", "净利", "利润率"),
    "revenue_yoy": ("营收增速", "收入增速", "增长", "增速", "同比"),
    "debt_asset_ratio": ("资产负债率", "负债率", "杠杆", "偿债", "负债水平"),
    "ocf_margin": ("经营现金流", "现金流", "回款", "收现"),
    "cash_conversion": ("现金含量", "含金量", "利润含金"),
}

INDUSTRY_WORDS = {
    "beer": ("啤酒",), "baijiu": ("白酒",), "dairy": ("乳制品", "乳业", "牛奶"),
    "appliance": ("家电", "空调", "白电"), "auto": ("汽车", "整车", "新能源车"),
    "solar": ("光伏", "组件", "硅片"),
}

INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("compare", ("对比", "比较", "谁高", "谁低", "差异", "相比", "vs", "哪个",
                 "位置", "排名", "水平", "同行")),
    ("why", ("为什么", "原因", "驱动", "解释", "怎么会", "导致")),
    ("trend", ("趋势", "这几年", "历年", "变化", "走势")),
    ("risk", ("风险", "隐患", "异常", "问题", "警报")),
    ("chain", ("产业链", "上下游", "供应商", "渠道", "关联企业", "图谱")),
    ("coverage", ("缺", "没有", "覆盖", "资料", "来源", "口径", "可信", "证据")),
    ("list", ("哪些", "列出", "有哪些", "多少家")),
]


def parse(question: str) -> dict[str, Any]:
    q = question.strip()
    low = q.lower()
    year = None
    m = re.search(r"(20\d{2})\s*年?", q)
    if m:
        year = int(m.group(1))
    elif "去年" in q:
        year = 2024

    metrics = [code for code, words in METRIC_WORDS.items() if any(w in q for w in words)]
    industries = [code for code, words in INDUSTRY_WORDS.items() if any(w in q for w in words)]
    entities = resolve_entities(q)

    intent = "summary"
    for name, words in INTENT_RULES:
        if any(w in q or w in low for w in words):
            intent = name
            break
    if intent == "summary" and entities:
        intent = "compare" if len(entities) > 1 else "value"
    if intent == "summary" and metrics:
        intent = "value"
    return {"question": q, "year": year, "metrics": metrics, "industries": industries,
            "entities": entities, "intent": intent}


def resolve_entities(text: str) -> list[dict[str, Any]]:
    """按公司简称/代码/全称匹配，返回去重后的实体。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ent in repo.list_entities():
        cur = repo.get_conn().execute(
            "SELECT alias FROM aliases WHERE entity_id=?", (ent["entity_id"],))
        names = [ent["name"], ent["ticker"]] + [r[0] for r in cur]
        if any(n and len(n) >= 2 and n in text for n in names):
            if ent["entity_id"] not in seen:
                seen.add(ent["entity_id"])
                out.append(ent)
    return out


# --------------------------------------------------------------------------- #
# 取值
# --------------------------------------------------------------------------- #


def _metric_ref(metric_ids: Sequence[str], code: str, year: int | None = None) -> dict[str, Any] | None:
    hits: list[dict[str, Any]] = []
    for mid in metric_ids:
        m = repo.get_metric(mid)
        if not m or m["metric_code"] != code:
            continue
        if year and m["fiscal_year"] != year:
            continue
        hits.append(m)
    if not hits:
        return None
    return max(hits, key=lambda m: (m["fiscal_year"], m.get("computed_at") or ""))


def _formula_note(code: str) -> str:
    from ..domain.metrics import FORMULAS
    spec = FORMULAS.get(code)
    return f"{spec.label} = {spec.formula_text}" if spec else ""


MARGIN_CODES = ("gross_margin", "net_margin", "debt_asset_ratio", "ocf_margin", "revenue_yoy")

EXTRA_LABELS = {"gross_margin": "毛利率", "net_margin": "归母净利率",
                "debt_asset_ratio": "资产负债率", "ocf_margin": "经营现金流/营收",
                "revenue_yoy": "营收同比"}


def _label_of(field: str) -> str:
    return EXTRA_LABELS.get(field) or market.MARKET_FIELDS.get(field, (None, None, field))[2]


def _market_value(eid: str, field: str, year: int) -> tuple[float | None, str | None]:
    """取第三方口径的指标值；比率类现场算，避免依赖本地重算结果。"""
    from .analysis import market_metric
    from ..domain.metrics import FORMULAS

    if field in market.MARKET_FIELDS:
        f = repo.market_fact(eid, field, year)
        return (int(float(f["value_text"])) if f else None, f["source_url"] if f else None)

    if field == "net_margin":
        np_ = repo.market_fact(eid, "net_profit_parent", year)
        rev = repo.market_fact(eid, "revenue", year)
        if np_ and rev and float(rev["value_text"]):
            return (round(float(np_["value_text"]) / float(rev["value_text"]) * 100, 2), rev["source_url"])
        return (None, None)
    if field == "revenue_yoy":
        cur = repo.market_fact(eid, "revenue", year)
        prev = repo.market_fact(eid, "revenue", year - 1)
        if cur and prev and float(prev["value_text"]):
            return (round((float(cur["value_text"]) / float(prev["value_text"]) - 1) * 100, 2),
                    cur["source_url"])
        return (None, None)
    if field in MARGIN_CODES:
        v = market_metric(eid, field, year)
        f = repo.market_fact(eid, "revenue", year)
        return (round(float(v) * 100, 2) if v is not None else None, f["source_url"] if f else None)
    return (None, None)


def _market_rows(entity_ids: Iterable[str], field: str, year: int) -> list[dict[str, Any]]:
    rows = []
    for eid in entity_ids:
        ent = repo.get_entity(eid) or {}
        value, url = _market_value(eid, field, year)
        prev, _ = _market_value(eid, field, year - 1)
        yoy = None
        if value is not None and prev not in (None, 0) and field not in MARGIN_CODES:
            yoy = round((value / prev - 1) * 100, 2)
        rows.append({"entity_id": eid, "name": ent.get("name", eid),
                     "value": value, "yoy": yoy, "url": url})
    return rows


def _external_sources(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for r in rows:
        url = r.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append({"title": f"{r['name']} · 第三方结构化财务数据", "url": url,
                        "publisher": "东方财富（公开接口）"})
    return out


# --------------------------------------------------------------------------- #
# 回答
# --------------------------------------------------------------------------- #


def answer(report_id: str, version_no: int, question: str,
           history: list[str] | None = None) -> dict[str, Any]:
    version = repo.get_report_version(report_id, version_no)
    if not version:
        raise KeyError("版本不存在")
    sections = {s["section_key"]: s for s in repo.sections_of(report_id, version_no)}
    metric_ids = repo.version_object_ids(report_id, version_no, "metric")
    subject_id = repo.entity_of_report(report_id)
    subject = repo.get_entity(subject_id) or {}
    years = sorted({(repo.get_metric(mid) or {}).get("fiscal_year") for mid in metric_ids} - {None}) or [2025]
    latest = max(years)

    p = parse(question)
    inherited: list[str] = []
    # 多轮上下文：当前问题没有主体/指标时，沿用最近一轮提到的内容。
    # 只在同一次会话内继承，并在回答里显式说明，避免「它」指代不清。
    if history and not p["entities"] and not p["industries"]:
        for prev in reversed(history[-4:]):
            hp = parse(prev)
            if hp["entities"]:
                p["entities"] = hp["entities"]
                if not p["metrics"]:
                    p["metrics"] = hp["metrics"]
                if not p["year"]:
                    p["year"] = hp["year"]
                inherited = [f"主体沿用上一问：{e['name']}" for e in hp["entities"]]
                break
    intent, year = p["intent"], p["year"]
    target_year = year or latest
    refs: list[str] = []
    sources: list[dict[str, Any]] = []
    lines: list[str] = []
    premise = None
    followups = suggest(report_id, version_no, limit=4)

    def add_metric(code: str, y: int | None = None) -> dict[str, Any] | None:
        hit = _metric_ref(metric_ids, code, y or year)
        if hit:
            refs.append(hit["result_id"])
        return hit

    # ---------- 跨公司/跨行业：用第三方结构化数据回答，明确标注 ----------
    others = [e for e in p["entities"] if e["entity_id"] != subject_id]
    if p["entities"] and (intent in ("compare", "value", "trend", "list")
                          or (intent == "why" and others)):
        field = (p["metrics"] or ["revenue"])[0]
        label = _label_of(field)
        if len(p["entities"]) >= 2 or intent == "compare":
            eids = [e["entity_id"] for e in p["entities"]]
            rows = _market_rows(eids, field, target_year)
            lines.append(f"按第三方结构化数据（{target_year} 年年报口径）比较{label}：")
            for r in sorted(rows, key=lambda x: -(x["value"] or 0)):
                if r["value"] is None:
                    lines.append(f"· {r['name']}：无数据")
                    continue
                yoy = f"，同比 {r['yoy']:+.2f}%" if r["yoy"] is not None else ""
                if field in ("gross_margin", "net_margin", "debt_asset_ratio", "ocf_margin", "revenue_yoy"):
                    lines.append(f"· {r['name']}：{r['value']:.2f}%{yoy}")
                else:
                    lines.append(f"· {r['name']}：{r['value'] / 1e8:,.2f} 亿元{yoy}")
            lines.append("这组数字来自公开接口，不是本报告的原件证据；点开来源可核对，"
                         "若要写进正文仍需回到年报相应页。")
            sources = _external_sources(rows)
            if others and subject.get("industry_id") and \
                    any(e.get("industry_id") == subject.get("industry_id") for e in others):
                lines.append("同一行业内比规模意义有限，接着看毛利率与费用率更能解释差异。")
        else:
            ent = p["entities"][0]
            r = _market_rows([ent["entity_id"]], field, target_year)[0]
            if r["value"] is None:
                lines.append(f"{ent['name']} 的{label}在 {target_year} 年没有取到数据。")
            else:
                yoy = f"，同比 {r['yoy']:+.2f}%" if r["yoy"] is not None else ""
                if field in ("gross_margin", "net_margin", "debt_asset_ratio", "ocf_margin", "revenue_yoy"):
                    shown = f"{r['value']:.2f}%"
                else:
                    shown = f"{r['value'] / 1e8:,.2f} 亿元"
                lines.append(f"{ent['name']} {target_year} 年{label} {shown}{yoy}"
                             f"（第三方结构化数据，可点来源核对）。")
            sources = _external_sources([r])
            if ent["entity_id"] != subject_id:
                lines.append("若要把它作为同业基准写进报告，需要先下载其年报原件并完成入库。")
            if intent == "why":
                lines.append("原因分析需要该公司的年报原件与分部数据；当前只给第三方口径的数值，"
                             "不根据一个数字推断原因。")

    elif intent == "chain":
        ind = (p["industries"] or [subject.get("industry_id")])[0]
        spec = market.industry(ind) or {}
        g = repo.chain_graph(ind)
        lines.append(f"{spec.get('name', ind)}产业链共 {len(g['nodes'])} 个节点、{len(g['edges'])} 条关系：")
        role_cn = {"upstream": "上游", "packaging": "包材", "core": "中游制造",
                   "downstream": "下游渠道", "demand": "终端需求"}
        by_role: dict[str, list[str]] = {}
        for n in g["nodes"]:
            by_role.setdefault(n["role"], []).append(n["name"])
        for role, names in by_role.items():
            lines.append(f"· {role_cn.get(role, role)}：{'、'.join(names[:8])}")
        name_of = {n["node_id"]: n["name"] for n in g["nodes"]}
        for e in g["edges"][:3]:
            lines.append(f"· 关系示例：{name_of.get(e['src'], e['src'])} → "
                         f"{name_of.get(e['dst'], e['dst'])}（{e['relation']}，依据：{e['basis']}）")
        lines.append("关系边标注依据；行业常识与年报披露分开写，不把推断当披露。")

    elif intent == "compare" and p["industries"] and not p["entities"]:
        from .sectors import industry_matrix

        matrix = industry_matrix(target_year)
        pick = [r for r in matrix["rows"] if r["industry"] in p["industries"]]
        if not pick:
            pick = matrix["rows"]
        lines.append(f"按第三方结构化数据比较 {target_year} 年样本口径：")
        for r in pick:
            parts = [f"营收合计 {r['revenue_sum'] / 1e8:,.1f} 亿元" if r["revenue_sum"] else "营收缺",
                     f"同比 {r['growth_pct']:+.2f}%" if r["growth_pct"] is not None else "同比缺",
                     f"毛利率 {r['gross_margin_pct']:.2f}%" if r["gross_margin_pct"] is not None else "毛利率缺",
                     f"资产负债率 {r['debt_ratio_pct']:.2f}%" if r["debt_ratio_pct"] is not None else "杠杆缺"]
            lines.append(f"· {r['name']}（n={r['n']}）：" + "，".join(parts))
        lines.append("这里每一行是三家公司的样本合计，不是行业总量；跨行业比较只用同一指标、同一年度。")
        if inherited:
            lines = inherited + lines

    elif intent == "compare":
        peer = sections.get("peer", {}).get("content", {})
        for row in peer.get("rows", []):
            cells = "，".join(f"{c['name']} {c['display'] or '缺失'}" for c in row["cells"])
            lines.append(f"{row['label']}：{cells}；中位数 {row.get('median_display') or '不适用'}"
                         f"（n={row.get('n', 0)}）。")
            for cell in row["cells"]:
                if cell.get("ref"):
                    refs.append(cell["ref"])
        if not peer.get("rows"):
            lines.append("该版本没有同业对比表。")
        lines.append("n<2 不输出基准；样本营收合计不等于行业规模。")

    elif intent == "why":
        code = (p["metrics"] or ["gross_margin"])[0]
        m = add_metric(code)
        premise = None
        if m:
            from ..domain.metrics import FORMULAS as _F2
            label = _F2[code].label if code in _F2 else code
            lines.append(f"FY{m['fiscal_year']} {label}为 {m['display']}。算式：{_formula_note(code)}。")
            # 先核对问题里的方向前提，避免为一个并不存在的「下降」编原因。
            prev_m = None
            for mid in metric_ids:
                pm = repo.get_metric(mid)
                if pm and pm["metric_code"] == code and pm["fiscal_year"] == m["fiscal_year"] - 1:
                    prev_m = pm
                    break
            if prev_m and m.get("value_text") and prev_m.get("value_text"):
                cur_v, prev_v = D(m["value_text"]), D(prev_m["value_text"])
                delta = cur_v - prev_v
                claim_down = any(k in question for k in ("下降", "下滑", "下跌", "减少", "恶化"))
                claim_up = any(k in question for k in ("上升", "增长", "提高", "改善"))
                if (claim_down and delta > 0) or (claim_up and delta < 0):
                    actual = "上升" if delta > 0 else "下降"
                    unit = "个百分点" if code in ("gross_margin", "net_margin", "ocf_margin", "debt_asset_ratio") else "%"
                    change = abs(delta) * 100 if unit == "个百分点" else abs(delta / prev_v) * 100
                    lines.insert(0, f"先核对前提：{label}并未{'下降' if claim_down else '上升'}，"
                                    f"FY{m['fiscal_year']} 为 {m['display']}，比上年{actual}{change:.2f}{unit}。")
                    premise = {"claimed": "down" if claim_down else "up",
                               "actual": "up" if delta > 0 else "down",
                               "change": round(float(change), 2), "unit": unit}
        decomp = sections.get("operations", {}).get("content", {}).get("decomposition") or []
        if decomp:
            d = decomp[0]
            lines.append(f"恒等分解：结构项 {d['structure_pp']}pp、分部毛利率项 {d['margin_pp']}pp、"
                         f"残差 {d['residual_pp']}pp。")
            lines.append("分解只说明变动由哪一部分贡献，不证明因果；因果需要吨价、吨成本或费用明细。")
        rules = sections.get("risk", {}).get("content", {}).get("rules") or []
        trig = [r for r in rules if r["status"] == "TRIGGERED"]
        if trig:
            lines.append("已触发的判断：" + "；".join(f"{r['label']}——{r['headline']}" for r in trig))
        # 报告正文已经写过的跨材料线索，优先复用，而不是另起一段猜测。
        hits = _fallback(question, sections, refs)
        if hits:
            lines.append("报告里已有的线索：")
            lines.extend(hits)
        if not decomp and not trig and not hits:
            lines.append("该版本没有可支撑「为什么」的分解或规则结果，需要补充分部或费用明细。")

    elif intent == "trend":
        code = (p["metrics"] or ["gross_margin"])[0]
        series: list[str] = []
        for mid in metric_ids:
            m = repo.get_metric(mid)
            if (m and m["metric_code"] == code and m.get("status") == "OK"
                    and m.get("display") and m.get("fiscal_year")):
                series.append((m["fiscal_year"], m["display"], m["result_id"]))
        series.sort()
        refs.extend(r for _y, _d, r in series)
        label = market.MARKET_FIELDS.get(code, (0, 0, code))[2] if code in market.MARKET_FIELDS else code
        lines.append(f"{label}历年：" + "；".join(f"{y} {d}" for y, d, _r in series)
                     if series else "该指标没有多期结果。")
        if len(series) >= 2:
            lines.append("趋势只描述方向；拐点要结合披露口径变化一起看。")

    elif intent == "risk":
        rules = sections.get("risk", {}).get("content", {}).get("rules") or []
        for r in rules:
            lines.append(f"[{r['status']}] {r['label']}：{r['headline']}")
            if r["status"] == "TRIGGERED":
                lines.append(f"  反证：{r['counter_evidence']}")
                lines.append(f"  下一份材料：{r['next_material']}")
        if not rules:
            lines.append("该版本没有风险规则结果。")
        not_eval = [r["label"] for r in rules if r["status"] == "NOT_EVALUABLE"]
        if not_eval:
            lines.append(f"未评估项：{'、'.join(not_eval)}——未评估不等于已通过。")

    elif intent == "coverage":
        dq = sections.get("data_quality", {}).get("content", {})
        cov = dq.get("coverage") or []
        lines.append("覆盖：" + "，".join(f"{c['label']} {c['value']} {c['unit']}" for c in cov))
        for g in (dq.get("groups") or [])[:5]:
            extra = f"，涉及第 {'、'.join(str(x) for x in g['pages'][:6])} 页" if g.get("pages") else ""
            lines.append(f"{g['label']}：{g['count']} 处{extra}")
        blocked = dq.get("blocked_claims") or []
        if blocked:
            lines.append(f"被审核阻断的结论 {len(blocked)} 条，未进入正文。")
        if not cov and not dq.get("groups"):
            lines.append("该版本没有数据质量记录。")

    else:
        if p["metrics"]:
            code = p["metrics"][0]
            m = add_metric(code)
            if m:
                prev = _metric_ref(metric_ids, code, m["fiscal_year"] - 1)
                from ..domain.metrics import FORMULAS as _F
                _label = _F[code].label if code in _F else code
                lines.append(f"{_label}：FY{m['fiscal_year']} {m['display']}"
                             + (f"（上年 {prev['display']}）" if prev else ""))
                lines.append(f"算式：{_formula_note(code)}；输入都在合并报表主表，可点开原件核对。")
        if not lines:
            hit = _fallback(question, sections, refs)
            if hit:
                lines.append("在已发布的结论里检索到：")
                lines.extend(hit)
            else:
                lines.append(f"没有在本版本里找到与「{question}」直接相关的结论。")
                lines.append("可以换成：公司 + 年份 + 指标（如「美的 2024 年毛利率」）、"
                             "「为什么毛利率下降」、「讲一下白酒产业链」、「哪些资料没拿到」。")

    if inherited and lines and lines[0] != inherited[0]:
        lines = inherited + lines

    if not lines:
        lines.append("这个问题没有命中该版本的证据，暂不作答。")

    qid = content_id("q", {"r": report_id, "v": version_no, "q": question})
    payload = {
        "question": question,
        "answer": "\n".join(lines),
        "refs": [r for r in dict.fromkeys(refs)][:12],
        "sources": sources,
        "intent": intent,
        "parsed": {"year": year, "metrics": p["metrics"],
                   "entities": [e["name"] for e in p["entities"]], "industries": p["industries"]},
        "followups": followups,
        "inherited": inherited,
        "premise": premise,
        "basis": {"version": version_no, "as_of": version["as_of"],
                  "content_hash": version["content_hash"][:12]},
        "notice": "回答钉住该版本；第三方数据单独标注来源，不与年报原件混用。",
    }
    repo.save_question({"question_id": qid, "report_id": report_id, "version_no": version_no,
                        "question": question, "answer": payload["answer"], "refs": payload["refs"],
                        "intent": intent, "created_at": utcnow()})
    return payload


def _fallback(question: str, sections: dict[str, Any], refs: list[str]) -> list[str]:
    """按字面重合度检索章节段落，返回最相关的几句（带引用）。"""
    import jieba

    tokens = {t for t in jieba.cut(question) if len(t) >= 2}
    if not tokens:
        return []
    scored: list[tuple[int, str, list[str]]] = []
    for sec in sections.values():
        for para in sec.get("content", {}).get("paragraphs", []):
            text = para.get("text", "")
            score = sum(1 for t in tokens if t in text)
            if score:
                scored.append((score, text, para.get("refs") or []))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _score, text, r in scored[:3]:
        out.append("· " + text)
        refs.extend(r)
    return out


def suggest(report_id: str, version_no: int, limit: int = 4) -> list[str]:
    """按当前报告的薄弱点生成推荐问题，而不是写死几个句子。"""
    sections = {s["section_key"]: s for s in repo.sections_of(report_id, version_no)}
    out: list[str] = []

    ops = sections.get("operations", {}).get("content", {})
    if ops.get("decomposition"):
        out.append("毛利率的变化由什么贡献？")
    risk = sections.get("risk", {}).get("content", {})
    trig = [r for r in risk.get("rules", []) if r["status"] == "TRIGGERED"]
    if trig:
        out.append(f"「{trig[0]['label']}」这条判断的依据和反证是什么？")
    peer = sections.get("peer", {}).get("content", {})
    if peer.get("rows"):
        out.append(f"{peer['rows'][0]['label']}在同行里处于什么位置？")
    dq = sections.get("data_quality", {}).get("content", {})
    if dq.get("groups"):
        out.append("哪些资料没拿到，会影响哪个结论？")
    ent = repo.get_entity(repo.entity_of_report(report_id)) or {}
    if ent.get("industry_id"):
        name = (market.industry(ent["industry_id"]) or {}).get("name", "")
        out.append(f"讲一下{name}产业链的上下游。")
        peers = [c for c in market.companies(ent["industry_id"]) if c["entity_id"] != ent["entity_id"]]
        if peers:
            out.append(f"{peers[0]['name']} 2025 年毛利率是多少？")
    return list(dict.fromkeys(out))[:limit]
