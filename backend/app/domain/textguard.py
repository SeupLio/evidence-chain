"""Claim 文本守卫。

模型可以选模板、选引用，但不能自己写数字。做法：
1. 模板里的数字只能由 ``{{m:...}}`` / ``{{f:...}}`` 等 token 渲染进来，渲染时记录每个数值的字符区间。
2. 渲染完成后扫描全文：**区间之外出现阿拉伯数字** → 判为未绑定数字，直接 BLOCK。
   这样“毛利率下降 4pp”这种手写数字无法蒙混过关。
3. 过强因果词（必然/证实/造假）BLOCK；一般归因词（导致/说明）WARN，交人工复核。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import ClaimKind, Verdict

TOKEN_RE = re.compile(r"\{\{([a-z][a-z0-9]?):([^}]+)\}\}")
CJK_DIGIT_RE = re.compile(r"[一二三四五六七八九十百千万亿]+(?=[成倍番折])")
ARABIC_RE = re.compile(r"[0-9]")

BLOCK_WORDS = ("必然", "一定会", "必将", "证实了", "证明了", "造假", "舞弊", "财务造假", "违约", "崩盘", "资不抵债")
WARN_WORDS = ("导致", "表明", "意味着", "反映了", "根本原因", "显著提升", "大幅改善")


@dataclass
class RenderedClaim:
    text: str
    refs: list[str] = field(default_factory=list)
    value_spans: list[tuple[int, int]] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    verdict: Verdict = Verdict.PASS
    unresolved: list[str] = field(default_factory=list)

    def with_findings(self) -> "RenderedClaim":
        verdict = Verdict.PASS
        for f in self.findings:
            level = f.get("level")
            if level == "BLOCK":
                verdict = Verdict.BLOCK
            elif level == "WARN" and verdict != Verdict.BLOCK:
                verdict = Verdict.WARN
        self.verdict = verdict
        return self


def render(template: str, resolver) -> RenderedClaim:
    """``resolver(kind, ref) -> (display_text, ref_id|None)``，返回 None 表示解析失败。"""
    out_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    refs: list[str] = []
    findings: list[dict] = []
    unresolved: list[str] = []
    cursor = 0
    length = 0

    for m in TOKEN_RE.finditer(template):
        chunk = template[cursor:m.start()]
        out_parts.append(chunk)
        length += len(chunk)
        kind, ref = m.group(1), m.group(2).strip()
        resolved = resolver(kind, ref)
        if resolved is None:
            unresolved.append(f"{kind}:{ref}")
            placeholder = "［待补证］"
            out_parts.append(placeholder)
            length += len(placeholder)
            findings.append({
                "code": "CLAIM_REF_UNRESOLVED", "level": "BLOCK",
                "detail": f"引用 {kind}:{ref} 无法解析到本次运行的证据",
            })
        else:
            display, ref_id = resolved
            spans.append((length, length + len(display)))
            out_parts.append(display)
            length += len(display)
            if ref_id and ref_id not in refs:
                refs.append(ref_id)
        cursor = m.end()
    tail = template[cursor:]
    out_parts.append(tail)
    text = "".join(out_parts)

    # 未绑定数字检测
    for i, ch in enumerate(text):
        if not ARABIC_RE.match(ch):
            continue
        if any(a <= i < b for a, b in spans):
            continue
        # 允许出现在已绑定数值紧邻的上下文中（例如 “较上年” 后面的 2025 年由 ref 给出）
        findings.append({
            "code": "CLAIM_UNBOUND_NUMBER", "level": "BLOCK",
            "detail": f"位置 {i} 出现未绑定数字：…{text[max(0, i - 12):i + 12]}…",
        })
        break

    # 中文数量词（如“两家同行”）属于模板常量，不判违规；但“增长三成”这类结论性数量要复核
    if CJK_DIGIT_RE.search(text):
        findings.append({
            "code": "CLAIM_CJK_QUANTITY", "level": "WARN",
            "detail": "文本含中文数量词，需人工确认是否为模板常量",
        })

    for w in BLOCK_WORDS:
        if w in text:
            findings.append({"code": "CLAIM_STRONG_CAUSALITY", "level": "BLOCK", "detail": f"出现强断言词「{w}」"})
    for w in WARN_WORDS:
        if w in text:
            findings.append({"code": "CLAIM_CAUSAL_WORDING", "level": "WARN", "detail": f"出现因果措辞「{w}」，需核证据是否支持"})

    return RenderedClaim(text=text, refs=refs, value_spans=spans, findings=findings, unresolved=unresolved).with_findings()


def check_numeric_claim(kind: ClaimKind, text: str) -> list[dict]:
    """对 interpretation / hypothesis 额外检查：结论不得脱离已绑定数值。"""
    if kind in (ClaimKind.INTERPRETATION, ClaimKind.HYPOTHESIS):
        if not any(k in text for k in ("可能", "线索", "待核", "待补证", "未评估", "假设", "情景",
                                       "需", "复核", "验证", "未经", "不构成")):
            return [{"code": "CLAIM_OVERCLAIM", "level": "WARN", "detail": "解释性结论缺少不确定性限定词"}]
    return []
