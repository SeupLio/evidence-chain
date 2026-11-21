"""大模型通道（OpenAI 兼容接口）。

边界写死在这里，不靠提示词自觉：
- 模型**不能写数字**：输出经过数字守卫，出现阿拉伯数字或中文数量词直接丢弃；
- 模型**不能新增引用**：只能从给定的 evidence 列表里挑 id，挑不中就当没挑；
- 模型**不能决定结论**：指标、规则、判定全部由确定性代码算完，模型只做
  「选哪些结论进入摘要」与「写一段不带数字的阅读提示」。

未配置 key 时 `available()` 为 False，整条链路自动走确定性策略，
不影响演示与评测。
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

DEFAULT_BASE = "https://api.openai.com/v1"
TIMEOUT = 45


def config() -> dict[str, Any]:
    return {
        "base_url": (os.environ.get("LLM_BASE_URL") or DEFAULT_BASE).rstrip("/"),
        "model": os.environ.get("LLM_MODEL") or "",
        "api_key": os.environ.get("LLM_API_KEY") or "",
    }


def available() -> bool:
    c = config()
    return bool(c["api_key"] and c["model"])


def status() -> dict[str, Any]:
    c = config()
    return {"configured": available(), "model": c["model"] or None,
            "base_url": c["base_url"], "key_present": bool(c["api_key"])}


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    c = config()
    req = urllib.request.Request(
        f"{c['base_url']}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {c['api_key']}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def complete(system: str, user: str, *, temperature: float = 0.2,
             max_tokens: int = 900) -> str:
    if not available():
        raise RuntimeError("LLM 未配置：请设置 LLM_API_KEY / LLM_MODEL")
    body = {
        "model": config()["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    data = _post("/chat/completions", body)
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def chain_brief(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    """让模型写一段产业链阅读提示；只提示传导路径，不写数字、不评价好坏。"""
    import re

    from ..domain.textguard import BLOCK_WORDS, WARN_WORDS

    lines = [f"{e.get('relation')}：{e.get('src_name')} → {e.get('dst_name')}"
             for e in edges[:24]]
    system = (
        "你是产业链研究助手。只写一段不超过 90 字的产业链阅读提示："
        "先看哪一段传导，再核对什么。只提示阅读顺序，不评价风险，"
        "不得出现数字、金额、百分比或日期，不得使用「导致」「说明」这类因果断言，"
        "不使用「异常」「风险」「问题」「恶化」「改善」等判断词，并用「需…」收尾。"
        "直接输出提示文本，不要 JSON，不要解释。"
    )
    user = "产业链节点：" + "、".join(n.get("name", "") for n in nodes[:40]) + "\n关系：\n" + "\n".join(lines)
    brief = complete(system, user, temperature=0.2, max_tokens=220).strip()
    brief = brief.strip("`").strip()
    if (not brief or re.search(r"[0-9]", brief)
            or any(w in brief for w in BLOCK_WORDS + WARN_WORDS + ("异常", "风险", "问题", "恶化", "改善"))):
        return ""
    return brief[:200]


def pick_and_brief(facts_brief: str, candidates: list[dict[str, str]]) -> dict[str, Any]:
    """让模型选结论 + 写阅读提示；返回值一律经过守卫。"""
    import re

    from ..domain.contracts import ClaimKind
    from ..domain.textguard import BLOCK_WORDS, WARN_WORDS, check_numeric_claim

    system = (
        "你是财报研究助手。你只能做两件事：\n"
        "1) 从候选结论中挑选最多 6 条最能支撑判断的，返回它们的 id；\n"
        "2) 写一段不超过 80 字的阅读提示，只回答「先看什么、再核对什么」，"
        "只提示阅读顺序，不评价风险，不使用「异常」「风险」「问题」「恶化」「改善」等判断词，"
        "不得出现任何阿拉伯数字、百分比、金额或日期，不得使用「导致」「说明」这类因果断言，"
        "并用「需…」收尾。\n"
        "严格输出 JSON：{\"picks\":[\"id\"],\"brief\":\"...\"}"
    )
    user = json.dumps({"evidence": facts_brief, "candidates": candidates}, ensure_ascii=False)
    raw = complete(system, user)
    try:
        start, end = raw.find("{"), raw.rfind("}")
        obj = json.loads(raw[start:end + 1])
    except Exception:
        return {"picks": [], "brief": "", "error": "模型输出不是合法 JSON"}

    valid_ids = {c["id"] for c in candidates}
    picks = [p for p in obj.get("picks", []) if p in valid_ids][:6]
    brief = str(obj.get("brief", "")).strip()[:200]
    if (re.search(r"[0-9]", brief)
            or any(w in brief for w in BLOCK_WORDS + WARN_WORDS + ("异常", "风险", "问题", "恶化", "改善"))):
        return {"picks": picks, "brief": "", "rejected": ["LLM_BRIEF_UNSAFE"]}
    findings = check_numeric_claim(ClaimKind.INTERPRETATION, brief)
    if findings:
        return {"picks": picks, "brief": "", "rejected": [f["code"] for f in findings]}
    return {"picks": picks, "brief": brief}
