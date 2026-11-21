"""字段字典：行名词典 + 口径定义。

抽取层的硬约束：**字段只能从自己所属的报表里取**。
把「营业成本」从「营业总成本」行取到，或者从目录页取到，都会污染整条证据链，
所以这里既给别名，也给 ``statement`` 边界，并要求完整行名匹配优先于包含匹配。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    code: str
    label: str
    aliases: tuple[str, ...]
    statement: str          # balance_sheet | income_statement | cash_flow | segment | summary | industry
    period_kind: str        # FY（流量） | POINT（期末余额）
    unit_kind: str          # cny | percent | volume
    definition_id: str
    sign: int = 1
    core: bool = False      # P0 核心字段


FIELDS: dict[str, FieldSpec] = {
    # ---------------- 利润表（合并，年度） ----------------
    "revenue": FieldSpec(
        "revenue", "营业收入",
        ("营业收入", "其中：营业收入"),
        "income_statement", "FY", "cny", "cas_income_statement_revenue_v1", core=True,
    ),
    "total_revenue_alt": FieldSpec(
        "total_revenue_alt", "营业总收入",
        ("营业总收入", "一、营业总收入"),
        "income_statement", "FY", "cny", "cas_income_statement_total_revenue_v1",
    ),
    "operating_cost": FieldSpec(
        "operating_cost", "营业成本",
        ("营业成本", "其中：营业成本"),
        "income_statement", "FY", "cny", "cas_income_statement_cost_v1", core=True,
    ),
    "net_profit_total": FieldSpec(
        "net_profit_total", "净利润",
        ("净利润", "五、净利润", "四、净利润", "净利润（净亏损以“－”号填列）"),
        "income_statement", "FY", "cny", "cas_income_statement_np_v1", core=True,
    ),
    "net_profit_parent": FieldSpec(
        "net_profit_parent", "归属于母公司所有者的净利润",
        ("归属于母公司所有者的净利润", "归属于母公司股东的净利润", "归属于上市公司股东的净利润"),
        "income_statement", "FY", "cny", "cas_income_statement_npp_v1", core=True,
    ),
    "minority_interest": FieldSpec(
        "minority_interest", "少数股东损益",
        ("少数股东损益",),
        "income_statement", "FY", "cny", "cas_income_statement_mi_v1",
    ),
    # ---------------- 资产负债表（合并，期末） ----------------
    "total_assets": FieldSpec(
        "total_assets", "资产总计",
        ("资产总计", "资产合计", "总资产"),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_assets_v1", core=True,
    ),
    "total_liabilities": FieldSpec(
        "total_liabilities", "负债合计",
        ("负债合计",),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_liab_v1", core=True,
    ),
    "total_equity": FieldSpec(
        "total_equity", "所有者权益合计",
        ("所有者权益（或股东权益）合计", "所有者权益合计", "股东权益合计"),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_equity_v1", core=True,
    ),
    "liab_equity_total": FieldSpec(
        "liab_equity_total", "负债和所有者权益总计",
        ("负债和所有者权益（或股东权益）总计", "负债和所有者权益总计", "负债和股东权益总计"),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_lie_v1",
    ),
    "inventories": FieldSpec(
        "inventories", "存货",
        ("存货",),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_inv_v1",
    ),
    "receivables": FieldSpec(
        "receivables", "应收账款",
        ("应收账款",),
        "balance_sheet", "POINT", "cny", "cas_balance_sheet_ar_v1",
    ),
    # ---------------- 现金流量表（合并，年度） ----------------
    "operating_cashflow": FieldSpec(
        "operating_cashflow", "经营活动产生的现金流量净额",
        ("经营活动产生的现金流量净额",),
        "cash_flow", "FY", "cny", "cas_cashflow_ocf_v1", core=True,
    ),
    # ---------------- 分部（管理层讨论/附注） ----------------
    "seg_revenue_beer": FieldSpec(
        "seg_revenue_beer", "啤酒业务营业收入",
        ("啤酒业务", "啤酒业务收入", "主营业务—啤酒"),
        "segment", "FY", "cny", "seg_beer_revenue_v1",
    ),
    "seg_cost_beer": FieldSpec(
        "seg_cost_beer", "啤酒业务营业成本",
        ("啤酒业务成本", "啤酒业务营业成本"),
        "segment", "FY", "cny", "seg_beer_cost_v1",
    ),
    "seg_revenue_other": FieldSpec(
        "seg_revenue_other", "其他业务营业收入",
        ("其他业务", "其他业务收入"),
        "segment", "FY", "cny", "seg_other_revenue_v1",
    ),
    "seg_cost_other": FieldSpec(
        "seg_cost_other", "其他业务营业成本",
        ("其他业务成本", "其他业务营业成本"),
        "segment", "FY", "cny", "seg_other_cost_v1",
    ),
}

CORE_FIELDS = tuple(c for c, s in FIELDS.items() if s.core)

#: 报表类型 → 允许抽取的字段
STATEMENT_FIELDS: dict[str, tuple[str, ...]] = {
    "income_statement": ("revenue", "operating_cost", "net_profit_total", "net_profit_parent",
                         "minority_interest", "total_revenue_alt"),
    "balance_sheet": ("total_assets", "total_liabilities", "total_equity", "liab_equity_total",
                      "inventories", "receivables"),
    "cash_flow": ("operating_cashflow",),
    "segment": ("seg_revenue_beer", "seg_cost_beer", "seg_revenue_other", "seg_cost_other"),
    # 主要会计数据用同一会计定义，只是单位与精度不同；审计层级更低
    "summary": ("revenue", "operating_cost", "net_profit_total", "net_profit_parent",
                "operating_cashflow", "total_assets", "total_liabilities", "total_equity"),
}

STATEMENT_TITLES: dict[str, tuple[str, ...]] = {
    "income_statement": ("合并利润表", "利润表"),
    "balance_sheet": ("合并资产负债表", "资产负债表"),
    "cash_flow": ("合并现金流量表", "现金流量表"),
    "segment": ("分部信息", "主营业务分行业情况", "分行业经营情况"),
}

#: 目录页/摘要页的识别词，命中后整页不作为抽取候选
NOISE_MARKERS = ("目录", "CONTENTS", "重要提示")

#: 形似但口径不同的行名——命中即拒绝，绝不靠包含匹配蒙混
EXCLUSIONS: dict[str, str] = {
    "营业总成本": "营业总成本含税金及附加与期间费用，不等于营业成本",
    "营业总收入": "营业总收入口径大于营业收入，另立字段",
    "营业利润": "营业利润不等于净利润",
    "利润总额": "利润总额不等于净利润",
    "归属于上市公司股东的净资产": "归母净资产不等于所有者权益合计",
    "归属于母公司所有者权益合计": "归母权益不等于所有者权益合计",
    "流动资产合计": "流动资产合计只是资产的一部分",
    "非流动资产合计": "非流动资产合计只是资产的一部分",
    "流动负债合计": "流动负债合计只是负债的一部分",
    "非流动负债合计": "非流动负债合计只是负债的一部分",
    "资产减值损失": "减值损失不是资产总计",
    "营业收入合计": "多栏合计行需人工确认口径",
}

FIELD_BY_LABEL: dict[str, str] = {}
for _code, _spec in FIELDS.items():
    for _alias in _spec.aliases:
        FIELD_BY_LABEL[_alias.replace(" ", "")] = _code


_PREFIX = re.compile(r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十\d]+[）)]|其中[：:]|加[：:]|减[：:]|\d+[.．、])")


def match_field(label: str) -> str | None:
    """行名 → 字段码。

    匹配顺序：精确 → 去掉「四、」「其中：」等前缀后精确 → 前缀式包含。
    **不做任意包含匹配**：否则「流动资产合计」会被当成「资产合计」。
    """
    norm = _norm_label(label)
    if not norm or norm in EXCLUSIONS:
        return None
    if norm in FIELD_BY_LABEL:
        return FIELD_BY_LABEL[norm]
    stripped = norm
    for _ in range(3):
        new = _PREFIX.sub("", stripped)
        if new == stripped:
            break
        stripped = new
    if stripped in EXCLUSIONS:
        return None
    if stripped in FIELD_BY_LABEL:
        return FIELD_BY_LABEL[stripped]
    for alias, code in FIELD_BY_LABEL.items():
        if len(alias) >= 4 and stripped.startswith(alias):
            return code
    return None


def _norm_label(label: str) -> str:
    """统一空格与括号形态。

    PDF 抽取会把全角括号规范成半角（NFKC），而别名表用全角；
    不统一的话「所有者权益（或股东权益）合计」会永远匹配不上。
    """
    return ((label or "").replace(" ", "").replace("\u3000", "").strip("　:：")
            .replace("(", "（").replace(")", "）"))


def exclusion_reason(label: str) -> str | None:
    norm = _norm_label(label)
    return EXCLUSIONS.get(norm) or EXCLUSIONS.get(_PREFIX.sub("", norm))
