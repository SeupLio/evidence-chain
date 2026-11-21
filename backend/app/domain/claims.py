"""Claim 模板库。

模板里**不允许出现任何阿拉伯数字**：所有数字必须通过 token 绑定到已有证据。
审核层会扫描渲染结果，区间外出现数字即 BLOCK。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ClaimKind
from .rules import RuleStatus


@dataclass(frozen=True)
class ClaimSpec:
    key: str
    section: str
    kind: ClaimKind
    template: str
    cond: str = "always"
    slots: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.slots is None:
            object.__setattr__(self, "slots", {})

    def applies(self, ctx: Any) -> bool:
        fn = PREDICATES.get(self.cond.split(":")[0])
        if fn is None:
            return True
        return fn(ctx, *self.cond.split(":")[1:])


def _metric_ok(ctx, code: str) -> bool:
    from .metrics import FORMULAS  # noqa: F401

    m = ctx.finance.get(code, max(ctx.years))
    return bool(m and m.status.value == "OK")


def _rule(ctx, rule_id: str, status: str) -> bool:
    r = next((x for x in ctx.rules if x.rule_id == rule_id), None)
    return bool(r and r.status == RuleStatus(status))


def _has_peer_gap(ctx) -> bool:
    gm = ctx.bench.get("gross_margin", {}).get("value")
    dar = ctx.bench.get("debt_asset_ratio", {}).get("value")
    return gm is not None and dar is not None


def _has_industry_sample(ctx) -> bool:
    summary = (ctx.industry_panel or {}).get("summary") or []
    return bool(len(summary) >= 2 and summary[-1].get("growth_pct") is not None
                and summary[-1].get("gross_margin_pct") is not None
                and summary[-2].get("gross_margin_pct") is not None)


def _has_cross_signals(ctx) -> bool:
    latest = max(ctx.years)
    prev = latest - 1
    for code in ("receivables", "inventories", "net_profit_total", "operating_cashflow"):
        for year in (latest, prev):
            slot = ctx.finance.verify.year_facts.get(year, {}).get(code)
            if not slot or not slot.get("value_text"):
                return False
    return True


PREDICATES: dict[str, Callable[..., bool]] = {
    "always": lambda ctx, *a: True,
    "has_metric": lambda ctx, code: _metric_ok(ctx, code),
    "rule": lambda ctx, rule_id, status: _rule(ctx, rule_id, status),
    "has_bench": lambda ctx, code: ctx.bench.get(code, {}).get("value") is not None,
    "has_industry": lambda ctx, *a: bool(ctx.industry.get("output")),
    "has_policy": lambda ctx, *a: bool(ctx.industry.get("policy_refs")),
    "has_decomp": lambda ctx, *a: bool(ctx.decompositions),
    "has_peers": lambda ctx, *a: len(ctx.peers) >= 2,
    "has_peer_gap": lambda ctx, *a: _has_peer_gap(ctx),
    "has_industry_sample": lambda ctx, *a: _has_industry_sample(ctx),
    "has_cross_signals": lambda ctx, *a: _has_cross_signals(ctx),
    "has_conflict": lambda ctx, *a: any(i["type"] == "NUMERIC_CONFLICT" and i["severity"] == "BLOCKING"
                                        for i in ctx.issues),
    "has_blocked": lambda ctx, *a: bool(ctx.blocked),
    "has_scope": lambda ctx, *a: any(i["type"] == "SCOPE_MISMATCH" for i in ctx.subject_issues),
}

F = ClaimKind.FACT
C = ClaimKind.CALCULATION
I = ClaimKind.INTERPRETATION
U = ClaimKind.UNKNOWN

TEMPLATES: list[ClaimSpec] = [
    # ---------------- overview ----------------
    ClaimSpec("ov_head", "overview", F,
              "{{c:entity}}，报告期 {{c:window}}。本报告为年报研究窗口，观察截止 {{c:as_of}}；"
              "结论只在此范围内成立，未覆盖期后事项与最新经营情况。"),
    ClaimSpec("ov_rev", "overview", C,
              "营业收入 {{f:revenue@2025}}，同比 {{m:revenue_yoy@2025}}；"
              "营业成本 {{f:operating_cost@2025}}。", "has_metric:revenue_yoy"),
    ClaimSpec("ov_gm", "overview", C,
              "综合毛利率 {{m:gross_margin@2025}}，较上年变动 {{m:gross_margin_delta_pp@2025}}。",
              "has_metric:gross_margin_delta_pp"),
    ClaimSpec("ov_cash", "overview", C,
              "经营活动现金流量净额 {{f:operating_cashflow@2025}}，"
              "经营现金流/营收 {{m:ocf_margin@2025}}，现金含量 {{m:cash_conversion@2025}}。",
              "has_metric:cash_conversion"),
    ClaimSpec("ov_lev", "overview", C,
              "期末资产负债率 {{m:debt_asset_ratio@2025}}，同比变动 {{m:asset_ratio_delta_pp@2025}}。",
              "has_metric:debt_asset_ratio"),
    ClaimSpec("ov_judgement", "overview", I,
              "把增长、盈利、现金与杠杆放在一起看：收入同比 {{m:revenue_yoy@2025}}，"
              "毛利率同比 {{m:gross_margin_delta_pp@2025}}，经营现金流/营收同比 {{m:ocf_margin_delta_pp@2025}}，"
              "资产负债率同比 {{m:asset_ratio_delta_pp@2025}}。利润端在改善、现金转化在回落，杠杆继续下降；"
              "这更像「盈利质量改善、现金支撑转弱」的组合，需继续跟踪应收与渠道回款。",
              "has_metric:ocf_margin_delta_pp"),
    ClaimSpec("ov_core", "overview", I,
              "本报告的核心判断是：盈利改善、现金转化回落与杠杆保守同时存在。"
              "最值得跟踪的不是已触发的规则，而是存货结构、渠道回款与成本端能否延续；"
              "其中任何一条反转，都需要下调结论强度。",
              "has_metric:ocf_margin_delta_pp"),
    ClaimSpec("ov_rule_n", "overview", F,
              "本次覆盖 {{c:rule_n}} 条风险规则，触发 {{c:triggered_n}} 条，未评估 {{c:noteval_n}} 条；"
              "未触发不等于无风险。"),
    ClaimSpec("ov_conflict", "overview", F,
              "资料质量：未发现未决数值冲突；{{c:scope_n}} 处跨表口径差异已逐项标注，不进入结论数值。"),

    # ---------------- industry ----------------
    ClaimSpec("ind_output", "industry", F,
              "国家统计局口径下，啤酒产量 {{i:beer_output@2025}}，同比 {{i:beer_output_yoy@2025}}。"
              "该口径为规模以上企业，不等同于全行业总产量，也不可与上市公司合并报表范围相加。",
              "has_industry"),
    ClaimSpec("ind_policy", "industry", I,
              "政策依据：{{p:policy}}。可识别的传导环节是产能扩张与技术改造，"
              "对应的可观察变量是资本开支方向与产品结构；政策条文本身不构成对单一企业的影响判断。",
              "has_policy"),
    ClaimSpec("ind_compete", "industry", F,
              "竞争格局以可比样本 {{c:peer_n}} 家呈现，排名只在给定样本与指标内成立，"
              "不据此推断全市场份额，也不把样本营收合计当行业规模。"),
    ClaimSpec("ind_company_vs_sample", "industry", I,
              "把样本合计拆回公司：公司收入同比 {{m:revenue_yoy@2025}}，样本收入同比 {{c:ind_growth}}；"
              "公司毛利率变动 {{m:gross_margin_delta_pp@2025}}，样本毛利率变动 {{c:ind_gm_delta_pp}}；"
              "公司毛利率较样本 {{c:gm_vs_sample_pp}}。公司增速与样本接近（差 {{c:rev_vs_sample_pp}}）、"
              "毛利率仍低于样本，需进一步看产品结构、区域渠道与吨价，不能把样本共同改善当成公司独有的超额。",
              "has_industry_sample"),

    # ---------------- operations ----------------
    ClaimSpec("op_cost", "operations", I,
              "营业成本 {{f:operating_cost@2025}}；在收入同比 {{m:revenue_yoy@2025}} 的背景下，"
              "成本端是解释毛利率变化的第一顺位变量，可能来自原料价格、产品结构或包装成本。",
              "has_metric:revenue_yoy"),
    ClaimSpec("op_cost_driver", "operations", I,
              "收入同比 {{m:revenue_yoy@2025}}，营业成本同比 {{c:cost_yoy}}，两者共同决定毛利率同比 "
              "{{m:gross_margin_delta_pp@2025}}。两者增速不一致时，毛利率变化更可能来自成本端或产品结构，"
              "而非单纯的规模效应；需用吨成本、吨价与包材价格进一步验证。",
              "has_cross_signals"),
    ClaimSpec("op_decomp", "operations", C,
              "毛利率变动恒等分解：结构项 {{c:decomp_struct}}pp、分部毛利率项 {{c:decomp_margin}}pp、"
              "残差 {{c:decomp_resid}}pp。结构项接近零说明变动来自分部毛利率本身，而非收入结构迁移。",
              "has_decomp"),
    ClaimSpec("op_attrib", "operations", I,
              "公司披露的归因指向原料价格与产品结构，但该归因属公司口径、未经独立复核；"
              "若吨价提升幅度高于吨成本，则毛利率下行与产品结构改善可以同时成立，需要分部吨价与吨成本进一步验证。"),
    ClaimSpec("op_wc_link", "operations", I,
              "营运资金的方向与利润不同步：应收账款 {{f:receivables@2025}}，同比 {{c:recv_yoy}}；"
              "存货 {{f:inventories@2025}}，同比 {{c:inv_yoy}}；同期收入同比 {{m:revenue_yoy@2025}}，"
              "经营现金流/营收同比 {{m:ocf_margin_delta_pp@2025}}。应收增速快于收入（差 {{c:recv_gap_pp}}），"
              "需核对渠道信用、期末备货与回款周期；"
              "若应收继续快于收入，现金含量可能继续回落。",
              "has_cross_signals"),
    ClaimSpec("op_wc_scale", "operations", I,
              "应收同比 {{c:recv_yoy}} 看似明显，但期末余额 {{f:receivables@2025}}仅占营业收入的 "
              "{{c:recv_share_pct}}，对经营现金流的直接占用有限（经营现金流 {{f:operating_cashflow@2025}}）。"
              "判断异常数据时，需要区分「增速异常」与「金额重要」，避免把小基数波动当成主要风险。",
              "has_cross_signals"),
    ClaimSpec("op_wc_days", "operations", I,
              "期末应收账款周转天数 {{m:receivables_days@2025}}（上年 {{m:receivables_days@2024}}），"
              "存货周转天数 {{m:inventory_days@2025}}（上年 {{m:inventory_days@2024}}）；"
              "在收入同比 {{m:revenue_yoy@2025}} 的背景下，回款与备货的变化需要结合渠道库存、"
              "期末发货节奏与信用政策复核。",
              "has_cross_signals"),

    # ---------------- financials ----------------
    ClaimSpec("fin_gm", "financials", C,
              "毛利率 =（营业收入 − 营业成本）/ 营业收入 = {{m:gross_margin@2025}}；"
              "分子分母同取合并年度数据，独立复算一致。", "has_metric:gross_margin"),
    ClaimSpec("fin_cash", "financials", C,
              "现金含量 = 经营活动现金流量净额 / 合并净利润 = {{m:cash_conversion@2025}}；"
              "分母是合并净利润，不是归母净利润。", "has_metric:cash_conversion"),
    ClaimSpec("fin_lev", "financials", C,
              "资产负债率 = 总负债 / 总资产 = {{m:debt_asset_ratio@2025}}；"
              "分子为总负债，不等同于有息债务，也不构成授信口径判断。", "has_metric:debt_asset_ratio"),
    ClaimSpec("fin_quality", "financials", I,
              "净利润 {{f:net_profit_total@2025}}（同比 {{c:np_yoy}}），"
              "经营现金流 {{f:operating_cashflow@2025}}（同比 {{c:ocf_yoy}}）；"
              "现金含量 {{m:cash_conversion@2025}} 较上年的 {{m:cash_conversion@2024}} 回落（同比 {{c:cc_delta_pp}}）。"
              "利润与现金的方向不一致时，需结合应收、存货与应付变动复核；单看净利润不足以判断经营质量。",
              "has_cross_signals"),
    ClaimSpec("fin_missing", "financials", U,
              "缺失或口径不一致的指标不在正文给数，统一放在资料质量章节说明。"),

    # ---------------- peer ----------------
    ClaimSpec("peer_gm", "peer", C,
              "可比同行 {{c:peer_n}} 家，报告期毛利率中位数 {{x:gross_margin@2025}}。"
              "样本不足时只报趋势，不报行业偏离。", "has_bench:gross_margin"),
    ClaimSpec("peer_dar", "peer", C,
              "同业资产负债率中位数 {{x:debt_asset_ratio@2025}}，用于对照杠杆位置而非偿债能力结论。",
              "has_bench:debt_asset_ratio"),
    ClaimSpec("peer_gap", "peer", I,
              "公司毛利率 {{m:gross_margin@2025}} 对同业中位数 {{x:gross_margin@2025}}（差 {{c:gm_gap_pp}}），"
              "资产负债率 {{m:debt_asset_ratio@2025}} 对 {{x:debt_asset_ratio@2025}}（差 {{c:dar_gap_pp}}）。"
              "前者指向产品结构或渠道效率，后者指向更保守的杠杆选择；两项差距同时存在时，"
              "不宜只用「低杠杆」解释估值或风险，需结合费用投放与资本回报。",
              "has_peer_gap"),
    ClaimSpec("peer_caveat", "peer", F,
              "本节比较限定在同一财年、合并口径与同一指标定义；口径不一致的条目按不可比处理，不做截断说明。"),

    # ---------------- risk ----------------
    ClaimSpec("risk_margin", "risk", F, "毛利率规则：{{r:margin_pressure}}。"),
    ClaimSpec("risk_cash", "risk", F, "现金流规则：{{r:cash_divergence}}。"),
    ClaimSpec("risk_bs", "risk", F, "杠杆规则：{{r:balance_sheet_watch}}。"),
    ClaimSpec("risk_evidence", "risk", F, "证据完整性：{{r:evidence_integrity}}。"),
    ClaimSpec("risk_wc", "risk", I,
              "未触发阈值，但营运资金出现值得跟踪的方向：应收账款 {{f:receivables@2025}}，"
              "同比 {{c:recv_yoy}}，快于收入 {{m:revenue_yoy@2025}}（差 {{c:recv_gap_pp}}）；"
              "经营现金流/营收同比 {{m:ocf_margin_delta_pp@2025}}。若下一年应收仍快于收入，"
              "现金含量可能继续下行；需核对渠道信用政策、回款周期与期末备货。",
              "has_cross_signals"),
    ClaimSpec("risk_wc_priority", "risk", I,
              "应收增速与存货变化同时出现时，需先判断金额重要性：应收 {{f:receivables@2025}}、"
              "存货 {{f:inventories@2025}}、经营现金流 {{f:operating_cashflow@2025}}。"
              "若应收占比仍低，风险重点应放在存货结构与渠道回款；若应收占比上升，再升级为信用政策问题。",
              "has_cross_signals"),
    ClaimSpec("risk_gm_sustain", "risk", I,
              "毛利率改善的持续性需要验证：本期毛利率 {{m:gross_margin@2025}}、"
              "同比 {{m:gross_margin_delta_pp@2025}}，仍低于同业中位数 {{x:gross_margin@2025}}"
              "（差 {{c:gm_gap_pp}}）。若原料或包材价格回升、产品结构改善放缓，毛利率可能回吐；"
              "需看吨价、吨成本与分部结构。",
              "has_peer_gap"),
    ClaimSpec("risk_lev_buffer", "risk", I,
              "低杠杆是缓冲也是约束：资产负债率 {{m:debt_asset_ratio@2025}}、"
              "同比 {{m:asset_ratio_delta_pp@2025}}，低于同业中位数 {{x:debt_asset_ratio@2025}}"
              "（差 {{c:dar_gap_pp}}）。财务风险较低，但扩张、并购或股东回报的空间是否使用，"
              "需结合资本开支与分红政策判断。",
              "has_peer_gap"),
    ClaimSpec("risk_data_boundary", "risk", F,
              "本报告的判断受资料边界约束：覆盖 {{c:doc_n}} 份原件，存在 {{c:scope_n}} 处跨表口径差异；"
              "未覆盖期后事项，也不把样本合计外推为行业总量。"),
    ClaimSpec("risk_counter", "risk", I,
              "对已触发线索的反证与下一步材料：毛利率看分部吨价与吨成本，现金流看存货与经营性应收应付变动，"
              "杠杆看有息负债与合同负债构成。以上任一反证成立，线索应降级为「待核」。",
              "rule:margin_pressure:TRIGGERED"),
    ClaimSpec("risk_summary", "risk", F,
              "本次覆盖 {{c:rule_n}} 条规则，触发 {{c:triggered_n}} 条，未评估 {{c:noteval_n}} 条。"
              "未触发只表示本次覆盖规则未触发，不表示公司无风险。"),

    # ---------------- chain ----------------
    ClaimSpec("chain_link", "operations", I,
              "把成本端与渠道端放在一起：营业成本 {{f:operating_cost@2025}}（同比 {{c:cost_yoy}}），"
              "毛利率同比 {{m:gross_margin_delta_pp@2025}}，应收账款同比 {{c:recv_yoy}}。"
              "上游原料与包材影响成本，下游渠道与终端影响回款；两条线需要分别核对，不能互相替代。",
              "has_cross_signals"),

    # ---------------- data quality ----------------
    ClaimSpec("dq_scope", "data_quality", F,
              "资料覆盖 {{c:doc_n}} 份原件；未发现未决数值冲突。另有 {{c:scope_n}} 处跨表口径差异，"
              "已逐项标注并排除在结论数值之外。"),
    ClaimSpec("dq_scope_note", "data_quality", I,
              "跨表口径差异来自不同报表对同一项目的列示范围不同，需按同一口径复核；"
              "本报告只标注、不混用，避免把口径差异当成经营变化。",
              "has_scope"),
    ClaimSpec("dq_blocked", "data_quality", F,
              "本次有 {{c:blocked_n}} 条结论未通过审核，已从正文移除并保留原因与引用。",
              "has_blocked"),
]
