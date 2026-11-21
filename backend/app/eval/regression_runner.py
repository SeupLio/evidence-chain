"""在独立 DATA_DIR 中运行合成回归赛道，输出 JSON。

由 ``app.eval.regression`` 以子进程方式调用：父进程继续使用真实公开数据库，
子进程只在自己的临时库里 seed / run / 计算，互不污染。
"""

from __future__ import annotations

import json
import sys

from ..services.ingest import seed_corpus
from ..storage.db import init_db
from ..workflow.runner import execute


def main() -> None:
    init_db()
    seeded = seed_corpus()
    if seeded.get("error"):
        print(json.dumps({"error": seeded}, ensure_ascii=False))
        return
    req = {"entity_id": "SH:600600", "fiscal_years": [2023, 2024, 2025],
           "as_of": "2026-04-30", "peer_ids": ["SH:600132", "SZ:002461"], "run_id": "reg-run"}
    result = execute(req, model_mode="mock", source_mode="replay")
    if not result.get("version"):
        print(json.dumps({"error": "run_failed", "result": result}, ensure_ascii=False))
        return

    from .harness import conflict_scores, extraction_scores, incremental_scores

    payload = {
        "status": "ok",
        "extraction": extraction_scores(),
        "conflicts": conflict_scores(),
        "incremental": incremental_scores(),
    }
    print("<<<REGRESSION_JSON>>>" + json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
    sys.exit(0)
