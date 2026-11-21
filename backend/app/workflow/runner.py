"""任务执行器：建 run、跑图、写事件。

任务与 SSE 解耦：执行器只往 run_events 追加事件，SSE 端按 seq 补发。
慢连接不会拖住任务；同一事件可能重复送达，前端按 (run_id, seq) 去重。
"""

from __future__ import annotations

import asyncio
import traceback
from typing import Any

from ..agents.base import LLMClient
from ..storage import repo
from ..storage.db import utcnow
from . import graph as graph_module

BUDGET = {"wall_clock_s": 90, "llm_calls_max": 14}


class EventBus:
    def __init__(self, run_id: str):
        self.run_id = run_id
        row = repo.get_conn().execute(
            "SELECT COALESCE(MAX(seq),0) FROM run_events WHERE run_id=?", (run_id,)).fetchone()
        self.seq = int(row[0]) if row else 0

    def __call__(self, node: str, status: str, message: str, counts: dict[str, int]) -> None:
        self.seq += 1
        repo.add_event(self.run_id, self.seq, "stage", {
            "run_id": self.run_id, "seq": self.seq, "node": node, "status": status,
            "message": message, "counts": counts, "elapsed_ms": counts.get("elapsed_ms", 0),
            "ts": utcnow(),
        })


def compute_state(req: dict[str, Any], *, model_mode: str, source_mode: str,
                  base_version_no: int | None = None, base_sections: list | None = None,
                  changed_sections: set[str] | None = None, staged: list[str] | None = None,
                  publish_state: str = "published", label: str = "") -> dict[str, Any]:
    subject = repo.get_entity(req["entity_id"])
    if not subject:
        raise ValueError(f"未收录的实体：{req['entity_id']}")
    peers = [repo.get_entity(p) for p in req.get("peer_ids", [])]
    peers = [p for p in peers if p]
    return {
        "run_id": req.get("run_id", ""),
        "subject": subject,
        "peers": peers,
        "years": req["fiscal_years"],
        "as_of": req["as_of"],
        "source_mode": source_mode,
        "model_mode": model_mode,
        "llm": LLMClient(mode=model_mode),
        "base_version_no": base_version_no,
        "base_sections": base_sections,
        "changed_sections": changed_sections,
        "staged_doc_ids": staged or [],
        "publish_state": publish_state,
        "label": label,
        "statuses": {},
        "issues": [],
    }


def execute(req: dict[str, Any], *, model_mode: str = "mock", source_mode: str = "replay",
            base_version_no: int | None = None, base_sections: list | None = None,
            changed_sections: set[str] | None = None, staged: list[str] | None = None,
            publish_state: str = "published", label: str = "") -> dict[str, Any]:
    run_id = req["run_id"]
    bus = EventBus(run_id)
    repo.update_run(run_id, status="running", heartbeat_at=utcnow())
    bus("__run__", "start", "研究任务开始", {"budget_s": BUDGET["wall_clock_s"]})
    state = compute_state(req, model_mode=model_mode, source_mode=source_mode,
                          base_version_no=base_version_no, base_sections=base_sections,
                          changed_sections=changed_sections, staged=staged,
                          publish_state=publish_state, label=label)
    compiled = graph_module.build(bus)
    try:
        final = compiled.invoke(state)
    except Exception as exc:  # pragma: no cover
        repo.update_run(run_id, status="failed", error=f"{exc}", finished_at=utcnow())
        bus("__run__", "fail", f"任务失败：{exc}", {})
        return {"status": "failed", "error": str(exc), "trace": traceback.format_exc()[-1500:]}

    version = final.get("version")
    status = "complete" if version else "partial"
    usage = state["llm"].usage
    agent_log = final.get("agent_log", [])
    llm_usage = {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
                 "completion_tokens": usage.completion_tokens, "repaired": usage.repaired,
                 "fallbacks": usage.fallbacks}
    repo.update_run(run_id, status=status, finished_at=utcnow(),
                    result={"version": version, "errors": final.get("errors", {}),
                            "agent_log": agent_log, "llm_usage": llm_usage})
    bus("__run__", "ok" if status == "complete" else "partial",
        f"任务{'完成' if status == 'complete' else '部分完成'}",
        {"elapsed_ms": 0, "llm_calls": usage.calls})
    return {"status": status, "version": version, "errors": final.get("errors", {}),
            "agent_log": agent_log, "llm_usage": llm_usage,
            "state": {k: v for k, v in final.items() if k in ("doc_ids", "queries", "risk_out", "audit_out")}}


def start_run(req: dict[str, Any], *, model_mode: str = "mock", source_mode: str = "replay",
              idempotency_key: str | None = None) -> str:
    from ..domain.keys import content_id

    run_id = content_id("run", {"req": req, "k": idempotency_key or ""})
    existing = repo.get_run(run_id)
    if existing:
        return run_id
    repo.create_run({
        "run_id": run_id, "job_kind": "research", "report_id": req.get("report_id"),
        "status": "queued", "idempotency_key": idempotency_key, "budget": BUDGET,
        "payload": req, "result": {}, "error": None, "heartbeat_at": utcnow(),
        "created_at": utcnow(), "finished_at": None,
    })
    return run_id
