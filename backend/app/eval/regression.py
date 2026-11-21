"""合成回归赛道的隔离执行器。

主库只读真实公开数据；回归赛道在临时 DATA_DIR 中启动子进程完成
seed → run → 指标/冲突/增量计算，再把 JSON 结果带回来。
这样既不污染主库，又能在评测页展示完整的两条赛道。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
MARK = "<<<REGRESSION_JSON>>>"
_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
TTL = 900


def run_isolated(force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _CACHE["data"] and now - _CACHE["at"] < TTL:
        return _CACHE["data"]

    tmp = tempfile.mkdtemp(prefix="ec-regression-")
    env = {**os.environ, "DATA_DIR": tmp, "PYTHONIOENCODING": "utf-8"}
    code = "from app.eval.regression_runner import main; main()"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "note": "回归赛道超过 180 秒未完成"}

    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(MARK)), None)
    if not line:
        return {"status": "failed", "note": "回归子进程没有返回结果",
                "stderr": (proc.stderr or "")[-600:]}
    data = json.loads(line[len(MARK):])
    data["isolated"] = True
    data["db"] = tmp
    data["note"] = "在独立临时 DATA_DIR 中运行；主库仍只含 real_cninfo，未被污染。"
    _CACHE.update({"at": now, "data": data})
    return data
