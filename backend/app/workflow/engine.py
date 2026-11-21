"""极简 DAG 执行器（LangGraph StateGraph 同形接口）。

为什么不用 LangGraph：本机首次 `uv sync` 依赖下载不稳定，比赛现场更不能赌安装。
本执行器只保留本项目真正用到的语义——命名节点、并发分支、多起点汇合、
按 key 合并的 reducer、每节点状态事件——接口与 LangGraph 保持一致，
将来替换只需改 `workflow/graph.py` 的构造部分。

选择记录见 docs/ADR-0001-workflow-engine.md。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]
Emitter = Callable[[str, str, str, dict[str, int]], None]

#: 这些 key 用「按 id 合并」的 reducer，汇合时不会被覆盖
LIST_REDUCERS = {"issues": "issue_id", "events": "seq", "findings": "code", "agent_log": "role"}


@dataclass
class Node:
    name: str
    fn: NodeFn
    label: str = ""
    parallel_group: str = ""
    deps: set[str] = field(default_factory=set)


class StateGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.entry: str | None = None

    def add_node(self, name: str, fn: NodeFn, *, label: str = "", parallel_group: str = "") -> None:
        self.nodes[name] = Node(name=name, fn=fn, label=label or name, parallel_group=parallel_group)

    def add_edge(self, src: str, dst: str) -> None:
        if dst not in self.nodes or src not in self.nodes:
            raise KeyError(f"未注册的节点：{src}->{dst}")
        self.nodes[dst].deps.add(src)

    def set_entry(self, name: str) -> None:
        self.entry = name

    def describe(self) -> dict[str, Any]:
        return {
            "nodes": [{"name": n.name, "label": n.label, "parallel_group": n.parallel_group,
                       "deps": sorted(n.deps)} for n in self.nodes.values()],
            "entry": self.entry,
        }

    def compile(self, emit: Emitter | None = None) -> "CompiledGraph":
        if self.entry is None:
            raise ValueError("未设置入口节点")
        missing = [n.name for n in self.nodes.values() if n.name != self.entry and not n.deps]
        if missing:
            raise ValueError(f"存在孤立节点：{missing}")
        return CompiledGraph(list(self.nodes.values()), self.entry, emit)


class CompiledGraph:
    def __init__(self, nodes: list[Node], entry: str, emit: Emitter | None):
        self.nodes = {n.name: n for n in nodes}
        self.entry = entry
        self.emit = emit

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        remaining = dict(self.nodes)
        completed: dict[str, dict[str, Any]] = {}
        state = dict(state)
        while remaining:
            ready = [n for n in remaining.values() if n.deps <= set(completed)]
            if not ready:
                raise RuntimeError(f"依赖成环或缺失：{[n.name for n in remaining.values()]}")
            results = await asyncio.gather(*[self._run_node(n, state) for n in ready])
            for node, res in zip(ready, results):
                state = self._merge(state, res)
                completed[node.name] = res
                remaining.pop(node.name)
        return state

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.ainvoke(state))

    def describe(self) -> dict[str, Any]:
        return {"nodes": [{"name": n.name, "label": n.label, "parallel_group": n.parallel_group,
                           "deps": sorted(n.deps)} for n in self.nodes.values()],
                "entry": self.entry}

    async def _run_node(self, node: Node, state: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        if self.emit:
            self.emit(node.name, "start", f"{node.label} 开始", {})
        try:
            out = node.fn(state)
            if inspect.isawaitable(out):
                out = await out
            out = out or {}
        except Exception as exc:  # 单支失败不拖垮另一支
            import traceback
            tb = traceback.format_exc().strip().splitlines()[-4:]
            elapsed = int((time.perf_counter() - started) * 1000)
            if self.emit:
                self.emit(node.name, "fail", f"{node.label} 失败：{exc}", {"elapsed_ms": elapsed})
            return {"statuses": {node.name: "fail"},
                    "errors": {node.name: f"{exc} @ {' | '.join(tb)}"}}
        elapsed = int((time.perf_counter() - started) * 1000)
        if self.emit:
            counts = out.get("counts", {})
            self.emit(node.name, "ok", f"{node.label} 完成", {**counts, "elapsed_ms": elapsed})
            if "statuses" in out and out["statuses"]:
                out = {**out, "statuses": {**state.get("statuses", {}), **out["statuses"]}}
        return out

    @staticmethod
    def _merge(state: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
        merged = dict(state)
        for key, value in delta.items():
            if key in LIST_REDUCERS and isinstance(value, list):
                idkey = LIST_REDUCERS[key]
                existing = {item.get(idkey): item for item in merged.get(key, []) if isinstance(item, dict)}
                for item in value:
                    if isinstance(item, dict):
                        existing[item.get(idkey)] = item
                    else:
                        existing.setdefault(str(item), item)
                merged[key] = list(existing.values())
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged
