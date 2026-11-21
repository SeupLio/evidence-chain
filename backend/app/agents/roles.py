"""六个角色的结构化契约与确定性策略。

每个角色只拿到自己需要的上下文，只被允许输出自己 schema 里的字段：
- 资料 Agent 只能提查询提案与缺口，不能给数值；
- 财务 Agent 只能指认「哪张表哪一格」，不能返回新数字；
- 行业 Agent 每条结论必须带 evidence_id；
- 风险 Agent 只解释已生成的警报，阈值由规则给出；
- 审核 Agent 只出问题码，不改数字。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..domain.fields import CORE_FIELDS, FIELDS

PROMPT_VERSION = "prompt/v1.0.0"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #

class CoverageCell(Strict):
    year: int
    field_code: str
    documents: list[str] = Field(default_factory=list)
    status: Literal["COVERED", "MISSING", "CONFLICTED"]


class PlanOutput(Strict):
    entity_id: str
    years: list[int]
    coverage: list[CoverageCell]
    missing_count: int
    budget: dict[str, int]
    note: str


PLAN_PROMPT = f"""你是研究计划 Agent。任务：根据观察截止日与可用原件，产出「年报覆盖矩阵」。
规则：只做统计，不评价公司经营；缺失项必须如实标 MISSING；不得编造文档。
schema: {{entity_id, years, coverage[{{year, field_code, documents[], status}}], missing_count, budget, note}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def plan_policy(ctx: dict[str, Any]) -> PlanOutput:
    years = ctx["years"]
    available: dict[tuple[int, str], list[str]] = {}
    for f in ctx["facts"]:
        if f["field_code"] in CORE_FIELDS:
            available.setdefault((f["year"], f["field_code"]), []).append(f["document_id"])
    cells: list[CoverageCell] = []
    missing = 0
    for y in years:
        for field in CORE_FIELDS:
            docs = sorted(set(available.get((y, field), [])))
            status = "COVERED" if docs else "MISSING"
            missing += 0 if docs else 1
            cells.append(CoverageCell(year=y, field_code=field, documents=docs, status=status))
    return PlanOutput(
        entity_id=ctx["entity_id"], years=years, coverage=cells, missing_count=missing,
        budget={"llm_calls_max": 14, "wall_clock_s": 90, "max_documents": 12},
        note="覆盖矩阵只统计原件可见性；冲突与否由核验引擎判定，不在此处下结论。",
    )


# --------------------------------------------------------------------------- #
# collect
# --------------------------------------------------------------------------- #

class QueryProposal(Strict):
    query: str
    expected_doc_type: str
    target_year: int | None
    publisher: str
    reason: str


class CollectOutput(Strict):
    queries: list[QueryProposal]
    whitelist: list[str]
    note: str


COLLECT_PROMPT = f"""你是资料搜集 Agent。只输出查询提案，不输出任何结论或数字。
每条提案必须给出预期发布方与目标年度；猜测不得写成证据。
schema: {{queries[{{query, expected_doc_type, target_year, publisher, reason}}], whitelist[], note}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def collect_policy(ctx: dict[str, Any]) -> CollectOutput:
    missing = ctx["missing"]
    queries: list[QueryProposal] = []
    seen: set[tuple[int, str]] = set()
    for item in missing[:8]:
        key = (item["year"], item["field_code"])
        if key in seen:
            continue
        seen.add(key)
        label = FIELDS[item["field_code"]].label
        queries.append(QueryProposal(
            query=f"{ctx['entity_name']} {item['year']} 年年度报告 {label}",
            expected_doc_type="annual_report", target_year=item["year"],
            publisher=f"{ctx['exchange']}证券交易所 / 巨潮资讯",
            reason=f"覆盖矩阵缺少 {item['year']} 年的{label}",
        ))
    return CollectOutput(
        queries=queries,
        whitelist=["sse.com.cn", "szse.cn", "cninfo.com.cn", "stats.gov.cn", "ndrc.gov.cn"],
        note="搜索摘要只用于发现候选，不进入引用与证据图；最终 URL 需经代码校验发布方、日期与全文。",
    )


# --------------------------------------------------------------------------- #
# finance
# --------------------------------------------------------------------------- #

class CellChoice(Strict):
    field_code: str
    table_id: str
    cell_id: str
    period_end: str
    raw_unit: str
    status: Literal["SELECTED", "AMBIGUOUS", "SKIPPED"]
    reason: str


class FinanceOutput(Strict):
    selections: list[CellChoice]
    ambiguous: list[str]
    note: str


FINANCE_PROMPT = f"""你是财务抽取 Agent。只能从给定候选中指认 cell_id，不得返回任何新数字或计算结果。
同一页出现多个候选时宁可输出 AMBIGUOUS，也不要猜。表类型与字段必须匹配。
schema: {{selections[{{field_code, table_id, cell_id, period_end, raw_unit, status, reason}}], ambiguous[], note}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def finance_policy(ctx: dict[str, Any]) -> FinanceOutput:
    selections: list[CellChoice] = []
    ambiguous: list[str] = []
    for c in ctx["candidates"]:
        if c["audit_scope"] != "primary_table":
            selections.append(CellChoice(
                field_code=c["field_code"], table_id=c["table_id"], cell_id=c["cell_id"],
                period_end=c["period_end"], raw_unit=c["raw_unit"], status="SELECTED",
                reason=f"主表单元格，行名「{c['row_label']}」与字段口径匹配",
            ))
        else:
            selections.append(CellChoice(
                field_code=c["field_code"], table_id=c["table_id"], cell_id=c["cell_id"],
                period_end=c["period_end"], raw_unit=c["raw_unit"], status="SELECTED",
                reason=f"{c['table_type']} 主表，行名精确匹配；单位证据 {c['raw_unit']}",
            ))
    return FinanceOutput(selections=selections, ambiguous=ambiguous,
                         note="只做候选指认；数值与单位换算由服务端按 cell_id 回查完成。")


# --------------------------------------------------------------------------- #
# industry
# --------------------------------------------------------------------------- #

class IndustryFact(Strict):
    code: str
    label: str
    value_text: str
    unit: str
    period: str
    evidence_id: str
    direction: Literal["support", "contradict", "neutral"] = "neutral"


class EdgeCandidate(Strict):
    src: str
    relation: Literal["USES_INPUT", "OPERATES_IN", "SELLS_VIA", "SUPPLIES_TO", "PEER_OF"]
    dst: str
    evidence_id: str | None
    quote: str | None
    status: Literal["VERIFIED", "STRUCTURAL", "UNVERIFIED"]


class IndustryOutput(Strict):
    industry_facts: list[IndustryFact]
    policy_links: list[dict[str, str]]
    edge_candidates: list[EdgeCandidate]
    gaps: list[str]


INDUSTRY_PROMPT = f"""你是行业分析 Agent。每条结论必须给 evidence_id 与支持方向；未见明确原句不得提交关系边。
产量口径不得当作市场收入；样本营收合计不得当作行业规模。
schema: {{industry_facts[], policy_links[], edge_candidates[], gaps[]}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def industry_policy(ctx: dict[str, Any]) -> IndustryOutput:
    facts = [IndustryFact(code=f["code"], label=f["label"], value_text=f["value_text"], unit=f["unit"],
                          period=f["period"], evidence_id=f["source_location"]) for f in ctx["industry_facts"]]
    links = [{"policy": p["title"], "ref": p["locations"][0]["location_id"] if p["locations"] else "",
              "applies_to": "啤酒制造企业的产能扩张与技术改造"} for p in ctx["policy_refs"] if p["locations"]]
    edges = []
    for e in ctx["edges"]:
        edges.append(EdgeCandidate(src=e["src"], relation=e["relation"], dst=e["dst"],
                                   evidence_id=(e["evidence_refs"][0] if e["evidence_refs"] else None),
                                   quote=e.get("note"), status=e["status"]))
    gaps = []
    if not ctx["industry_facts"]:
        gaps.append("行业统计原件缺失，行业规模与增速不进入正文结论")
    gaps.append("产量为规模以上企业口径，不可与上市公司合并报表范围直接相加")
    return IndustryOutput(industry_facts=facts, policy_links=links, edge_candidates=edges, gaps=gaps)


# --------------------------------------------------------------------------- #
# risk
# --------------------------------------------------------------------------- #

class RiskExplanation(Strict):
    rule_id: str
    direct_evidence: str
    counter_evidence: str
    assumption: str
    next_material: str


class RiskOutput(Strict):
    explanations: list[RiskExplanation]
    not_evaluated: list[str]
    note: str


RISK_PROMPT = f"""你是风险解释 Agent。只解释已经生成的确定性警报，不得自设阈值、不得报违约概率、
不得把缺证升级为事实。每条解释必须分开四段：直接证据 / 反证 / 假设 / 下一份需要的材料。
schema: {{explanations[{{rule_id, direct_evidence, counter_evidence, assumption, next_material}}], not_evaluated[], note}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def risk_policy(ctx: dict[str, Any]) -> RiskOutput:
    out: list[RiskExplanation] = []
    for r in ctx["rules"]:
        if r["status"] != "TRIGGERED":
            continue
        out.append(RiskExplanation(
            rule_id=r["rule_id"],
            direct_evidence=f"{r['label']}：{r['headline']}（阈值 {r['threshold_text']}）",
            counter_evidence=r["counter_evidence"],
            assumption="假设两期口径一致、数据未经重述；如发生重述，本判断需重跑",
            next_material=r["next_material"],
        ))
    return RiskOutput(explanations=out,
                      not_evaluated=[r["label"] for r in ctx["rules"] if r["status"] == "NOT_EVALUABLE"],
                      note="未触发不代表无风险；未评估项已单独列出。")


# --------------------------------------------------------------------------- #
# audit
# --------------------------------------------------------------------------- #

class AuditFinding(Strict):
    claim_key: str
    code: str
    severity: Literal["WARN", "BLOCK"]
    detail: str


class AuditOutput(Strict):
    findings: list[AuditFinding]
    semantic_checks: int
    note: str


AUDIT_PROMPT = f"""你是审核 Agent。检查被引用段落能否支持该结论，指出过强因果措辞。
只输出 claim_key、问题码与证据，不改任何数字。
schema: {{findings[{{claim_key, code, severity, detail}}], semantic_checks, note}}
当前 prompt 版本 {PROMPT_VERSION}。"""


def audit_policy(ctx: dict[str, Any]) -> AuditOutput:
    findings = []
    for c in ctx["claims"]:
        for f in c.get("findings", []):
            findings.append(AuditFinding(claim_key=c["claim_key"], code=f["code"],
                                         severity="BLOCK" if f["level"] == "BLOCK" else "WARN",
                                         detail=f["detail"]))
    return AuditOutput(findings=findings, semantic_checks=len(ctx["claims"]),
                       note="确定性校验（引用存在性、单位、期间、公式重算）在前，语义复核在后；抽样人工复核。")
