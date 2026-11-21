"""评测：金标对照 + 独立复算 + 引用可达 + 冲突判别 + 增量隔离。

独立复算刻意不复用生产公式：这里用 Fraction 重写一遍，
避免「同一函数算两遍」造成的假一致。
"""

from __future__ import annotations

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..domain.keys import FactKey
from ..storage import repo

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
D = Decimal


def _synthetic_docs() -> list[str]:
    return [r["document_id"] for r in repo.get_conn().execute(
        "SELECT document_id FROM documents WHERE dataset_tag='synthetic_regression'")]


def _not_available(what: str) -> dict[str, Any]:
    return {"status": "not_available", "label": what,
            "note": "本库没有合成回归语料。回归赛道需在独立 DATA_DIR 运行："
                    "DATA_DIR=data/regression python -m app.cli seed --pack beer-demo"}


# --------------------------------------------------------------------------- #
# 1. 抽取准确率 / 召回（合成回归赛道）
# --------------------------------------------------------------------------- #

def extraction_scores() -> dict[str, Any]:
    if not _synthetic_docs():
        return _not_available("模板语料回归")
    gold = json.loads((FIXTURES / "gold.json").read_text(encoding="utf-8"))
    target = [g for g in gold["facts"] if not g.get("rounded") and g.get("basis") != "restated"]
    hits, misses, wrong = [], [], []
    for g in target:
        rows = repo.get_conn().execute(
            """SELECT f.value_text, f.raw_unit, f.precision_step FROM facts f
               JOIN documents d ON d.document_id=f.document_id
               WHERE f.entity_id=? AND f.field_code=? AND f.period_end LIKE ?
                 AND f.consolidation='consolidated'
                 AND d.dataset_tag='synthetic_regression'
                 AND f.document_id NOT LIKE '%correction%'""",
            (g["entity_id"], g["field_code"], str(g["fiscal_year"]) + "%")).fetchall()
        if not rows:
            misses.append(g)
            continue
        want = D(g["value_text"])
        ok = any(abs(D(r["value_text"]) - want) <= D(r["precision_step"]) / 2 for r in rows)
        (hits if ok else wrong).append(g)
    precision = len(hits) / max(len(hits) + len(wrong), 1)
    recall = len(hits) / max(len(target), 1)
    return {"status": "ok", "dataset_tag": "synthetic_regression",
            "gold": len(target), "hit": len(hits), "miss": len(misses), "wrong": len(wrong),
            "precision": round(precision, 4), "recall": round(recall, 4),
            "examples_missed": [f"{m['entity_id']}/{m['field_code']}/{m['fiscal_year']}" for m in misses[:5]],
            "examples_wrong": [f"{m['entity_id']}/{m['field_code']}/{m['fiscal_year']}" for m in wrong[:5]]}


# --------------------------------------------------------------------------- #
# 2. 独立复算
# --------------------------------------------------------------------------- #

def _q(resolution_id: str) -> dict[str, Any] | None:
    row = repo.get_conn().execute("SELECT * FROM resolutions WHERE resolution_id=?", (resolution_id,)).fetchone()
    return dict(row) if row else None


def _num(x: str | None) -> Fraction | None:
    if x in (None, ""):
        return None
    return Fraction(Decimal(x))


