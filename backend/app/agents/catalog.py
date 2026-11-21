"""多智能体角色目录：前端「研究台」直接读这份定义，而不是在前端硬编码。

设计原则：角色不是人格设定，而是**权限边界 + 结构化契约**。
每个角色只拿到自己需要的上下文，只能输出自己 schema 内的字段；
图只负责调度，业务真值留在服务端对象里。
"""

from __future__ import annotations

from typing import Any

AGENTS: list[dict[str, Any]] = [
    {
        "id": "plan", "name": "计划 Agent", "code": "PLAN", "stage": "规划",
        "nodes": ["plan"], "verb": "先看有什么，再决定要什么",
        "mission": "根据观察截止日与可用原件，生成「财年 × 字段」覆盖矩阵；缺失项如实标 MISSING。",
        "inputs": ["实体", "财年", "as_of", "已入库事实"],
        "outputs": ["覆盖矩阵", "缺失计数", "预算"],
        "tools": ["原件可见性查询", "字段字典"],
        "forbidden": ["评价经营", "补造文档", "输出数值"],
        "contract": "PlanOutput",
        "guard": "只统计可见性；冲突与否交给核验引擎。",
        "color": "#d6fb6a",
    },
    {
        "id": "collect", "name": "资料 Agent", "code": "COLLECT", "stage": "搜集",
        "nodes": ["collect", "ingest"], "verb": "只提查询提案，不写结论",
        "mission": "按缺口提出可执行的检索提案，标明预期发布方、文档类型与目标年度；通过后登记原件与定位。",
        "inputs": ["缺口清单", "实体与交易所", "来源白名单"],
        "outputs": ["查询提案", "查询白名单", "入库文档与页码定位"],
        "tools": ["巨潮公告检索", "交易所 orgId 表", "PDF 下载与哈希"],
        "forbidden": ["把搜索摘要当证据", "抓取白名单外域名", "生成数字"],
        "contract": "CollectOutput",
        "guard": "搜索摘要最多用于发现；最终 URL 要由代码校验发布方与日期。",
        "color": "#7fa6ff",
    },
    {
        "id": "finance", "name": "财务 Agent", "code": "FINANCE", "stage": "核验",
        "nodes": ["finance_extract", "verify_calc"], "verb": "只指认单元格，不返回数字",
        "mission": "在三张主表里指认候选单元格；由服务端按 cell_id 回读原值，再做同键比较、冲突判定与 Decimal 复算。",
        "inputs": ["候选单元格", "FactKey 口径", "第三方结构化数据"],
        "outputs": ["单元格选择", "事实决策", "指标结果"],
        "tools": ["行名词典", "口径分桶", "舍入相容", "勾稽检查"],
        "forbidden": ["回写原值", "跨口径比较", "在冲突时取一个值"],
        "contract": "FinanceOutput",
        "guard": "同级冲突即 FREEZE；缺证显示缺证，不显示 0。",
        "color": "#e8c583",
    },
    {
        "id": "industry", "name": "行业 Agent", "code": "INDUSTRY", "stage": "行业",
        "nodes": ["industry", "validate_industry"], "verb": "每条关系都要能点回原文",
        "mission": "汇总行业样本与产业链关系；每条边给依据，打不开原文的关系降级或移除。",
        "inputs": ["行业事实", "政策引用", "关系边候选"],
        "outputs": ["行业事实", "关系边", "缺口"],
        "tools": ["行业样本聚合", "产业链边表", "证据可达性校验"],
        "forbidden": ["把推断当披露", "把样本合计当行业总量", "编造交易关系"],
        "contract": "IndustryOutput",
        "guard": "样本 n<2 不输出基准；未具名供应商不补全。",
        "color": "#9be6c4",
    },
    {
        "id": "risk", "name": "风险 Agent", "code": "RISK", "stage": "解释",
        "nodes": ["risk_explain"], "verb": "只解释已触发的警报",
        "mission": "对确定性规则产出的警报，补上观察事实、潜在影响、反证与下一份材料。",
        "inputs": ["规则结果", "指标快照", "同业基准"],
        "outputs": ["风险解释", "未评估项", "补证建议"],
        "tools": ["规则解释模板", "反证检索"],
        "forbidden": ["改阈值", "改判", "输出违约概率或投资建议"],
        "contract": "RiskOutput",
        "guard": "未触发只能说「本次覆盖规则未触发」，不能写「公司无风险」。",
        "color": "#ff7a6b",
    },
    {
        "id": "audit", "name": "审核 Agent", "code": "AUDIT", "stage": "审核",
        "nodes": ["compose", "audit"], "verb": "不改数字，只挑问题",
        "mission": "检查每条结论的引用是否可达、数字是否绑定、措辞是否过强；未过审的结论不进入正文。",
        "inputs": ["Claim 草稿", "引用索引", "版本边界"],
        "outputs": ["审核问题码", "阻断清单", "发布版本"],
        "tools": ["数字守卫", "引用可达性", "数字绑定检查"],
        "forbidden": ["改数字", "绕过阻断", "超出当前版本证据"],
        "contract": "AuditOutput",
        "guard": "模板里不允许出现阿拉伯数字；数字只能由槽位注入。",
        "color": "#b79cff",
    },
]

PIPELINE = [
    {"from": "plan", "to": "collect", "label": "覆盖矩阵"},
    {"from": "collect", "to": "finance", "label": "原件与定位"},
    {"from": "collect", "to": "industry", "label": "行业资料"},
    {"from": "finance", "to": "risk", "label": "指标与事实"},
    {"from": "industry", "to": "risk", "label": "行业基准"},
    {"from": "risk", "to": "audit", "label": "解释与反证"},
]


def catalog() -> dict[str, Any]:
    return {
        "agents": AGENTS,
        "pipeline": PIPELINE,
        "roles": len(AGENTS),
        "note": "角色边界由工作流与 Pydantic 契约执行；提示词只是其中一层。",
        "parallel": [
            {"group": "finance", "agents": ["finance"], "nodes": ["finance_extract", "verify_calc"]},
            {"group": "industry", "agents": ["industry"], "nodes": ["industry", "validate_industry"]},
        ],
    }
