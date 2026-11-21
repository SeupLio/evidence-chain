"""确定性指标引擎。

三条硬规则：
1. 只用白名单 Python 函数注册表计算，不 eval、不执行模型生成的表达式。
2. 全程 Decimal + ``localcontext(prec=34)``；比例不提前舍入，展示时 2 位 ROUND_HALF_UP。
3. 缺输入返回 null + MISSING_INPUT，除零/负基数返回 INVALID_BASE，绝不把缺失展示成 0。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Callable, Iterable

from .contracts import Confidence, MetricInput, MetricResult, MetricStatus
from .keys import dec_str, metric_result_id

PREC = 34
D = Decimal
ZERO = D(0)


# --------------------------------------------------------------------------- #
# 数值工具
# --------------------------------------------------------------------------- #

def q(value: Decimal, places: str = "0.0001") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def pct(value: Decimal, places: int = 2) -> str:
    """比例 → 百分比展示。0.4247 → 42.47%"""
    with localcontext() as ctx:
        ctx.prec = PREC
        scaled = value * D(100)
    return f"{q(scaled, '0.01' if places == 2 else '0.' + '0' * places)}%"


def pp(value: Decimal) -> str:
    """百分点 → 带符号展示。数字本身已是 pp，前端不得再乘 100。"""
    v = q(value, "0.01")
    return f"{'+' if v >= 0 else ''}{v}pp"


def cny_yi(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = PREC
        yi = value / D(10**8)
    return f"{q(yi, '0.01')} 亿元"


# --------------------------------------------------------------------------- #
# 公式注册表
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FormulaSpec:
    code: str
    version: int
    unit: str                     # fraction | pp | cny
    label: str
    description: str
    formula_text: str
    slots: tuple[str, ...]
    requires_positive: tuple[str, ...]
    fn: Callable[[dict[str, Decimal]], Decimal]


def _revenue_yoy(v: dict[str, Decimal]) -> Decimal:
    return (v["revenue"] - v["revenue_prev"]) / v["revenue_prev"]


def _gross_margin(v: dict[str, Decimal]) -> Decimal:
    return (v["revenue"] - v["operating_cost"]) / v["revenue"]


def _parent_net_margin(v: dict[str, Decimal]) -> Decimal:
    return v["net_profit_parent"] / v["revenue"]


def _debt_asset_ratio(v: dict[str, Decimal]) -> Decimal:
    return v["total_liabilities"] / v["total_assets"]


def _ocf_margin(v: dict[str, Decimal]) -> Decimal:
    return v["operating_cashflow"] / v["revenue"]


def _cash_conversion(v: dict[str, Decimal]) -> Decimal:
    return v["operating_cashflow"] / v["net_profit_total"]


def _receivables_days(v: dict[str, Decimal]) -> Decimal:
    # 期末口径，不取平均余额；与同业对比时统一用同一口径。
    return v["receivables"] / v["revenue"] * D(365)


def _inventory_days(v: dict[str, Decimal]) -> Decimal:
    return v["inventories"] / v["operating_cost"] * D(365)


def _delta_pp(v: dict[str, Decimal]) -> Decimal:
    return (v["cur"] - v["prev"]) * D(100)


FORMULAS: dict[str, FormulaSpec] = {
    "revenue_yoy": FormulaSpec(
        "revenue_yoy", 1, "fraction", "营业收入同比",
        "本期营业收入相对上一完整同口径财年的增长率",
        "(revenue_t / revenue_t1) - 1",
        ("revenue", "revenue_prev"), ("revenue_prev",), _revenue_yoy,
    ),
    "gross_margin": FormulaSpec(
        "gross_margin", 1, "fraction", "毛利率",
        "(营业收入 - 营业成本) / 营业收入，合并口径",
        "(revenue - operating_cost) / revenue",
        ("revenue", "operating_cost"), ("revenue",), _gross_margin,
    ),
    "parent_net_margin": FormulaSpec(
        "parent_net_margin", 1, "fraction", "归母净利率",
        "归母净利润 / 营业收入；不当作合并净利率使用",
        "net_profit_parent / revenue",
        ("net_profit_parent", "revenue"), ("revenue",), _parent_net_margin,
    ),
    "debt_asset_ratio": FormulaSpec(
        "debt_asset_ratio", 1, "fraction", "资产负债率",
        "总负债 / 总资产，期末余额；分子是总负债而非有息债务",
        "total_liabilities / total_assets",
        ("total_liabilities", "total_assets"), ("total_assets",), _debt_asset_ratio,
    ),
    "ocf_margin": FormulaSpec(
        "ocf_margin", 1, "fraction", "经营现金流/营收",
        "经营活动产生的现金流量净额 / 营业收入",
        "operating_cashflow / revenue",
        ("operating_cashflow", "revenue"), ("revenue",), _ocf_margin,
    ),
    "cash_conversion": FormulaSpec(
        "cash_conversion", 1, "fraction", "现金含量",
        "经营现金流 / 合并净利润；分母为合并净利润，非归母",
        "operating_cashflow / net_profit_total",
        ("operating_cashflow", "net_profit_total"), (), _cash_conversion,
    ),
    "receivables_days": FormulaSpec(
        "receivables_days", 1, "days", "应收账款周转天数",
        "期末应收账款 / 营业收入 × 365，期末口径；不与平均余额口径混用",
        "receivables / revenue * 365",
        ("receivables", "revenue"), ("revenue",), _receivables_days,
    ),
    "inventory_days": FormulaSpec(
        "inventory_days", 1, "days", "存货周转天数",
        "期末存货 / 营业成本 × 365，期末口径；用于观察备货与成本节奏",
        "inventories / operating_cost * 365",
        ("inventories", "operating_cost"), ("operating_cost",), _inventory_days,
    ),
    "gross_margin_delta_pp": FormulaSpec(
        "gross_margin_delta_pp", 1, "pp", "毛利率变动",
        "两期毛利率之差，单位为百分点",
        "(gross_margin_t - gross_margin_t1) * 100",
        ("cur", "prev"), (), _delta_pp,
    ),
    "asset_ratio_delta_pp": FormulaSpec(
        "asset_ratio_delta_pp", 1, "pp", "资产负债率变动",
        "两期期末资产负债率之差，单位为百分点",
        "(debt_asset_ratio_t - debt_asset_ratio_t1) * 100",
        ("cur", "prev"), (), _delta_pp,
    ),
    "ocf_margin_delta_pp": FormulaSpec(
        "ocf_margin_delta_pp", 1, "pp", "经营现金流/营收变动",
        "两期经营现金流/营收比率之差，单位为百分点",
        "(ocf_margin_t - ocf_margin_t1) * 100",
        ("cur", "prev"), (), _delta_pp,
    ),
}

FORMULA_VERSION = "metrics/v1.0.0"
#: 计算顺序：基础比率先算，变动类指标依赖基础比率
COMPUTE_ORDER = (
    "gross_margin", "debt_asset_ratio", "ocf_margin", "parent_net_margin",
    "receivables_days", "inventory_days", "revenue_yoy", "cash_conversion",
    "gross_margin_delta_pp", "asset_ratio_delta_pp", "ocf_margin_delta_pp",
)
DELTA_SOURCES = {
    "gross_margin_delta_pp": ("gross_margin", "gross_margin"),
    "asset_ratio_delta_pp": ("debt_asset_ratio", "debt_asset_ratio"),
    "ocf_margin_delta_pp": ("ocf_margin", "ocf_margin"),
}


# --------------------------------------------------------------------------- #
# 计算
# --------------------------------------------------------------------------- #

@dataclass
class FactSlot:
    value: Decimal | None
    fact_id: str | None
    confidence: Confidence
    status: str = "OK"
    display_raw: str | None = None


def compute_one(
    code: str,
    *,
    entity_id: str,
    fiscal_year: int,
    mkey: str,
    values: dict[str, FactSlot],
    compare_scope: str = "single",
) -> MetricResult:
    spec = FORMULAS[code]
    inputs: list[MetricInput] = []
    confs: list[Confidence] = []
    blocked = False
    missing: list[str] = []

    for slot in spec.slots:
        fs = values.get(slot)
        if fs is None or fs.value is None:
            missing.append(slot)
            inputs.append(MetricInput(slot=slot, value_text=None, fact_id=None, status="MISSING"))
            continue
        inputs.append(
            MetricInput(slot=slot, value_text=dec_str(fs.value), fact_id=fs.fact_id, status=fs.status)
        )
        confs.append(fs.confidence)
        if fs.status in ("BLOCKED", "AMBIGUOUS"):
            blocked = True

    base = dict(
        metric_key=mkey,
        metric_code=code,
        formula_id=f"{code}:v{spec.version}",
        formula_version=spec.version,
        entity_id=entity_id,
        fiscal_year=fiscal_year,
        unit=spec.unit,  # type: ignore[arg-type]
        inputs=inputs,
        input_refs=[i.fact_id for i in inputs if i.fact_id],
        compare_scope=compare_scope,
        computed_at=datetime.now(timezone.utc),
    )

    if blocked:
        return _finish(base, MetricStatus.BLOCKED_INPUT, "输入事实存在未解决的同级冲突，指标冻结", inputs, Confidence.LOW)
    if missing:
        return _finish(base, MetricStatus.MISSING_INPUT, f"缺少输入：{', '.join(missing)}", inputs, Confidence.LOW)

    vals = {slot: values[slot].value for slot in spec.slots}  # type: ignore[misc]
    for name in spec.requires_positive:
        v = vals.get(name)
        if v is None:
            return _finish(base, MetricStatus.MISSING_INPUT, f"缺少输入：{name}", inputs, Confidence.LOW)
        if v <= ZERO:
            return _finish(base, MetricStatus.INVALID_BASE, f"基数不合法：{name} = {dec_str(v)}（需为正数）", inputs, Confidence.LOW)

    if code == "cash_conversion" and vals["net_profit_total"] <= ZERO:
        raw = _raw_pair(vals)
        return _finish(
            base, MetricStatus.INVALID_BASE,
            "分母（合并净利润）≤ 0，不输出比例，仅展示原值：" + raw, inputs,
            Confidence.weakest(confs),
        )

    try:
        with localcontext() as ctx:
            ctx.prec = PREC
            value = spec.fn(vals)  # type: ignore[arg-type]
    except (ZeroDivisionError, InvalidOperation) as exc:  # pragma: no cover - 由上面的守卫兜住
        return _finish(base, MetricStatus.INVALID_BASE, f"计算失败：{exc}", inputs, Confidence.LOW)

    if not value.is_finite():
        return _finish(base, MetricStatus.INVALID_BASE, "计算结果非有限值", inputs, Confidence.LOW)

    result = _finish(base, MetricStatus.OK, None, inputs, Confidence.weakest(confs))
    return result.model_copy(
        update={
            "value_text": dec_str(q(value, "0.0000000001")),
            "display": _display(code, spec.unit, value),
            "result_id": metric_result_id(mkey, result.formula_id, spec.version, result.input_refs, "OK", dec_str(q(value, "0.0000000001"))),
        }
    )


def _raw_pair(vals: dict[str, Decimal]) -> str:
    return f"经营现金流 {cny_yi(vals['operating_cashflow'])}，净利润 {cny_yi(vals['net_profit_total'])}"


def _display(code: str, unit: str, value: Decimal) -> str:
    if unit == "fraction":
        return pct(value)
    if unit == "pp":
        return pp(value)
    if unit == "days":
        return f"{q(value, '0.01')} 天"
    return cny_yi(value)


def _finish(base: dict, status: MetricStatus, reason: str | None, inputs: list[MetricInput], conf: Confidence) -> MetricResult:
    payload = dict(base, status=status, missing_reason=reason, confidence=conf)
    payload["result_id"] = metric_result_id(
        base["metric_key"], base["formula_id"], base["formula_version"], base["input_refs"], status.value, None
    )
    return MetricResult(**payload)


class InvalidOperation(Exception):  # pragma: no cover
    pass


def compute_suite(
    *,
    entity_id: str,
    fiscal_year: int,
    year_facts: dict[int, dict[str, FactSlot]],
    metric_lookup: dict[tuple[str, int], MetricResult],
) -> dict[str, MetricResult]:
    """按 COMPUTE_ORDER 计算一个实体一年份的全部指标（依赖已算好的更早年份）。"""
    from .keys import metric_key as mk

    out: dict[str, MetricResult] = {}
    for code in COMPUTE_ORDER:
        spec = FORMULAS[code]
        mkey = mk(entity_id, code, fiscal_year)
        if code in DELTA_SOURCES:
            src_code, _ = DELTA_SOURCES[code]
            cur = metric_lookup.get((src_code, fiscal_year)) or out.get(src_code)
            prev = metric_lookup.get((src_code, fiscal_year - 1))
            values = {
                "cur": FactSlot(_dec(cur.value_text) if cur and cur.value_text else None,
                                cur.result_id if cur else None,
                                cur.confidence if cur else Confidence.LOW,
                                "OK" if cur and cur.status == MetricStatus.OK else "BLOCKED"),
                "prev": FactSlot(_dec(prev.value_text) if prev and prev.value_text else None,
                                 prev.result_id if prev else None,
                                 prev.confidence if prev else Confidence.LOW,
                                 "OK" if prev and prev.status == MetricStatus.OK else "BLOCKED"),
            }
        else:
            facts = year_facts.get(fiscal_year, {})
            values = {}
            for slot in spec.slots:
                if slot == "revenue_prev":
                    prev_facts = year_facts.get(fiscal_year - 1, {})
                    values[slot] = prev_facts.get("revenue", FactSlot(None, None, Confidence.LOW))
                else:
                    values[slot] = facts.get(slot, FactSlot(None, None, Confidence.LOW))
        out[code] = compute_one(code, entity_id=entity_id, fiscal_year=fiscal_year, mkey=mkey, values=values)
        metric_lookup[(code, fiscal_year)] = out[code]
    return out


def _dec(text: str) -> Decimal:
    return Decimal(text)