def independent_recompute(metric: dict[str, Any]) -> tuple[bool, str | None, Fraction | None]:
    """用 Fraction 从输入原值重算，返回 (是否一致, 错误说明, 重算值)。"""
    vals: dict[str, Fraction | None] = {}
    inputs = json.loads(repo.get_conn().execute(
        "SELECT inputs FROM metric_results WHERE result_id=?", (metric["result_id"],)).fetchone()[0])
    for inp in inputs:
        vals[inp["slot"]] = _num(inp["value_text"])
    code = metric["metric_code"]
    if metric["status"] != "OK":
        return True, None, None
    if any(v is None for v in vals.values()):
        return False, "状态为 OK 但存在空输入", None
    try:
        if code == "gross_margin":
            got = (vals["revenue"] - vals["operating_cost"]) / vals["revenue"]
        elif code == "revenue_yoy":
            got = vals["revenue"] / vals["revenue_prev"] - 1
        elif code == "parent_net_margin":
            got = vals["net_profit_parent"] / vals["revenue"]
        elif code == "debt_asset_ratio":
            got = vals["total_liabilities"] / vals["total_assets"]
        elif code == "ocf_margin":
            got = vals["operating_cashflow"] / vals["revenue"]
        elif code == "cash_conversion":
            got = vals["operating_cashflow"] / vals["net_profit_total"]
        elif code == "receivables_days":
            got = vals["receivables"] / vals["revenue"] * 365
        elif code == "inventory_days":
            got = vals["inventories"] / vals["operating_cost"] * 365
        elif code in ("gross_margin_delta_pp", "asset_ratio_delta_pp", "ocf_margin_delta_pp"):
            got = (vals["cur"] - vals["prev"]) * 100
        else:
            return False, f"未覆盖的公式 {code}", None
    except (ZeroDivisionError, KeyError) as exc:
        return False, f"重算异常 {exc}", None
    stored = Fraction(Decimal(metric["value_text"]))
    tol = max(abs(got) / Fraction(10**9), Fraction(1, 10**7))
    return abs(got - stored) <= tol, None if abs(got - stored) <= tol else f"{float(got)} vs {metric['value_text']}", got


def recompute_scores() -> dict[str, Any]:
    rows = repo.get_conn().execute("SELECT * FROM metric_results").fetchall()
    total = ok = 0
    failures = []
    for r in rows:
        m = dict(r)
        total += 1
        good, err, _ = independent_recompute(m)
        if good:
            ok += 1
        else:
            failures.append({"metric": m["metric_key"], "error": err})
    return {"metrics": total, "consistent": ok,
            "rate": round(ok / max(total, 1), 4), "failures": failures[:5]}


# --------------------------------------------------------------------------- #
# 3. 引用可达
# --------------------------------------------------------------------------- #

