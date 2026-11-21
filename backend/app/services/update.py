"""增量更新：预览 → 审核 → 提交。

核心不是「重新生成」，而是**只动受影响的部分**：
1. 用新截止日/新材料重跑核验，得到新旧 resolution 的差异；
2. 以事实键为起点在依赖图上做下游 BFS（旧图 ∪ 新图，覆盖删除与替代）；
3. 只对命中的章节生成新版本，未命中章节沿用旧 section_version_id 与 hash；
4. commit 用 compare-and-swap 更新 head，过期基线返回 409 STALE_BASE。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from ..domain.contracts import MetricStatus
from ..domain.keys import content_id
from ..storage import repo
from .analysis import compute_finance, industry_view, build_graph
from .report import (ReportContext, build_claims, build_context, compose_sections, content_hash_of,
                     publish_version, report_id_for, SECTION_ORDER)

D = Decimal


class StaleBase(Exception):
    """基线已过期：另一份草稿先提交了。"""

    code = "STALE_BASE"


class NoChange(Exception):
    code = "NO_CHANGE"


@dataclass
class ChangeSet:
    changed_fact_keys: list[str]
    impacted: set[str]
    impacted_sections: set[str]
    new_facts: list[str]


def _resolution_index(ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    from ..storage.db import loads

    out = {}
    for rid in ids:
        row = repo.get_conn().execute("SELECT * FROM resolutions WHERE resolution_id=?", (rid,)).fetchone()
        if row:
            d = dict(row)
            for k in ("observed_values", "candidate_ids", "conflict_ids"):
                d[k] = loads(d.get(k), [])
            out[row["fact_key"]] = d
    return out


def _bfs(deps: Sequence[dict[str, Any]], seeds: Sequence[str]) -> set[str]:
    adj: dict[str, set[str]] = {}
    for d in deps:
        adj.setdefault(d["source_key"], set()).add(d["dependent_key"])
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        key = stack.pop()
        for nxt in adj.get(key, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def compute_changes(report_id: str, base_version: int, new_ctx: ReportContext) -> ChangeSet:
    old_res = _resolution_index(repo.version_object_ids(report_id, base_version, "resolution"))
    new_res = new_ctx.finance.verify.resolutions
    changed: list[str] = []
    new_keys: list[str] = []
    for fk, res in new_res.items():
        old = old_res.get(fk)
        if old is None:
            new_keys.append(fk)
            changed.append(fk)
            continue
        if (old["chosen_fact_id"] != res["chosen_fact_id"] or old["decision"] != res["decision"]
                or old["confidence"] != res["confidence"]):
            changed.append(fk)
    for fk in old_res:
        if fk not in new_res:
            changed.append(fk)  # 证据被剔除/不可见也算变动

    deps = repo.dependencies(f"{report_id}@v{base_version}")
    seeds = [f"fact:{fk}" for fk in changed] + [f"coverage:{fk.split('|')[0]}:{fk.split('|')[2][:4]}:{fk.split('|')[1]}"
                                                for fk in new_keys]
    impacted = _bfs(deps, seeds)
    sections = {k.split(":", 1)[1] for k in impacted if k.startswith("section:")}
    # 交付纪律：数据质量章节永远跟着改，因为它的计数会变
    sections.add("data_quality")
    return ChangeSet(changed_fact_keys=changed, impacted=impacted,
                     impacted_sections=sections, new_facts=new_keys)


def build_new_context(req: dict[str, Any], *, as_of: str, staged: list[str],
                      model_mode: str, source_mode: str) -> ReportContext:
    years = req["fiscal_years"]
    subject = repo.get_entity(req["entity_id"])
    peers = [p for p in (repo.get_entity(x) for x in req.get("peer_ids", [])) if p]
    finance = compute_finance(req["entity_id"], years, as_of, staged)
    peer_finance = {p["entity_id"]: compute_finance(p["entity_id"], [max(years)], as_of, staged)
                    for p in peers}
    iv = industry_view(subject["industry_id"], years)
    doc = next((d for d in repo.documents_visible(as_of)
                if d["issuer"] == subject["entity_id"] and d["source_type"] == "annual_report"
                and (d["period_end"] or "").startswith(str(max(years)))), None)
    graph = build_graph(subject, peers, doc)
    docs = [d for d in repo.documents_visible(as_of)
            if d["issuer"] in [subject["entity_id"]] + [p["entity_id"] for p in peers]
            or d["source_type"] in ("industry_stats", "policy", "market_note")]
    return build_context(subject=subject, peers=peers, years=years, as_of=as_of, finance=finance,
                         peer_finance=peer_finance, industry=iv, graph=graph,
                         model_mode=model_mode, source_mode=source_mode,
                         doc_ids=[d["document_id"] for d in docs])


def diff_payload(report_id: str, base_version: int, new_version: int,
                 changes: ChangeSet, ctx: ReportContext) -> dict[str, Any]:
    base_secs = {s["section_key"]: s for s in repo.sections_of(report_id, base_version)}
    new_secs = {s["section_key"]: s for s in repo.sections_of(report_id, new_version)}

    sections = []
    for key in SECTION_ORDER:
        b, n = base_secs.get(key), new_secs.get(key)
        changed = bool(b and n and b["content_hash"] != n["content_hash"])
        sections.append({
            "section_key": key, "title": (n or b or {}).get("content", {}).get("title", key),
            "changed": changed, "old_hash": b["content_hash"][:12] if b else None,
            "new_hash": n["content_hash"][:12] if n else None,
            "same_version_id": bool(b and n and b["section_version_id"] == n["section_version_id"]),
            "impacted": key in changes.impacted_sections,
        })

    # 指标级 diff
    old_metrics = {mid: repo.get_metric(mid) for mid in repo.version_object_ids(report_id, base_version, "metric")}
    old_by_key = {m["metric_key"]: m for m in old_metrics.values() if m}
    metric_diff = []
    for ms in ctx.finance.metrics.values():
        for m in ms.values():
            old = old_by_key.get(m.metric_key)
            if not old:
                continue
            if old["value_text"] != m.value_text or old["status"] != m.status.value:
                metric_diff.append({
                    "metric_key": m.metric_key, "label": m.metric_code, "year": m.fiscal_year,
                    "old_value": old["value_text"], "old_display": old["display"],
                    "new_value": m.value_text, "new_display": m.display,
                    "old_status": old["status"], "new_status": m.status.value,
                    "ref": m.result_id,
                })

    # 事实级 diff：谁变了、为什么
    old_res = _resolution_index(repo.version_object_ids(report_id, base_version, "resolution"))
    fact_diff = []
    for fk in changes.changed_fact_keys:
        old = old_res.get(fk)
        new = ctx.finance.verify.resolutions.get(fk)
        fact_diff.append({
            "fact_key": fk,
            "field_code": (new or old or {}).get("field_code"),
            "period_end": (new or old or {}).get("period_end"),
            "old_decision": old["decision"] if old else None,
            "new_decision": new["decision"] if new else None,
            "old_reason": old["reason"] if old else None,
            "new_reason": new["reason"] if new else None,
            "old_value": _chosen_value(old),
            "new_value": _chosen_value(new),
            "ref": (new or old or {}).get("resolution_id"),
        })

    return {
        "base_version": base_version, "new_version": new_version,
        "sections": sections,
        "metrics": metric_diff,
        "facts": fact_diff,
        "counts": {
            "facts_changed": len(fact_diff),
            "metrics_changed": len(metric_diff),
            "sections_changed": sum(1 for s in sections if s["changed"]),
            "sections_unchanged": sum(1 for s in sections if not s["changed"]),
            "objects_impacted": len(changes.impacted),
        },
    }


def _discard_stale_draft(report_id: str, version_no: int) -> None:
    """同一基线重复预览时，旧草稿作废重建；已发布的版本绝不动。"""
    row = repo.get_report_version(report_id, version_no)
    if not row:
        return
    if row["state"] != "draft":
        raise StaleBase(f"v{version_no} 已存在且不是草稿，无法在其上重建预览")
    conn = repo.get_conn()
    conn.execute("DELETE FROM section_versions WHERE report_id=? AND version_no=?", (report_id, version_no))
    # 旧草稿的对象链接必须一起清掉，否则重建后新旧指标会同时挂在这个版本上，
    # 答疑就可能引用到已被替换的旧值（正文与答疑不一致）。
    conn.execute("DELETE FROM version_objects WHERE report_id=? AND version_no=?", (report_id, version_no))
    conn.execute("DELETE FROM dependencies WHERE snapshot_id=?", (f"{report_id}@v{version_no}",))
    conn.execute("DELETE FROM report_versions WHERE report_id=? AND version_no=?", (report_id, version_no))


def _chosen_value(res: dict[str, Any] | None) -> str | None:
    if not res:
        return None
    chosen = res.get("chosen_fact_id")
    for o in res.get("observed_values", []):
        if o["fact_id"] == chosen:
            return o["value_text"]
    return None


def preview(report_id: str, base_version: int, req: dict[str, Any], *, as_of: str | None = None,
            staged: list[str] | None = None, model_mode: str = "mock",
            source_mode: str = "replay") -> dict[str, Any]:
    base = repo.get_report_version(report_id, base_version)
    if not base:
        raise StaleBase(f"基线版本不存在：v{base_version}")
    as_of = as_of or base["as_of"]
    staged = staged or []
    ctx = build_new_context(req, as_of=as_of, staged=staged, model_mode=model_mode,
                            source_mode=source_mode)
    changes = compute_changes(report_id, base_version, ctx)
    base_secs = repo.sections_of(report_id, base_version)
    claims, _ = build_claims(ctx)
    if content_hash_of(compose_sections(ctx, claims)) == base["content_hash"]:
        raise NoChange("输入未改变任何结论，未生成新版本")
    _discard_stale_draft(report_id, base_version + 1)
    version = publish_version(ctx, claims, report_id=report_id, base_version_no=base_version,
                              base_sections=base_secs, changed_sections=changes.impacted_sections,
                              state="draft", label=f"v{base_version} 补证草稿")
    # 草稿不推进 head
    diff = diff_payload(report_id, base_version, version["version_no"], changes, ctx)
    return {"draft_version": version["version_no"], "base_version": base_version,
            "as_of": as_of, "staged_doc_ids": staged, "diff": diff,
            "changed_sections": sorted(changes.impacted_sections),
            "sections": version["sections"], "content_hash": version["content_hash"]}


def commit(report_id: str, draft_version: int, base_version: int, idempotency_key: str | None = None) -> dict[str, Any]:
    head = repo.head_version(report_id)
    draft = repo.get_report_version(report_id, draft_version)
    if not draft:
        raise StaleBase(f"草稿不存在：v{draft_version}")
    if draft["state"] != "draft":
        # 幂等：同一草稿重复提交返回原结果
        return {"status": "ALREADY_COMMITTED", "version_no": draft_version, "head": head}
    if head != base_version:
        raise StaleBase(f"当前最新版本已是 v{head}，草稿基于 v{base_version}，请重建预览")
    base = repo.get_report_version(report_id, base_version)
    if base and base["input_fingerprint"] == draft["input_fingerprint"] and base["content_hash"] == draft["content_hash"]:
        raise NoChange("草稿与基线内容一致")
    repo.get_conn().execute(
        "UPDATE report_versions SET state='published' WHERE report_id=? AND version_no=?",
        (report_id, draft_version))
    repo.set_head(report_id, draft_version)
    return {"status": "COMMITTED", "report_id": report_id, "old_version": base_version,
            "new_version": draft_version, "head": draft_version,
            "old_hash": base["content_hash"] if base else None, "new_hash": draft["content_hash"]}
