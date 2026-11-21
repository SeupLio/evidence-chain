"""LLM 客户端与角色契约。

三种模式同形：
- live：调用 OpenAI 兼容接口，强制 JSON；
- mock：走各角色的确定性策略（没有密钥也能跑完整链路，界面上明确标注）；
- replay：读已录制的结构化响应。

无论哪种模式，输出都必须通过 pydantic 校验；校验失败先修复一次，仍失败则落确定性模板，
**不允许假装成功**。模型不写库、不联网、不计算、不发布。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Type

import httpx
from pydantic import BaseModel, ValidationError


class AgentError(Exception):
    pass


@dataclass
class LLMUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    repaired: int = 0
    fallbacks: int = 0


@dataclass
class AgentResult:
    role: str
    output: BaseModel
    mode: str
    used_fallback: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "mode": self.mode, "used_fallback": self.used_fallback,
                "notes": self.notes, "output": self.output.model_dump()}


class LLMClient:
    """限额、缓存、修复都收在一处，避免每个 Agent 各写一套。"""

    def __init__(self, *, mode: str = "mock", base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, max_calls: int = 14, timeout: float = 60.0):
        self.mode = mode
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or ""
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.max_calls = max_calls
        self.timeout = timeout
        self.usage = LLMUsage()
        self._cache: dict[str, dict[str, Any]] = {}

    @property
    def live(self) -> bool:
        return self.mode == "live" and bool(self.base_url) and bool(self.api_key)

    def generate_json(self, *, role: str, schema: Type[BaseModel], context: dict[str, Any],
                      instructions: str, fallback: Callable[[dict[str, Any]], BaseModel],
                      cache_key: str | None = None) -> AgentResult:
        key = cache_key or f"{role}:{hash(json.dumps(context, sort_keys=True, default=str))}"
        if key in self._cache:
            return AgentResult(role=role, output=schema.model_validate(self._cache[key]),
                               mode=self.mode, notes=["命中本进程缓存"])

        if not self.live:
            out = fallback(context)
            self._validate(out, schema, role)
            self._cache[key] = out.model_dump()
            return AgentResult(role=role, output=out, mode=self.mode,
                               used_fallback=True, notes=["确定性策略（未调用外部模型）"])

        if self.usage.calls >= self.max_calls:
            raise AgentError(f"超出本次任务模型调用上限 {self.max_calls} 次")

        payload = None
        try:
            payload = self._post(role, instructions, context)
        except Exception as exc:
            # 单次网络超时/限流不应打断整条研究链路：落确定性策略并留痕。
            self.usage.fallbacks += 1
            out = fallback(context)
            self._validate(out, schema, role)
            self._cache[key] = out.model_dump()
            return AgentResult(role=role, output=out, mode=self.mode, used_fallback=True,
                               notes=[f"模型调用失败，已落确定性模板：{str(exc)[:180]}"])
        self.usage.calls += 1
        try:
            out = schema.model_validate(payload)
        except ValidationError as exc:
            self.usage.repaired += 1
            payload = self._post(role, instructions + "\n\n上一次输出未通过校验，请严格按 schema 返回 JSON。", context,
                                 error=str(exc)[:800])
            try:
                out = schema.model_validate(payload)
            except ValidationError:
                self.usage.fallbacks += 1
                out = fallback(context)
                self._validate(out, schema, role)
                self._cache[key] = out.model_dump()
                return AgentResult(role=role, output=out, mode=self.mode, used_fallback=True,
                                   notes=["模型输出两次未通过校验，已落确定性模板"])
        self._cache[key] = out.model_dump()
        return AgentResult(role=role, output=out, mode=self.mode)

    def _post(self, role: str, instructions: str, context: dict[str, Any], error: str = "") -> dict[str, Any]:
        system = (instructions
                  + "\n\n只输出一个合法 JSON 对象，不要输出 Markdown 代码块、前后缀或解释。")
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)[:24000]
                 + (f"\n\n校验错误：{error}" if error else "")},
            ],
        }
        # 部分 OpenAI 兼容网关不支持 response_format；400 时去掉它重试一次。
        for attempt in range(2):
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=body,
                                   headers={"Authorization": f"Bearer {self.api_key}"})
            if resp.status_code < 400:
                data = resp.json()
                break
            if resp.status_code == 400 and "response_format" in body:
                body.pop("response_format", None)
                continue
            raise AgentError(
                f"{role} 调用失败 HTTP {resp.status_code}：{resp.text[:600]}"
            )
        else:  # pragma: no cover - 两次都失败
            raise AgentError(f"{role} 调用失败")
        self.usage.prompt_tokens += int(data.get("usage", {}).get("prompt_tokens", 0))
        self.usage.completion_tokens += int(data.get("usage", {}).get("completion_tokens", 0))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.rstrip().endswith("```"):
                content = content.rstrip()[:-3]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentError(f"{role} 返回非 JSON：{exc}；原文：{content[:300]}") from exc

    @staticmethod
    def _validate(out: BaseModel, schema: Type[BaseModel], role: str) -> None:
        if not isinstance(out, schema):
            raise AgentError(f"{role} 输出类型不符：{type(out).__name__}")
