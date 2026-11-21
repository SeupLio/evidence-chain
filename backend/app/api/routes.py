"""REST + SSE 接口。"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..domain.contracts import RunRequest, SourceMode
from ..domain.keys import content_id
from ..services import evidence as evidence_service
from ..services import provenance, qa, sectors, update
from ..services.ingest import seed_corpus
from ..services.report import SECTION_ORDER
from ..storage import repo
from ..storage.db import init_db, utcnow
from ..workflow import runner

router = APIRouter(prefix="/api")

JOBQ: "queue.Queue[tuple[str, dict[str, Any], dict[str, Any]]]" = queue.Queue()
_WORKER: threading.Thread | None = None


def _worker_loop() -> None:
    while True:
        kind, payload, opts = JOBQ.get()
        try:
            if kind == "research":
                runner.execute(payload, **opts)
        finally:
            JOBQ.task_done()


def start_worker() -> None:
    global _WORKER
    if _WORKER and _WORKER.is_alive():
        return
    _WORKER = threading.Thread(target=_worker_loop, name="research-worker", daemon=True)
    _WORKER.start()


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #

@router.get("/health")
def health() -> dict[str, Any]:
    info = init_db()
    return {"ok": True, **info, "worker": bool(_WORKER and _WORKER.is_alive())}


@router.get("/meta")
def meta() -> dict[str, Any]:
    from ..agents.catalog import catalog
    from ..domain.fields import FIELDS
    from ..domain.metrics import FORMULAS
    from ..workflow import graph as graph_module

    from ..workflow.engine import StateGraph

    g = graph_module.build(lambda *a: None)
    pipeline = {
        "nodes": [{"name": n.name, "label": n.label, "parallel_group": n.parallel_group,
                   "deps": sorted(n.deps)} for n in g.nodes.values()],
        "entry": g.entry,
    }
    return {
        "sections": [{"key": k, "title": t} for k, t in [
            ("overview", "结论摘要"), ("industry", "行业背景与竞争格局"), ("operations", "经营变化与驱动"),
            ("financials", "财务指标与复算"), ("peer", "同业比较"), ("risk", "风险线索与反证"),
            ("chain", "产业链与关联企业"), ("data_quality", "资料覆盖与数据质量")]],
        "pipeline": pipeline,
        "metrics": [{"code": c, "label": s.label, "formula": s.formula_text, "unit": s.unit,
                     "version": s.version} for c, s in FORMULAS.items()],
        "fields": [{"code": c, "label": s.label, "statement": s.statement, "unit": s.unit_kind}
                   for c, s in FIELDS.items()],
        "agents": catalog(),
        "source_modes": ["live", "cached", "replay"],
        "model_modes": ["live", "mock", "replay"],
        "policy": {"resolve": "resolve/v1.3.0", "rules": "rules/v1.0.0", "workflow": "workflow/v1.0.0"},
    }


@router.get("/overview")
def overview() -> dict[str, Any]:
    return sectors.overview()


@router.get("/agents")
def agents() -> dict[str, Any]:
    from ..agents.catalog import catalog

    return catalog()


@router.post("/seed")
def seed(force: bool = False) -> Any:
    init_db()
    repo.mark_stale_runs()
    start_worker()
    result = seed_corpus(force=force)
    if result.get("error") == "DATASET_CONFLICT":
        return JSONResponse(status_code=409, content=result)
    return result


# --------------------------------------------------------------------------- #
# 实体
# --------------------------------------------------------------------------- #

@router.get("/entities")
def entities(q: str = Query(default="")) -> dict[str, Any]:
    if q.strip():
        hits = repo.search_entities(q)
        if not hits:
            return {"mode": "not_found", "candidates": [],
                    "message": "仅支持预置范围：本演示收录啤酒制造业的三家样本，未生成假报告"}
        if len(hits) == 1:
            return {"mode": "unique", "candidates": hits}
        return {"mode": "ambiguous", "candidates": hits,
                "message": "NEEDS_ENTITY_CONFIRMATION：存在多个候选，请选择后再运行"}
    return {"mode": "list", "candidates": repo.list_entities()}


@router.get("/entities/{entity_id}/documents")
def documents(entity_id: str, as_of: str | None = None) -> dict[str, Any]:
    docs = [d for d in repo.documents_visible(as_of, issuer=entity_id)]
    return {"entity_id": entity_id, "documents": docs}


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #

class RunBody(BaseModel):
    entity_id: str
    fiscal_years: list[int] = Field(default_factory=lambda: [2023, 2024, 2025])
    as_of: str = "2026-04-30"
    peer_ids: list[str] = Field(default_factory=list)
    source_mode: str = "replay"
    model_mode: str = "mock"


@router.post("/runs", status_code=202)
def create_run(body: RunBody, request: Request) -> dict[str, Any]:
    start_worker()
    idem = request.headers.get("Idempotency-Key")
    req = {"entity_id": body.entity_id, "fiscal_years": body.fiscal_years, "as_of": body.as_of,
           "peer_ids": body.peer_ids, "source_mode": body.source_mode}
    if not repo.get_entity(body.entity_id):
        raise HTTPException(404, f"未收录的实体：{body.entity_id}")
    run_id = content_id("run", {"req": req, "k": idem or utcnow()})
    req["run_id"] = run_id
    repo.create_run({
        "run_id": run_id, "job_kind": "research", "report_id": None, "status": "queued",
        "idempotency_key": idem, "budget": runner.BUDGET, "payload": req, "result": {},
        "error": None, "heartbeat_at": utcnow(), "created_at": utcnow(), "finished_at": None,
    })
    JOBQ.put(("research", req, {"model_mode": body.model_mode, "source_mode": body.source_mode}))
    return {"run_id": run_id, "status": "queued", "events_url": f"/api/runs/{run_id}/events"}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(404, "run 不存在")
    return run


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request, last_event_id: str | None = None,
                     cursor: int = 0) -> StreamingResponse:
    start = max(cursor, int(last_event_id or 0))

    async def gen():
        seq = start
        idle = 0.0
        yield f": stream start\n\n"
        while True:
            if await request.is_disconnected():
                break
            events = repo.events_after(run_id, seq, 60)
            if events:
                idle = 0.0
                for e in events:
                    seq = e["seq"]
                    data = json.dumps(e["data"], ensure_ascii=False)
                    yield f"id: {seq}\nevent: stage\ndata: {data}\n\n"
            else:
                idle += 0.35
                if idle >= 10:
                    idle = 0.0
                    yield f": heartbeat {int(asyncio.get_event_loop().time())}\n\n"
            run = repo.get_run(run_id)
            if run and run["status"] in ("complete", "partial", "failed", "interrupted") and not events:
                payload = json.dumps({"run_id": run_id, "status": run["status"],
                                      "result": run["result"], "error": run["error"]}, ensure_ascii=False)
                yield f"event: done\ndata: {payload}\n\n"
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #

@router.get("/reports")
def list_reports() -> dict[str, Any]:
    rows = repo.get_conn().execute(
        """SELECT r.report_id, r.entity_id, r.head_version_no, e.name,
                  (SELECT COUNT(*) FROM report_versions v WHERE v.report_id=r.report_id) AS versions
           FROM reports r LEFT JOIN entities e ON e.entity_id=r.entity_id
           ORDER BY r.created_at DESC""").fetchall()
    return {"reports": [dict(r) for r in rows]}


@router.get("/reports/{report_id}/versions")
def versions(report_id: str) -> dict[str, Any]:
    return {"report_id": report_id, "versions": repo.list_report_versions(report_id),
            "head": repo.head_version(report_id)}


@router.get("/reports/{report_id}/versions/{version_no}")
def get_version(report_id: str, version_no: int) -> dict[str, Any]:
    v = repo.get_report_version(report_id, version_no)
    if not v:
        raise HTTPException(404, "版本不存在")
    sections = repo.sections_of(report_id, version_no)
    claims = []
    for sec in sections:
        for cid in sec["claim_ids"]:
            c = repo.get_claim(cid)
            if c:
                claims.append({"claim_version_id": c["claim_version_id"], "claim_key": c["claim_key"],
                               "kind": c["kind"], "verdict": c["verdict"], "text": c["text"],
                               "refs": c["reference_ids"], "section": c["section_key"],
                               "findings": c["findings"]})
    return {"version": v, "sections": sections, "claims": claims,
            "questions": repo.questions_of(report_id)}


@router.get("/reports/{report_id}/diff")
def diff(report_id: str, frm: int = Query(alias="from"), to: int = Query()) -> dict[str, Any]:
    base_secs = {s["section_key"]: s for s in repo.sections_of(report_id, frm)}
    new_secs = {s["section_key"]: s for s in repo.sections_of(report_id, to)}
    sections = []
    for key in SECTION_ORDER:
        b, n = base_secs.get(key), new_secs.get(key)
        sections.append({
            "section_key": key, "title": (n or b or {}).get("content", {}).get("title", key),
            "changed": bool(b and n and b["content_hash"] != n["content_hash"]),
            "old_hash": b["content_hash"][:12] if b else None,
            "new_hash": n["content_hash"][:12] if n else None,
            "same_version_id": bool(b and n and b["section_version_id"] == n["section_version_id"]),
        })
    return {"from": frm, "to": to, "sections": sections}


# --------------------------------------------------------------------------- #
# 引用 / 文档
# --------------------------------------------------------------------------- #

@router.get("/evidence/{ref:path}")
def get_evidence(ref: str) -> dict[str, Any]:
    return evidence_service.resolve(ref).model_dump()


@router.get("/reports/{report_id}/versions/{version_no}/provenance")
def get_provenance(report_id: str, version_no: int) -> dict[str, Any]:
    if not repo.get_report_version(report_id, version_no):
        raise HTTPException(404, "版本不存在")
    return provenance.graph(report_id, version_no)


@router.get("/search")
def search(q: str = Query(default="", min_length=0)) -> dict[str, Any]:
    """命令面板：实体、行业、章节与可执行动作，一次返回。"""
    query = q.strip()
    if not query:
        return {"entities": [], "industries": [], "actions": [
            {"kind": "run", "label": "运行一次研究", "target": "run"},
            {"kind": "industry", "label": "打开产业链", "target": "industry"},
            {"kind": "eval", "label": "查看评测与失败样本", "target": "eval"},
        ]}
    ents = repo.search_entities(query, limit=6)
    inds = [i for i in sectors.market.industries()
            if query in i["name"] or query in i.get("short", "") or query in i["id"]]
    actions = []
    for e in ents[:3]:
        actions.append({"kind": "ask", "label": f"追问 · {e['name']} 的最新毛利率",
                        "target": e["entity_id"]})
    for i in inds[:2]:
        actions.append({"kind": "industry", "label": f"行业 · {i['name']} 样本与产业链",
                        "target": i["id"]})
    if any(w in query for w in ("评测", "一致率", "误差", "失败")):
        actions.append({"kind": "eval", "label": "查看跨源互证与失败样本", "target": "eval"})
    if any(w in query for w in ("缺", "覆盖", "资料")):
        actions.append({"kind": "report", "label": "查看资料覆盖与数据质量", "target": "data_quality"})
    return {"entities": ents, "industries": inds, "actions": actions}


@router.get("/documents/{document_id}")
def get_document(document_id: str) -> dict[str, Any]:
    doc = repo.get_document(document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    locs = repo.get_conn().execute(
        "SELECT location_id,page_index,cell_id,row_label,table_type,excerpt FROM source_locations "
        "WHERE document_id=? ORDER BY page_index LIMIT 400", (document_id,)).fetchall()
    return {"document": doc, "locations": [dict(r) for r in locs]}


@router.get("/documents/{document_id}/file")
def get_file(document_id: str) -> FileResponse:
    doc = repo.get_document(document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return FileResponse(doc["local_path"], media_type="application/pdf")


@router.get("/documents/{document_id}/page/{page}.png")
def get_page_png(document_id: str, page: int) -> FileResponse:
    try:
        path = evidence_service.page_image(document_id, page)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type="image/png")


# --------------------------------------------------------------------------- #
# 追问 / 更新
# --------------------------------------------------------------------------- #

class QuestionBody(BaseModel):
    version_no: int
    question: str
    history: list[str] = Field(default_factory=list)


@router.post("/reports/{report_id}/questions")
def ask(report_id: str, body: QuestionBody) -> dict[str, Any]:
    try:
        return qa.answer(report_id, body.version_no, body.question, history=body.history)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class PreviewBody(BaseModel):
    base_version: int
    staged_doc_ids: list[str] = Field(default_factory=list)
    as_of: str | None = None
    entity_id: str | None = None
    fiscal_years: list[int] = Field(default_factory=lambda: [2023, 2024, 2025])
    peer_ids: list[str] = Field(default_factory=list)
    model_mode: str = "mock"
    source_mode: str = "replay"


@router.post("/reports/{report_id}/updates/preview")
def preview_update(report_id: str, body: PreviewBody) -> dict[str, Any]:
    head = repo.head_version(report_id)
    if head is None:
        raise HTTPException(404, "报告尚无正式版本")
    if head != body.base_version:
        return JSONResponse(status_code=409, content={"code": "STALE_BASE",
                                                     "message": f"最新版本是 v{head}，请基于它重建预览"})
    entity_id = body.entity_id or repo.entity_of_report(report_id)
    req = {"entity_id": entity_id, "fiscal_years": body.fiscal_years, "as_of": body.as_of or "",
           "peer_ids": body.peer_ids}
    try:
        return update.preview(report_id, body.base_version, req, as_of=body.as_of,
                              staged=body.staged_doc_ids, model_mode=body.model_mode,
                              source_mode=body.source_mode)
    except update.NoChange as exc:
        return JSONResponse(status_code=200, content={"code": "NO_CHANGE", "message": str(exc)})
    except update.StaleBase as exc:
        return JSONResponse(status_code=409, content={"code": "STALE_BASE", "message": str(exc)})


class CommitBody(BaseModel):
    base_version: int
    idempotency_key: str | None = None


@router.post("/reports/{report_id}/updates/{draft_version}/commit")
def commit_update(report_id: str, draft_version: int, body: CommitBody) -> Any:
    try:
        return update.commit(report_id, draft_version, body.base_version, body.idempotency_key)
    except update.StaleBase as exc:
        return JSONResponse(status_code=409, content={"code": "STALE_BASE", "message": str(exc)})
    except update.NoChange as exc:
        return JSONResponse(status_code=200, content={"code": "NO_CHANGE", "message": str(exc)})


# --------------------------------------------------------------------------- #
# 行业与产业链（真实公开数据）
# --------------------------------------------------------------------------- #


@router.get("/industries")
def get_industries() -> dict[str, Any]:
    return {"industries": sectors.industries_overview()}


@router.get("/industry-matrix")
def get_industry_matrix(year: int = 2025) -> dict[str, Any]:
    return sectors.industry_matrix(year)


@router.get("/industries/{industry_id}")
def get_industry(industry_id: str, years: str = "2022,2023,2024,2025") -> dict[str, Any]:
    if not sectors.market.industry(industry_id):
        raise HTTPException(status_code=404, detail="行业不存在")
    return sectors.industry_panel(industry_id, [int(y) for y in years.split(",") if y])


@router.get("/industries/{industry_id}/chain")
def get_chain(industry_id: str, year: int = 2025) -> dict[str, Any]:
    if not sectors.market.industry(industry_id):
        raise HTTPException(status_code=404, detail="行业不存在")
    return sectors.chain_with_metrics(industry_id, year)


@router.get("/compare")
def get_compare(field: str = "revenue", year: int = 2025) -> dict[str, Any]:
    return sectors.compare(field, year)


@router.get("/llm")
def get_llm() -> dict[str, Any]:
    from ..providers import llm

    return llm.status()


@router.get("/reports/{report_id}/versions/{version_no}/suggestions")
def get_suggestions(report_id: str, version_no: int) -> dict[str, Any]:
    return {"suggestions": qa.suggest(report_id, version_no, limit=6)}


@router.get("/eval")
def get_eval() -> dict[str, Any]:
    from ..eval.harness import run_eval

    return run_eval()


@router.get("/reports/{report_id}/questions")
def list_questions(report_id: str) -> dict[str, Any]:
    return {"questions": repo.questions_of(report_id)}


@router.get("/reports/{report_id}/versions/{version_no}/export")
def export_version(report_id: str, version_no: int) -> dict[str, Any]:
    v = repo.get_report_version(report_id, version_no)
    if not v:
        raise HTTPException(404, "版本不存在")
    sections = repo.sections_of(report_id, version_no)
    md = [f"# {report_id} · v{version_no}", f"观察截止：{v['as_of']}　指纹：{v['input_fingerprint'][:16]}", ""]
    for s in sections:
        md.append(f"## {s['content'].get('title', s['section_key'])}")
        for p in s["content"].get("paragraphs", []):
            md.append(p["text"])
        md.append("")
    return {"report_id": report_id, "version_no": version_no, "markdown": "\n".join(md),
            "content_hash": v["content_hash"]}
