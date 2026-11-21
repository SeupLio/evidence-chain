"""核心不变量测试。用 `pytest -q` 跑。

原则：期望值独立写死在测试里，不复用生产公式函数——否则「同一函数算两遍」没有意义。
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ec-test-"))

from app.domain.contracts import Confidence, Decision, MetricStatus  # noqa: E402
from app.domain.keys import FactKey, canonical_json, dec_str  # noqa: E402
from app.domain.metrics import FORMULAS, FactSlot, compute_one, pct, pp  # noqa: E402
from app.domain.textguard import render  # noqa: E402
from app.domain.fields import match_field  # noqa: E402

D = Decimal


def _slot(v: str | None, ok: bool = True) -> FactSlot:
    return FactSlot(D(v) if v else None, f"fact:{v}", Confidence.HIGH, "OK" if ok else "BLOCKED")


# --------------------------------------------------------------------------- #
# 指标：缺证、边界、单位
# --------------------------------------------------------------------------- #

def test_missing_input_is_null_not_zero():
    m = compute_one("gross_margin", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"revenue": _slot("100"), "operating_cost": _slot(None)})
    assert m.status == MetricStatus.MISSING_INPUT
    assert m.value_text is None
    assert m.display is None
    assert "operating_cost" in (m.missing_reason or "")


def test_zero_revenue_is_invalid_base():
    m = compute_one("gross_margin", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"revenue": _slot("0"), "operating_cost": _slot("70")})
    assert m.status == MetricStatus.INVALID_BASE


def test_gross_margin_value_and_display():
    m = compute_one("gross_margin", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"revenue": _slot("100"), "operating_cost": _slot("70")})
    assert m.status == MetricStatus.OK
    assert m.value_text == "0.3"          # 比率存储，50% 存 0.5
    assert m.display == "30.00%"


def test_pp_is_already_multiplied():
    m = compute_one("gross_margin_delta_pp", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"cur": _slot("0.30"), "prev": _slot("0.34")})
    assert m.value_text == "-4"   # 十进制字符串去尾零
    assert m.display == "-4.00pp"          # 前端不得再乘 100


def test_cash_conversion_negative_denominator_keeps_raw():
    m = compute_one("cash_conversion", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"operating_cashflow": _slot("10"), "net_profit_total": _slot("-5")})
    assert m.status == MetricStatus.INVALID_BASE
    assert m.display is None
    assert "经营现金流" in (m.missing_reason or "")


def test_blocked_input_freezes_metric():
    m = compute_one("debt_asset_ratio", entity_id="E", fiscal_year=2025, mkey="k",
                    values={"total_liabilities": _slot("50", ok=False), "total_assets": _slot("100")})
    assert m.status == MetricStatus.BLOCKED_INPUT


def test_all_formulas_have_version_and_text():
    for code, spec in FORMULAS.items():
        assert spec.version >= 1
        assert spec.formula_text
        assert spec.slots


# --------------------------------------------------------------------------- #
# 文本守卫：模型不能自己写数字
# --------------------------------------------------------------------------- #

def _resolver(mapping):
    def r(kind, ref):
        return mapping.get(ref)
    return r


def test_unbound_number_is_blocked():
    out = render("毛利率下降 4pp。", _resolver({}))
    assert out.verdict.value == "BLOCK"
    assert any(f["code"] == "CLAIM_UNBOUND_NUMBER" for f in out.findings)


def test_bound_number_passes():
    out = render("毛利率 {{m:gross_margin@2025}}。", _resolver({"gross_margin@2025": ("41.36%", "metric:1")}))
    assert out.verdict.value == "PASS"
    assert out.refs == ["metric:1"]


def test_strong_causality_blocked():
    out = render("毛利率下滑必然导致利润下降。", _resolver({}))
    assert any(f["code"] == "CLAIM_STRONG_CAUSALITY" and f["level"] == "BLOCK" for f in out.findings)


def test_unresolved_ref_blocks():
    out = render("毛利率 {{m:not_exist@2025}}。", _resolver({}))
    assert out.verdict.value == "BLOCK"
    assert "［待补证］" in out.text


# --------------------------------------------------------------------------- #
# 口径：行名匹配必须拒绝近似但不同的概念
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label,expected", [
    ("营业收入", "revenue"),
    ("其中：营业收入", "revenue"),
    ("营业成本", "operating_cost"),
    ("其中：营业成本", "operating_cost"),
    ("四、净利润", "net_profit_total"),
    ("归属于母公司所有者的净利润", "net_profit_parent"),
])
def test_row_label_matches(label, expected):
    assert match_field(label) == expected


@pytest.mark.parametrize("label", ["营业总成本", "营业总收入", "流动资产合计", "非流动资产合计", "营业利润"])
def test_row_label_rejects_near_misses(label):
    assert match_field(label) is None


# --------------------------------------------------------------------------- #
# FactKey：口径不同就不是同一个键
# --------------------------------------------------------------------------- #

def test_fact_key_separates_scope_and_consolidation():
    base = dict(entity_id="E", field_code="revenue", period_start="2025-01-01", period_end="2025-12-31",
                period_kind="FY", currency="CNY", definition_id="d")
    cons = FactKey(**base, consolidation="consolidated", business_scope="total")
    parent = FactKey(**base, consolidation="parent", business_scope="total")
    seg = FactKey(**base, consolidation="consolidated", business_scope="segment:beer")
    assert len({cons.key, parent.key, seg.key}) == 3


def test_period_kind_point_vs_flow_differs():
    flow = FactKey("E", "revenue", "2025-01-01", "2025-12-31", "FY", "consolidated", "CNY", "total", "d")
    point = FactKey("E", "total_assets", "2025-12-31", "2025-12-31", "POINT", "consolidated", "CNY", "total", "d")
    assert flow.key != point.key


# --------------------------------------------------------------------------- #
# 格式化
# --------------------------------------------------------------------------- #

def test_formatters():
    assert pct(D("0.4136")) == "41.36%"
    assert pp(D("-2.5666")) == "-2.57pp"
    assert pp(D("1.2")) == "+1.20pp"
    assert dec_str(D("19360412880.62")) == "19360412880.62"
    assert canonical_json({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'
