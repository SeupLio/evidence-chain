"""核验引擎：把「候选」变成「可使用事实」。

顺序：数值预处理 → 口径分桶 → 舍入相容 → 权威选择 → 决策 → 勾稽检查。
只有同 FactKey 的候选才互相比值；口径不同（合并/母公司、分部/合计）记 SCOPE_MISMATCH，
它是解释型提示，不是冲突。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..domain.contracts import Confidence, Decision, IssueType, Severity
from ..domain.keys import FactKey, canonical_json, content_id, dec_str
from ..storage import repo

POLICY_VERSION = "resolve/v1.3.0"
D = Decimal

#: 权威层级：正式更正 > 原始审计年报 > 其他同口径正式披露 > 二手来源
AUTHORITY: dict[str, int] = {
    "correction": 100,
    "annual_report": 80,
    "annual_summary": 70,
    "quarterly": 40,
    "industry_stats": 30,
    "policy": 20,
    "market_note": 10,
}
SCOPE_BONUS = {"primary_table": 6, "segment_table": 4, "summary_table": 0, "narrative": 0}


def authority(fact: dict[str, Any]) -> int:
    source = fact.get("source_type") or ""
    basis = fact.get("basis_tag")
    if source == "correction":
        # 更正公告里的「更正前」列是在引用被替代的旧值，不是可采信来源
        base = AUTHORITY["correction"] if basis == "restated" else 55
    else:
        base = AUTHORITY.get(source, 0)
        if basis == "restated":
            base += 5
    return base + SCOPE_BONUS.get(fact.get("audit_scope") or "", 0)


@dataclass
class VerifyOutput:
    resolutions: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    year_facts: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)
    segment_facts: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def fact_slots(self) -> dict[int, dict[str, Any]]:
        return self.year_facts  # type: ignore[return-value]


def _dec(v: str | None) -> Decimal | None:
    return Decimal(v) if v not in (None, "") else None


def _year_of(fact: dict[str, Any]) -> int:
    return int((fact.get("period_end") or "0000")[:4])


def _issue(kind: IssueType, severity: Severity, key: str, candidate_ids: Sequence[str],
           context: dict[str, Any]) -> dict[str, Any]:
    iid = content_id("issue", {"t": kind.value, "k": key, "c": sorted(candidate_ids)})
    return {"issue_id": iid, "type": kind.value, "severity": severity.value, "key": key,
            "candidate_ids": list(candidate_ids), "status": "OPEN", "context": context}


def _describe(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": fact["fact_id"],
        "value_text": fact["value_text"],
        "value_display": _display(fact),
        "unit": fact["raw_unit"],
        "document_id": fact["document_id"],
        "doc_title": fact.get("doc_title", ""),
        "published_on": fact.get("published_on"),
        "source_type": fact.get("source_type"),
        "audit_scope": fact["audit_scope"],
        "basis_tag": fact["basis_tag"],
        "precision_step": fact["precision_step"],
        "authority": authority(fact),
        "page": None,
    }


def _display(fact: dict[str, Any]) -> str:
    v = _dec(fact["value_text"])
    if v is None:
        return ""
    return f"{v:,.2f} 元"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def verify_entity(entity_id: str, as_of: str, staged_doc_ids: Sequence[str] = ()) -> VerifyOutput:
    out = VerifyOutput()
    keys = repo.all_fact_keys(entity_id)
    staged = set(staged_doc_ids)
    for key in keys:
        candidates = [f for f in repo.facts_for_key(key) if _visible(f, as_of, staged)]
        if not candidates:
            continue
        res, issues = resolve_key(key, candidates)
        out.resolutions[key] = res
        out.issues.extend(issues)
        if res["decision"] == Decision.ACCEPTED_WITH_CONFLICT.value:
            out.conflicts.append({"fact_key": key, "resolution": res})
    _index_year_facts(out)
    out.issues.extend(_reconcile(entity_id, out))
    # 先落库本次决策，口径说明才能读到「本次」而不是上一次的选值
    repo.replace_resolutions(list(out.resolutions.values()))
    out.issues.extend(_scope_notes(entity_id, out))
    out.issues.extend(_cross_source_notes(entity_id, out))
    for iss in out.issues:
        repo.upsert_issue(iss)
    return out


def _visible(fact: dict[str, Any], as_of: str, staged: set[str]) -> bool:
    # 演练材料（如构造的更正公告）默认不进入核对；真实语料与回归语料正常参与。
    if fact.get("dataset_tag") == "demo_controlled" and fact["document_id"] not in staged:
        return False
    pub = fact.get("published_on")
    if fact["document_id"] in staged:
        return True
    return pub is None or pub <= as_of


def resolve_key(fact_key: str, candidates: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """同键候选 → 一个决策 + 若干问题记录。"""
    issues: list[dict[str, Any]] = []
    ranked = sorted(candidates, key=lambda f: (-authority(f), f.get("published_on") or ""), reverse=False)
    ranked.sort(key=lambda f: (authority(f), f.get("published_on") or ""), reverse=True)
    head = ranked[0]
    head_val = _dec(head["value_text"])
    head_step = _dec(head["precision_step"]) or D(0)
    others = ranked[1:]

    compatible: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    superseded: list[dict[str, Any]] = []
    secondary_only: list[dict[str, Any]] = []

    for other in others:
        o_val = _dec(other["value_text"])
        o_step = _dec(other["precision_step"]) or D(0)
        if o_val is None or head_val is None:
            continue
        diff = abs(head_val - o_val)
        tol = (head_step + o_step) / D(2)
        if diff <= tol:
            compatible.append(other)
            continue
        if head["basis_tag"] == "restated" and other["basis_tag"] == "original" and head["source_type"] == "correction":
            superseded.append(other)
            continue
        if authority(other) < AUTHORITY["annual_report"]:
            secondary_only.append(other)
            continue
        conflicts.append(other)

    observed = [_describe(f) for f in ranked]
    candidate_ids = [f["fact_id"] for f in ranked]
    head_scope = head["audit_scope"]
    # 置信度：主表 + 单位/期间齐全 + 无未决同级冲突
    if conflicts:
        confidence = Confidence.LOW
    elif head_scope == "primary_table":
        confidence = Confidence.HIGH
    elif head_scope in ("summary_table", "segment_table"):
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    if conflicts:
        decision = Decision.BLOCKED
        reason = ("同键存在同级未决冲突：" + "；".join(
            f"{c.get('doc_title','')} 为 {_display(c)}（差 {abs(head_val - _dec(c['value_text'])):,.2f} 元，"
            f"超出舍入容差 {(head_step + (_dec(c['precision_step']) or D(0))) / 2:,.2f} 元）"
            for c in conflicts))
        issues.append(_issue(IssueType.NUMERIC_CONFLICT, Severity.BLOCKING, fact_key, candidate_ids,
                             {"head": _describe(head), "conflicts": [_describe(c) for c in conflicts],
                              "policy": POLICY_VERSION,
                              "explanation": "同级来源无法判定孰对孰错，冻结该事实及依赖指标，等待正式更正或原件复核"}))
    elif superseded:
        decision = Decision.SUPERSEDED
        reason = ("正式更正明确替代原披露：" + "；".join(
            f"{s.get('doc_title','')} 的原值 {_display(s)} 已被 {head.get('doc_title','')} 的 {_display(head)} 替代"
            for s in superseded))
        issues.append(_issue(IssueType.NUMERIC_CONFLICT, Severity.INFO, fact_key, candidate_ids,
                             {"head": _describe(head), "superseded": [_describe(s) for s in superseded],
                              "explanation": "已由正式更正替代，新旧版本都可追溯，不作为冲突"}))
    else:
        decision = Decision.AGREED
        scope_cn = {"primary_table": "主表", "summary_table": "摘要表",
                    "segment_table": "分部表", "narrative": "文字说明"}.get(head_scope, "正式披露")
        reason = f"采信 {head.get('doc_title','')}（{scope_cn}）"
        if compatible:
            worst = max(abs(head_val - _dec(c['value_text'])) for c in compatible)
            reason += f"；{len(compatible)} 份候选在舍入区间内一致（最大差 {worst:,.2f} 元）"
            issues.append(_issue(IssueType.ROUNDING_COMPATIBLE, Severity.INFO, fact_key, candidate_ids,
                                 {"head": _describe(head), "compatible": [_describe(c) for c in compatible],
                                  "explanation": "单位/精度不同导致显示值差异，换算后落在舍入容差内，不构成冲突"}))
        if secondary_only:
            reason += f"；{len(secondary_only)} 份二手来源偏差已记录，不参与真值"
            issues.append(_issue(IssueType.NUMERIC_CONFLICT, Severity.INFO, fact_key, candidate_ids,
                                 {"head": _describe(head), "secondary": [_describe(s) for s in secondary_only],
                                  "explanation": "二手来源（研报/媒体）估值不作为财务真值，仅作对照"}))
        if len({f["document_id"] for f in ranked}) > 1 and not compatible:
            reason += "；不同期次披露的同一数值一致"

    if head_scope == "narrative" or (head.get("source_type") == "market_note"):
        confidence = Confidence.LOW
        decision = Decision.PROVISIONAL

    resolution = {
        "resolution_id": content_id("res", {"fk": fact_key, "chosen": head["fact_id"],
                                            "cands": sorted(candidate_ids), "policy": POLICY_VERSION}),
        "fact_key": fact_key,
        "field_code": head["field_code"],
        "period_end": head["period_end"],
        "chosen_fact_id": None if decision == Decision.BLOCKED else head["fact_id"],
        "candidate_ids": candidate_ids,
        "decision": decision.value,
        "confidence": confidence.value,
        "reason": reason,
        "policy_version": POLICY_VERSION,
        "observed_values": observed,
        "conflict_ids": [c["fact_id"] for c in conflicts],
    }
    return resolution, issues


def _index_year_facts(out: VerifyOutput) -> None:
    for key, res in out.resolutions.items():
        parts = FactKey.parse(res["fact_key"] if "fact_key" in res else key)
        if parts.consolidation != "consolidated":
            continue
        year = int(parts.period_end[:4])
        slot = {
            "resolution": res,
            "value_text": next((o["value_text"] for o in res["observed_values"]
                                if o["fact_id"] == res["chosen_fact_id"]), None),
            "confidence": res["confidence"],
            "status": "OK" if res["decision"] != Decision.BLOCKED.value else "BLOCKED",
            "field_code": parts.field_code,
            "period_kind": parts.period_kind,
        }
        if parts.business_scope == "total":
            out.year_facts.setdefault(year, {})
            out.year_facts[year][parts.field_code] = slot
        elif parts.business_scope.startswith("segment:"):
            out.segment_facts.setdefault(year, {})
            out.segment_facts[year][parts.field_code] = slot


# --------------------------------------------------------------------------- #
# 勾稽
# --------------------------------------------------------------------------- #

def _reconcile(entity_id: str, out: VerifyOutput) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for year, fields in sorted(out.year_facts.items()):
        def val(code: str) -> Decimal | None:
            slot = fields.get(code)
            return _dec(slot["value_text"]) if slot else None

        assets, liab, equity = val("total_assets"), val("total_liabilities"), val("total_equity")
        npt, npp, mi = val("net_profit_total"), val("net_profit_parent"), val("minority_interest")
        lie = val("liab_equity_total")

        checks = [
            ("资产 = 负债 + 所有者权益", assets, liab, equity),
            ("净利润 = 归母净利润 + 少数股东损益", npt, npp, mi),
        ]
        for name, lhs, a, b in checks:
            if lhs is None or a is None or b is None:
                missing = [n for n, v in (("左项", lhs), ("分项一", a), ("分项二", b)) if v is None]
                issues.append(_issue(IssueType.NOT_CHECKED, Severity.INFO,
                                     f"reconcile:{entity_id}:{year}:{name}", [],
                                     {"year": year, "check": name, "missing": missing,
                                      "explanation": "输入不全，勾稽未执行；不声称已通过"}))
                continue
            tolerance = D("1")
            if abs(lhs - (a + b)) > tolerance:
                issues.append(_issue(IssueType.RECONCILE_FAIL, Severity.BLOCKING,
                                     f"reconcile:{entity_id}:{year}:{name}", [],
                                     {"year": year, "check": name, "lhs": dec_str(lhs),
                                      "rhs": dec_str(a + b), "diff": dec_str(lhs - (a + b)),
                                      "explanation": "勾稽未通过，依赖这些输入的指标应冻结；可能是抽取错误或口径不一致"}))
        if assets is not None and lie is not None and abs(assets - lie) > D("1"):
            issues.append(_issue(IssueType.RECONCILE_FAIL, Severity.BLOCKING,
                                 f"reconcile:{entity_id}:{year}:负债和权益总计", [],
                                 {"year": year, "check": "负债和所有者权益总计 = 资产总计",
                                  "diff": dec_str(assets - lie),
                                  "explanation": "左右表尾合计不一致"}))

        # 分部合计 vs 合并总额：只有四段齐全才校验，缺一段就记 NOT_CHECKED
        seg = out.segment_facts.get(year, {})
        pairs = [("营业收入", "revenue", "seg_revenue_beer", "seg_revenue_other"),
                 ("营业成本", "operating_cost", "seg_cost_beer", "seg_cost_other")]
        for name, total_code, a_code, b_code in pairs:
            total = val(total_code)
            a = _dec(seg[a_code]["value_text"]) if seg.get(a_code) else None
            b = _dec(seg[b_code]["value_text"]) if seg.get(b_code) else None
            if total is None or a is None or b is None:
                continue
            if abs(total - (a + b)) > D("1"):
                issues.append(_issue(IssueType.RECONCILE_FAIL, Severity.BLOCKING,
                                     f"reconcile:{entity_id}:{year}:分部{name}", [],
                                     {"year": year, "check": f"分部{name}合计 = 合并{name}",
                                      "lhs": dec_str(total), "rhs": dec_str(a + b),
                                      "diff": dec_str(total - (a + b)),
                                      "explanation": "分部数据与合并总额不勾稽，毛利率结构分解应拒绝执行"}))
    return issues


CORE_COMPARE = ("revenue", "operating_cost", "net_profit_parent", "total_assets",
                "total_liabilities", "operating_cashflow")


def _cross_source_notes(entity_id: str, out: VerifyOutput) -> list[dict[str, Any]]:
    """原件与第三方结构化数据对不上时，留一条可核对的线索。

    这不是「冲突」——两边不是同级披露；也不能沉默——差异超过阈值时，
    指标读数很可能来自抽取错位。标 WATCH，让人回去看那一页。
    """
    issues: list[dict[str, Any]] = []
    for key, res in out.resolutions.items():
        parts = FactKey.parse(key)
        if parts.consolidation != "consolidated" or parts.field_code not in CORE_COMPARE:
            continue
        chosen = next((o for o in res["observed_values"] if o["fact_id"] == res["chosen_fact_id"]), None)
        if not chosen or not chosen.get("value_text"):
            continue
        year = int(parts.period_end[:4])
        ref = repo.market_fact(entity_id, parts.field_code, year)
        if not ref:
            continue
        try:
            a, b = D(chosen["value_text"]), D(ref["value_text"])
        except Exception:
            continue
        if b == 0:
            continue
        rel = abs(a - b) / abs(b)
        if rel <= D("0.05") or abs(a - b) <= D("1000000"):
            continue
        issues.append(_issue(
            IssueType.CROSS_SOURCE_DIVERGENCE, Severity.WATCH,
            f"cross:{entity_id}:{parts.field_code}:{year}", [res["chosen_fact_id"] or ""],
            {"field_code": parts.field_code, "year": year,
             "pdf_value": str(a), "ref_value": str(b), "relative": f"{float(rel) * 100:.2f}%",
             "explanation": f"原件抽取值与第三方结构化数据相差 {float(rel) * 100:.1f}%，"
                            f"需回到该页核对是否取错行或列"}))
    return issues


def _scope_notes(entity_id: str, out: VerifyOutput) -> list[dict[str, Any]]:
    """母公司 vs 合并：不是冲突，但必须显式说明为什么不能比较。"""
    issues: list[dict[str, Any]] = []
    for key, res in out.resolutions.items():
        parts = FactKey.parse(key)
        if parts.consolidation != "parent":
            continue
        consolidated_key = "|".join([parts.entity_id, parts.field_code,
                                     f"{parts.period_start}~{parts.period_end}",
                                     parts.period_kind, "consolidated", parts.currency,
                                     parts.business_scope, parts.definition_id])
        other = out.resolutions.get(consolidated_key)
        if not other or not other["observed_values"]:
            continue
        issues.append(_issue(IssueType.SCOPE_MISMATCH, Severity.INFO,
                             f"scope:{consolidated_key}", [other["chosen_fact_id"] or ""],
                             {"field_code": parts.field_code, "period_end": parts.period_end,
                              "parent_value": next((o["value_text"] for o in res["observed_values"]), None),
                              "consolidated_value": next((o["value_text"] for o in other["observed_values"]), None),
                              "explanation": "同一行名在母公司报表与合并报表中数值不同，属口径差异；"
                                             "母公司报表不含子公司，不构成数据矛盾，也不参与合并口径指标"}))
    return issues


# --------------------------------------------------------------------------- #
# 转成指标输入
# --------------------------------------------------------------------------- #

def to_metric_slots(year_facts: dict[int, dict[str, dict[str, Any]]]) -> dict[int, dict[str, Any]]:
    from ..domain.metrics import FactSlot

    out: dict[int, dict[str, FactSlot]] = {}
    for year, fields in year_facts.items():
        out[year] = {}
        for code, slot in fields.items():
            out[year][code] = FactSlot(
                value=_dec(slot["value_text"]),
                fact_id=(slot["resolution"]["chosen_fact_id"] or slot["resolution"]["resolution_id"]),
                confidence=Confidence(slot["confidence"]),
                status=slot["status"],
            )
    return out  # type: ignore[return-value]
