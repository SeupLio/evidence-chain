"""把 docs/实施与验收说明.md 渲染成排版过的 Word 文档。

只支持本项目用到的语法：标题、段落、无序列表、表格、代码块、**加粗**、`行内代码`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "实施与验收说明.md"
OUT = ROOT / "docs" / "经营证据链_实施与验收说明.docx"

SANS = "微软雅黑"
SERIF = "宋体"
MONO = "Consolas"
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x59, 0x59, 0x59)
ACCENT = RGBColor(0x1F, 0x4E, 0x79)


# --------------------------------------------------------------------------- #
# 低层工具
# --------------------------------------------------------------------------- #

def set_run_font(run, name: str, size: float | None = None, bold: bool | None = None,
                 color: RGBColor | None = None) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color


def shade(cell_or_par, hex_fill: str) -> None:
    el = cell_or_par._element
    pr = el.find(qn("w:tcPr")) if el.tag.endswith("tc") else el.get_or_add_pPr()
    if pr is None:
        pr = OxmlElement("w:tcPr")
        el.append(pr)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    pr.append(shd)


def para_border(par, color: str = "1F4E79", size: int = 12, side: str = "left") -> None:
    ppr = par._element.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size))
    el.set(qn("w:space"), "6")
    el.set(qn("w:color"), color)
    pbdr.append(el)
    ppr.append(pbdr)


def add_page_field(par) -> None:
    """插入 PAGE 域；fldSimple 内必须带一个 run，否则 Word 渲染为空。"""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), " PAGE ")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    par._p.append(fld)


# --------------------------------------------------------------------------- #
# 解析 markdown
# --------------------------------------------------------------------------- #

def parse(text: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    lines = text.split("\n")
    i = 0
    para: list[str] = []

    def flush() -> None:
        nonlocal para
        if para:
            # 行尾两个空格（\u0000 标记）= 软换行，保留为段内换行而不是并成一行
            out = ""
            for idx, seg in enumerate(para):
                soft = seg.endswith("\u0000")
                body = seg.replace("\u0000", "").strip()
                if idx == 0:
                    out = body
                else:
                    out += ("\n" if para[idx - 1].endswith("\u0000") else " ") + body
            blocks.append(("p", out))
            para = []

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(buf)))
            i += 1
            continue
        if re.match(r"^#{1,4}\s", line):
            flush()
            level = len(line) - len(line.lstrip("#"))
            blocks.append((f"h{level}", line[level:].strip()))
            i += 1
            continue
        if line.strip() == "---":
            flush()
            blocks.append(("hr", ""))
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|[\s:\-|]+\|$", lines[i].strip()):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        if line.strip().startswith(("- ", "* ")):
            flush()
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append(("ul", items))
            continue
        if re.match(r"^\d+\.\s", line.strip()):
            flush()
            items = []
            while i < len(lines) and (re.match(r"^\d+\.\s", lines[i].strip()) or lines[i].startswith("   ")):
                s = lines[i].strip()
                if re.match(r"^\d+\.\s", s):
                    items.append(re.sub(r"^\d+\.\s", "", s))
                elif items:
                    items[-1] += " " + s
                i += 1
            blocks.append(("ol", items))
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        para.append(line.strip() + ("\u0000" if line.endswith("  ") else ""))
        i += 1
    flush()
    return blocks


INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def add_inline(par, text: str, size: float = 10.5, color: RGBColor = INK) -> None:
    for chunk in INLINE.split(text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            run = par.add_run(chunk[2:-2])
            set_run_font(run, SANS, size, bold=True, color=color)
        elif chunk.startswith("`") and chunk.endswith("`"):
            run = par.add_run(chunk[1:-1])
            set_run_font(run, MONO, size - 1, color=RGBColor(0xB0, 0x30, 0x60))
        else:
            run = par.add_run(chunk)
            set_run_font(run, SERIF, size, color=color)


# --------------------------------------------------------------------------- #
# 生成
# --------------------------------------------------------------------------- #

def build() -> Path:
    text = SRC.read_text(encoding="utf-8")
    blocks = parse(text)

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.6)
    section.top_margin = Cm(2.4)
    section.bottom_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = SERIF
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), SERIF)
    normal.paragraph_format.line_spacing = 1.55
    normal.paragraph_format.space_after = Pt(6)

    # 页脚页码
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("经营证据链 · 实施与验收说明　·　第 ")
    set_run_font(run, SERIF, 8.5, color=MUTED)
    add_page_field(footer)
    run2 = footer.add_run(" 页")
    set_run_font(run2, SERIF, 8.5, color=MUTED)

    # ---------- 封面 ----------
    for _ in range(2):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("经营证据链")
    set_run_font(r, SANS, 30, bold=True, color=ACCENT)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Evidence Chain")
    set_run_font(r, SANS, 13, color=MUTED)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(22)
    r = p.add_run("AI 驱动的行业研究与企业经营分析助手")
    set_run_font(r, SANS, 15, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("实施与验收说明")
    set_run_font(r, SANS, 15, bold=True)

    for _ in range(4):
        doc.add_paragraph()

    meta = [
        ("命题", "工商银行企业命题二：AI 驱动的行业研究与企业经营分析助手"),
        ("形态", "单人开发的可运行原型（本地单机）"),
        ("技术栈", "Python 3.13 / FastAPI / SQLite（WAL）/ React + TypeScript / ECharts"),
        ("文档性质", "实施记录 · 验收证据 · 交接说明"),
        ("版本 / 日期", "v1.0　/　2026-11-20"),
    ]
    table = doc.add_table(rows=len(meta), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, (k, v) in enumerate(meta):
        row = table.rows[i]
        row.cells[0].width = Cm(3.4)
        row.cells[1].width = Cm(11.6)
        c0 = row.cells[0].paragraphs[0]
        r = c0.add_run(k)
        set_run_font(r, SANS, 9.5, bold=True, color=ACCENT)
        c1 = row.cells[1].paragraphs[0]
        r = c1.add_run(v)
        set_run_font(r, SERIF, 9.5)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("本文所有数字均来自本机实际运行；演示语料为合成数据，每页标注，解析链路为真实链路。")
    set_run_font(r, SERIF, 8.5, color=MUTED)

    doc.add_page_break()

    # ---------- 文档结构 ----------
    p = doc.add_paragraph()
    r = p.add_run("文档结构")
    set_run_font(r, SANS, 16, bold=True, color=ACCENT)
    para_border(p, "1F4E79", 12, "bottom")

    outline = [str(x) for x in [
        "1. 文档目的　2. 交付范围对照　3. 系统架构　4. 数据契约要点",
        "5. 证据链四层　6. 核验引擎判定策略　7. 指标与公式　8. 风险规则",
        "9. 报告、Claim 与引用守卫　10. 版本、依赖与增量更新　11. 接口清单",
        "12. 评测方法与结果　13. 未实现项与已知风险　14. 复现步骤　15. 附录：文件索引",
    ]]
    for line in outline:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(line)
        set_run_font(r, SERIF, 10.5)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    r = p.add_run("阅读建议：先读第 2 章（交付对照）与第 12 章（实测结果），再按需读技术细节。")
    set_run_font(r, SERIF, 9.5, color=MUTED)

    doc.add_page_break()

    # ---------- 正文 ----------
    first_h1 = True
    for kind, payload in blocks:
        if kind == "h1":
            if not first_h1:
                doc.add_page_break()
            first_h1 = False
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(10)
            r = p.add_run(str(payload))
            set_run_font(r, SANS, 19, bold=True, color=ACCENT)
            para_border(p, "1F4E79", 18, "bottom")
        elif kind == "h2":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            r = p.add_run(str(payload))
            set_run_font(r, SANS, 14, bold=True, color=RGBColor(0x1F, 0x3A, 0x5F))
        elif kind == "h3":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(str(payload))
            set_run_font(r, SANS, 11.5, bold=True)
        elif kind == "h4":
            p = doc.add_paragraph()
            r = p.add_run(str(payload))
            set_run_font(r, SANS, 10.5, bold=True)
        elif kind == "p":
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0)
            for n, segment in enumerate(str(payload).split("\n")):
                if n:
                    p.add_run().add_break()
                add_inline(p, segment)
        elif kind == "ul":
            for item in payload:  # type: ignore[union-attr]
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.left_indent = Cm(0.75)
                add_inline(p, str(item))
        elif kind == "ol":
            for item in payload:  # type: ignore[union-attr]
                p = doc.add_paragraph(style="List Number")
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.left_indent = Cm(0.75)
                add_inline(p, str(item))
        elif kind == "code":
            for line in str(payload).split("\n"):
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.left_indent = Cm(0.4)
                r = p.add_run(line if line else " ")
                set_run_font(r, MONO, 8.5, color=RGBColor(0x1B, 0x2A, 0x3A))
                shade(p, "F2F5F9")
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
        elif kind == "table":
            rows = payload  # type: ignore[assignment]
            n_cols = max(len(r) for r in rows)
            t = doc.add_table(rows=len(rows), cols=n_cols)
            t.style = "Table Grid"
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            usable = 15.8
            for ri, row in enumerate(rows):
                for ci in range(n_cols):
                    cell = t.cell(ri, ci)
                    text_cell = row[ci] if ci < len(row) else ""
                    cell.paragraphs[0].text = ""
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_after = Pt(1)
                    p.paragraph_format.line_spacing = 1.15
                    add_inline(p, text_cell, size=8.5 if ri else 8.8,
                               color=INK if ri else RGBColor(0x1F, 0x3A, 0x5F))
                    if ri == 0:
                        for run in p.runs:
                            run.font.bold = True
                        shade(cell, "E8EEF6")
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif kind == "hr":
            p = doc.add_paragraph()
            para_border(p, "C9D3E0", 6, "bottom")
            p.paragraph_format.space_after = Pt(8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"written {path}  {path.stat().st_size / 1024:.1f} KB")
