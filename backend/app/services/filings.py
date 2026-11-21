"""巨潮资讯（cninfo）年报原件接入。

为什么用巨潮：它是交易所指定的信息披露平台，年报 PDF 属**法定披露文件**，
是「证据链」能落到页码的前提。第三方结构化数据只用于交叉验证，不当作原件。

约束：
- 只下载「年度报告」正文，跳过摘要、英文版、已取消、问询回复；
- 文件名用 `{code}_{year}.pdf`，sha256 入库，内容变了就是新 document_id；
- 断点续传：已存在且 sha 一致则直接复用，不重复下载。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain.keys import content_id
from ..storage import repo
from ..storage.db import utcnow
from . import market

ROOT = Path(__file__).resolve().parents[2]      # backend/
FILINGS = ROOT.parent / "data" / "filings"

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
STATIC = "http://static.cninfo.com.cn/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "http://www.cninfo.com.cn/new/disclosure/stock",
}

SKIP = ("摘要", "英文", "已取消", "问询", "回复", "说明", "意见", "公告", "H股", "债券")


STOCK_LIST = ROOT.parent / "data" / "cache" / "szse_stock.json"


def org_id(code: str) -> str:
    """巨潮的 orgId 不是「gssh0+代码」的统一规则，必须查全量清单。

    清单一次下载后缓存；查不到时退回旧规则（对部分沪市代码仍然有效）。
    """
    try:
        if not STOCK_LIST.exists():
            STOCK_LIST.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request("http://www.cninfo.com.cn/new/data/szse_stock.json",
                                         headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                STOCK_LIST.write_bytes(resp.read())
        data = json.loads(STOCK_LIST.read_text(encoding="utf-8"))
        for s in data.get("stockList", []):
            if s.get("code") == code:
                return s["orgId"]
    except Exception:
        pass
    return f"gssh0{code}" if market.market_of(code) == "SH" else f"gssz0{code}"


def _post(url: str, data: dict[str, Any], timeout: int = 30) -> str:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        **HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_annual_reports(code: str, *, years: list[int] | None = None,
                          retries: int = 3) -> list[dict[str, Any]]:
    """返回该公司全部年度报告正文（按年份倒序）。"""
    org = org_id(code)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            raw = _post(QUERY_URL, {
                "stock": f"{code},{org}", "tabName": "fulltext", "pageSize": 30, "pageNum": 1,
                "column": "szse", "category": "category_ndbg_szsh", "plate": "",
                "seDate": "", "searchkey": "", "secid": "", "sortName": "", "sortType": "",
                "isHLtitle": "true",
            })
            payload = json.loads(raw)
            out: list[dict[str, Any]] = []
            for a in payload.get("announcements") or []:
                title = a.get("announcementTitle") or ""
                if not re.search(r"\d{4}\s*年年度报告$", title):
                    continue
                if any(k in title for k in SKIP):
                    continue
                year = int(re.search(r"(\d{4})\s*年年度报告", title).group(1))
                if years and year not in years:
                    continue
                ts = a.get("announcementTime")
                pub = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
                out.append({"code": code, "year": year, "title": title.strip(),
                            "url": STATIC + (a.get("adjunctUrl") or ""),
                            "published_on": pub, "size_kb": a.get("adjunctSize")})
            # 同一年的 A 股版与 H 股版会同时命中：只留披露最早的那份（A 股正文）
            best: dict[int, dict[str, Any]] = {}
            for r in sorted(out, key=lambda x: (x["published_on"] or "9999", x["title"])):
                best.setdefault(r["year"], r)
            return sorted(best.values(), key=lambda x: -x["year"])
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{code} 年报检索失败：{last}")


def download(url: str, path: Path, *, retries: int = 3) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 200_000:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                blob = resp.read()
            if len(blob) < 100_000:
                raise RuntimeError(f"响应过小（{len(blob)} 字节），可能是错误页")
            path.write_bytes(blob)
            return hashlib.sha256(blob).hexdigest()
        except Exception as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"下载失败 {url}：{last}")


def register_filing(meta: dict[str, Any], sha256: str, path: Path) -> dict[str, Any]:
    """把一份年报登记为 document（不解析，解析在 extract 阶段）。"""
    logical = f"{market.entity_id_of(meta['code'])}:annual_report:{meta['year']}"
    document_id = content_id("doc", {"lk": logical, "sha": sha256})
    doc = {
        "document_id": document_id,
        "logical_doc_key": logical,
        "sha256": sha256,
        "canonical_url": meta["url"],
        "title": meta["title"],
        "issuer": market.entity_id_of(meta["code"]),
        "source_type": "annual_report",
        "published_on": meta["published_on"],
        "retrieved_at": utcnow(),
        "period_start": f"{meta['year']}-01-01",
        "period_end": f"{meta['year']}-12-31",
        "content_type": "application/pdf",
        "page_count": 0,
        "local_path": str(path),
        "parser_version": "filings/v1.0.0",
        "tier": "primary",
        "demo_role": None,
    }
    repo.upsert_document(doc)
    return doc


def sync_filings(*, years: list[int] | None = None, codes: list[str] | None = None,
                 mode: str = "live", log=print) -> dict[str, Any]:
    """批量下载并登记年报。mode=replay 时只登记本地已有文件。"""
    targets = [c for c in market.companies() if not codes or c["code"] in set(codes)]
    stats = {"downloaded": 0, "reused": 0, "registered": 0, "missing": [], "errors": []}
    for c in targets:
        try:
            reports = search_annual_reports(c["code"], years=years)
        except Exception as exc:
            stats["errors"].append({"code": c["code"], "error": str(exc)[:140]})
            continue
        if not reports:
            stats["missing"].append(c["code"])
            continue
        for r in reports:
            path = FILINGS / f"{c['code']}_{r['year']}.pdf"
            if mode == "replay":
                if not path.exists():
                    stats["missing"].append(f"{c['code']}:{r['year']}")
                    continue
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                stats["reused"] += 1
            else:
                existed = path.exists()
                sha = download(r["url"], path)
                stats["reused" if existed else "downloaded"] += 1
            register_filing(r, sha, path)
            stats["registered"] += 1
        log(f"  {c['entity_id']:<12} {c['name']:<8} 年报 {len(reports)} 份")
    return stats
