"""风险规则：先规则、后解释。

规则是**确定性函数**，只吃 MetricsSnapshot + 同业基准，输出 TRIGGERED / NOT_TRIGGERED / NOT_EVALUABLE。
模型不能设阈值、不能改判定、不能把 NOT_EVALUABLE 升格成事实。
未触发时只能说“本次覆盖规则未触发”，并在同页列出未评估项——不写“公司无风险”。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .contracts import Confidence, Issue, IssueType, MetricResult, MetricStatus, RuleStatus

D = Decimal


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    version: str
    label: str
    status: RuleStatus
    severity: str                 # 关注 | 需人工核对
    headline: str
    observed: dict[str, str] = field(default_factory=dict)
    input_ids: list[str] = field(default_factory=list)
    threshold_text: str = ""
    potential_impact: str = ""
    counter_evidence: str = ""
    next_material: str = ""
    enhanced: bool = False
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "label": self.label,
            "status": self.status.value,
            "severity": self.severity,
            "headline": self.headline,
            "observed": self.observed,
            "input_ids": self.input_ids,
            "threshold_text": self.threshold_text,
            "potential_impact": self.potential_impact,
            "counter_evidence": self.counter_evidence,
            "next_material": self.next_material,
            "enhanced": self.enhanced,
            "missing": self.missing,
        }


DEFAULT_PACK: dict[str, Any] = {
    "id": "operating_watch_v1",
    "version": "rules/v1.0.0",
    "margin_pressure": {
        "delta_pp_le": -2.0,
        "peer_gap_pp_le": -3.0,
        "severity": "关注",
    },
    "cash_divergence": {
        "ocf_margin_delta_pp_le": -5.0,
        "severity": "关注",
    },
    "balance_sheet_watch": {
        "delta_pp_ge": 5.0,
        "ratio_ge": 0.65,
        "severity": "需人工核对",
    },
}


ROOT = Path(__file__).resolve().parents[2]  # backend/


def load_pack(path: str | Path | None = None) -> dict[str, Any]:
    """从配置读阈值；相对路径同时按 CWD 与仓库根解析，避免换目录启动就失配。"""
    if path:
        candidates = [Path(path), ROOT / path]
        for c in candidates:
            if c.exists():
                data = yaml.safe_load(c.read_text(encoding="utf-8")) or {}
                return {**DEFAULT_PACK, **data}
    return dict(DEFAULT_PACK)


def _val(m: MetricResult | None) -> Decimal | None:
    if m is None or m.status != MetricStatus.OK or not m.value_text:
        return None
    return D(m.value_text)


def _f(obj, key: str, default=None):
    """同时兼容 pydantic 对象与 dict（核验层返回的是 dict）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _fmt_pct(v: Decimal) -> str:
    return f"{(v * 100).quantize(D('0.01'))}%"


