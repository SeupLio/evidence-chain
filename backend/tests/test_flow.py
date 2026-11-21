"""端到端验收：从原件到版本，再到补证与提交。

对应计划书第 15 章的三条端到端测试：
1) 固定输入主体 + 两期 → 指标可复算 → 报告引用可解析 → 缺证不填 0；
2) 合成更正改一个 FactKey → 预览 → 提交 → 旧版不变、受影响章节更新、无影响章节 hash 不变；
3) replay（无网络、无模型）下核心数字仍可重新计算。
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ec-e2e-")

from app.domain.contracts import Decision  # noqa: E402
from app.services import update  # noqa: E402
from app.services.ingest import seed_corpus  # noqa: E402
from app.storage import repo  # noqa: E402
from app.storage.db import init_db  # noqa: E402
from app.workflow.runner import execute  # noqa: E402

REPORT = "rpt:SH:600600:2023-2025"
REQ = {"entity_id": "SH:600600", "fiscal_years": [2023, 2024, 2025], "as_of": "2026-04-30",
       "peer_ids": ["SH:600132", "SZ:002461"], "run_id": "t-run"}


@pytest.fixture(scope="module")
def seeded():
    init_db()
    out = seed_corpus()
    assert out["ok"] == out["documents"]
    return out


@pytest.fixture(scope="module")
def first_version(seeded):
    result = execute(dict(REQ), model_mode="mock", source_mode="replay")
    assert result["status"] == "complete", result
    return result["version"]


def test_corpus_parses_real_tables(seeded):
    n = repo.get_conn().execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    assert n > 300
    loc = repo.get_conn().execute(
        "SELECT COUNT(*) FROM source_locations WHERE kind='pdf_cell' AND bbox IS NOT NULL").fetchone()[0]
    assert loc > 250


def test_metrics_recomputable(first_version):
    m = repo.get_conn().execute(
        "SELECT value_text, display, status FROM metric_results "
        "WHERE entity_id='SH:600600' AND metric_code='gross_margin' AND fiscal_year=2025").fetchone()
    assert m["status"] == "OK"
    assert m["display"] == "41.36%"
    # 独立算一遍：(33015286417.35 - 19360412880.62) / 33015286417.35
    expected = (33015286417.35 - 19360412880.62) / 33015286417.35
    assert abs(float(m["value_text"]) - expected) < 1e-9


def test_missing_field_is_not_zero(first_version):
    # 母公司报表不参与合并指标；合并口径字段齐备，故检查同行 2022 的缺口处理
    rows = repo.get_conn().execute(
        "SELECT COUNT(*) FROM metric_results WHERE status!='OK' AND (display IS NOT NULL OR value_text IS NOT NULL)"
    ).fetchone()[0]
    assert rows == 0


def test_every_citation_resolves(first_version):
    from app.services.evidence import resolve

    ids = repo.version_object_ids(REPORT, first_version["version_no"], "claim")
    total = 0
    for cid in ids:
        c = repo.get_claim(cid)
        for ref in c["reference_ids"]:
            total += 1
            ev = resolve(ref)
            assert ev.title and (ev.document or ev.formula or ev.basis or ev.excerpt), ref
    assert total > 20


def test_unannounced_restatement_blocks_metric(seeded):
    key = next(k for k in repo.all_fact_keys("SZ:002461")
               if "revenue" in k and k.split("|")[2].startswith("2023"))
    res = repo.latest_resolution(key)
    assert res["decision"] == Decision.BLOCKED.value
    m = repo.get_conn().execute(
        "SELECT status FROM metric_results WHERE entity_id='SZ:002461' AND metric_code='gross_margin' "
        "AND fiscal_year=2023").fetchone()
    assert m["status"] in ("BLOCKED_INPUT", "MISSING_INPUT")


def test_incremental_update_is_isolated(seeded, first_version):
    corr = next(d for d in repo.documents_visible() if d["source_type"] == "correction")
    prev = update.preview(REPORT, first_version["version_no"], REQ, as_of="2026-06-30",
                          staged=[corr["document_id"]])
    sections = {s["section_key"]: s for s in prev["diff"]["sections"]}
    assert sections["financials"]["changed"] is True
    assert sections["industry"]["changed"] is False
    assert sections["industry"]["same_version_id"] is True
    assert sections["chain"]["same_version_id"] is True
    # 只有一个 FactKey 家族的决策变化（营业成本 + 其分部科目）
    codes = {f["field_code"] for f in prev["diff"]["facts"]}
    assert "operating_cost" in codes
    assert "revenue" not in codes

    committed = update.commit(REPORT, prev["draft_version"], first_version["version_no"])
    assert committed["status"] == "COMMITTED"
    assert repo.head_version(REPORT) == prev["draft_version"]

    # 旧版本仍然可读，且内容没被覆盖
    old = repo.get_report_version(REPORT, first_version["version_no"])
    assert old["content_hash"] == first_version["content_hash"]
    # 新版本里 industry 复用了旧 section_version_id
    old_secs = {s["section_key"]: s for s in repo.sections_of(REPORT, first_version["version_no"])}
    new_secs = {s["section_key"]: s for s in repo.sections_of(REPORT, prev["draft_version"])}
    assert old_secs["industry"]["section_version_id"] == new_secs["industry"]["section_version_id"]
    assert old_secs["financials"]["section_version_id"] != new_secs["financials"]["section_version_id"]


def test_stale_base_is_rejected(seeded, first_version):
    with pytest.raises(update.StaleBase):
        update.commit(REPORT, first_version["version_no"] + 99, first_version["version_no"])


def test_no_change_does_not_create_version(seeded, first_version):
    """同一份输入再预览一次，必须返回 NO_CHANGE，不产生新版本。"""
    head = repo.head_version(REPORT)
    row = repo.get_report_version(REPORT, head)
    corr = next(d for d in repo.documents_visible() if d["source_type"] == "correction")
    with pytest.raises(update.NoChange):
        update.preview(REPORT, head, {**REQ, "as_of": row["as_of"]}, as_of=row["as_of"],
                       staged=[corr["document_id"]])


def test_correction_supersedes_original(first_version):
    corr = next(d for d in repo.documents_visible() if d["source_type"] == "correction")
    key = next(k for k in repo.all_fact_keys("SH:600600")
               if "operating_cost" in k and k.split("|")[2].startswith("2025"))
    # 在 2026-06-30 截止日下重新核验
    from app.services.verify import verify_entity

    out = verify_entity("SH:600600", "2026-06-30", [corr["document_id"]])
    assert out.resolutions[key]["decision"] == Decision.SUPERSEDED.value
    assert out.resolutions[key]["confidence"] == "HIGH"


# --------------------------------------------------------------------------- #
# 产品层：数据集隔离、证据地图、追问
# --------------------------------------------------------------------------- #

def test_synthetic_corpus_is_tagged_and_overview_is_real_only(seeded):
    tags = {r[0] for r in repo.get_conn().execute("SELECT DISTINCT dataset_tag FROM documents")}
    assert tags == {"synthetic_regression"}
    from app.services import sectors

    o = sectors.overview()
    assert o["counts"]["documents"] == 0
    assert o["counts"]["annual_reports"] == 0
    assert o["note"].startswith("统计只读")


def test_seed_refuses_to_mix_real_and_synthetic(seeded):
    conn = repo.get_conn()
    fake = "doc:test-real-only"
    conn.execute(
        "INSERT INTO documents(document_id,logical_doc_key,sha256,title,issuer,source_type,"
        "page_count,local_path,dataset_tag) VALUES(?,?,?,?,?,?,?,?,?)",
        (fake, "test:real", "a" * 64, "测试真实年报", "SH:600600", "annual_report", 1, "", "real_cninfo"),
    )
    try:
        out = seed_corpus()
        assert out.get("error") == "DATASET_CONFLICT"
    finally:
        conn.execute("DELETE FROM documents WHERE document_id=?", (fake,))


def test_provenance_graph_links_claims_to_documents(first_version):
    from app.services import provenance

    g = provenance.graph(REPORT, first_version["version_no"])
    stats = g["stats"]
    assert stats["sections"] == 8
    assert stats["claims"] >= 27
    assert stats["metrics"] > 0 and stats["facts"] > 0 and stats["documents"] > 0
    node_ids = {n["id"] for n in g["nodes"]}
    for e in g["edges"]:
        assert e["source"] in node_ids and e["target"] in node_ids
    from_doc = [e for e in g["edges"] if e["kind"] == "FROM_DOC"]
    assert from_doc and all(e["target"].startswith("doc:") for e in from_doc)


def test_qa_multi_turn_and_peer_comparison(first_version):
    from app.services import qa

    a = qa.answer(REPORT, first_version["version_no"], "毛利率在同行里处于什么位置？")
    assert a["intent"] == "compare"
    assert a["refs"], "同业比较必须带可点击引用"
    assert "重庆啤酒" in a["answer"]

    b = qa.answer(REPORT, first_version["version_no"], "为什么下降", history=["重庆啤酒 2024 年毛利率"])
    assert b["inherited"] and "重庆啤酒" in b["inherited"][0]
    assert "重庆啤酒" in b["answer"]


def test_qa_corrects_false_premise(first_version):
    from app.services import qa

    a = qa.answer(REPORT, first_version["version_no"], "为什么毛利率上升")
    assert a["premise"] == {"claimed": "up", "actual": "down", "change": a["premise"]["change"],
                            "unit": "个百分点"}
    assert a["premise"]["change"] > 0
    assert "并未上升" in a["answer"]

