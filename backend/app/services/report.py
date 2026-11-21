"""报告编排：章节、Claim 渲染、审核、版本与依赖登记。

数字全部来自 token 绑定；模型只能选模板与引用。
未过审的 Claim 不进正文，而是进 data_quality 的「被阻断」清单。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence

from ..domain.claims import TEMPLATES, ClaimSpec
from ..domain.contracts import (Claim, ClaimKind, Confidence, MetricResult, MetricStatus, Severity,
                                Verdict, IssueType)
from ..domain.keys import (claim_version_id, content_id, report_fingerprint, section_content_hash)
from ..domain.metrics import FORMULAS, cny_yi, pct, pp
from ..domain.rules import RuleOutcome, evaluate, load_pack
from ..domain.textguard import check_numeric_claim, render
from ..storage import repo
from ..storage.db import utcnow
from .analysis import FinanceBundle, peer_median
from .issues import group_issues, summarize as issue_summary

D = Decimal
SECTION_ORDER = ("overview", "industry", "operations", "financials", "peer", "risk", "chain", "data_quality")
SECTION_TITLES = {
    "overview": "结论摘要",
    "industry": "行业背景与竞争格局",
    "operations": "经营变化与驱动",
    "financials": "财务指标与复算",
    "peer": "同业比较",
    "risk": "风险线索与反证",
    "chain": "产业链与关联企业",
    "data_quality": "资料覆盖与数据质量",
}
WORKFLOW_VERSION = "workflow/v1.0.0"
PROMPT_VERSION = "prompt/v1.0.0"
PARSER_VERSION = "pdfplumber/1.2"


@dataclass
class ReportContext:
    subject: dict[str, Any]
    peers: list[dict[str, Any]]
    years: list[int]
    as_of: str
    finance: FinanceBundle
    peer_finance: dict[str, FinanceBundle] = field(default_factory=dict)
    bench: dict[str, dict[str, Any]] = field(default_factory=dict)
    rules: list[RuleOutcome] = field(default_factory=list)
    industry: dict[str, Any] = field(default_factory=dict)
    graph: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    subject_issues: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    industry_panel: dict[str, Any] | None = None
    chain_panel: dict[str, Any] | None = None
    decompositions: list[dict[str, Any]] = field(default_factory=list)
    model_mode: str = "mock"
    source_mode: str = "replay"
    doc_ids: list[str] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    ai_brief: str | None = None
    chain_brief: str | None = None


def _issue_visible(issue: dict[str, Any], visible_docs: set[str]) -> bool:
    """问题记录若只引用了本次不可见的文档，就不进入报告的数据质量章节。"""
    ids: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "document_id" and isinstance(v, str):
                    ids.add(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(issue.get("context") or {})
    return not ids or ids <= visible_docs


def build_context(*, subject: dict[str, Any], peers: list[dict[str, Any]], years: list[int],
                  as_of: str, finance: FinanceBundle, peer_finance: dict[str, FinanceBundle],
                  industry: dict[str, Any], graph: dict[str, Any], model_mode: str,
                  source_mode: str, doc_ids: list[str]) -> ReportContext:
    ctx = ReportContext(subject=subject, peers=peers, years=years, as_of=as_of, finance=finance,
                        peer_finance=peer_finance, industry=industry, graph=graph,
                        model_mode=model_mode, source_mode=source_mode, doc_ids=doc_ids)
    latest = max(years)
    # 同业基准
    for code in ("gross_margin", "debt_asset_ratio", "ocf_margin", "parent_net_margin"):
        med, n, detail = peer_median(finance, [p["entity_id"] for p in peers], latest, code)
        ctx.bench[code] = {"value": med, "n": n, "detail": detail, "year": latest,
                           "ref": f"bench:{code}:{latest}" if med is not None else None}
    # 规则
    issues = repo.open_issues()
    visible_docs = set(doc_ids)
    ctx.issues = [i for i in issues if i["status"] == "OPEN" and _issue_visible(i, visible_docs)]
    subject_issues = [i for i in ctx.issues if subject["entity_id"] in i["key"]]
    ctx.subject_issues = subject_issues
    from . import sectors as _sectors
    ind_id = subject.get("industry_id")
    if ind_id:
        try:
            ctx.industry_panel = _sectors.industry_panel(ind_id, list(years))
            ctx.chain_panel = _sectors.chain_with_metrics(ind_id, max(years))
        except Exception:
            ctx.industry_panel = None
            ctx.chain_panel = None
    ctx.gaps = [i for i in ctx.issues
                if i["type"] in ("COVERAGE_GAP", "SCANNED_UNSUPPORTED")
                and (i["context"].get("document_id") or "") in set(doc_ids)]
    gm_med, gm_n, _ = peer_median(finance, [p["entity_id"] for p in peers], latest, "gross_margin")
    fact_values = {code: (D(slot["value_text"]) if slot and slot.get("value_text") else None)
                   for code, slot in finance.verify.year_facts.get(latest, {}).items()}
    fact_refs = {code: (slot["resolution"]["chosen_fact_id"] or slot["resolution"]["resolution_id"])
                 for code, slot in finance.verify.year_facts.get(latest, {}).items()}
    ctx.rules = evaluate(
        metrics=finance.metrics.get(latest, {}),
        peer_median={c: (ctx.bench[c]["value"]) for c in ctx.bench},
        peer_n=ctx.bench["gross_margin"]["n"],
        issues=subject_issues,
        pack=load_pack("config/rules/operating_watch_v1.yaml"),
        fact_values=fact_values,
        fact_refs=fact_refs,
    )
    ctx.decompositions = gross_margin_decomposition(finance, latest)
    return ctx


# --------------------------------------------------------------------------- #
# 分部毛利率变化恒等分解（只在勾稽通过时执行）
# --------------------------------------------------------------------------- #

def gross_margin_decomposition(bundle: FinanceBundle, year: int) -> list[dict[str, Any]]:
    from ..domain.keys import FactKey

    def seg(year_: int, code: str) -> Decimal | None:
        for k, res in bundle.verify.resolutions.items():
            p = FactKey.parse(k)
            if (p.field_code == code and p.business_scope.startswith("segment")
                    and p.period_end.startswith(str(year_)) and res["decision"] != "BLOCKED"):
                v = next((o["value_text"] for o in res["observed_values"] if o["fact_id"] == res["chosen_fact_id"]), None)
                return D(v) if v else None
        return None

    out: list[dict[str, Any]] = []
    parts = [("beer", "啤酒业务", "seg_revenue_beer", "seg_cost_beer"),
             ("other", "其他业务", "seg_revenue_other", "seg_cost_other")]
    w0, w1, m0, m1 = {}, {}, {}, {}
    total1 = bundle.get("gross_margin", year)
    total0 = bundle.get("gross_margin", year - 1)
    for key, label, rc, cc in parts:
        r0, c0, r1, c1 = seg(year - 1, rc), seg(year - 1, cc), seg(year, rc), seg(year, cc)
        if None in (r0, c0, r1, c1) or r0 == 0 or r1 == 0:
            return []
        m0[key] = (r0 - c0) / r0
        m1[key] = (r1 - c1) / r1
        w0[key] = r0
        w1[key] = r1
    s0, s1 = sum(w0.values()), sum(w1.values())
    for k in w0:
        w0[k] = w0[k] / s0
        w1[k] = w1[k] / s1
    structure = sum((w1[k] - w0[k]) * m0[k] for k in w0)
    margin = sum(w1[k] * (m1[k] - m0[k]) for k in w0)
    actual = (m1["beer"] * w1["beer"] + m1["other"] * w1["other"]) - (m0["beer"] * w0["beer"] + m0["other"] * w0["other"])
    residual = actual - (structure + margin)
    if abs(residual) * 100 > D("0.05"):
        return []
    out.append({
        "year": year, "kind": "gross_margin_bridge",
        "structure_pp": str((structure * 100).quantize(D("0.01"))),
        "margin_pp": str((margin * 100).quantize(D("0.01"))),
        "residual_pp": str((residual * 100).quantize(D("0.001"))),
        "total_pp": str((actual * 100).quantize(D("0.01"))),
        "segments": [{"key": k, "w0": str(w0[k].quantize(D("0.0001"))), "w1": str(w1[k].quantize(D("0.0001"))),
                      "m0": str((m0[k] * 100).quantize(D("0.01"))), "m1": str((m1[k] * 100).quantize(D("0.01")))}
                     for k in w0],
        "note": "结构项 = Σ(w₁−w₀)·m₀；分部毛利率项 = Σ w₁·(m₁−m₀)。只解释变动来源，不证明因果。",
        "check": "分部收入/成本合计与合并总额勾稽通过，且残差 ≤ 0.05pp",
    })
    return out


# --------------------------------------------------------------------------- #
# Claim 渲染
# --------------------------------------------------------------------------- #

def _resolver(ctx: ReportContext) -> Callable[[str, str], tuple[str, str] | None]:
    latest = max(ctx.years)
    prev = latest - 1

    def fact_dec(code: str, year: int) -> Decimal | None:
        slot = ctx.finance.verify.year_facts.get(year, {}).get(code)
        try:
            return D(slot["value_text"]) if slot and slot.get("value_text") else None
        except Exception:
            return None

    def metric_dec(code: str, year: int) -> Decimal | None:
        m = ctx.finance.get(code, year)
        try:
            return D(m.value_text) if m and m.value_text else None
        except Exception:
            return None

    def yoy(cur: Decimal | None, prior: Decimal | None) -> Decimal | None:
        if cur is None or prior in (None, D(0)):
            return None
        return ((cur / prior - 1) * D(100)).quantize(D("0.01"))

    def gap(a: Decimal | None, b: Decimal | None) -> Decimal | None:
        if a is None or b is None:
            return None
        return (a - b).quantize(D("0.01"))

    def fp(v: Decimal | None) -> str | None:
        return f"{v:+.2f}%" if v is not None else None

    def fpp(v: Decimal | None) -> str | None:
        return f"{v:+.2f}pp" if v is not None else None

    recv_yoy = yoy(fact_dec("receivables", latest), fact_dec("receivables", prev))
    inv_yoy = yoy(fact_dec("inventories", latest), fact_dec("inventories", prev))
    np_yoy = yoy(fact_dec("net_profit_total", latest), fact_dec("net_profit_total", prev))
    ocf_yoy = yoy(fact_dec("operating_cashflow", latest), fact_dec("operating_cashflow", prev))
    cost_yoy = yoy(fact_dec("operating_cost", latest), fact_dec("operating_cost", prev))
    rev_abs = fact_dec("revenue", latest)
    recv_abs = fact_dec("receivables", latest)
    recv_share = ((recv_abs / rev_abs * D(100)).quantize(D("0.01"))
                  if rev_abs not in (None, D(0)) and recv_abs is not None else None)
    rev_yoy = metric_dec("revenue_yoy", latest)
    rev_yoy_pct = rev_yoy * D(100) if rev_yoy is not None else None
    gm = metric_dec("gross_margin", latest)
    dar = metric_dec("debt_asset_ratio", latest)
    cc_cur = metric_dec("cash_conversion", latest)
    cc_prev = metric_dec("cash_conversion", prev)
    b_gm = ctx.bench.get("gross_margin", {}).get("value")
    b_dar = ctx.bench.get("debt_asset_ratio", {}).get("value")
    b_gm_dec = D(str(b_gm)) if b_gm is not None else None
    b_dar_dec = D(str(b_dar)) if b_dar is not None else None
    summary = (ctx.industry_panel or {}).get("summary") or []
    last_ind = summary[-1] if summary else {}
    prev_ind = summary[-2] if len(summary) > 1 else {}
    ind_growth = D(str(last_ind["growth_pct"])) if last_ind.get("growth_pct") is not None else None
    ind_gm = D(str(last_ind["gross_margin_pct"])) if last_ind.get("gross_margin_pct") is not None else None
    ind_gm_prev = D(str(prev_ind["gross_margin_pct"])) if prev_ind.get("gross_margin_pct") is not None else None
    ind_gm_delta = gap(ind_gm, ind_gm_prev)
    gm_gap_pp = gap(gm * D(100) if gm is not None else None, b_gm_dec * D(100) if b_gm_dec is not None else None)
    dar_gap_pp = gap(dar * D(100) if dar is not None else None, b_dar_dec * D(100) if b_dar_dec is not None else None)
    gm_vs_sample_pp = gap(gm * D(100) if gm is not None else None, ind_gm)
    rev_vs_sample_pp = gap(rev_yoy_pct, ind_growth)
    cc_delta_pp = gap(cc_cur * D(100) if cc_cur is not None else None,
                      cc_prev * D(100) if cc_prev is not None else None)
    cp = ctx.chain_panel or {}
    nodes = cp.get("nodes") or ctx.graph.get("nodes", [])
    edges = cp.get("edges") or ctx.graph.get("edges", [])
    structural_n = sum(1 for e in edges if e.get("status") == "STRUCTURAL")

    def resolve(kind: str, ref: str) -> tuple[str, str] | None:
        name, _, at = ref.partition("@")
        year = int(at) if at.isdigit() else latest
        if kind == "m":
            m = ctx.finance.get(name, year)
            if not m or m.status != MetricStatus.OK or not m.display:
                return None
            return m.display, m.result_id
        if kind == "f":
            slot = ctx.finance.verify.year_facts.get(year, {}).get(name)
            if not slot or not slot["value_text"]:
                return None
            return cny_yi(D(slot["value_text"])), slot["resolution"]["chosen_fact_id"] or slot["resolution"]["resolution_id"]
        if kind == "x":
            b = ctx.bench.get(name)
            if not b or b["value"] is None:
                return None
            disp = pct(b["value"]) if FORMULAS[name].unit == "fraction" else str(b["value"])
            return f"{disp}（n={b['n']}）", b["ref"] or f"bench:{name}:{year}"
        if kind == "i":
            ind_map = {"beer_output": ("output", "display"), "beer_output_yoy": ("output", "yoy"),
                       "beer_revenue_above_scale": ("revenue_above_scale", "display"),
                       "beer_revenue_yoy": ("revenue_above_scale", "yoy")}
            if name not in ind_map:
                return None
            series_key, mode = ind_map[name]
            for f in ctx.industry.get(series_key, []):
                if f["period"] != str(year):
                    continue
                if mode == "yoy":
                    if f.get("yoy_pct") is None:
                        return None
                    return f"{f['yoy_pct']}%", f["location"]
                return f["display"], f["location"]
            return None
        if kind == "r":
            rule = next((r for r in ctx.rules if r.rule_id == name), None)
            if not rule:
                return None
            return rule.headline, f"rule:{rule.rule_id}"
        if kind == "p":
            refs = ctx.industry.get("policy_refs") or []
            if not refs:
                return None
            loc = refs[0]["locations"][0] if refs[0]["locations"] else None
            return refs[0]["title"], (loc["location_id"] if loc else refs[0]["document_id"])
        if kind == "c":
            dec = ctx.decompositions[0] if ctx.decompositions else {}
            mapping = {
                "entity": ctx.subject["name"],
                "as_of": ctx.as_of,
                "window": f"{min(ctx.years)}–{max(ctx.years)} 财年",
                "peer_n": str(max(len(ctx.peers), 0)),
                "years": f"{min(ctx.years)}–{max(ctx.years)}",
                "node_n": str(len(nodes)),
                "edge_n": str(len(edges)),
                "structural_n": str(structural_n),
                "recv_yoy": fp(recv_yoy) or "—",
                "inv_yoy": fp(inv_yoy) or "—",
                "np_yoy": fp(np_yoy) or "—",
                "ocf_yoy": fp(ocf_yoy) or "—",
                "cost_yoy": fp(cost_yoy) or "—",
                "recv_share_pct": f"{recv_share:.2f}%" if recv_share is not None else "—",
                "recv_gap_pp": fpp(gap(recv_yoy, rev_yoy_pct)) or "—",
                "cc_delta_pp": fpp(cc_delta_pp) or "—",
                "gm_gap_pp": fpp(gm_gap_pp) or "—",
                "dar_gap_pp": fpp(dar_gap_pp) or "—",
                "ind_growth": fp(ind_growth) or "—",
                "ind_gm_delta_pp": fpp(ind_gm_delta) or "—",
                "gm_vs_sample_pp": fpp(gm_vs_sample_pp) or "—",
                "rev_vs_sample_pp": fpp(rev_vs_sample_pp) or "—",
                "triggered_n": str(sum(1 for r in ctx.rules if r.status.value == "TRIGGERED")),
                "noteval_n": str(sum(1 for r in ctx.rules if r.status.value == "NOT_EVALUABLE")),
                "rule_n": str(len(ctx.rules)),
                "conflict_n": str(sum(1 for i in ctx.subject_issues if i["type"] == "NUMERIC_CONFLICT"
                                       and i["severity"] == "BLOCKING")),
                "rounding_n": str(sum(1 for i in ctx.subject_issues if i["type"] == "ROUNDING_COMPATIBLE")),
                "scope_n": str(sum(1 for i in ctx.subject_issues if i["type"] == "SCOPE_MISMATCH")),
                "gap_n": str(len(ctx.gaps)),
                "doc_n": str(len(ctx.doc_ids)),
                "blocked_n": str(len(ctx.blocked)),
                "model_mode": ctx.model_mode,
                "source_mode": ctx.source_mode,
                "decomp_struct": dec.get("structure_pp", "-"),
                "decomp_margin": dec.get("margin_pp", "-"),
                "decomp_resid": dec.get("residual_pp", "-"),
            }
            # 上下文 token（实体名、截止日、计数）不是证据，不进 reference_ids，
            # 否则前端会冒出一堆点不开的引用
            return mapping.get(name), ""
        return None

    return resolve


def _instantiate(template: str, ctx: ReportContext, resolve) -> str:
    """把 {{c:...}} 与数值 token 一起渲染；c: 用于把日期/年份也纳入绑定区间。"""
    return render(template, lambda k, r: resolve(k, r)).text


def build_claims(ctx: ReportContext) -> tuple[dict[str, list[Claim]], list[dict[str, Any]]]:
    resolve = _resolver(ctx)
    by_section: dict[str, list[Claim]] = {k: [] for k in SECTION_ORDER}
    for spec in TEMPLATES:
        if not spec.applies(ctx):
            continue
        rendered = render(spec.template, resolve)
        findings = list(rendered.findings) + check_numeric_claim(spec.kind, rendered.text)
        verdict = Verdict.PASS
        for f in findings:
            if f["level"] == "BLOCK":
                verdict = Verdict.BLOCK
            elif f["level"] == "WARN" and verdict != Verdict.BLOCK:
                verdict = Verdict.WARN
        cid = claim_version_id(spec.key, spec.template, {k: v for k, v in spec.slots.items()},
                               rendered.refs, rendered.text, verdict.value)
        claim = Claim(
            claim_version_id=cid, claim_key=spec.key, kind=spec.kind, template=spec.template,
            slots=dict(spec.slots), reference_ids=rendered.refs, verdict=verdict,
            section_key=spec.section, text=rendered.text, findings=findings,
        )
        by_section[spec.section].append(claim)
        repo.insert_claim({
            "claim_version_id": claim.claim_version_id, "claim_key": claim.claim_key,
            "kind": claim.kind.value, "template": claim.template, "slots": claim.slots,
            "reference_ids": claim.reference_ids, "verdict": claim.verdict.value,
            "section_key": claim.section_key, "text": claim.text,
            "findings": claim.findings, "created_at": utcnow(),
        })
        if verdict == Verdict.BLOCK:
            ctx.blocked.append({"claim_key": spec.key, "text": rendered.text,
                                "findings": findings, "section": spec.section})
    return by_section, ctx.blocked


# --------------------------------------------------------------------------- #
# 章节组装
# --------------------------------------------------------------------------- #

def _kpi(label: str, value: str | None, *, ref: str | None, unit: str = "", status: str = "OK",
         confidence: str = "HIGH", formula: str = "", basis: str = "") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "ref": ref, "status": status,
            "confidence": confidence, "formula": formula, "basis": basis}


def _ref_index(ctx: ReportContext, claims: list[Claim]) -> dict[str, dict[str, str]]:
    """给前端用的引用标签：{ref: {kind, label}}。只包含本节真正用到的引用，
    这样其它章节的 hash 不会被无关的数值变化带脏。"""
    metrics: dict[str, Any] = {}
    for ms in ctx.finance.metrics.values():
        for m in ms.values():
            metrics[m.result_id] = m
    for bundle in ctx.peer_finance.values():
        for ms in bundle.metrics.values():
            for m in ms.values():
                metrics[m.result_id] = m
    facts: dict[str, Any] = {}
    for fk, res in ctx.finance.verify.resolutions.items():
        parts = fk.split("|")
        for o in res["observed_values"]:
            facts[o["fact_id"]] = (parts[1], parts[2][:4])
    rules = {f"rule:{r.rule_id}": r for r in ctx.rules}
    out: dict[str, dict[str, str]] = {}
    for c in claims:
        for ref in c.reference_ids:
            if ref in out:
                continue
            if ref in metrics:
                m = metrics[ref]
                out[ref] = {"kind": "指标", "label": f"{FORMULAS[m.metric_code].label} {m.display or '—'}"}
            elif ref in facts:
                field, year = facts[ref]
                label = field
                try:
                    from ..domain.fields import FIELDS
                    label = FIELDS[field].label
                except Exception:
                    pass
                out[ref] = {"kind": "原表", "label": f"{label} {year}"}
            elif ref.startswith("rule:") and ref in rules:
                out[ref] = {"kind": "规则", "label": rules[ref].label}
            elif ref.startswith("bench:"):
                out[ref] = {"kind": "同业", "label": "同业中位数"}
            elif ref.startswith("ctx:"):
                out[ref] = {"kind": "口径", "label": ref.split(":", 1)[1]}
            elif ref.startswith("loc:"):
                out[ref] = {"kind": "原件", "label": "原件页"}
            else:
                out[ref] = {"kind": "引用", "label": ref[:18]}
    return out


def compose_sections(ctx: ReportContext, claims: dict[str, list[Claim]]) -> dict[str, dict[str, Any]]:
    latest = max(ctx.years)
    sections: dict[str, dict[str, Any]] = {}

    def paras(key: str) -> list[dict[str, Any]]:
        return [{"type": "para", "text": c.text, "claim": c.claim_key, "refs": c.reference_ids,
                 "kind": c.kind.value, "verdict": c.verdict.value}
                for c in claims.get(key, []) if c.verdict != Verdict.BLOCK]

    # ---- overview ----
    fin = ctx.finance
    kpis = []
    for code, label in (("revenue_yoy", "营业收入同比"), ("gross_margin", "毛利率"),
                        ("ocf_margin", "经营现金流/营收"), ("debt_asset_ratio", "资产负债率")):
        m = fin.get(code, latest)
        kpis.append(_kpi(label, m.display if m else None, ref=m.result_id if m else None,
                         status=m.status.value if m else "MISSING_INPUT",
                         confidence=m.confidence.value if m else "LOW",
                         formula=FORMULAS[code].formula_text))
    sections["overview"] = {
        "key": "overview", "title": SECTION_TITLES["overview"],
        "paragraphs": paras("overview"), "kpis": kpis,
        "ai_brief": ctx.ai_brief,
        "highlights": [{"rule": r.rule_id, "status": r.status.value, "headline": r.headline,
                        "severity": r.severity} for r in ctx.rules],
    }

    # ---- industry ----
    ind_blocks = paras("industry")
    panel = ctx.industry_panel
    if panel:
        summary = panel.get("summary") or []
        members = panel.get("members") or []
        last_row = summary[-1] if summary else {}
        prev_row = summary[-2] if len(summary) > 1 else {}
        names = "、".join(m["name"] for m in members)
        ind_paras = [
            f"样本为 {names}，共 {last_row.get('n', 0)} 家；"
            f"FY{last_row.get('year', max(ctx.years))} 样本营业收入合计 "
            f"{(last_row.get('revenue_sum') or 0) / 1e8:,.2f} 亿元"
            + (f"，同比 {last_row['growth_pct']:+.2f}%。" if last_row.get("growth_pct") is not None else "。"),
            f"样本毛利率 {last_row.get('gross_margin_pct') or '—'}%，"
            + (f"较上年 {(last_row.get('gross_margin_pct') or 0) - (prev_row.get('gross_margin_pct') or 0):+.2f} 个百分点；"
               if prev_row.get("gross_margin_pct") is not None else "")
            + "样本内公司的差异见同业章节，合计值不代表行业总量。",
            "以上均为样本口径：只覆盖样本内公司，不能外推为行业规模或市场份额；"
            "样本数据来自第三方结构化接口，逐项口径与原件研究分开标注。",
        ]
        sections["industry"] = {
            "key": "industry", "title": SECTION_TITLES["industry"],
            "paragraphs": [{"text": t, "refs": []} for t in ind_paras] + ind_blocks,
            "sample": [{"year": s_["year"], "revenue_sum": s_["revenue_sum"],
                        "growth_pct": s_["growth_pct"], "gross_margin_pct": s_["gross_margin_pct"],
                        "debt_ratio_pct": s_["debt_ratio_pct"], "n": s_["n"]} for s_ in summary],
            "members": [{"name": m["name"], "entity_id": m["entity_id"], "ticker": m["ticker"],
                         "role": m.get("role"), "tag": m.get("tag"),
                         "latest_revenue": m.get("latest_revenue"), "latest_gm": m.get("latest_gm")}
                        for m in members],
            "series": [],
            "policy": [],
            "n_note": "样本合计 ≠ 行业总量；n<2 时不输出中位数基准。",
        }
    else:
        sections["industry"] = {
            "key": "industry", "title": SECTION_TITLES["industry"],
            "paragraphs": ind_blocks, "series": [], "policy": [],
            "n_note": "行业样本未接入。",
        }

    # ---- operations ----
    sections["operations"] = {
        "key": "operations", "title": SECTION_TITLES["operations"],
        "paragraphs": paras("operations"),
        "decomposition": ctx.decompositions,
        "drivers": [
            {"name": "营业成本", "value": _fmt_cny(fin.verify.year_facts.get(latest, {}).get("operating_cost")),
             "ref": _fact_ref(fin, "operating_cost", latest)},
            {"name": "营业收入", "value": _fmt_cny(fin.verify.year_facts.get(latest, {}).get("revenue")),
             "ref": _fact_ref(fin, "revenue", latest)},
        ],
    }

    # ---- financials ----
    rows = []
    for code in ("revenue_yoy", "gross_margin", "parent_net_margin", "debt_asset_ratio",
                 "ocf_margin", "cash_conversion", "receivables_days", "inventory_days",
                 "gross_margin_delta_pp", "asset_ratio_delta_pp", "ocf_margin_delta_pp"):
        spec = FORMULAS[code]
        series = []
        for y in ctx.years:
            m = fin.get(code, y)
            series.append({"year": y, "value": (float(m.value_text) if m and m.value_text else None),
                           "display": m.display if m else None, "ref": m.result_id if m else None,
                           "status": m.status.value if m else "MISSING_INPUT"})
        latest_m = fin.get(code, latest)
        rows.append({"metric_code": code, "label": spec.label, "unit": spec.unit,
                     "formula": spec.formula_text, "formula_id": f"{code}:v{spec.version}",
                     "series": series,
                     "status": latest_m.status.value if latest_m else "MISSING_INPUT",
                     "confidence": latest_m.confidence.value if latest_m else "LOW",
                     "missing_reason": latest_m.missing_reason if latest_m else "未计算"})
    sections["financials"] = {
        "key": "financials", "title": SECTION_TITLES["financials"],
        "paragraphs": paras("financials"), "rows": rows,
        "note": "数值以比例存储（0.4136），展示保留两位小数；pp 指标已乘 100，前端不再换算。",
    }

    # ---- peer ----
    peer_rows = []
    for code in ("gross_margin", "debt_asset_ratio", "ocf_margin"):
        cells = []
        sm = fin.get(code, latest)
        cells.append({"entity_id": ctx.subject["entity_id"], "name": ctx.subject["name"],
                      "display": sm.display if sm else None, "status": sm.status.value if sm else "MISSING_INPUT",
                      "ref": sm.result_id if sm else None})
        detail = {d["entity_id"]: d for d in ctx.bench.get(code, {}).get("detail", [])}
        for p in ctx.peers:
            pm = ctx.peer_finance.get(p["entity_id"])
            m = pm.get(code, latest) if pm else None
            ok = bool(m and m.status.value == "OK")
            d = detail.get(p["entity_id"], {})
            cells.append({"entity_id": p["entity_id"], "name": p["name"],
                          "display": (m.display if ok else d.get("display")),
                          "status": "OK" if ok else (d.get("status") or (m.status.value if m else "MISSING_INPUT")),
                          "source": "annual_report" if ok else d.get("source"),
                          "ref": m.result_id if ok and m else None})
        peer_rows.append({"metric_code": code, "label": FORMULAS[code].label, "cells": cells,
                          "median": ctx.bench.get(code, {}).get("value"),
                          "median_display": (pct(ctx.bench[code]["value"])
                                             if ctx.bench.get(code, {}).get("value") is not None
                                             and FORMULAS[code].unit == "fraction" else None),
                          "n": ctx.bench.get(code, {}).get("n", 0)})
    sections["peer"] = {
        "key": "peer", "title": SECTION_TITLES["peer"],
        "paragraphs": paras("peer"), "rows": peer_rows, "year": latest,
        "n_note": "n<2 时不输出基准、不触发对标规则。",
    }

    # ---- risk ----
    sections["risk"] = {
        "key": "risk", "title": SECTION_TITLES["risk"],
        "paragraphs": paras("risk"),
        "rules": [r.as_dict() for r in ctx.rules],
        "matrix": [{"rule_id": r.rule_id, "status": r.status.value, "evidence_n": len(r.input_ids),
                    "missing": r.missing} for r in ctx.rules],
    }

    # ---- chain ----
    cp = ctx.chain_panel
    if cp:
        role_cn = {"upstream": "上游原料", "packaging": "包材辅材", "core": "中游制造",
                   "downstream": "渠道服务", "demand": "终端需求"}
        roles = {}
        for n in cp["nodes"]:
            roles.setdefault(n["role"], []).append(n["name"])
        chain_paras = [
            f"产业链共 {len(cp['nodes'])} 个节点、{len(cp['edges'])} 组关系，"
            + "、".join(f"{role_cn.get(k, k)} {len(v)} 个" for k, v in roles.items()) + "。",
            "图谱按上游原料、包材辅材、中游制造、渠道服务、终端需求五层组织；"
            "每条边都标注依据与关系类型，行业常识、年报披露与推断关系分开记录。",
            "样本公司位于中游制造；上下游关系标注依据（行业公开资料），"
            "未具名供应商与客户不编造交易关系。",
            "上游原料与包材、下游渠道与终端共同决定毛利率和回款节奏；"
            "把成本端与渠道端放在一起看，才能区分毛利率改善是采购红利还是产品结构改善。",
            "当前毛利率改善与应收增速加快同时出现：前者更接近成本或结构因素，"
            "后者更接近渠道信用或备货变化；两条线需要分别核对，不能互相替代。",
            "节点带财务数据的仅限上市公司；点击可看其最近一年营收与毛利率。",
        ]
        sections["chain"] = {
            "key": "chain", "title": SECTION_TITLES["chain"],
            "paragraphs": [{"text": t, "refs": []} for t in chain_paras],
            "nodes": cp["nodes"], "edges": cp["edges"], "metrics": cp.get("metrics", {}),
            "ai_brief": ctx.chain_brief,
            "unbuilt": [],
            "n_note": "边的关系类型与依据随图返回；推断关系不应被当作披露事实。",
        }
    else:
        sections["chain"] = {
            "key": "chain", "title": SECTION_TITLES["chain"],
            "paragraphs": paras("chain"),
            "nodes": ctx.graph.get("nodes", []), "edges": ctx.graph.get("edges", []),
            "unbuilt": ctx.graph.get("unbuilt", []),
        }

    # ---- data quality ----
    # 同原因的重复问题合并成一条，带次数与页码；否则真实语料上会出现
    # 十几条一模一样的「声明了资产负债表但没有表格」。
    groups = group_issues(ctx.subject_issues or ctx.issues)
    gap_groups = [g for g in groups if g["type"] in ("COVERAGE_GAP", "SCANNED_UNSUPPORTED",
                                                     "STATEMENT_NOT_FOUND", "HEADER_UNRESOLVED",
                                                     "PAGE_RUN_IGNORED")]
    sections["data_quality"] = {
        "key": "data_quality", "title": SECTION_TITLES["data_quality"],
        "paragraphs": paras("data_quality"),
        "groups": groups,
        "summary": issue_summary(groups),
        "peer_issue_n": max(0, len(ctx.issues) - len(ctx.subject_issues)),
        "gaps": gap_groups,
        "blocked_claims": ctx.blocked,
        "coverage": [{"label": "原件", "value": len(ctx.doc_ids), "unit": "份"},
                     {"label": "已核验事实", "value": len(fin.verify.resolutions), "unit": "条"},
                     {"label": "覆盖财年", "value": len(ctx.years), "unit": "年"}],
        "source_mode": ctx.source_mode, "model_mode": ctx.model_mode,
    }
    for key, sec in sections.items():
        sec["ref_index"] = _ref_index(ctx, claims.get(key, []))
    return sections


def _fmt_cny(slot: dict[str, Any] | None) -> str | None:
    if not slot or not slot.get("value_text"):
        return None
    return cny_yi(D(slot["value_text"]))


def _collect_refs(obj: Any, acc: set[str] | None = None) -> set[str]:
    """把章节内容里所有 ref / refs / input_ids 收集起来（用于登记章节级依赖）。"""
    acc = acc if acc is not None else set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("ref", "refs", "input_ids"):
                if isinstance(v, str) and v:
                    acc.add(v)
                elif isinstance(v, list):
                    acc.update(x for x in v if isinstance(x, str) and x)
            else:
                _collect_refs(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _collect_refs(v, acc)
    return acc


def _fact_ref(fin: FinanceBundle, code: str, year: int) -> str | None:
    slot = fin.verify.year_facts.get(year, {}).get(code)
    if not slot:
        return None
    return slot["resolution"]["chosen_fact_id"] or slot["resolution"]["resolution_id"]


# --------------------------------------------------------------------------- #
# 依赖图
# --------------------------------------------------------------------------- #

def build_dependencies(ctx: ReportContext, sections: dict[str, dict],
                       claims: dict[str, list[Claim]]) -> list[tuple[str, str, str]]:
    edges: list[tuple[str, str, str]] = []
    metric_index: dict[str, str] = {}
    fact_index: dict[str, str] = {}
    for bundle in [ctx.finance, *ctx.peer_finance.values()]:
        for ms in bundle.metrics.values():
            for m in ms.values():
                metric_index[m.result_id] = m.metric_key
        for fk, res in bundle.verify.resolutions.items():
            for o in res["observed_values"]:
                fact_index[o["fact_id"]] = fk
            if res.get("chosen_fact_id"):
                fact_index[res["chosen_fact_id"]] = fk

    for sec, cs in claims.items():
        for c in cs:
            for ref in c.reference_ids:
                if ref in metric_index:
                    edges.append((f"metric:{metric_index[ref]}", f"claim:{c.claim_key}", "value"))
                elif ref in fact_index:
                    edges.append((f"fact:{fact_index[ref]}", f"claim:{c.claim_key}", "value"))
                elif ref.startswith(("rule:", "bench:")):
                    edges.append((ref, f"claim:{c.claim_key}", "value"))
                elif ref.startswith("ctx:"):
                    continue
                else:
                    edges.append((f"ref:{ref}", f"claim:{c.claim_key}", "value"))
            edges.append((f"claim:{c.claim_key}", f"section:{sec}", "value"))

    for sec in sections:
        edges.append((f"section:{sec}", "summary", "value"))

    # 事实 → 指标；并登记「覆盖哨兵」，让「以前没有的新事实」也能命中下游
    for year, ms in ctx.finance.metrics.items():
        for code, m in ms.items():
            spec = FORMULAS[code]
            for inp in m.inputs:
                if not inp.fact_id:
                    continue
                if inp.fact_id in metric_index:
                    edges.append((f"metric:{metric_index[inp.fact_id]}", f"metric:{m.metric_key}", "value"))
                elif inp.fact_id in fact_index:
                    edges.append((f"fact:{fact_index[inp.fact_id]}", f"metric:{m.metric_key}", "value"))
            if code.endswith("_delta_pp"):
                continue
            for slot in spec.slots:
                fy = year - 1 if slot == "revenue_prev" else year
                field = "revenue" if slot == "revenue_prev" else slot
                edges.append((f"coverage:{ctx.subject['entity_id']}:{fy}:{field}",
                              f"metric:{m.metric_key}", "coverage"))

    # 指标 → 规则：规则吃了哪些指标，指标变了规则就要重跑
    for r in ctx.rules:
        for ref in r.input_ids:
            if ref in metric_index:
                edges.append((f"metric:{metric_index[ref]}", f"rule:{r.rule_id}", "value"))
            elif ref in fact_index:
                edges.append((f"fact:{fact_index[ref]}", f"rule:{r.rule_id}", "value"))
        edges.append((f"rule:{r.rule_id}", f"section:risk", "value"))

    # 章节实际展示了哪些对象，就依赖哪些对象
    # （表格、KPI、序列里的 ref 不是 Claim 的引用，但同样是依赖）
    for key, sec in sections.items():
        for ref in _collect_refs(sec):
            if ref in metric_index:
                edges.append((f"metric:{metric_index[ref]}", f"section:{key}", "value"))
            elif ref in fact_index:
                edges.append((f"fact:{fact_index[ref]}", f"section:{key}", "value"))
            elif ref.startswith(("rule:", "bench:")):
                edges.append((ref, f"section:{key}", "value"))

    for year in ctx.years:
        for code in ("gross_margin", "debt_asset_ratio", "ocf_margin"):
            edges.append((f"peer_set:{ctx.subject['entity_id']}:{year}:{code}", f"bench:{code}:{year}", "membership"))
    for p in ctx.industry.get("output", []):
        edges.append((f"topic:industry:beer_cn_a:{p['period']}", "claim:ind_output", "topic"))
    return edges


# --------------------------------------------------------------------------- #
# 版本发布
# --------------------------------------------------------------------------- #

def content_hash_of(sections: dict[str, dict[str, Any]]) -> str:
    """章节集合的内容指纹：只由各章节内容决定，与时间、版本号无关。"""
    return hashlib.sha256(
        "|".join(f"{k}:{section_content_hash(sections[k])}" for k in SECTION_ORDER).encode()
    ).hexdigest()


def report_id_for(entity_id: str, years: Sequence[int]) -> str:
    return f"rpt:{entity_id}:{min(years)}-{max(years)}"


def publish_version(ctx: ReportContext, claims: dict[str, list[Claim]], *,
                    report_id: str, base_version_no: int | None = None,
                    base_sections: list[dict[str, Any]] | None = None,
                    changed_sections: set[str] | None = None,
                    state: str = "published", label: str = "") -> dict[str, Any]:
    sections = compose_sections(ctx, claims)
    if base_version_no is None:
        base_version_no = repo.head_version(report_id)
    if base_sections is None and base_version_no is not None:
        base_sections = repo.sections_of(report_id, base_version_no)
    ver = (base_version_no or 0) + 1
    base_map = {s["section_key"]: s for s in (base_sections or [])}

    written: list[dict[str, Any]] = []
    reused: list[str] = []
    for key in SECTION_ORDER:
        content = sections[key]
        h = section_content_hash(content)
        old = base_map.get(key)
        if old and old["content_hash"] == h:
            sid = old["section_version_id"]
            reused.append(key)
        else:
            sid = content_id("sec", {"r": report_id, "v": ver, "k": key, "h": h})
        written.append({"section_key": key, "section_version_id": sid, "content_hash": h,
                        "reused": key in reused, "content": content,
                        "claim_ids": [c.claim_version_id for c in claims.get(key, [])
                                      if c.verdict != Verdict.BLOCK]})

    content_hash = content_hash_of(sections)

    # 无语义变更就不升版本：重复跑同一份输入必须返回 NO_CHANGE
    head = repo.head_version(report_id)
    if state == "published" and head is not None:
        head_row = repo.get_report_version(report_id, head)
        if head_row and head_row["content_hash"] == content_hash:
            return {"report_id": report_id, "version_no": head, "content_hash": content_hash,
                    "sections": [{k: w[k] for k in ("section_key", "section_version_id",
                                                     "content_hash", "reused")} for w in written],
                    "reused_sections": reused, "changed_sections": [], "no_change": True,
                    "input_fingerprint": head_row["input_fingerprint"], "state": head_row["state"]}

    for w in written:
        repo.insert_section({
            "section_version_id": w["section_version_id"], "section_key": w["section_key"],
            "report_id": report_id, "version_no": ver, "content": w["content"],
            "content_hash": w["content_hash"], "claim_ids": w["claim_ids"],
        })

    evidence_ids = sorted({o["fact_id"] for res in ctx.finance.verify.resolutions.values()
                           for o in res["observed_values"]})
    fingerprint = report_fingerprint(
        parser_version=PARSER_VERSION, extractor_version="extract/1.2.0",
        model_config={"mode": ctx.model_mode}, prompt_version=PROMPT_VERSION,
        rules_version="rules/v1.0.0", evidence_ids=evidence_ids, as_of=ctx.as_of,
        workflow_version=WORKFLOW_VERSION,
    )
    repo.ensure_report(report_id, ctx.subject["entity_id"])
    repo.insert_report_version({
        "report_id": report_id, "version_no": ver,
        "base_version_id": f"{report_id}@v{base_version_no}" if base_version_no else None,
        "input_fingerprint": fingerprint, "as_of": ctx.as_of,
        "workflow_version": WORKFLOW_VERSION, "state": state, "content_hash": content_hash,
        "created_at": utcnow(), "label": label,
    })

    repo.clear_version_objects(report_id, ver)
    for res in ctx.finance.verify.resolutions.values():
        repo.link_version_object(report_id, ver, "resolution", res["resolution_id"])
    for ms in ctx.finance.metrics.values():
        for m in ms.values():
            repo.link_version_object(report_id, ver, "metric", m.result_id)
    for cs in claims.values():
        for c in cs:
            repo.link_version_object(report_id, ver, "claim", c.claim_version_id)
    for w in written:
        repo.link_version_object(report_id, ver, "section", w["section_version_id"])

    repo.replace_dependencies(f"{report_id}@v{ver}", build_dependencies(ctx, sections, claims))
    if state == "published":
        repo.set_head(report_id, ver)
    return {"report_id": report_id, "version_no": ver, "content_hash": content_hash,
            "sections": [{k: w[k] for k in ("section_key", "section_version_id",
                                             "content_hash", "reused")} for w in written],
            "reused_sections": reused,
            "changed_sections": sorted(changed_sections) if changed_sections is not None else None,
            "input_fingerprint": fingerprint, "state": state, "no_change": False}
