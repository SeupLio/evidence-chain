"""质量问题聚合。

同类型、同原因的问题在真实语料上会成批出现（一份年报里十几页都声明了
资产负债表却没有表格）。逐条列出会让正文变成流水账，也掩盖了「到底是什么问题」。

聚合规则：`(类型, 严重度, 解释)` 相同即合并为一条，附带出现次数、涉及页码、
财年与字段；原始条目保留在 `items` 里供展开核对。
"""

from __future__ import annotations

from typing import Any, Iterable

SEVERITY_RANK = {"BLOCKING": 0, "WARN": 1, "INFO": 2}

TYPE_LABEL = {
    "COVERAGE_GAP": "覆盖缺口",
    "SCANNED_UNSUPPORTED": "无文本层",
    "NUMERIC_CONFLICT": "数值冲突",
    "RECONCILE_FAIL": "勾稽不平",
    "ROUNDING_COMPATIBLE": "舍入相容",
    "SCOPE_MISMATCH": "口径差异",
    "DATE_UNRELIABLE": "日期不可靠",
    "NOT_CHECKED": "未做检查",
    "STATEMENT_NOT_FOUND": "报表缺失",
    "PAGE_RUN_IGNORED": "重复页段",
    "HEADER_UNRESOLVED": "表头未识别",
}


def _collect(item: dict[str, Any], bucket: dict[str, set]) -> None:
    ctx = item.get("context") or {}
    page = ctx.get("page") or ctx.get("page_index")
    if page:
        bucket["pages"].add(int(page))
    for y in (ctx.get("year"), ctx.get("fiscal_year")):
        if y:
            bucket["years"].add(str(y))
    for f in (ctx.get("field"), ctx.get("field_code")):
        if f:
            bucket["fields"].add(str(f))
    for p in ctx.get("pages") or []:
        try:
            bucket["pages"].add(int(p))
        except (TypeError, ValueError):
            pass


def group_issues(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for i in issues:
        ctx = i.get("context") or {}
        explanation = (ctx.get("explanation") or "").strip()
        sig = (i["type"], i["severity"], explanation)
        g = merged.get(sig)
        if g is None:
            g = merged[sig] = {
                "type": i["type"], "label": TYPE_LABEL.get(i["type"], i["type"]),
                "severity": i["severity"], "explanation": explanation, "count": 0,
                "pages": set(), "years": set(), "fields": set(), "items": [],
            }
        g["count"] += 1
        _collect(i, g)
        if len(g["items"]) < 40:
            g["items"].append({"issue_id": i["issue_id"], "key": i["key"],
                               "context": {k: v for k, v in ctx.items() if k != "explanation"}})

    out: list[dict[str, Any]] = []
    for g in merged.values():
        g["pages"] = sorted(g["pages"])
        g["years"] = sorted(g["years"])
        g["fields"] = sorted(g["fields"])
        out.append(g)
    out.sort(key=lambda g: (SEVERITY_RANK.get(g["severity"], 9), -g["count"], g["type"]))
    return out


def summarize(groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "groups": len(groups),
        "items": sum(g["count"] for g in groups),
        "blocking": sum(g["count"] for g in groups if g["severity"] == "BLOCKING"),
        "merged_away": sum(g["count"] - 1 for g in groups),
    }