def citation_scores(report_id: str | None = None) -> dict[str, Any]:
    from ..services.evidence import resolve

    report_id = report_id or repo.get_conn().execute(
        "SELECT report_id FROM reports ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    version = repo.head_version(report_id)
    if version is None:
        return {"error": "尚无正式版本"}
    claim_ids = repo.version_object_ids(report_id, version, "claim")
    total = reachable = 0
    broken = []
    for cid in claim_ids:
        c = repo.get_claim(cid)
        if not c:
            continue
        for ref in c["reference_ids"]:
            total += 1
            try:
                ev = resolve(ref)
            except Exception:
                broken.append({"ref": ref, "reason": "解析异常"})
                continue
            ok = bool(ev.document or ev.formula or ev.basis or ev.excerpt)
            if ok:
                reachable += 1
            else:
                broken.append({"ref": ref, "reason": "无原文可打开"})
    return {"refs": total, "reachable": reachable,
            "rate": round(reachable / max(total, 1), 4), "broken": broken[:5]}


# --------------------------------------------------------------------------- #
# 4. 冲突判别
# --------------------------------------------------------------------------- #

def conflict_scores() -> dict[str, Any]:
    if not _synthetic_docs():
        return _not_available("冲突判别 / 重述注入")
    from ..services.verify import verify_entity

    gold = json.loads((FIXTURES / "gold.json").read_text(encoding="utf-8"))
    # 更正公告的披露日晚于默认观察截止日；评测在 2026-06-30 重新核验一次，
    # 确保「正式更正可见」这一前提成立，而不是拿旧截止日的决策硬判。
    for eid in {inj["entity_id"] for inj in gold["injected"]}:
        verify_entity(eid, "2026-06-30")
    cases = []
    injected_keys: set[str] = set()
    injected_scope: set[tuple[str, int]] = set()
    for inj in gold["injected"]:
        injected_scope.add((inj["entity_id"], int(inj["fiscal_year"])))
        key = None
        for k in repo.all_fact_keys(inj["entity_id"]):
            p = FactKey.parse(k)
            if p.field_code == inj["field_code"] and p.period_end.startswith(str(inj["fiscal_year"])):
                key = k
                injected_keys.add(k)
                break
        res = repo.latest_resolution(key) if key else None
        decision = res["decision"] if res else "MISSING"
        expected = "SUPERSEDED" if inj["type"] == "official_correction" else "BLOCKED"
        ok = decision == expected
        cases.append({"case": inj["type"], "entity": inj["entity_id"], "expected": expected,
                      "actual": decision, "pass": ok, "fact_key": key})
    blocking = [dict(r) for r in repo.get_conn().execute(
        "SELECT key FROM issues WHERE type='NUMERIC_CONFLICT' AND severity='BLOCKING'")]
    tp = sum(1 for b in blocking if b["key"] in injected_keys)

    def same_root(key: str) -> bool:
        try:
            p = FactKey.parse(key)
        except Exception:
            return False
        return (p.entity_id, int((p.period_end or "0000")[:4])) in injected_scope

    fp = [b["key"] for b in blocking if b["key"] not in injected_keys and not same_root(b["key"])]
    scope = repo.get_conn().execute("SELECT COUNT(*) FROM issues WHERE type='SCOPE_MISMATCH'").fetchone()[0]
    rounding = repo.get_conn().execute(
        "SELECT COUNT(*) FROM issues WHERE type='ROUNDING_COMPATIBLE'").fetchone()[0]
    return {"status": "ok", "dataset_tag": "synthetic_regression",
            "cases": cases, "pass": sum(1 for c in cases if c["pass"]), "total": len(cases),
            "true_positive": tp, "extra_blocking": fp,
            "note": "同实体同年度的并列字段（如同一行的总额/净额）视为同根重复，不计误报",
            "same_root_blocking": len([b for b in blocking
                                       if b["key"] not in injected_keys and same_root(b["key"])]),
            "scope_mismatch_noted": scope, "rounding_compatible_noted": rounding,
            "false_as_conflict": 0 if not fp else len(fp)}


# --------------------------------------------------------------------------- #
# 5. 增量隔离
# --------------------------------------------------------------------------- #

def incremental_scores() -> dict[str, Any]:
    from ..services import update

    if not _synthetic_docs():
        return _not_available("增量更新隔离")
    report_id = repo.get_conn().execute(
        "SELECT report_id FROM reports ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    head = repo.head_version(report_id)
    if head is None:
        return {"error": "尚无正式版本"}
    corr = next((d for d in repo.documents_visible()
                 if d["source_type"] == "correction" and d["dataset_tag"] == "synthetic_regression"), None)
    if not corr:
        return {"status": "not_available", "label": "增量更新隔离",
                "note": "合成语料缺少更正公告 fixture，本赛道未运行。"}
    req = {"entity_id": repo.entity_of_report(report_id), "fiscal_years": [2023, 2024, 2025],
           "peer_ids": ["SH:600132", "SZ:002461"]}
    try:
        prev = update.preview(report_id, head, req, as_of="2026-06-30", staged=[corr["document_id"]])
    except update.NoChange:
        return {"no_change": True}
    sections = prev["diff"]["sections"]
    unchanged = [s for s in sections if not s["changed"]]
    isolated = [s for s in unchanged if s["same_version_id"]]
    changed = [s["section_key"] for s in sections if s["changed"]]
    ok = len(unchanged) == len(isolated) and "financials" in changed and "industry" not in changed
    predicted = list(prev.get("changed_sections") or [])
    actual = changed
    result = {
        "draft_version": prev["draft_version"], "changed_sections": changed,
        "predicted_sections": sorted(predicted),
        "impact_exact": sorted(predicted) == sorted(actual),
        "unchanged_sections": [s["section_key"] for s in unchanged],
        "unchanged_keep_same_version_id": len(isolated), "pass": bool(ok),
        "facts_changed": prev["diff"]["counts"]["facts_changed"],
        "metrics_changed": prev["diff"]["counts"]["metrics_changed"],
        "sample_metric_diff": prev["diff"]["metrics"][:3],
        "sample_fact_diff": [
            {k: f[k] for k in ("field_code", "old_decision", "new_decision", "old_value", "new_value")}
            for f in prev["diff"]["facts"][:3]
        ],
    }
    # 清理评测产生的草稿，避免污染演示版本列表
    conn = repo.get_conn()
    conn.execute("DELETE FROM section_versions WHERE report_id=? AND version_no=?",
                 (report_id, prev["draft_version"]))
    conn.execute("DELETE FROM report_versions WHERE report_id=? AND version_no=?",
                 (report_id, prev["draft_version"]))
    conn.execute("DELETE FROM dependencies WHERE snapshot_id=?",
                 (f"{report_id}@v{prev['draft_version']}",))
    return result


# --------------------------------------------------------------------------- #
# 6. 缺证与边界
# --------------------------------------------------------------------------- #

def gap_scores() -> dict[str, Any]:
    rows = repo.get_conn().execute(
        "SELECT type, COUNT(*) n FROM issues GROUP BY type").fetchall()
    frozen = repo.get_conn().execute(
        "SELECT COUNT(*) FROM metric_results WHERE status IN ('MISSING_INPUT','INVALID_BASE','BLOCKED_INPUT')"
    ).fetchone()[0]
    zero_display = repo.get_conn().execute(
        "SELECT COUNT(*) FROM metric_results WHERE status!='OK' AND display IS NOT NULL").fetchone()[0]
    return {"issues_by_type": {r["type"]: r["n"] for r in rows},
            "metrics_not_ok": frozen, "not_ok_but_displayed": zero_display}


def run_eval() -> dict[str, Any]:
    from .crosscheck import crosscheck

    cross = crosscheck()
    extraction = extraction_scores()
    recompute = recompute_scores()
    citations = citation_scores()
    conflicts = conflict_scores()
    incremental = incremental_scores()

    # 主库没有合成语料时，在独立临时 DATA_DIR 里跑回归赛道；
    # 主库保持 real_cninfo 单赛道，评测页仍能展示完整结果。
    isolated = None
    if any(x.get("status") == "not_available" for x in (extraction, conflicts, incremental)):
        from .regression import run_isolated

        isolated = run_isolated()
        if isolated.get("status") == "ok":
            extraction = isolated["extraction"]
            conflicts = isolated["conflicts"]
            incremental = isolated["incremental"]

    gaps = gap_scores()
    return {
        # 主口径：跨源互证（原件 vs 第三方结构化数据），只读 real_cninfo
        "cross_source": cross,
        # 回归口径：合成语料的逐格金标，只用于防止抽取器退化，不能当真实精度
        "template_track": {**extraction, "label": "模板语料回归（非真实精度）"},
        "extraction": extraction,
        "recompute": recompute,
        "citations": citations,
        "conflicts": conflicts,
        "incremental": incremental,
        "issues": gaps,
        "tracks": {
            "cross_source": {"dataset_tag": "real_cninfo", "status": "ok",
                             "note": "真实公开年报 vs 第三方结构化数据，外部参照，不是自建金标"},
            "template_regression": {"dataset_tag": "synthetic_regression",
                                    "status": extraction.get("status", "ok"),
                                    "isolated": bool(isolated),
                                    "note": "只用于抽取器回归；在独立临时 DATA_DIR 运行" if isolated
                                            else "只用于抽取器回归，需独立 DATA_DIR"},
            "conflict_injection": {"dataset_tag": "synthetic_regression",
                                   "status": conflicts.get("status", "ok"),
                                   "isolated": bool(isolated),
                                   "note": "冲突与重述注入用例"},
            "incremental": {"dataset_tag": "synthetic_regression",
                            "status": incremental.get("status", "ok"),
                            "isolated": bool(isolated),
                            "note": "更正公告 → 增量预览 → 未命中章节版本不变"},
        },
        "regression_suite": isolated,
        "details": {"extraction": extraction, "recompute": recompute, "citations": citations,
                    "conflicts": conflicts, "incremental": incremental},
    }
