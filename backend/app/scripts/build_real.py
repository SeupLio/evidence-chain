"""一次性把真实数据装进库里：实体 → 结构化财务 → 产业链 → 年报原件 → 事实。

用法：python -m app.scripts.build_real --years 2023 2024 2025
可重复执行：已下载的年报不会重复下载，已解析的文档不会重复写事实。
"""

from __future__ import annotations

import argparse
import time

from ..services import filings, market, real_ingest
from ..storage.db import init_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, default=[2023, 2024, 2025])
    ap.add_argument("--mode", default="live", choices=["live", "cached", "replay"])
    ap.add_argument("--skip-filings", action="store_true")
    ap.add_argument("--skip-parse", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    print(f"[1/4] 初始化 {init_db()['path']}")
    print(f"[2/4] 实体 {market.sync_entities()} 家")
    s = market.sync_market_facts(mode=args.mode)
    print(f"      结构化：{s['companies']} 家 / {s['records']} 个年度 / {s['facts']} 条事实")
    if s["errors"]:
        print("      失败：", s["errors"])
    print(f"      产业链 {market.sync_chains()}")

    if not args.skip_filings:
        print(f"[3/4] 年报原件（{args.years}）")
        f = filings.sync_filings(years=args.years, mode=args.mode)
        print(f"      下载 {f['downloaded']} 复用 {f['reused']} 登记 {f['registered']}")
        if f["errors"]:
            print("      失败：", f["errors"][:4])

    if not args.skip_parse:
        print("[4/4] 解析并入库")
        r = real_ingest.ingest_all(years=args.years, log=print)
        print(f"      文档 {r['documents']} 事实 {r['facts']} 空 {len(r['empty'])}")
    print(f"完成，用时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
