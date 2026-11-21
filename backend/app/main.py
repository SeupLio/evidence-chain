"""FastAPI 应用入口。

单进程、单 worker：研究任务由内部有界队列串行执行，解析/检索在任务内部再并发。
默认只监听 127.0.0.1；没有鉴权，不对外暴露。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router, start_worker
from .storage import repo
from .storage.db import init_db

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    info = init_db()
    stale = repo.mark_stale_runs()
    start_worker()
    print(f"[startup] db={info['path']} integrity={info['integrity']} stale_runs={stale}")
    print("[startup] 如语料为空，请先执行：python -m app.cli seed --pack beer-demo")
    yield


app = FastAPI(title="经营证据链 · Evidence Chain", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        candidate = FRONTEND_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
