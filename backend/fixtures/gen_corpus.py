"""生成演示语料：结构化 PDF + 金标。

为什么用脚本生成而不是下载真实年报：
1. 金标由**生成方**独立持有，抽取器不知道答案，评测才有意义；
2. 可以精确注入口径陷阱（目录页、母公司报表、万元摘要、更正公告），
   这些陷阱在真实年报里存在但没法稳定复现；
3. 真实 PDF 解析链路照跑——pdfplumber 读的是真表格、真坐标、真页码。

每份 PDF 首页与页脚都标注「黑客松演示样本 · 合成数据」，不冒充真实披露。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
GOLD = ROOT / "gold.json"

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
FONT = "STSong-Light"

H1 = ParagraphStyle("H1", fontName=FONT, fontSize=17, leading=24, spaceAfter=8)
H2 = ParagraphStyle("H2", fontName=FONT, fontSize=12.5, leading=19, spaceAfter=6)
BODY = ParagraphStyle("BODY", fontName=FONT, fontSize=9.5, leading=15)
SMALL = ParagraphStyle("SMALL", fontName=FONT, fontSize=8, leading=12, textColor=colors.HexColor("#666666"))
COVER = ParagraphStyle("COVER", fontName=FONT, fontSize=28, leading=40, alignment=1)
COVER2 = ParagraphStyle("COVER2", fontName=FONT, fontSize=15, leading=26, alignment=1)

D = Decimal
MARGIN = 18 * mm


def money(v: Decimal) -> str:
    return f"{v:,.2f}"


def yi(v: Decimal, places: str = "0.01") -> Decimal:
    return (v / D(10**8)).quantize(D(places), rounding=ROUND_HALF_UP)


def wan(v: Decimal, places: str = "0.01") -> Decimal:
    return (v / D(10**4)).quantize(D(places), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# 合成财务数据（元）。所有勾稽关系在构造时即成立。
# --------------------------------------------------------------------------- #

def build_company(
    *, rev: str, cost: str, npt: str, minority: str, ocf: str, assets: str, liab: str, **extra: str
) -> dict[str, Decimal]:
    r, c = D(rev), D(cost)
    total, mi = D(npt), D(minority)
    a, l = D(assets), D(liab)
    d = {
        "revenue": r,
        "operating_cost": c,
        "net_profit_total": total,
        "minority_interest": mi,
        "net_profit_parent": total - mi,
        "operating_cashflow": D(ocf),
        "total_assets": a,
        "total_liabilities": l,
        "total_equity": a - l,
        "liab_equity_total": a,
    }
    for k, v in extra.items():
        d[k] = D(v)
    return d


DATA: dict[str, dict[int, dict[str, Decimal]]] = {
    "SH:600600": {
        2022: build_company(rev="32168221405.60", cost="18420110552.31", npt="4320118220.44", minority="190110220.31",
                            ocf="4910220118.22", assets="49220110338.10", liab="21980112447.20"),
        2023: build_company(rev="33937286044.12", cost="18964120883.51", npt="4461022318.77", minority="193200441.08",
                            ocf="5128336910.02", assets="50832117664.28", liab="22615220881.44"),
        2024: build_company(rev="32138419206.85", cost="18021335704.19", npt="4532208914.06", minority="187102554.02",
                            ocf="4815220377.61", assets="52166401238.55", liab="22844110507.31",
                            seg_revenue_beer="31580110338.20", seg_cost_beer="17541140221.30",
                            seg_revenue_other="558308868.65", seg_cost_other="480195482.89"),
        2025: build_company(rev="33015286417.35", cost="19360412880.62", npt="4688102553.11", minority="186204331.05",
                            ocf="3210466918.44", assets="54520338977.10", liab="26510220845.73",
                            seg_revenue_beer="32410220441.30", seg_cost_beer="18840264338.20",
                            seg_revenue_other="605065976.05", seg_cost_other="520148542.42"),
    },
    "SH:600132": {
        2022: build_company(rev="14210110338.20", cost="7520110441.10", npt="1264110338.40", minority="24110220.10",
                            ocf="2540110220.10", assets="15120110338.20", liab="8420110441.20"),
        2023: build_company(rev="14860110220.40", cost="7790110338.20", npt="1337110441.60", minority="27110220.10",
                            ocf="2690110338.10", assets="15870110441.30", liab="8820110338.10"),
        2024: build_company(rev="14645220338.10", cost="7615220118.40", npt="1302110220.55", minority="17110220.10",
                            ocf="2810110441.20", assets="16820110338.50", liab="9230110220.30"),
        2025: build_company(rev="15230442118.20", cost="7920331047.55", npt="1385220441.30", minority="25110220.14",
                            ocf="3025110338.20", assets="17540220441.60", liab="9510110552.40"),
    },
    "SZ:002461": {
        2022: build_company(rev="5120110338.40", cost="2890110441.10", npt="598110220.30", minority="13110220.10",
                            ocf="840110220.30", assets="8920110338.10", liab="2940110220.30"),
        2023: build_company(rev="5378110220.30", cost="3015110338.10", npt="624110441.20", minority="14110220.10",
                            ocf="890110338.20", assets="9210110441.20", liab="3020110338.10"),
        2024: build_company(rev="5731220338.10", cost="3180110441.20", npt="702110338.40", minority="14110220.10",
                            ocf="955110220.40", assets="9840110338.20", liab="3210110441.10"),
        2025: build_company(rev="6090220441.30", cost="3360110338.20", npt="785110220.40", minority="15110220.10",
                            ocf="1010220338.20", assets="10420110441.50", liab="3450110220.30"),
    },
}

PARENT_DATA: dict[str, dict[int, dict[str, Decimal]]] = {
    "SH:600600": {
        2025: {"revenue": D("24880110338.20"), "operating_cost": D("14920220441.30"),
               "net_profit_total": D("3120110338.20"), "net_profit_parent": D("3120110338.20"),
               "minority_interest": D("0"), "operating_cashflow": D("2210220338.20"),
               "total_assets": D("42110220338.20"), "total_liabilities": D("18220110441.30"),
               "total_equity": D("23890109896.90"), "liab_equity_total": D("42110220338.20")},
        2024: {"revenue": D("24110220338.20"), "operating_cost": D("14520110441.30"),
               "net_profit_total": D("2980110338.20"), "net_profit_parent": D("2980110338.20"),
               "minority_interest": D("0"), "operating_cashflow": D("2110220338.20"),
               "total_assets": D("40220110441.20"), "total_liabilities": D("1711010338.20"),
               "total_equity": D("2311901103.00"), "liab_equity_total": D("40220110441.20")},
    }
}
# 修正母公司 2024 权益使勾稽成立
PARENT_DATA["SH:600600"][2024]["total_equity"] = D("40220110441.20") - D("1711010338.20")

COMPANIES = {
    "SH:600600": dict(name="青岛啤酒股份有限公司", short="青岛啤酒", ticker="600600", exchange="SH"),
    "SH:600132": dict(name="重庆啤酒股份有限公司", short="重庆啤酒", ticker="600132", exchange="SH"),
    "SZ:002461": dict(name="广州珠江啤酒股份有限公司", short="珠江啤酒", ticker="002461", exchange="SZ"),
}

CORRECTION = {
    "entity_id": "SH:600600",
    "fiscal_year": 2025,
    "title": "关于2025年年度报告营业成本的更正公告",
    "published_on": "2026-06-15",
    "rows": {
        "operating_cost": (D("19360412880.62"), D("19020338204.15")),
        "seg_cost_beer": (D("18840264338.20"), D("18500189661.73")),
    },
}

INDUSTRY = {
    "beer": {
        "output": {2023: D("3555.5"), 2024: D("3521.8"), 2025: D("3488.2")},
        "revenue_yi": {2023: D("1820.5"), 2024: D("1865.3"), 2025: D("1890.4")},
    }
}

POLICY = dict(
    title="产业结构调整指导目录（2024年本）摘录",
    issuer="国家发展和改革委员会",
    published_on="2024-02-01",
    effective_on="2024-02-01",
    status="现行有效",
)

#: 辅助科目按年份取固定系数——同一年份在任何一份年报里都必须得到同一个数，
#: 否则「比较期列」与「当期列」会互相打架（这正是核验引擎应该抓到的问题）。
INV_RATIO = {2022: D("0.081"), 2023: D("0.078"), 2024: D("0.076"), 2025: D("0.075")}
AR_RATIO = {2022: D("0.0115"), 2023: D("0.0110"), 2024: D("0.0112"), 2025: D("0.0120")}

#: 注入一处真实世界的「未公告重述」：某同行 2024 年报把 2023 年营业收入改成另一个数，
#: 但没有发布更正公告。核验引擎应当判为同级冲突 → BLOCKED，而不是挑一个数继续算。
COMPARATIVE_OVERRIDE: dict[tuple[str, int, str], Decimal] = {
    ("SZ:002461", 2024, "revenue"): D("5368110220.30"),
}
COMPARATIVE_OVERRIDE: dict[tuple[str, int, str], Decimal] = {
    ("SZ:002461", 2024, "revenue"): D("5368110220.30"),
}


# --------------------------------------------------------------------------- #
# PDF 构件
# --------------------------------------------------------------------------- #

def table(data: list[list[str]], widths: list[float], *, font_size: float = 8.2,
          align_right_from: int = 1) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8899aa")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in range(align_right_from, len(data[0])):
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


class Pager:
    def __init__(self, label: str, footer: str):
        self.page = 0
        self.label = label
        self.footer = footer

    def __call__(self, canvas, doc):
        self.page += 1
        canvas.saveState()
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(MARGIN, 12 * mm, self.footer)
        canvas.drawRightString(A4[0] - MARGIN, 12 * mm, f"第 {self.page} 页")
        canvas.restoreState()


def build_pdf(path: Path, story: list, pager: Pager) -> int:
    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=18 * mm,
        title=path.stem, author="hackathon-demo",
    )
    doc.build(story, onFirstPage=pager, onLaterPages=pager)
    return pager.page


# --------------------------------------------------------------------------- #
# 年报
# --------------------------------------------------------------------------- #

def annual_report(entity_id: str, year: int, out: Path) -> dict:
    meta = COMPANIES[entity_id]
    cur = DATA[entity_id][year]
    prev = dict(DATA[entity_id][year - 1])
    for (ent, fy, fld), v in COMPARATIVE_OVERRIDE.items():
        if ent == entity_id and fy == year:
            prev[fld] = v
            if fld == "revenue":
                prev["revenue"] = v  # 营业总收入行同步，避免自相矛盾
    footer = f"【黑客松演示样本 · 合成数据】{meta['short']} {year} 年年度报告 · 不代表真实披露"
    pager = Pager(meta["short"], footer)
    story: list = []
    pages: dict[str, int] = {}
    pg = 0

    def mark(key: str, delta: int = 1) -> None:
        nonlocal pg
        pg += delta
        pages[key] = pg

    # ---- P1 封面 ----
    mark("cover")
    story += [
        Spacer(1, 55 * mm),
        Paragraph(meta["name"], COVER),
        Spacer(1, 12 * mm),
        Paragraph(f"{year} 年年度报告", COVER2),
        Spacer(1, 30 * mm),
        Paragraph(f"股票代码：{meta['ticker']}    上市地：{'上海' if meta['exchange'] == 'SH' else '深圳'}证券交易所", COVER2),
        Paragraph(f"披露日期：{year + 1}-03-28", COVER2),
        Spacer(1, 45 * mm),
        Paragraph("本文件为黑客松比赛演示用合成样本，由脚本按公开年报版式生成，", SMALL),
        Paragraph("财务数值为构造数据，不代表任何真实公司的经营情况。", SMALL),
        PageBreak(),
    ]

    # ---- P2 目录（陷阱：出现报表名但不是报表页）----
    mark("toc")
    story += [Paragraph("目录", H1), Spacer(1, 4 * mm)]
    toc_rows = [
        ["第一节  重要提示、目录和释义", "3"],
        ["第二节  公司简介和主要财务指标", "4"],
        ["第三节  管理层讨论与分析", "6"],
        ["第四节  财务报告", "8"],
        ["        合并资产负债表", "9"],
        ["        合并利润表", "10"],
        ["        合并现金流量表", "11"],
        ["        母公司资产负债表", "13"],
    ]
    t = Table(toc_rows, colWidths=[120 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [t, Spacer(1, 6 * mm), Paragraph("注：目录页仅列示章节，不构成任何数据来源。", SMALL), PageBreak()]

    # ---- P3 主要会计数据（单位：万元，舍入源）----
    mark("summary")
    story += [
        Paragraph("第二节  公司简介和主要财务指标", H2),
        Paragraph("（一）主要会计数据", BODY),
        Paragraph("单位：万元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    rows = [["项目", f"{year}年", f"{year - 1}年", "本年比上年增减(%)"]]
    for code, label in (
        ("revenue", "营业收入"), ("operating_cost", "营业成本"),
        ("net_profit_parent", "归属于上市公司股东的净利润"),
        ("net_profit_total", "净利润"),
        ("operating_cashflow", "经营活动产生的现金流量净额"),
        ("total_assets", "总资产"), ("total_equity", "所有者权益合计"),
    ):
        a, b = wan(cur[code]), wan(prev[code])
        chg = ((a - b) / b * 100).quantize(D("0.01")) if b else D("0")
        rows.append([label, f"{a:,.2f}", f"{b:,.2f}", f"{chg:+.2f}"])
    story += [table(rows, [72 * mm, 33 * mm, 33 * mm, 33 * mm]), Spacer(1, 5 * mm)]
    story += [Paragraph("上述数据摘自经审计的合并财务报表，单位由元折算为万元并保留两位小数。", SMALL), PageBreak()]

    # ---- P4 管理层讨论（含归因与分部）----
    mark("mdna")
    gm_c = (cur["revenue"] - cur["operating_cost"]) / cur["revenue"] * 100
    gm_p = (prev["revenue"] - prev["operating_cost"]) / prev["revenue"] * 100
    story += [Paragraph("第三节  管理层讨论与分析", H2)]
    story += [Paragraph(
        f"报告期内，公司实现营业收入 {yi(cur['revenue']):,} 亿元，同比增长 "
        f"{((cur['revenue'] / prev['revenue'] - 1) * 100).quantize(D('0.01'))}%；"
        f"营业成本 {yi(cur['operating_cost']):,} 亿元；综合毛利率 {gm_c.quantize(D('0.01'))}%，"
        f"较上年同期的 {gm_p.quantize(D('0.01'))}% 变动 {(gm_c - gm_p).quantize(D('0.01'))} 个百分点。", BODY)]
    story += [Spacer(1, 3 * mm), Paragraph("（一）主营业务分行业情况", BODY), Paragraph("单位：元", SMALL), Spacer(1, 1.5 * mm)]
    seg_rows = [["分行业", "营业收入", "营业成本", "毛利率(%)"]]
    for key_r, key_c, label in (("seg_revenue_beer", "seg_cost_beer", "啤酒业务"),
                                ("seg_revenue_other", "seg_cost_other", "其他业务")):
        if key_r in cur:
            r_, c_ = cur[key_r], cur[key_c]
            seg_rows.append([label, money(r_), money(c_), f"{((r_ - c_) / r_ * 100).quantize(D('0.01'))}"])
    seg_rows.append(["合计", money(cur["revenue"]), money(cur["operating_cost"]), f"{gm_c.quantize(D('0.01'))}"])
    story += [table(seg_rows, [40 * mm, 50 * mm, 50 * mm, 30 * mm]), Spacer(1, 4 * mm)]
    story += [Paragraph(
        "公司披露的归因：报告期内主要原材料大麦、玻璃瓶与铝罐采购价格上行，"
        "叠加产品结构调整带来包装与酿造环节成本上升；同时公司继续推进高端化，"
        "主销产品结构有所优化，但吨成本上升幅度超过吨价提升幅度。"
        "上述归因为公司披露口径，未经独立复核。", BODY)]
    story += [Paragraph(
        "销售模式方面，公司产品销售以经销商分销为主，并直接供货商超与电商平台；"
        "报告期内前五名客户销售额占年度销售总额比例较低，未单独披露具名客户与供应商。", BODY)]
    story += [PageBreak()]

    # ---- P5 合并资产负债表 ----
    mark("balance_sheet")
    story += [
        Paragraph("第四节  财务报告", H2),
        Paragraph("合并资产负债表", H2),
        Paragraph(f"编制单位：{meta['name']}    单位：元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    bs = [["项目", f"{year}年12月31日", f"{year - 1}年12月31日"]]
    bs += [
        ["流动资产合计", money(cur["total_assets"] * D("0.58")), money(prev["total_assets"] * D("0.58"))],
        ["其中：应收账款", money(cur["total_assets"] * AR_RATIO[year]), money(prev["total_assets"] * AR_RATIO[year - 1])],
        ["      存货", money(cur["total_assets"] * INV_RATIO[year]), money(prev["total_assets"] * INV_RATIO[year - 1])],
        ["非流动资产合计", money(cur["total_assets"] * D("0.42")), money(prev["total_assets"] * D("0.42"))],
        ["资产总计", money(cur["total_assets"]), money(prev["total_assets"])],
        ["流动负债合计", money(cur["total_liabilities"] * D("0.72")), money(prev["total_liabilities"] * D("0.70"))],
        ["非流动负债合计", money(cur["total_liabilities"] * D("0.28")), money(prev["total_liabilities"] * D("0.30"))],
        ["负债合计", money(cur["total_liabilities"]), money(prev["total_liabilities"])],
        ["所有者权益（或股东权益）合计", money(cur["total_equity"]), money(prev["total_equity"])],
        ["负债和所有者权益（或股东权益）总计", money(cur["liab_equity_total"]), money(prev["liab_equity_total"])],
    ]
    story += [table(bs, [70 * mm, 48 * mm, 48 * mm]), PageBreak()]

    # ---- P6 合并利润表 ----
    mark("income_statement")
    story += [
        Paragraph("合并利润表", H2),
        Paragraph(f"编制单位：{meta['name']}    单位：元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    isr = [["项目", f"{year}年度", f"{year - 1}年度"]]
    isr += [
        ["一、营业总收入", money(cur["revenue"]), money(prev["revenue"])],
        ["    其中：营业收入", money(cur["revenue"]), money(prev["revenue"])],
        ["二、营业总成本", money(cur["operating_cost"] * D("1.235")), money(prev["operating_cost"] * D("1.243"))],
        ["    其中：营业成本", money(cur["operating_cost"]), money(prev["operating_cost"])],
        ["          税金及附加", money(cur["revenue"] * D("0.021")), money(prev["revenue"] * D("0.022"))],
        ["          销售费用", money(cur["revenue"] * D("0.132")), money(prev["revenue"] * D("0.128"))],
        ["          管理费用", money(cur["revenue"] * D("0.045")), money(prev["revenue"] * D("0.047"))],
        ["三、营业利润", money(cur["net_profit_total"] * D("1.18")), money(prev["net_profit_total"] * D("1.19"))],
        ["四、净利润", money(cur["net_profit_total"]), money(prev["net_profit_total"])],
        ["    归属于母公司所有者的净利润", money(cur["net_profit_parent"]), money(prev["net_profit_parent"])],
        ["    少数股东损益", money(cur["minority_interest"]), money(prev["minority_interest"])],
    ]
    story += [table(isr, [70 * mm, 48 * mm, 48 * mm]), PageBreak()]

    # ---- P7 合并现金流量表 ----
    mark("cash_flow")
    story += [
        Paragraph("合并现金流量表", H2),
        Paragraph(f"编制单位：{meta['name']}    单位：元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    cf = [["项目", f"{year}年度", f"{year - 1}年度"]]
    cf += [
        ["销售商品、提供劳务收到的现金", money(cur["revenue"] * D("1.06")), money(prev["revenue"] * D("1.07"))],
        ["经营活动现金流入小计", money(cur["revenue"] * D("1.08")), money(prev["revenue"] * D("1.09"))],
        ["购买商品、接受劳务支付的现金", money(cur["operating_cost"] * D("0.92")), money(prev["operating_cost"] * D("0.90"))],
        ["经营活动现金流出小计", money(cur["revenue"] * D("1.02") - cur["operating_cashflow"] * D("0.05")),
         money(prev["revenue"] * D("1.02") - prev["operating_cashflow"] * D("0.05"))],
        ["经营活动产生的现金流量净额", money(cur["operating_cashflow"]), money(prev["operating_cashflow"])],
        ["投资活动产生的现金流量净额", money(cur["operating_cashflow"] * D("-0.42")), money(prev["operating_cashflow"] * D("-0.38"))],
        ["筹资活动产生的现金流量净额", money(cur["operating_cashflow"] * D("-0.31")), money(prev["operating_cashflow"] * D("-0.33"))],
    ]
    story += [table(cf, [70 * mm, 48 * mm, 48 * mm]), PageBreak()]

    # ---- P8 母公司资产负债表（陷阱：口径不同，不构成冲突）----
    mark("parent_bs")
    story += [
        Paragraph("母公司资产负债表", H2),
        Paragraph(f"编制单位：{meta['name']}    单位：元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    p = PARENT_DATA.get(entity_id, {}).get(year)
    if p:
        pbs = [["项目", f"{year}年12月31日", f"{year - 1}年12月31日"]]
        p_prev = PARENT_DATA[entity_id].get(year - 1, p)
        pbs += [
            ["资产总计", money(p["total_assets"]), money(p_prev["total_assets"])],
            ["负债合计", money(p["total_liabilities"]), money(p_prev["total_liabilities"])],
            ["所有者权益（或股东权益）合计", money(p["total_equity"]), money(p_prev["total_equity"])],
            ["负债和所有者权益（或股东权益）总计", money(p["liab_equity_total"]), money(p_prev["liab_equity_total"])],
        ]
        story += [table(pbs, [70 * mm, 48 * mm, 48 * mm])]
        story += [Spacer(1, 4 * mm), Paragraph(
            "母公司报表口径与合并报表不同：母公司报表不含子公司，不能与合并数据直接比较，"
            "两者出现差异不构成数据矛盾。", SMALL)]
    else:
        story += [Paragraph("（本样本未提供该公司母公司报表）", BODY)]
    story += [PageBreak()]

    n = build_pdf(out, story[:-1], pager)
    return {"pages": pages, "page_count": n}


def correction_notice(out: Path) -> dict:
    meta = COMPANIES["SH:600600"]
    footer = "【黑客松演示样本 · 合成数据】更正公告 · 不代表真实披露"
    pager = Pager("correction", footer)
    story = [
        Paragraph(CORRECTION["title"], H1),
        Paragraph(f"证券代码：{meta['ticker']}    证券简称：{meta['short']}    公告编号：2026-041", BODY),
        Spacer(1, 4 * mm),
        Paragraph(
            "本公司董事会及全体董事保证本公告内容不存在任何虚假记载、误导性陈述或者重大遗漏，"
            "并对其内容的真实性、准确性和完整性承担个别及连带责任。", BODY),
        Spacer(1, 4 * mm),
        Paragraph(
            "经复核，本公司于 2026 年 3 月 28 日披露的《2025 年年度报告》中合并利润表"
            "“营业成本”及相关分部成本存在归集差错，现将更正情况公告如下。", BODY),
        Spacer(1, 4 * mm),
        Paragraph("一、更正事项及影响", BODY),
        Paragraph("单位：元", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    rows = [["项目", "2025年度（更正前）", "2025年度（更正后）", "差异"]]
    for key, (before, after) in CORRECTION["rows"].items():
        label = "营业成本" if key == "operating_cost" else "其中：啤酒业务成本"
        rows.append([label, money(before), money(after), money(after - before)])
    story += [table(rows, [58 * mm, 40 * mm, 40 * mm, 28 * mm])]
    story += [
        Spacer(1, 4 * mm),
        Paragraph(
            "本次更正仅涉及营业成本在啤酒业务与其他业务之间的归集，以及营业成本总额的差错更正，"
            "不涉及营业收入、净利润、经营活动现金流量及资产负债项目。更正后数据已经年审会计师复核。", BODY),
        Spacer(1, 4 * mm),
        Paragraph("二、其他说明", BODY),
        Paragraph(
            "公司对本次更正给投资者带来的不便深表歉意。本公告为黑客松演示用合成样本，"
            "所列公司、编号与数值均为构造内容。", BODY),
        Spacer(1, 6 * mm),
        Paragraph(f"{meta['name']}  董事会", BODY),
        Paragraph(CORRECTION["published_on"], BODY),
    ]
    n = build_pdf(out, story, pager)
    return {"pages": {"correction": 1}, "page_count": n}


def industry_stats(out: Path) -> dict:
    pager = Pager("industry", "【黑客松演示样本 · 合成数据】行业统计摘编 · 数值为构造数据")
    story = [
        Paragraph("2025年啤酒行业运行情况", H1),
        Paragraph("数据来源：国家统计局工业统计快报（摘编）    统计范围：规模以上啤酒制造企业（年主营业务收入 2000 万元及以上）", BODY),
        Spacer(1, 3 * mm),
        Paragraph("一、产量", BODY),
        Paragraph("单位：万千升", SMALL),
        Spacer(1, 1.5 * mm),
    ]
    rows = [["指标", "2023年", "2024年", "2025年"]]
    rows.append(["啤酒产量", *(f"{INDUSTRY['beer']['output'][y]:,.1f}" for y in (2023, 2024, 2025))])
    story += [table(rows, [60 * mm, 35 * mm, 35 * mm, 35 * mm])]
    story += [Spacer(1, 4 * mm), Paragraph("二、规模以上企业营业收入", BODY), Paragraph("单位：亿元", SMALL), Spacer(1, 1.5 * mm)]
    rows2 = [["指标", "2023年", "2024年", "2025年"]]
    rows2.append(["规模以上啤酒企业营业收入",
                  *(f"{INDUSTRY['beer']['revenue_yi'][y]:,.1f}" for y in (2023, 2024, 2025))])
    story += [table(rows2, [60 * mm, 35 * mm, 35 * mm, 35 * mm])]
    story += [
        Spacer(1, 5 * mm),
        Paragraph(
            "口径说明：产量为规模以上企业口径，不等同于全行业总产量；营业收入为规模以上啤酒制造企业合计，"
            "其统计对象与上市公司合并报表范围不一致，不可直接相加或用于推算单一企业市场份额。", SMALL),
    ]
    n = build_pdf(out, story, pager)
    return {"pages": {"industry_stats": 1}, "page_count": n}


def policy_doc(out: Path) -> dict:
    pager = Pager("policy", "【黑客松演示样本 · 合成数据】政策摘录 · 条文为演示用途改写")
    story = [
        Paragraph(POLICY["title"], H1),
        Paragraph(f"发布机关：{POLICY['issuer']}    发布日期：{POLICY['published_on']}    "
                  f"施行日期：{POLICY['effective_on']}    状态：{POLICY['status']}", BODY),
        Paragraph("适用范围：中华人民共和国境内（全国）    适用主体：啤酒制造企业及其投资项目", BODY),
        Spacer(1, 4 * mm),
        Paragraph("第一类  鼓励类", BODY),
        Paragraph("十一、食品  3．啤酒：采用先进酿造工艺、吨酒综合能耗与取水量达到行业先进值，"
                  "以及纯生啤酒、无醇啤酒等中高端产品生产能力建设。", BODY),
        Spacer(1, 3 * mm),
        Paragraph("第二类  限制类", BODY),
        Paragraph("十二、轻工  5．新建、扩建年产能 3 万千升以下的啤酒生产线（不含现有产能技术改造）。", BODY),
        Spacer(1, 4 * mm),
        Paragraph("条文关联说明", BODY),
        Paragraph(
            "本目录对啤酒行业的影响环节为产能扩张与技术改造：鼓励类指向单位能耗与产品结构，"
            "限制类指向小规模新增产能。对企业经营的可观察变量是资本开支方向、产能利用率与产品结构，"
            "本条目不构成对任一企业的影响判断。", SMALL),
    ]
    n = build_pdf(out, story, pager)
    return {"pages": {"policy": 1}, "page_count": n}


def market_note(out: Path) -> dict:
    pager = Pager("market", "【黑客松演示样本 · 合成数据】行业观察（二级来源） · 估算值不可作为财务真值")
    story = [
        Paragraph("啤酒行业高端化趋势观察（二级来源）", H1),
        Paragraph("来源类型：公开市场观察摘编    性质：二手解释材料，仅用于对照与矛盾识别，不作为财务真值", BODY),
        Spacer(1, 3 * mm),
        Paragraph(
            "2025 年啤酒行业继续呈现总量平稳、结构上行的特征。样本企业高端产品销量占比提升，"
            "但吨价提升幅度收窄，行业整体吨成本受大麦、玻璃与铝罐价格影响而上行。", BODY),
        Spacer(1, 3 * mm),
        Paragraph(
            "据本观察估算，2025 年样本企业合计营业收入约 3,286,000 万元，"
            "较上年增长约 2.0%；该估算采用样本企业口径直接加总，"
            "未调整内部交易与口径差异，不能替代企业年报数据。", BODY),
        Spacer(1, 4 * mm),
        Paragraph(
            "本材料中的估算值与上市公司年报披露值可能存在差异，差异本身不构成数据矛盾；"
            "在证据链中应记录为二手来源观测，不参与真值竞争。", SMALL),
    ]
    n = build_pdf(out, story, pager)
    return {"pages": {"market_note": 1}, "page_count": n}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    gold: dict = {
        "generated_from": "fixtures/gen_corpus.py",
        "note": "金标由生成方独立持有，抽取器不可见；数值单位统一为元（人民币）。",
        "documents": [],
        "facts": [],
        "industry": [],
        "injected": [
            {"type": "unannounced_restatement", "entity_id": "SZ:002461", "fiscal_year": 2023,
             "field_code": "revenue", "original": "5378110220.30", "restated_in_next_report": "5368110220.30",
             "expect": "NUMERIC_CONFLICT / BLOCKED"},
            {"type": "official_correction", "entity_id": "SH:600600", "fiscal_year": 2025,
             "field_code": "operating_cost", "original": "19360412880.62", "corrected": "19020338204.15",
             "expect": "SUPERSEDED"},
        ],
    }
    manifest: list[dict] = []

    for entity_id, meta in COMPANIES.items():
        for year in (2023, 2024, 2025):
            fname = f"{meta['ticker']}_{year}_annual_report.pdf"
            path = CORPUS / fname
            info = annual_report(entity_id, year, path)
            gold["documents"].append({
                "file": fname,
                "entity_id": entity_id,
                "doc_type": "annual_report",
                "fiscal_year": year,
                "published_on": f"{year + 1}-03-28",
                "pages": info["pages"],
                "page_count": info["page_count"],
                "title": f"{meta['name']} {year} 年年度报告",
            })
            # 金标事实：当期列 + 上一年列
            for col_year in (year, year - 1):
                data = DATA[entity_id][col_year]
                for field, value in data.items():
                    statement = ("income_statement" if field in
                                 ("revenue", "operating_cost", "net_profit_total", "net_profit_parent", "minority_interest")
                                 else "balance_sheet" if field in
                                 ("total_assets", "total_liabilities", "total_equity", "liab_equity_total")
                                 else "cash_flow" if field == "operating_cashflow" else "segment")
                    page_key = {"income_statement": "income_statement", "balance_sheet": "balance_sheet",
                                "cash_flow": "cash_flow", "segment": "mdna"}[statement]
                    gold["facts"].append({
                        "entity_id": entity_id,
                        "field_code": field,
                        "fiscal_year": col_year,
                        "value_text": str(value),
                        "doc": fname,
                        "page": info["pages"][page_key],
                        "statement": statement,
                        "consolidation": "consolidated",
                        "unit": "元",
                    })
            # 摘要表（万元）金标仅记录舍入后的展示值
            for col_year in (year, year - 1):
                for field in ("revenue", "operating_cost", "net_profit_parent", "operating_cashflow"):
                    gold["facts"].append({
                        "entity_id": entity_id, "field_code": field, "fiscal_year": col_year,
                        "value_text": str(wan(DATA[entity_id][col_year][field]) * D(10000)),
                        "doc": fname, "page": info["pages"]["summary"], "statement": "summary",
                        "consolidation": "consolidated", "unit": "万元", "rounded": True,
                    })
        # 母公司报表已包含在年报内（第 8 页），不单独登记为另一份文档

    info = correction_notice(CORPUS / "600600_2025_correction.pdf")
    gold["documents"].append({
        "file": "600600_2025_correction.pdf", "entity_id": "SH:600600", "doc_type": "correction",
        "fiscal_year": 2025, "published_on": CORRECTION["published_on"], "pages": info["pages"],
        "page_count": info["page_count"], "title": CORRECTION["title"],
    })
    for key, (before, after) in CORRECTION["rows"].items():
        gold["facts"].append({
            "entity_id": "SH:600600", "field_code": key, "fiscal_year": 2025,
            "value_text": str(after), "doc": "600600_2025_correction.pdf", "page": 1,
            "statement": "income_statement" if key == "operating_cost" else "segment",
            "consolidation": "consolidated", "unit": "元", "basis": "restated", "corrected_from": str(before),
        })

    industry_stats(CORPUS / "industry_beer_2025.pdf")
    gold["documents"].append({
        "file": "industry_beer_2025.pdf", "doc_type": "industry_stats", "entity_id": None,
        "pages": {"industry_stats": 1}, "page_count": 1, "title": "2025年啤酒行业运行情况",
        "published_on": "2026-01-20",
    })
    for y in (2023, 2024, 2025):
        gold["industry"].append({"code": "beer_output", "period": str(y),
                                 "value_text": str(INDUSTRY["beer"]["output"][y]), "unit": "万千升"})
        gold["industry"].append({"code": "beer_revenue_above_scale", "period": str(y),
                                 "value_text": str(INDUSTRY["beer"]["revenue_yi"][y]), "unit": "亿元"})

    policy_doc(CORPUS / "policy_catalog_2024.pdf")
    gold["documents"].append({
        "file": "policy_catalog_2024.pdf", "doc_type": "policy", "entity_id": None,
        "pages": {"policy": 1}, "page_count": 1, "title": POLICY["title"],
        "published_on": POLICY["published_on"],
    })
    market_note(CORPUS / "market_note_beer_2025.pdf")
    gold["documents"].append({
        "file": "market_note_beer_2025.pdf", "doc_type": "market_note", "entity_id": None,
        "pages": {"market_note": 1}, "page_count": 1, "title": "啤酒行业高端化趋势观察（二级来源）",
        "published_on": "2026-05-10",
    })

    GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")

    issuer_map = {
        "annual_report": None, "parent_statement_note": None, "correction": None,
        "industry_stats": "国家统计局", "policy": "国家发展和改革委员会",
        "market_note": "公开市场观察（二级来源）",
    }
    for d in gold["documents"]:
        ent = d.get("entity_id")
        manifest.append({
            "file": d["file"],
            "entity_id": ent,
            "issuer": ent if ent else issuer_map.get(d["doc_type"], "unknown"),
            "doc_type": d["doc_type"],
            "fiscal_year": d.get("fiscal_year"),
            "published_on": d.get("published_on"),
            "title": d.get("title") or d["file"],
            "tier": "secondary" if d["doc_type"] == "market_note" else "primary",
            "demo_role": d.get("demo_role") or "",
            "expected_parser": "pdfplumber",
        })
    (CORPUS.parent / "manifest.json").write_text(
        json.dumps({"pack": "beer-demo", "version": "1.0.0", "documents": manifest},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"documents={len(gold['documents'])} facts={len(gold['facts'])} -> {CORPUS}")
    for d in gold["documents"]:
        p = CORPUS / d["file"]
        print(f"  {d['file']:<34} {p.stat().st_size/1024:6.1f} KB  pages={d['page_count']}")


if __name__ == "__main__":
    main()