def evaluate(
    *,
    metrics: dict[str, MetricResult],
    peer_median: dict[str, Decimal | None],
    peer_n: int,
    issues: list,
    pack: dict[str, Any] | None = None,
    peer_names: list[str] | None = None,
    fact_values: dict[str, Decimal | None] | None = None,
    fact_refs: dict[str, str] | None = None,
) -> list[RuleOutcome]:
    pack = pack or DEFAULT_PACK
    ver = pack.get("version", "rules/v1.0.0")
    out: list[RuleOutcome] = []

    # ---------------- margin_pressure ----------------
    cfg = pack["margin_pressure"]
    gm, gmd = metrics.get("gross_margin"), metrics.get("gross_margin_delta_pp")
    gm_v, gmd_v = _val(gm), _val(gmd)
    if gm_v is None or gmd_v is None:
        out.append(RuleOutcome(
            "margin_pressure", ver, "毛利率承压", RuleStatus.NOT_EVALUABLE, "关注",
            "毛利率或上期毛利率缺失，规则未评估",
            missing=[k for k in ("gross_margin", "gross_margin_delta_pp") if _val(metrics.get(k)) is None],
            threshold_text=f"毛利率同比 ≤ {cfg['delta_pp_le']}pp",
            next_material="上一年度合并利润表（营业收入、营业成本同口径）",
        ))
    else:
        trig = gmd_v <= D(str(cfg["delta_pp_le"]))
        med = peer_median.get("gross_margin")
        enhanced = bool(trig and med is not None and peer_n >= 2 and (gm_v - med) * 100 <= D(str(cfg["peer_gap_pp_le"])))
        gap_txt = ""
        if med is not None and peer_n >= 2:
            gap_txt = f"，较可比同行中位数 {_fmt_pct(med)} 低 {((med - gm_v) * 100).quantize(D('0.01'))}pp"
        elif peer_n < 2:
            gap_txt = "，可比同行不足 2 家，不报行业偏离"
        out.append(RuleOutcome(
            "margin_pressure", ver, "毛利率承压",
            RuleStatus.TRIGGERED if trig else RuleStatus.NOT_TRIGGERED,
            cfg["severity"],
            (f"毛利率 {_fmt_pct(gm_v)}，同比下降 {abs(gmd_v).quantize(D('0.01'))}pp{gap_txt}" if trig
             else f"毛利率 {_fmt_pct(gm_v)}，同比变动 {gmd_v.quantize(D('0.01'))}pp，未触及阈值"),
            observed={"gross_margin": _fmt_pct(gm_v), "delta_pp": str(gmd_v.quantize(D('0.01')))},
            input_ids=[gm.result_id, gmd.result_id] if gm and gmd else [],
            threshold_text=f"毛利率同比 ≤ {cfg['delta_pp_le']}pp；若同时低于可比同行中位数 {cfg['peer_gap_pp_le']}pp 标增强",
            potential_impact="毛利率下行会压缩经营现金流对利息与资本开支的覆盖空间；本项仅为观察线索，不构成授信结论。",
            counter_evidence="若营业成本上升来自产品结构升级（高端化）而非单位成本上升，则毛利率下行与盈利能力改善可以并存；需分部吨价与吨成本验证。",
            next_material="分产品/分地区营业收入与成本明细、吨价与吨成本披露",
            enhanced=enhanced,
        ))

    # ---------------- cash_divergence ----------------
    cfg = pack["cash_divergence"]
    fv = fact_values or {}
    fr = fact_refs or {}
    np_v, ocf_v = fv.get("net_profit_total"), fv.get("operating_cashflow")
    ocfm_d = metrics.get("ocf_margin_delta_pp")
    yoy = metrics.get("revenue_yoy")
    ocfm_d_v, yoy_v = _val(ocfm_d), _val(yoy)
    if np_v is None and ocf_v is None and ocfm_d_v is None:
        out.append(RuleOutcome(
            "cash_divergence", ver, "利润与现金流背离", RuleStatus.NOT_EVALUABLE, "关注",
            "净利润/经营现金流/现金流比率缺失，规则未评估",
            missing=["net_profit_total", "operating_cashflow", "ocf_margin_delta_pp"],
            threshold_text=f"净利润>0 且 OCF<0；或营收同比>0 且 OCF/营收同比下降 ≥ {cfg['ocf_margin_delta_pp_le']}pp",
            next_material="合并现金流量表与合并利润表（同一财年）",
        ))
    else:
        cond_a = np_v is not None and ocf_v is not None and np_v > 0 and ocf_v < 0
        cond_b = (
            yoy_v is not None and ocfm_d_v is not None
            and yoy_v > 0 and ocfm_d_v <= D(str(cfg["ocf_margin_delta_pp_le"]))
        )
        trig = cond_a or cond_b
        if trig:
            if cond_a:
                head = f"净利润为正（{(np_v / D(10**8)).quantize(D('0.01'))} 亿元）但经营现金流为负（{(ocf_v / D(10**8)).quantize(D('0.01'))} 亿元）"
            else:
                head = f"营收同比 +{(yoy_v * 100).quantize(D('0.01'))}%，但经营现金流/营收同比下降 {abs(ocfm_d_v).quantize(D('0.01'))}pp"
        else:
            parts = []
            if ocfm_d_v is not None:
                parts.append(f"OCF/营收同比变动 {ocfm_d_v.quantize(D('0.01'))}pp")
            if np_v is not None and ocf_v is not None:
                parts.append(f"净利润 {(np_v / D(10**8)).quantize(D('0.01'))} 亿元对经营现金流 {(ocf_v / D(10**8)).quantize(D('0.01'))} 亿元")
            head = "；".join(parts) + "，未触及阈值"
        out.append(RuleOutcome(
            "cash_divergence", ver, "利润与现金流背离",
            RuleStatus.TRIGGERED if trig else RuleStatus.NOT_TRIGGERED,
            cfg["severity"], head,
            observed={
                "net_profit_total_yi": str((np_v / D(10**8)).quantize(D('0.01'))) if np_v is not None else "缺失",
                "ocf_yi": str((ocf_v / D(10**8)).quantize(D('0.01'))) if ocf_v is not None else "缺失",
                "ocf_margin_delta_pp": str(ocfm_d_v.quantize(D('0.01'))) if ocfm_d_v is not None else "缺失",
            },
            input_ids=[m.result_id for m in (ocfm_d, yoy) if m is not None]
                       + [fr.get(k, "") for k in ("net_profit_total", "operating_cashflow") if fr.get(k)],
            threshold_text=f"净利润>0 且 OCF<0；或营收同比>0 且 OCF/营收同比下降 ≥ {cfg['ocf_margin_delta_pp_le']}pp",
            potential_impact="利润未转化为现金，可能来自存货积压、渠道回款放缓或一次性经营性支出，影响短期偿债与再投入能力。",
            counter_evidence="若同期存在大额预付款、税费集中缴纳或原料集中采购，也可能形成单期现金流下探而利润健康；需看存货与应付款项变动。",
            next_material="现金流量表补充资料（存货变动、经营性应收应付变动）、存货与应收账款明细",
        ))

    # ---------------- balance_sheet_watch ----------------
    cfg = pack["balance_sheet_watch"]
    dar, dard = metrics.get("debt_asset_ratio"), metrics.get("asset_ratio_delta_pp")
    dar_v, dard_v = _val(dar), _val(dard)
    if dar_v is None or dard_v is None:
        out.append(RuleOutcome(
            "balance_sheet_watch", ver, "杠杆水平观察", RuleStatus.NOT_EVALUABLE, "需人工核对",
            "资产负债率或同比变动缺失，规则未评估",
            missing=[k for k in ("debt_asset_ratio", "asset_ratio_delta_pp") if _val(metrics.get(k)) is None],
            threshold_text=f"资产负债率同比升 ≥ {cfg['delta_pp_ge']}pp 且绝对值 ≥ {cfg['ratio_ge'] * 100}%",
            next_material="两个财年的合并资产负债表期末数",
        ))
    else:
        trig = dard_v >= D(str(cfg["delta_pp_ge"])) and dar_v >= D(str(cfg["ratio_ge"]))
        why = ""
        if dard_v >= D(str(cfg["delta_pp_ge"])) and dar_v < D(str(cfg["ratio_ge"])):
            why = f"，但绝对值 {_fmt_pct(dar_v)} 低于 {cfg['ratio_ge'] * 100}% 阈值"
        out.append(RuleOutcome(
            "balance_sheet_watch", ver, "杠杆水平观察",
            RuleStatus.TRIGGERED if trig else RuleStatus.NOT_TRIGGERED,
            cfg["severity"],
            (f"资产负债率 {_fmt_pct(dar_v)}，同比上升 {dard_v.quantize(D('0.01'))}pp，同时超过绝对值阈值"
             if trig else f"资产负债率 {_fmt_pct(dar_v)}，同比变动 {dard_v.quantize(D('0.01'))}pp{why}，未触及阈值"),
            observed={"debt_asset_ratio": _fmt_pct(dar_v), "delta_pp": str(dard_v.quantize(D('0.01')))},
            input_ids=[dar.result_id, dard.result_id] if dar and dard else [],
            threshold_text=f"资产负债率同比升 ≥ {cfg['delta_pp_ge']}pp 且绝对值 ≥ {cfg['ratio_ge'] * 100}%",
            potential_impact="杠杆抬升会削弱对利率与再融资环境的缓冲；本项为观察线索，不等同于银行授信口径的偿债能力判断。",
            counter_evidence="若负债上升主要来自预收款/合同负债等经营性无息负债，则财务杠杆实质压力小于比率读数；需看债务构成。",
            next_material="有息负债明细、短期借款与一年内到期非流动负债、合同负债",
        ))

    # ---------------- evidence_integrity ----------------
    # 只有 BLOCKING 级的数据质量问题才算「证据完整性」问题；
    # 被正式更替（INFO）或舍入相容（INFO）不应把规则点亮。
    bad = [i for i in issues
           if _f(i, "status") == "OPEN" and _f(i, "severity") == "BLOCKING"
           and _f(i, "type") in ("NUMERIC_CONFLICT", "RECONCILE_FAIL", "DATE_UNRELIABLE")]
    out.append(RuleOutcome(
        "evidence_integrity", ver, "证据完整性",
        RuleStatus.TRIGGERED if bad else RuleStatus.NOT_TRIGGERED, "需人工核对",
        (f"{len(bad)} 项数据质量问题待处理：" + "、".join(sorted({str(_f(i, 'type')) for i in bad})) if bad
         else "关键字段均已完成核验，勾稽检查未发现异常"),
        input_ids=[str(_f(i, "issue_id")) for i in bad],
        threshold_text="关键数字存在同级未决冲突、披露日不可靠或勾稽未通过",
        potential_impact="数据质量问题会同时影响所有依赖该事实的指标，需先处理再解读经营结论。",
        counter_evidence="单份摘要与年报差异可能来自单位/口径，不等于差错；本项只报证据状态，不推断经营事件。",
        next_material="正式更正公告或交易所原件复核",
    ))
    return out
