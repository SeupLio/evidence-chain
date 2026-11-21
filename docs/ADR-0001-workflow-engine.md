# ADR-0001：用极简 DAG 执行器替代 LangGraph

- 状态：已采纳
- 日期：2026-11-20
- 影响范围：`backend/app/workflow/`

## 背景

计划书第 2 章建议用 LangGraph `StateGraph` 编排多智能体工作流。本项目需要的能力只有五项：

1. 命名节点 + 函数签名 `state -> partial_state`；
2. 两支并行（财务核验 / 行业图谱），互不阻塞；
3. 多起点汇合（join）；
4. 按 key 合并的 reducer（公共 issue 按 `issue_id` 幂等合并）；
5. 每节点开始时/结束时的状态事件（推给 SSE）。

## 决策

实现 `app/workflow/engine.py`（约 130 行），提供与 LangGraph 同形的接口：
`add_node / add_edge / set_entry / compile / ainvoke / describe`，
用 Kahn 拓扑 + `asyncio.gather` 执行就绪节点，`_merge` 实现 reducer。

## 理由

1. **依赖风险不可接受**。本机首次安装时 `pymupdf` 63 MB 在 80 kB/s 下要 13 分钟；
   比赛现场重新 `uv sync` 赌不起。当前后端依赖只有 6 个，全部可离线缓存。
2. **语义只用到子集**。没有 checkpoint、没有中断恢复、没有子图、
   没有 human-in-the-loop，引入完整框架带来的抽象成本大于收益。
3. **可解释性**。评委问「为什么这两个分支能并行」，答案是一段 130 行可读代码，
   而不是「框架就是这么做的」。

## 兼容契约

- 节点函数签名与 LangGraph 一致：接收 state、返回 partial state；
- state 中的 `issues` 用「按 `issue_id` 合并」的 reducer，与 LangGraph 的 `Annotated[list, reducer]` 等价；
- 单支异常被捕获为本支 `statuses[node] = fail`，不向上抛；
- 将来替换只需改 `workflow/graph.py` 末段 10 行的构造代码，`compile()` 返回值同形。

## 验证

- `tests/test_flow.py::test_incremental_update_is_isolated` 验证合流后的章节隔离；
- 运行台页面直接渲染 `graph.describe()`，节点、并行组、依赖与实际执行一致；
- 事件序列（`run_events`）可回放，`(run_id, seq)` 幂等。

## 替代方案与否决理由

| 方案 | 否决理由 |
|---|---|
| LangGraph | 依赖体积与版本漂移风险；本项目只用其子集语义 |
| Celery / Redis 队列 | 单进程单任务，SQLite 足够；多一个中间件就多一个现场故障点 |
| 纯 `asyncio` 手写 `gather` | 无拓扑校验，容易写出隐式依赖；无法输出可展示的管线图 |
