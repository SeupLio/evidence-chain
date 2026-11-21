"""引用解析：把前端点的任意 ref 还原成「哪张表、哪一格、什么口径、怎么算、为什么采信」。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from ..domain.contracts import EvidenceRef
from ..domain.keys import FactKey
from ..domain.metrics import FORMULAS, cny_yi
from ..storage import repo

D = Decimal
PAGE_CACHE = Path(__file__).resolve().parents[3] / "data" / "pages"


def _document_block(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    ent = repo.get_entity(doc["issuer"]) or {}
    return {
        "document_id": doc["document_id"], "title": doc["title"], "issuer": doc["issuer"],
        "issuer_name": ent.get("name") or doc["issuer"],
        "source_type": doc["source_type"], "published_on": doc["published_on"],
        "retrieved_at": doc["retrieved_at"], "page_count": doc["page_count"],
        "sha256": doc["sha256"], "tier": doc["tier"], "parser_version": doc["parser_version"],
    }


def _location_block(loc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not loc:
        return None
    return {"page": loc["page_index"], "cell_id": loc["cell_id"], "row_label": loc["row_label"],
            "col_label": loc["col_label"], "table_id": loc["table_id"], "table_type": loc["table_type"],
            "bbox": loc["bbox"], "heading_path": loc["heading_path"], "excerpt": loc["excerpt"],
            "kind": loc["kind"]}


def resolve(ref: str) -> EvidenceRef:
    kind, _, rest = ref.partition(":")
    if kind == "fact":
        return _fact(rest)
    if kind == "metric":
        return _metric(rest)
    if kind == "rule":
        return _rule(rest)
    if kind == "bench":
        return _bench(rest)
    if kind == "edge":
        return _edge(rest)
    if kind == "loc":
        return _loc(rest)
    if kind == "claim":
        return _claim(rest)
    if kind == "gap":
        return EvidenceRef(ref=ref, kind="document", title="资料缺口", excerpt=rest)
    return EvidenceRef(ref=ref, kind="document", title="未识别的引用", excerpt=ref)


def _fact(fact_id: str) -> EvidenceRef:
    fact = repo.get_fact(fact_id) or repo.get_fact(f"fact:{fact_id}")
    if not fact:
        return EvidenceRef(ref=f"fact:{fact_id}", kind="fact", title="事实不存在", excerpt="该事实未入库")
    fact_id = fact["fact_id"]
    loc = repo.get_location(fact["location_id"])
    doc = repo.get_document(fact["document_id"])
    parts = FactKey.parse(fact["fact_key"])
    spec_label = fact["field_code"]
    res = repo.latest_resolution(fact["fact_key"])
    value = D(fact["value_text"])
    return EvidenceRef(
        ref=f"fact:{fact_id}", kind="fact",
        title=f"{loc['row_label'] if loc else fact['field_code']}（{parts.period_end}）",
        value_display=f"{value:,.2f}",
        unit=f"{fact['raw_unit']}→元",
        basis={
            "口径": "合并" if parts.consolidation == "consolidated" else "母公司",
            "期间": f"{parts.period_start} ~ {parts.period_end}（{parts.period_kind}）",
            "币种": parts.currency,
            "业务范围": parts.business_scope,
            "定义版本": parts.definition_id,
            "审计层级": fact["audit_scope"],
            "基数版本": fact["basis_tag"],
            "精度步长": f"{fact['precision_step']} 元",
            "抽取方式": fact["extraction_method"],
            "置信度提示": fact["confidence_hint"],
            "核验决策": res["decision"] if res else "未核验",
        },
        document=_document_block(doc),
        location=_location_block(loc),
        excerpt=loc["excerpt"] if loc else fact["raw_value"],
        reasons=[res["reason"]] if res and res.get("reason") else [],
        formula={"raw_value": fact["raw_value"], "unit_scale": fact["unit_scale"],
                 "value_text": fact["value_text"]},
    )


def _metric(result_id: str) -> EvidenceRef:
    m = repo.get_metric(result_id) or repo.get_metric(f"metric:{result_id}")
    if not m:
        return EvidenceRef(ref=f"metric:{result_id}", kind="metric", title="指标不存在")
    result_id = m["result_id"]
    spec = FORMULAS[m["metric_code"]]
    inputs = []
    for inp in m["inputs"]:
        fact = repo.get_fact(inp["fact_id"]) if inp.get("fact_id") else None
        loc = repo.get_location(fact["location_id"]) if fact else None
        doc = repo.get_document(fact["document_id"]) if fact else None
        inputs.append({
            "slot": inp["slot"],
            "ref": f"fact:{inp['fact_id']}" if inp.get("fact_id") else None,
            "value_text": inp["value_text"],
            "display": (f"{D(inp['value_text']):,.2f}" if inp["value_text"] else "缺失"),
            "fact_id": inp.get("fact_id"),
            "page": loc["page_index"] if loc else None,
            "cell_id": loc["cell_id"] if loc else None,
            "document": doc["title"] if doc else None,
            "published_on": doc["published_on"] if doc else None,
            "unit": fact["raw_unit"] if fact else None,
        })
    # 指标本身没有单一页面：取第一个有原表定位的输入，作为「原页」入口，
    # 其余输入在算式表里逐行可点（前端传 fact_id 继续下钻）。
    primary_fact = None
    for inp in m["inputs"]:
        if inp.get("fact_id"):
            f = repo.get_fact(inp["fact_id"])
            if f:
                primary_fact = f
                break
    p_loc = repo.get_location(primary_fact["location_id"]) if primary_fact else None
    p_doc = repo.get_document(primary_fact["document_id"]) if primary_fact else None
    return EvidenceRef(
        ref=f"metric:{result_id}", kind="metric",
        title=f"{spec.label} · FY{m['fiscal_year']}",
        value_display=m["display"], unit=m["unit"],
        document=_document_block(p_doc), location=_location_block(p_loc),
        excerpt=(p_loc["excerpt"] + "（本页为第一个输入的原表单元格；其余输入见算式表）") if p_loc else None,
        formula={"id": m["formula_id"], "version": m["formula_version"], "text": spec.formula_text,
                 "description": spec.description, "inputs": inputs,
                 "status": m["status"], "missing_reason": m["missing_reason"]},
        basis={"实体": m["entity_id"], "财年": str(m["fiscal_year"]), "比较范围": m["compare_scope"],
               "置信度": m["confidence"]},
        reasons=[f"按公式逐项复算，{len(m['input_refs'])} 项输入，结果：{'已核验' if m['status'] == 'OK' else '待补证'}"],
    )


def _rule(rule_id: str) -> EvidenceRef:
    from ..domain.rules import load_pack

    pack = load_pack("config/rules/operating_watch_v1.yaml")
    cfg = pack.get(rule_id, {})
    labels = {"margin_pressure": "毛利率承压", "cash_divergence": "利润与现金流背离",
              "balance_sheet_watch": "杠杆水平观察", "evidence_integrity": "证据完整性"}
    return EvidenceRef(
        ref=f"rule:{rule_id}", kind="risk", title=f"规则 · {labels.get(rule_id, '风险观察')}",
        basis={"关注级别": str(cfg.get("severity", ""))},
        formula={"rule_id": rule_id, "config": cfg, "pack": pack.get("id", "")},
        reasons=["阈值固定，解释不会改变判定"],
    )


def _bench(ref_body: str) -> EvidenceRef:
    code, _, year = ref_body.partition(":")
    spec = FORMULAS.get(code)
    return EvidenceRef(ref=f"bench:{ref_body}", kind="metric",
                       title=f"同业中位数 · {spec.label if spec else code}",
                       basis={"财年": year, "口径": "同一指标定义、同一财年、合并报表"},
                       reasons=["n<2 时不输出基准；中位数不称行业均值"])


def _edge(edge_id: str) -> EvidenceRef:
    e = repo.get_edge(edge_id)
    if not e:
        return EvidenceRef(ref=f"edge:{edge_id}", kind="edge", title="关系不存在")
    loc = repo.get_location(e["evidence_refs"][0]) if e.get("evidence_refs") else None
    doc = repo.get_document(loc["document_id"]) if loc else None
    return EvidenceRef(
        ref=f"edge:{edge_id}", kind="edge",
        title=f"{e['src']} --{e['relation']}--> {e['dst']}",
        basis={"状态": e["status"], "生效期": e["effective_period"], "范围": e["scope"]},
        document=_document_block(doc), location=_location_block(loc),
        excerpt=loc["excerpt"] if loc else None,
        reasons=[e.get("note") or ""],
    )


def _loc(location_id: str) -> EvidenceRef:
    loc = repo.get_location(location_id) or repo.get_location(f"loc:{location_id}")
    if not loc:
        return EvidenceRef(ref=f"loc:{location_id}", kind="document", title="定位不存在")
    doc = repo.get_document(loc["document_id"])
    return EvidenceRef(ref=f"loc:{location_id}", kind="document",
                       title=(doc["title"] if doc else "原件"),
                       document=_document_block(doc), location=_location_block(loc),
                       excerpt=loc["excerpt"])


def _claim(claim_id: str) -> EvidenceRef:
    c = repo.get_claim(claim_id) or repo.get_claim(f"claim:{claim_id}")
    if not c:
        return EvidenceRef(ref=f"claim:{claim_id}", kind="claim", title="结论不存在")
    return EvidenceRef(ref=f"claim:{claim_id}", kind="claim", title=c["claim_key"],
                       excerpt=c["text"], basis={"类型": c["kind"], "审核": c["verdict"]},
                       reasons=[c["template"]])


def page_image(document_id: str, page: int, scale: float = 2.0) -> Path:
    """用 pypdfium2 渲染原页，前端在图上叠 bbox 高亮。"""
    doc = repo.get_document(document_id)
    if not doc:
        raise FileNotFoundError("文档不存在")
    PAGE_CACHE.mkdir(parents=True, exist_ok=True)
    out = PAGE_CACHE / f"{document_id.split(':')[-1]}_{page}_{int(scale * 10)}.png"
    if out.exists():
        return out
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(doc["local_path"])
    try:
        pg = pdf[page - 1]
        bitmap = pg.render(scale=scale)
        bitmap.to_pil().save(out, format="PNG")
    finally:
        pdf.close()
    return out
