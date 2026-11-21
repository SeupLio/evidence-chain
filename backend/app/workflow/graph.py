"""研究工作流：plan → collect → ingest ∥ (finance → verify) (industry → validate)
→ risk → compose → audit → publish。

图只负责调度；业务真值全部在服务端对象里。任一分支失败只把本支标 partial，
不抛异常导致另一支消失。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..agents.base import AgentResult, LLMClient
from ..agents.roles import (CollectOutput, FinanceOutput, IndustryOutput, RiskOutput,
                            AuditOutput, audit_policy, collect_policy, finance_policy, industry_policy,
                            plan_policy, risk_policy, COLLECT_PROMPT, FINANCE_PROMPT, INDUSTRY_PROMPT,
                            RISK_PROMPT, AUDIT_PROMPT)
from ..domain.fields import CORE_FIELDS
from ..services.analysis import (build_graph, compute_finance, industry_view)
from ..services.report import (ReportContext, build_claims, build_context, publish_version,
                               report_id_for)
from ..storage import repo as _repo
from ..storage.db import utcnow
from .engine import CompiledGraph, StateGraph

Emit = Callable[[str, str, str, dict[str, int]], None]


def build(emit: Emit) -> CompiledGraph:
    g = StateGraph()

    async def plan(state: dict[str, Any]) -> dict[str, Any]:
        subject, years, as_of = state["subject"], state["years"], state["as_of"]
        raw_facts = [
            {"year": int(f["period_end"][:4]), "field_code": f["field_code"], "document_id": f["document_id"]}
            for f in _repo.facts_of_entity(subject["entity_id"])
            if f["consolidation"] == "consolidated" and f["extract_status"] == "OK"
        ]
        # 计划只关心「哪些年份 + 字段有原件」，传 1000 条明细只会拖慢模型；
        # 压成唯一的 (年份, 字段) 组合，保留一个代表文档即可。
        by_key: dict[tuple[int, str], str] = {}
        for f in raw_facts:
            by_key.setdefault((f["year"], f["field_code"]), f["document_id"])
        facts = [{"year": y, "field_code": code, "document_id": doc}
                 for (y, code), doc in sorted(by_key.items())]
        docs = [d for d in _repo.documents_visible(as_of) if d["issuer"] == subject["entity_id"]]
        # 覆盖矩阵是纯字段字典扫描，确定性结果比模型更准也更快；
        # 这里不调用模型，保留为「确定性计划 Agent」，其余角色再走 live。
        out = plan_policy({"entity_id": subject["entity_id"], "years": years,
                           "facts": facts, "missing": []})
        res = AgentResult(role="plan", output=out, mode="policy",
                          notes=["覆盖矩阵由字段字典确定性扫描"])
        return {
            "coverage": [c.model_dump() for c in out.coverage],
            "plan_note": out.note,
            "agent_log": [res.as_dict()],
            "counts": {"covered": sum(1 for c in out.coverage if c.status == "COVERED"),
                       "missing": out.missing_count, "documents": len(docs)},
        }

    async def collect(state: dict[str, Any]) -> dict[str, Any]:
        missing = [{"year": c["year"], "field_code": c["field_code"]}
                   for c in state.get("coverage", []) if c["status"] == "MISSING"]
        res = state["llm"].generate_json(
            role="collect", schema=CollectOutput,
            context={"entity_name": state["subject"]["name"], "exchange": state["subject"]["exchange"],
                     "missing": missing},
            instructions=COLLECT_PROMPT, fallback=collect_policy,
            cache_key=f"collect:{state['subject']['entity_id']}:{missing[:5]}",
        )
        out: CollectOutput = res.output  # type: ignore[assignment]
        return {"queries": [q.model_dump() for q in out.queries], "collect_note": out.note,
                "agent_log": [res.as_dict()], "counts": {"queries": len(out.queries)}}

    async def ingest(state: dict[str, Any]) -> dict[str, Any]:
        as_of = state["as_of"]
        subject, peers = state["subject"], state["peers"]
        wanted = [subject["entity_id"]] + [p["entity_id"] for p in peers]
        staged = set(state.get("staged_doc_ids") or [])

        def visible(d: dict[str, Any]) -> bool:
            return d.get("dataset_tag") != "demo_controlled" or d["document_id"] in staged

        docs = [d for d in _repo.documents_visible(as_of)
                if d["issuer"] in wanted and visible(d)]
        industry_docs = [d for d in _repo.documents_visible(as_of)
                         if d["source_type"] in ("industry_stats", "policy", "market_note") and visible(d)]
        state["doc_ids"] = [d["document_id"] for d in docs + industry_docs]
        return {"doc_ids": state["doc_ids"],
                "counts": {"documents": len(state["doc_ids"]), "company_docs": len(docs)}}

    async def finance_extract(state: dict[str, Any]) -> dict[str, Any]:
        candidates = []
        for f in _repo.facts_of_entity(state["subject"]["entity_id"]):
            if f["consolidation"] != "consolidated" or f["field_code"] not in CORE_FIELDS:
                continue
            loc = _repo.get_location(f["location_id"]) or {}
            candidates.append({
                "field_code": f["field_code"], "table_id": loc.get("table_id", ""),
                "cell_id": loc.get("cell_id", ""), "period_end": f["period_end"],
                "raw_unit": f["raw_unit"], "audit_scope": f["audit_scope"],
                "table_type": loc.get("table_type", ""), "row_label": loc.get("row_label", ""),
            })
        # 同一 (field, period) 只留审计层级最高的候选，避免把摘要表也当主表
        best: dict[tuple[str, str], dict[str, Any]] = {}
        rank = {"primary_table": 3, "segment_table": 2, "summary_table": 1, "narrative": 0}
        for c in candidates:
            k = (c["field_code"], c["period_end"])
            if k not in best or rank.get(c["audit_scope"], 0) > rank.get(best[k]["audit_scope"], 0):
                best[k] = c
        res = state["llm"].generate_json(
            role="finance_extract", schema=FinanceOutput,
            context={"candidates": list(best.values())},
            instructions=FINANCE_PROMPT, fallback=finance_policy,
            cache_key=f"fin:{state['subject']['entity_id']}:{len(best)}",
        )
        out: FinanceOutput = res.output  # type: ignore[assignment]
        return {"cell_choices": [s.model_dump() for s in out.selections], "agent_log": [res.as_dict()],
                "counts": {"candidates": len(best), "selected": len(out.selections)}}

    async def verify_calc(state: dict[str, Any]) -> dict[str, Any]:
        years = state["years"]
        bundle = compute_finance(state["subject"]["entity_id"], years, state["as_of"],
                                 state.get("staged_doc_ids", []))
        peer_bundles = {}
        for p in state["peers"]:
            peer_bundles[p["entity_id"]] = compute_finance(p["entity_id"], [max(years)],
                                                           state["as_of"], state.get("staged_doc_ids", []))
        state["finance"] = bundle
        state["peer_finance"] = peer_bundles
        ok = sum(1 for y in years for m in bundle.metrics.get(y, {}).values() if m.status.value == "OK")
        return {"finance": bundle, "peer_finance": peer_bundles,
                "counts": {"facts": len(bundle.verify.resolutions), "metrics": ok}}

    async def industry(state: dict[str, Any]) -> dict[str, Any]:
        iv = industry_view(state["subject"]["industry_id"], state["years"])
        doc = next((d for d in _repo.documents_visible(state["as_of"])
                    if d["issuer"] == state["subject"]["entity_id"]
                    and d["source_type"] == "annual_report"
                    and (d["period_end"] or "").startswith(str(max(state["years"])))), None)
        graph = build_graph(state["subject"], state["peers"], doc)
        state["industry"] = iv
        state["graph"] = graph
        res = state["llm"].generate_json(
            role="industry", schema=IndustryOutput,
            context={"industry_facts": _repo.industry_facts(state["subject"]["industry_id"]),
                     "policy_refs": iv["policy_refs"], "edges": graph["edges"]},
            instructions=INDUSTRY_PROMPT, fallback=industry_policy,
            cache_key=f"ind:{state['subject']['industry_id']}:{max(state['years'])}",
        )
        out: IndustryOutput = res.output  # type: ignore[assignment]
        return {"industry": iv, "graph": graph, "industry_out": out.model_dump(),
                "agent_log": [res.as_dict()],
                "counts": {"industry_facts": len(out.industry_facts),
                           "edges": len(out.edge_candidates), "gaps": len(out.gaps)}}

    async def validate_industry(state: dict[str, Any]) -> dict[str, Any]:
        """每条边必须能打开原文；打不开就降级为 UNVERIFIED 并从图里移除。"""
        kept, dropped = 0, 0
        edges = []
        for e in state.get("graph", {}).get("edges", []):
            if e["status"] == "STRUCTURAL":
                kept += 1
                edges.append(e)
                continue
            refs = [r for r in e.get("evidence_refs", []) if r and _repo.get_location(r)]
            if refs:
                kept += 1
                edges.append({**e, "evidence_refs": refs})
            else:
                dropped += 1
        state["graph"] = {**state.get("graph", {}), "edges": edges}
        return {"graph": state["graph"], "counts": {"edges_kept": kept, "edges_dropped": dropped}}

    async def build_ctx(state: dict[str, Any]) -> dict[str, Any]:
        ctx = build_context(
            subject=state["subject"], peers=state["peers"], years=state["years"], as_of=state["as_of"],
            finance=state["finance"], peer_finance=state["peer_finance"],
            industry=state["industry"], graph=state["graph"],
            model_mode=state["model_mode"], source_mode=state["source_mode"],
            doc_ids=state.get("doc_ids", []),
        )
        state["ctx"] = ctx
        return {"ctx": ctx, "counts": {"issues": len(ctx.issues), "rules": len(ctx.rules)}}

    async def risk_explain(state: dict[str, Any]) -> dict[str, Any]:
        ctx: ReportContext = state["ctx"]
        rules = [r.as_dict() for r in ctx.rules]
        res = state["llm"].generate_json(
            role="risk_explain", schema=RiskOutput, context={"rules": rules},
            instructions=RISK_PROMPT, fallback=risk_policy,
            cache_key=f"risk:{state['subject']['entity_id']}:{max(state['years'])}:{[r['status'] for r in rules]}",
        )
        out: RiskOutput = res.output  # type: ignore[assignment]
        # 模型只能解释已触发的规则；未触发规则的解释即使写得像模像样也不能进入结果。
        triggered = {r["rule_id"] for r in rules if r["status"] == "TRIGGERED"}
        out = out.model_copy(update={"explanations": [e for e in out.explanations if e.rule_id in triggered]})
        state["risk_out"] = out.model_dump()
        return {"risk_out": out.model_dump(), "agent_log": [res.as_dict()],
                "counts": {"triggered": sum(1 for r in rules if r["status"] == "TRIGGERED"),
                           "not_evaluated": len(out.not_evaluated)}}

    async def compose(state: dict[str, Any]) -> dict[str, Any]:
        ctx: ReportContext = state["ctx"]
        claims, blocked = build_claims(ctx)
        state["claims"] = claims
        # 仅在 live 模式下、且外部模型可用时，生成一段不带数字的阅读提示；
        # 它不参与结论、不改变数值，失败就直接省略。
        if state.get("model_mode") == "live":
            try:
                from ..providers import llm as llm_provider

                if llm_provider.available():
                    latest = max(ctx.years)
                    facts_brief = "；".join(
                        f"{m.display}" for m in ctx.finance.metrics.get(latest, {}).values() if m.display
                    )
                    candidates = [
                        {"id": c.claim_key, "text": c.text}
                        for cs in claims.values() for c in cs if c.verdict.value != "BLOCK"
                    ][:20]
                    got = llm_provider.pick_and_brief(facts_brief, candidates)
                    ctx.ai_brief = got.get("brief") or None
                    cp = ctx.chain_panel or {}
                    name_of = {n["node_id"]: n["name"] for n in cp.get("nodes", [])}
                    chain_edges = [{**e, "src_name": name_of.get(e.get("src"), e.get("src")),
                                    "dst_name": name_of.get(e.get("dst"), e.get("dst"))}
                                   for e in cp.get("edges", [])]
                    ctx.chain_brief = llm_provider.chain_brief(cp.get("nodes", []), chain_edges) or None
            except Exception:
                ctx.ai_brief = None
        return {"claims": claims, "blocked": blocked,
                "counts": {"claims": sum(len(v) for v in claims.values()), "blocked": len(blocked)}}

    async def audit(state: dict[str, Any]) -> dict[str, Any]:
        ctx: ReportContext = state["ctx"]
        claims = state["claims"]
        flat = [{"claim_key": c.claim_key, "findings": c.findings, "text": c.text[:120]}
                for cs in claims.values() for c in cs]
        res = state["llm"].generate_json(
            role="audit", schema=AuditOutput, context={"claims": flat},
            instructions=AUDIT_PROMPT, fallback=audit_policy, cache_key="audit:" + str(len(flat)),
        )
        out: AuditOutput = res.output  # type: ignore[assignment]
        report_id = report_id_for(ctx.subject["entity_id"], ctx.years)
        version = publish_version(ctx, claims, report_id=report_id, base_version_no=state.get("base_version_no"),
                                  base_sections=state.get("base_sections"),
                                  changed_sections=state.get("changed_sections"),
                                  state=state.get("publish_state", "published"), label=state.get("label", ""))
        state["version"] = version
        return {"audit_out": out.model_dump(), "version": version, "agent_log": [res.as_dict()],
                "counts": {"claims_audited": out.semantic_checks, "findings": len(out.findings),
                           "version": version["version_no"]}}

    g.add_node("plan", plan, label="计划：覆盖矩阵")
    g.add_node("collect", collect, label="资料：查询提案")
    g.add_node("ingest", ingest, label="入库：快照与定位")
    g.add_node("finance_extract", finance_extract, label="财务：候选单元格", parallel_group="finance")
    g.add_node("verify_calc", verify_calc, label="核验：事实与指标", parallel_group="finance")
    g.add_node("industry", industry, label="行业：统计与图谱", parallel_group="industry")
    g.add_node("validate_industry", validate_industry, label="行业：证据校验", parallel_group="industry")
    g.add_node("build_ctx", build_ctx, label="合流：基准与规则")
    g.add_node("risk_explain", risk_explain, label="风险：解释与反证")
    g.add_node("compose", compose, label="成文：模板与引用")
    g.add_node("audit", audit, label="审核：校验与发布")

    g.set_entry("plan")
    g.add_edge("plan", "collect")
    g.add_edge("collect", "ingest")
    g.add_edge("ingest", "finance_extract")
    g.add_edge("finance_extract", "verify_calc")
    g.add_edge("ingest", "industry")
    g.add_edge("industry", "validate_industry")
    g.add_edge("verify_calc", "build_ctx")
    g.add_edge("validate_industry", "build_ctx")
    g.add_edge("build_ctx", "risk_explain")
    g.add_edge("risk_explain", "compose")
    g.add_edge("compose", "audit")
    return g.compile(emit=emit)
