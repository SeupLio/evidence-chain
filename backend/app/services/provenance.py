"""证据地图：把一份已发布版本的「章节 → 结论 → 引用 → 事实 → 原件」还原成图。

不是知识图谱，而是**可审计的对象依赖**：
- 每条 Claim 只能连到它实际引用的 ref；
- 指标展开到公式输入的事实，事实再落到文档；
- 所有节点都带可点击的 ref，前端点击仍走同一个证据抽屉。

这样评委看到的不是一张装饰图，而是「哪条结论用了哪几份原件」的完整路径。
"""

from __future__ import annotations

from typing import Any

from ..domain.fields import FIELDS
from ..domain.metrics import FORMULAS
from ..storage import repo

TYPE_LABEL = {
    "section": "章节", "claim": "结论", "metric": "指标", "fact": "事实",
    "rule": "规则", "bench": "同业基准", "edge": "关系边", "document": "原件",
}


def _short(text: str | None, n: int = 46) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


REF_PREFIXES = ("metric:", "fact:", "rule:", "bench:", "edge:", "loc:", "gap:")


def _scan_refs(obj: Any, acc: set[str]) -> None:
    """章节内容里的 kpi / 指标行 / 同业单元格也带 ref，必须进入证据地图。"""
    if isinstance(obj, str):
        if obj.startswith(REF_PREFIXES):
            acc.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _scan_refs(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _scan_refs(v, acc)


def _metric_node(ref: str, nodes: dict[str, dict[str, Any]],
                 edges: list[dict[str, Any]], source: str, kind: str) -> None:
    body = ref.partition(":")[2]
    m = repo.get_metric(body) or repo.get_metric(f"metric:{body}")
    if not m:
        return
    mid = f"metric:{m['result_id']}"
    spec = FORMULAS.get(m["metric_code"])
    if mid not in nodes:
        nodes[mid] = {
            "id": mid, "type": "metric", "ref": m["result_id"],
            "label": spec.label if spec else m["metric_code"],
            "sub": f"FY{m['fiscal_year']} · {m['display'] or m['status']}",
            "value": m["display"], "status": m["status"], "section": None,
        }
    edges.append({"source": source, "target": mid, "kind": kind})
    for inp in m["inputs"]:
        if inp.get("fact_id"):
            _fact_node(inp["fact_id"], nodes, edges, mid)


def _add_ref(ref: str, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]],
             source: str, kind: str = "SECTION_REF") -> None:
    ref_kind, _, body = ref.partition(":")
    if ref_kind == "metric":
        _metric_node(ref, nodes, edges, source, kind)
    elif ref_kind == "fact":
        _fact_node(body, nodes, edges, source)
    elif ref_kind == "rule":
        rid = f"rule:{body}"
        nodes.setdefault(rid, {"id": rid, "type": "rule", "ref": ref,
                               "label": "规则 · " + body.replace("_", " "),
                               "sub": "确定性阈值", "section": None})
        edges.append({"source": source, "target": rid, "kind": kind})
    elif ref_kind == "bench":
        bid = f"bench:{body}"
        nodes.setdefault(bid, {"id": bid, "type": "bench", "ref": ref,
                               "label": "同业中位数", "sub": body, "section": None})
        edges.append({"source": source, "target": bid, "kind": kind})
    elif ref_kind == "edge":
        eid = f"edge:{body}"
        nodes.setdefault(eid, {"id": eid, "type": "edge", "ref": ref,
                               "label": "产业链关系", "sub": "带依据的关系边", "section": None})
        edges.append({"source": source, "target": eid, "kind": kind})
    elif ref_kind in ("loc", "gap"):
        lid = f"{ref_kind}:{body}"
        nodes.setdefault(lid, {"id": lid, "type": "document" if ref_kind == "loc" else "fact",
                               "ref": ref, "label": "定位" if ref_kind == "loc" else "资料缺口",
                               "sub": _short(body, 30), "section": None})
        edges.append({"source": source, "target": lid, "kind": kind})


def _fact_node(fact_id: str, nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]],
               source: str) -> str | None:
    fact = repo.get_fact(fact_id)
    if not fact:
        return None
    nid = f"fact:{fact['fact_id']}"
    if nid not in nodes:
        spec = FIELDS.get(fact["field_code"])
        doc = repo.get_document(fact["document_id"])
        loc = repo.get_location(fact["location_id"])
        nodes[nid] = {
            "id": nid, "type": "fact", "ref": fact["fact_id"],
            "label": spec.label if spec else fact["field_code"],
            "sub": f"{fact['period_end']} · {fact['raw_unit']} · P{loc['page_index'] if loc else '—'}",
            "value": f"{float(fact['value_text']):,.2f}" if fact["value_text"] else None,
            "document_id": fact["document_id"], "section": None,
        }
        if doc:
            did = f"doc:{doc['document_id']}"
            if did not in nodes:
                nodes[did] = {
                    "id": did, "type": "document", "ref": None,
                    "document_id": doc["document_id"],
                    "label": doc["title"], "sub": f"{doc['source_type']} · {doc['published_on']}",
                    "sha256": doc["sha256"], "pages": doc["page_count"], "section": None,
                }
            edges.append({"source": nid, "target": did, "kind": "FROM_DOC"})
    edges.append({"source": source, "target": nid, "kind": "INPUT"})
    return nid


def graph(report_id: str, version_no: int) -> dict[str, Any]:
    order = {k: i for i, k in enumerate(
        ("overview", "industry", "operations", "financials", "peer", "risk", "chain", "data_quality"))}
    sections = sorted(repo.sections_of(report_id, version_no),
                      key=lambda s: order.get(s["section_key"], 99))
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def add_edge(s: str, t: str, kind: str) -> None:
        key = (s, t, kind)
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": s, "target": t, "kind": kind})

    section_stats: list[dict[str, Any]] = []
    for sec in sections:
        skey = sec["section_key"]
        sid = f"sec:{skey}"
        content = sec.get("content") or {}
        claim_ids = list(sec.get("claim_ids") or [])
        nodes[sid] = {"id": sid, "type": "section", "ref": None, "label": content.get("title", skey),
                      "sub": f"{len(claim_ids)} 条结论", "section": skey}
        refs_n = 0
        for cid in claim_ids:
            claim = repo.get_claim(cid)
            if not claim:
                continue
            nid = f"claim:{claim['claim_key']}"
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid, "type": "claim", "ref": claim["claim_version_id"],
                    "label": _short(claim["text"], 38), "sub": f"{claim['kind']} · {claim['verdict']}",
                    "text": claim["text"], "verdict": claim["verdict"], "section": skey,
                }
            add_edge(sid, nid, "HAS_CLAIM")
            for ref in claim["reference_ids"]:
                refs_n += 1
                _add_ref(ref, nodes, edges, nid, kind="CITES")
        # KPI、指标行、同业单元格的 ref 不在 Claim 里，但同样需要可追溯。
        extra: set[str] = set()
        _scan_refs(content, extra)
        for ref in extra:
            refs_n += 1
            _add_ref(ref, nodes, edges, sid)
        section_stats.append({"section": skey, "title": content.get("title", skey),
                              "claims": len(claim_ids), "refs": refs_n, "documents": 0})

    # 去重边
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for e in edges:
        dedup[(e["source"], e["target"], e["kind"])] = e
    edges = list(dedup.values())

    # 每节可达的原件数（BFS）
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append(e["target"])
    for st in section_stats:
        seen: set[str] = set()
        stack = [f"sec:{st['section']}"]
        docs: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            node = nodes.get(cur)
            if node and node["type"] == "document" and node.get("document_id"):
                docs.add(node["document_id"])
            stack.extend(adj.get(cur, []))
        st["documents"] = len(docs)

    doc_nodes = [n for n in nodes.values() if n["type"] == "document" and n.get("document_id")]
    return {
        "report_id": report_id,
        "version_no": version_no,
        "nodes": list(nodes.values()),
        "edges": edges,
        "sections": section_stats,
        "stats": {
            "sections": len(sections),
            "claims": sum(1 for n in nodes.values() if n["type"] == "claim"),
            "metrics": sum(1 for n in nodes.values() if n["type"] == "metric"),
            "facts": sum(1 for n in nodes.values() if n["type"] == "fact"),
            "documents": len(doc_nodes),
            "edges": len(edges),
            "legend": TYPE_LABEL,
        },
        "documents": [{"document_id": n["document_id"], "title": n["label"],
                       "published_on": n.get("sub", "").split(" · ")[-1],
                       "sha256": n.get("sha256"), "pages": n.get("pages")} for n in doc_nodes],
        "note": "图中的边只表示「这条结论实际引用了什么」，不表示因果关系；原件节点可回到 PDF 原页。",
    }
