"""仓储层：只做读写，不含业务判断。"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from .db import dumps, get_conn, loads, utcnow


# --------------------------------------------------------------------------- #
# 实体 / 文档 / 定位
# --------------------------------------------------------------------------- #

def upsert_entity(e: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO entities(entity_id,name,exchange,ticker,industry_id,role,tag,market)
           VALUES(:entity_id,:name,:exchange,:ticker,:industry_id,:role,
                  COALESCE(:tag,''),COALESCE(:market,'A'))
           ON CONFLICT(entity_id) DO UPDATE SET name=excluded.name, role=excluded.role,
             industry_id=excluded.industry_id, tag=excluded.tag, market=excluded.market""",
        {**e, "tag": e.get("tag", ""), "market": e.get("market", "A")},
    )


def upsert_alias(alias: str, entity_id: str, alias_type: str = "short") -> None:
    get_conn().execute(
        "INSERT INTO aliases(alias,entity_id,alias_type) VALUES(?,?,?) "
        "ON CONFLICT(alias) DO UPDATE SET entity_id=excluded.entity_id",
        (alias, entity_id, alias_type),
    )


def get_entity(entity_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM entities WHERE entity_id=?", (entity_id,)).fetchone()
    return dict(row) if row else None


def search_entities(q: str, limit: int = 8) -> list[dict[str, Any]]:
    like = f"%{q.strip()}%"
    cur = get_conn().execute(
        """SELECT DISTINCT e.* FROM entities e
           LEFT JOIN aliases a ON a.entity_id = e.entity_id
           WHERE e.name LIKE ? OR e.entity_id LIKE ? OR e.ticker LIKE ? OR (a.alias LIKE ? AND a.alias_type != 'code')
           ORDER BY CASE e.role WHEN 'subject' THEN 0 ELSE 1 END, e.ticker
           LIMIT ?""",
        (like, like, like, like, limit),
    )
    return [dict(r) for r in cur]


def list_entities() -> list[dict[str, Any]]:
    cur = get_conn().execute("SELECT * FROM entities ORDER BY CASE role WHEN 'subject' THEN 0 ELSE 1 END, ticker")
    return [dict(r) for r in cur]


def upsert_document(d: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO documents(document_id,logical_doc_key,sha256,canonical_url,title,issuer,source_type,
              published_on,retrieved_at,period_start,period_end,content_type,page_count,local_path,
              parser_version,tier,demo_role,dataset_tag)
           VALUES(:document_id,:logical_doc_key,:sha256,:canonical_url,:title,:issuer,:source_type,
              :published_on,:retrieved_at,:period_start,:period_end,:content_type,:page_count,:local_path,
              :parser_version,:tier,:demo_role,:dataset_tag)
           ON CONFLICT(document_id) DO UPDATE SET title=excluded.title, local_path=excluded.local_path,
              page_count=excluded.page_count, published_on=excluded.published_on,
              dataset_tag=excluded.dataset_tag""",
        {"dataset_tag": "real_cninfo", **d},
    )


def get_document(document_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    return dict(row) if row else None


def documents_visible(as_of: str | None = None, issuer: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM documents WHERE 1=1"
    args: list[Any] = []
    if as_of:
        sql += " AND (published_on IS NULL OR published_on <= ?)"
        args.append(as_of)
    if issuer:
        sql += " AND issuer = ?"
        args.append(issuer)
    sql += " ORDER BY published_on, document_id"
    return [dict(r) for r in get_conn().execute(sql, args)]


def upsert_location(loc: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO source_locations(location_id,document_id,kind,page_index,printed_label,cell_id,
              row_label,col_label,table_id,table_type,bbox,heading_path,block_index,excerpt,extractor_version)
           VALUES(:location_id,:document_id,:kind,:page_index,:printed_label,:cell_id,:row_label,:col_label,
              :table_id,:table_type,:bbox,:heading_path,:block_index,:excerpt,:extractor_version)
           ON CONFLICT(location_id) DO NOTHING""",
        {**loc, "bbox": dumps(loc.get("bbox")) if not isinstance(loc.get("bbox"), str) else loc.get("bbox")},
    )


def get_location(location_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM source_locations WHERE location_id=?", (location_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["bbox"] = loads(d.get("bbox"), None)
    return d


# --------------------------------------------------------------------------- #
# 事实
# --------------------------------------------------------------------------- #

def insert_fact(f: dict[str, Any]) -> bool:
    cur = get_conn().execute(
        """INSERT INTO facts(fact_id,fact_key,key_parts,entity_id,field_code,location_id,document_id,
              raw_value,value_text,raw_unit,unit_scale,currency,precision_step,extraction_method,audit_scope,
              basis_tag,lineage_group,extract_status,confidence_hint,period_end,consolidation,created_at)
           VALUES(:fact_id,:fact_key,:key_parts,:entity_id,:field_code,:location_id,:document_id,
              :raw_value,:value_text,:raw_unit,:unit_scale,:currency,:precision_step,:extraction_method,
              :audit_scope,:basis_tag,:lineage_group,:extract_status,:confidence_hint,:period_end,
              :consolidation,:created_at)
           ON CONFLICT(fact_id) DO NOTHING""",
        {**f, "key_parts": dumps(f["key_parts"]), "created_at": f.get("created_at") or utcnow()},
    )
    return cur.rowcount > 0


def get_fact(fact_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM facts WHERE fact_id=?", (fact_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["key_parts"] = loads(d["key_parts"], {})
    return d


def facts_for_key(fact_key: str) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        """SELECT f.*, d.published_on, d.source_type, d.tier, d.title AS doc_title,
                  d.issuer AS doc_issuer, d.dataset_tag
           FROM facts f JOIN documents d ON d.document_id = f.document_id
           WHERE f.fact_key = ? ORDER BY d.published_on DESC""",
        (fact_key,),
    )
    out = []
    for r in cur:
        d = dict(r)
        d["key_parts"] = loads(d["key_parts"], {})
        out.append(d)
    return out


def all_fact_keys(entity_id: str | None = None) -> list[str]:
    if entity_id:
        cur = get_conn().execute("SELECT DISTINCT fact_key FROM facts WHERE entity_id=?", (entity_id,))
    else:
        cur = get_conn().execute("SELECT DISTINCT fact_key FROM facts")
    return [r[0] for r in cur]


def facts_of_entity(entity_id: str) -> list[dict[str, Any]]:
    cur = get_conn().execute("SELECT * FROM facts WHERE entity_id=? ORDER BY field_code, period_end", (entity_id,))
    out = []
    for r in cur:
        d = dict(r)
        d["key_parts"] = loads(d["key_parts"], {})
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# 核验结果
# --------------------------------------------------------------------------- #

def replace_resolutions(records: Sequence[dict[str, Any]]) -> None:
    conn = get_conn()
    for r in records:
        conn.execute(
            """INSERT INTO resolutions(resolution_id,fact_key,field_code,period_end,chosen_fact_id,candidate_ids,
                  decision,confidence,reason,policy_version,observed_values,conflict_ids,created_at)
               VALUES(:resolution_id,:fact_key,:field_code,:period_end,:chosen_fact_id,:candidate_ids,
                  :decision,:confidence,:reason,:policy_version,:observed_values,:conflict_ids,:created_at)
               ON CONFLICT(resolution_id) DO UPDATE SET reason=excluded.reason""",
            {
                **r,
                "candidate_ids": dumps(r["candidate_ids"]),
                "observed_values": dumps(r["observed_values"]),
                "conflict_ids": dumps(r.get("conflict_ids", [])),
                "created_at": r.get("created_at") or utcnow(),
            },
        )


def latest_resolution(fact_key: str) -> dict[str, Any] | None:
    row = get_conn().execute(
        "SELECT * FROM resolutions WHERE fact_key=? ORDER BY rowid DESC LIMIT 1", (fact_key,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("candidate_ids", "observed_values", "conflict_ids"):
        d[k] = loads(d[k], [])
    return d


def all_resolutions() -> list[dict[str, Any]]:
    cur = get_conn().execute("SELECT * FROM resolutions ORDER BY rowid")
    out = []
    for r in cur:
        d = dict(r)
        for k in ("candidate_ids", "observed_values", "conflict_ids"):
            d[k] = loads(d[k], [])
        out.append(d)
    return out


def upsert_issue(issue: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO issues(issue_id,type,severity,key,candidate_ids,status,context,created_at)
           VALUES(:issue_id,:type,:severity,:key,:candidate_ids,:status,:context,:created_at)
           ON CONFLICT(issue_id) DO UPDATE SET status=excluded.status, context=excluded.context""",
        {
            **issue,
            "candidate_ids": dumps(issue.get("candidate_ids", [])),
            "context": dumps(issue.get("context", {})),
            "created_at": issue.get("created_at") or utcnow(),
        },
    )


def open_issues() -> list[dict[str, Any]]:
    cur = get_conn().execute("SELECT * FROM issues ORDER BY severity, created_at")
    out = []
    for r in cur:
        d = dict(r)
        d["candidate_ids"] = loads(d["candidate_ids"], [])
        d["context"] = loads(d["context"], {})
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# 指标 / 行业事实 / 图
# --------------------------------------------------------------------------- #

def insert_metric(m: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO metric_results(result_id,metric_key,metric_code,formula_id,formula_version,entity_id,
              fiscal_year,value_text,display,unit,status,inputs,input_refs,compare_scope,confidence,
              missing_reason,computed_at)
           VALUES(:result_id,:metric_key,:metric_code,:formula_id,:formula_version,:entity_id,:fiscal_year,
              :value_text,:display,:unit,:status,:inputs,:input_refs,:compare_scope,:confidence,
              :missing_reason,:computed_at)
           ON CONFLICT(result_id) DO NOTHING""",
        {
            **m,
            "inputs": dumps(m.get("inputs", [])),
            "input_refs": dumps(m.get("input_refs", [])),
            "computed_at": (m["computed_at"].isoformat()
                            if hasattr(m.get("computed_at"), "isoformat") else m.get("computed_at")),
        },
    )


def get_metric(result_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM metric_results WHERE result_id=?", (result_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["inputs"] = loads(d["inputs"], [])
    d["input_refs"] = loads(d["input_refs"], [])
    return d


def metrics_of(entity_id: str, fiscal_year: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM metric_results WHERE entity_id=?"
    args: list[Any] = [entity_id]
    if fiscal_year is not None:
        sql += " AND fiscal_year=?"
        args.append(fiscal_year)
    sql += " ORDER BY fiscal_year, metric_code"
    out = []
    for r in get_conn().execute(sql, args):
        d = dict(r)
        d["inputs"] = loads(d["inputs"], [])
        d["input_refs"] = loads(d["input_refs"], [])
        out.append(d)
    return out


def upsert_industry_fact(f: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO industry_facts(industry_fact_id,industry_id,code,label,value_text,unit,geography,
              period,stat_scope,definition,source_location,document_id,confidence,created_at)
           VALUES(:industry_fact_id,:industry_id,:code,:label,:value_text,:unit,:geography,:period,
              :stat_scope,:definition,:source_location,:document_id,:confidence,:created_at)
           ON CONFLICT(industry_fact_id) DO UPDATE SET value_text=excluded.value_text""",
        {**f, "created_at": f.get("created_at") or utcnow()},
    )


def industry_facts(industry_id: str) -> list[dict[str, Any]]:
    cur = get_conn().execute("SELECT * FROM industry_facts WHERE industry_id=? ORDER BY period, code", (industry_id,))
    return [dict(r) for r in cur]


def upsert_node(n: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO graph_nodes(node_id,type,label,entity_id,meta) VALUES(:node_id,:type,:label,:entity_id,:meta)
           ON CONFLICT(node_id) DO UPDATE SET label=excluded.label""",
        {**n, "meta": dumps(n.get("meta", {}))},
    )


def upsert_edge(e: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO graph_edges(edge_id,edge_key,src,dst,relation,scope,evidence_refs,effective_period,status,note)
           VALUES(:edge_id,:edge_key,:src,:dst,:relation,:scope,:evidence_refs,:effective_period,:status,:note)
           ON CONFLICT(edge_id) DO NOTHING""",
        {**e, "evidence_refs": dumps(e.get("evidence_refs", []))},
    )


def graph(scope_prefix: str | None = None) -> dict[str, Any]:
    nodes = [dict(r) for r in get_conn().execute("SELECT * FROM graph_nodes")]
    edges = []
    for r in get_conn().execute("SELECT * FROM graph_edges WHERE status != 'UNVERIFIED'"):
        d = dict(r)
        d["evidence_refs"] = loads(d["evidence_refs"], [])
        edges.append(d)
    for n in nodes:
        n["meta"] = loads(n.get("meta"), {})
    return {"nodes": nodes, "edges": edges}


def get_edge(edge_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM graph_edges WHERE edge_id=?", (edge_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["evidence_refs"] = loads(d["evidence_refs"], [])
    return d


# --------------------------------------------------------------------------- #
# Claim / 报告版本
# --------------------------------------------------------------------------- #

def insert_claim(c: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO claims(claim_version_id,claim_key,kind,template,slots,reference_ids,verdict,section_key,
              text,findings,created_at)
           VALUES(:claim_version_id,:claim_key,:kind,:template,:slots,:reference_ids,:verdict,:section_key,
              :text,:findings,:created_at)
           ON CONFLICT(claim_version_id) DO NOTHING""",
        {
            **c,
            "slots": dumps(c.get("slots", {})),
            "reference_ids": dumps(c.get("reference_ids", [])),
            "findings": dumps(c.get("findings", [])),
            "created_at": c.get("created_at") or utcnow(),
        },
    )


def get_claim(claim_version_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM claims WHERE claim_version_id=?", (claim_version_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("slots", "reference_ids", "findings"):
        d[k] = loads(d[k], {})
    return d


def ensure_report(report_id: str, entity_id: str) -> None:
    get_conn().execute(
        "INSERT INTO reports(report_id,entity_id,created_at) VALUES(?,?,?) ON CONFLICT(report_id) DO NOTHING",
        (report_id, entity_id, utcnow()),
    )


def entity_of_report(report_id: str) -> str | None:
    row = get_conn().execute("SELECT entity_id FROM reports WHERE report_id=?", (report_id,)).fetchone()
    return row[0] if row else None


def head_version(report_id: str) -> int | None:
    row = get_conn().execute("SELECT head_version_no FROM reports WHERE report_id=?", (report_id,)).fetchone()
    return row[0] if row else None


def set_head(report_id: str, version_no: int) -> None:
    get_conn().execute("UPDATE reports SET head_version_no=? WHERE report_id=?", (version_no, report_id))


def insert_report_version(v: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO report_versions(report_id,version_no,base_version_id,input_fingerprint,as_of,
              workflow_version,state,content_hash,created_at,label)
           VALUES(:report_id,:version_no,:base_version_id,:input_fingerprint,:as_of,:workflow_version,
              :state,:content_hash,:created_at,:label)""",
        v,
    )


def get_report_version(report_id: str, version_no: int) -> dict[str, Any] | None:
    row = get_conn().execute(
        "SELECT * FROM report_versions WHERE report_id=? AND version_no=?", (report_id, version_no)
    ).fetchone()
    return dict(row) if row else None


def list_report_versions(report_id: str) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        "SELECT * FROM report_versions WHERE report_id=? ORDER BY version_no DESC", (report_id,)
    )
    return [dict(r) for r in cur]


def insert_section(s: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO section_versions(section_version_id,section_key,report_id,version_no,content,content_hash,claim_ids)
           VALUES(:section_version_id,:section_key,:report_id,:version_no,:content,:content_hash,:claim_ids)
           ON CONFLICT(report_id,version_no,section_key) DO NOTHING""",
        {**s, "content": dumps(s["content"]), "claim_ids": dumps(s.get("claim_ids", []))},
    )


def sections_of(report_id: str, version_no: int) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        "SELECT * FROM section_versions WHERE report_id=? AND version_no=? ORDER BY section_key",
        (report_id, version_no),
    )
    out = []
    for r in cur:
        d = dict(r)
        d["content"] = loads(d["content"], {})
        d["claim_ids"] = loads(d["claim_ids"], [])
        out.append(d)
    return out


def link_version_object(report_id: str, version_no: int, object_type: str, object_id: str) -> None:
    get_conn().execute(
        "INSERT INTO version_objects(report_id,version_no,object_type,object_id) VALUES(?,?,?,?) "
        "ON CONFLICT DO NOTHING",
        (report_id, version_no, object_type, object_id),
    )


def clear_version_objects(report_id: str, version_no: int) -> None:
    """重发同一版本号前先清空链接，保证版本对象集合与正文一致。"""
    get_conn().execute("DELETE FROM version_objects WHERE report_id=? AND version_no=?",
                       (report_id, version_no))


def version_object_ids(report_id: str, version_no: int, object_type: str) -> list[str]:
    cur = get_conn().execute(
        "SELECT object_id FROM version_objects WHERE report_id=? AND version_no=? AND object_type=?",
        (report_id, version_no, object_type),
    )
    return [r[0] for r in cur]


# --------------------------------------------------------------------------- #
# 依赖图
# --------------------------------------------------------------------------- #

def replace_dependencies(snapshot_id: str, edges: Iterable[tuple[str, str, str]]) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM dependencies WHERE snapshot_id=?", (snapshot_id,))
    conn.executemany(
        "INSERT INTO dependencies(snapshot_id,source_key,dependent_key,dependency_type) VALUES(?,?,?,?)",
        [(snapshot_id, s, d, t) for s, d, t in edges],
    )


def dependencies(snapshot_id: str) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        "SELECT source_key,dependent_key,dependency_type FROM dependencies WHERE snapshot_id=?", (snapshot_id,)
    )
    return [dict(r) for r in cur]


# --------------------------------------------------------------------------- #
# 运行 / 事件 / 问答
# --------------------------------------------------------------------------- #

def create_run(run: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO runs(run_id,job_kind,report_id,status,idempotency_key,budget,payload,result,error,
              heartbeat_at,created_at,finished_at)
           VALUES(:run_id,:job_kind,:report_id,:status,:idempotency_key,:budget,:payload,:result,:error,
              :heartbeat_at,:created_at,:finished_at)""",
        {
            **run,
            "budget": dumps(run.get("budget", {})),
            "payload": dumps(run.get("payload", {})),
            "result": dumps(run.get("result", {})),
            "status": run.get("status", "queued"),
            "created_at": run.get("created_at") or utcnow(),
        },
    )


def update_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    for k in ("budget", "payload", "result"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = dumps(fields[k])
    sets = ", ".join(f"{k}=:{k}" for k in fields)
    get_conn().execute(f"UPDATE runs SET {sets} WHERE run_id=:run_id", {**fields, "run_id": run_id})


def get_run(run_id: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    for k in ("budget", "payload", "result"):
        d[k] = loads(d[k], {})
    return d


def run_by_idempotency(key: str) -> dict[str, Any] | None:
    row = get_conn().execute("SELECT run_id FROM runs WHERE idempotency_key=?", (key,)).fetchone()
    return get_run(row[0]) if row else None


def add_event(run_id: str, seq: int, event: str, data: dict[str, Any]) -> None:
    get_conn().execute(
        "INSERT INTO run_events(run_id,seq,event,data,created_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(run_id,seq) DO NOTHING",
        (run_id, seq, event, dumps(data), utcnow()),
    )


def events_after(run_id: str, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        "SELECT * FROM run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?", (run_id, after_seq, limit)
    )
    out = []
    for r in cur:
        d = dict(r)
        d["data"] = loads(d["data"], {})
        out.append(d)
    return out


def mark_stale_runs() -> int:
    cur = get_conn().execute(
        "UPDATE runs SET status='interrupted', finished_at=? WHERE status IN ('queued','running')",
        (utcnow(),),
    )
    return cur.rowcount


def save_question(q: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO questions(question_id,report_id,version_no,question,answer,refs,intent,created_at)
           VALUES(:question_id,:report_id,:version_no,:question,:answer,:refs,:intent,:created_at)
           ON CONFLICT(question_id) DO UPDATE SET answer=excluded.answer, refs=excluded.refs,
             intent=excluded.intent, created_at=excluded.created_at""",
        {**q, "refs": dumps(q.get("refs", [])), "created_at": q.get("created_at") or utcnow()},
    )


def questions_of(report_id: str) -> list[dict[str, Any]]:
    cur = get_conn().execute(
        "SELECT * FROM questions WHERE report_id=? ORDER BY created_at", (report_id,)
    )
    out = []
    for r in cur:
        d = dict(r)
        d["refs"] = loads(d["refs"], [])
        out.append(d)
    return out


def add_finding(f: dict[str, Any]) -> None:
    get_conn().execute(
        "INSERT INTO audit_findings(finding_id,claim_version_id,code,severity,detail,created_at) VALUES(?,?,?,?,?,?)",
        (f["finding_id"], f["claim_version_id"], f["code"], f["severity"], f["detail"], f.get("created_at") or utcnow()),
    )


# --------------------------------------------------------------------------- #
# 真实公开数据：第三方结构化财务事实 + 产业链知识
# --------------------------------------------------------------------------- #


def upsert_market_fact(f: dict[str, Any]) -> None:
    """同一 (entity, field, year, source) 只保留最新一次抓取。"""
    get_conn().execute(
        """INSERT INTO market_facts(market_fact_id,entity_id,field_code,fiscal_year,period_end,
               consolidation,currency,value_text,unit,source,source_field,source_url,report_type,
               notice_date,fetched_at,raw)
           VALUES(:market_fact_id,:entity_id,:field_code,:fiscal_year,:period_end,:consolidation,
               :currency,:value_text,:unit,:source,:source_field,:source_url,:report_type,
               :notice_date,:fetched_at,:raw)
           ON CONFLICT(entity_id,field_code,fiscal_year,source) DO UPDATE SET
               value_text=excluded.value_text, period_end=excluded.period_end,
               notice_date=excluded.notice_date, fetched_at=excluded.fetched_at,
               raw=excluded.raw, source_url=excluded.source_url""",
        f,
    )


def market_fact(entity_id: str, field_code: str, fiscal_year: int,
                source: str = "eastmoney") -> dict[str, Any] | None:
    row = get_conn().execute(
        "SELECT * FROM market_facts WHERE entity_id=? AND field_code=? AND fiscal_year=? AND source=?",
        (entity_id, field_code, fiscal_year, source),
    ).fetchone()
    return dict(row) if row else None


def market_series(entity_id: str, field_code: str, source: str = "eastmoney") -> dict[int, str]:
    cur = get_conn().execute(
        "SELECT fiscal_year, value_text FROM market_facts WHERE entity_id=? AND field_code=? AND source=?",
        (entity_id, field_code, source),
    )
    return {int(r["fiscal_year"]): r["value_text"] for r in cur}


def market_facts_of(entity_id: str, fiscal_year: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM market_facts WHERE entity_id=?"
    args: list[Any] = [entity_id]
    if fiscal_year:
        sql += " AND fiscal_year=?"
        args.append(fiscal_year)
    return [dict(r) for r in get_conn().execute(sql, args)]


def market_years(entity_id: str) -> list[int]:
    cur = get_conn().execute(
        "SELECT DISTINCT fiscal_year FROM market_facts WHERE entity_id=? ORDER BY fiscal_year", (entity_id,)
    )
    return [int(r[0]) for r in cur]


def upsert_chain_node(n: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO chain_nodes(node_id,industry_id,name,role,note,entity_id,ticker,degree)
           VALUES(:node_id,:industry_id,:name,:role,:note,:entity_id,:ticker,:degree)
           ON CONFLICT(node_id) DO UPDATE SET name=excluded.name, role=excluded.role,
               note=excluded.note, entity_id=excluded.entity_id, ticker=excluded.ticker,
               degree=excluded.degree""",
        n,
    )


def upsert_chain_edge(e: dict[str, Any]) -> None:
    get_conn().execute(
        """INSERT INTO chain_edges(edge_id,industry_id,src,dst,relation,basis)
           VALUES(:edge_id,:industry_id,:src,:dst,:relation,:basis)
           ON CONFLICT(edge_id) DO UPDATE SET relation=excluded.relation, basis=excluded.basis""",
        e,
    )


def chain_graph(industry_id: str) -> dict[str, Any]:
    nodes = [dict(r) for r in get_conn().execute(
        "SELECT * FROM chain_nodes WHERE industry_id=? ORDER BY role, name", (industry_id,))]
    edges = [dict(r) for r in get_conn().execute(
        "SELECT * FROM chain_edges WHERE industry_id=?", (industry_id,))]
    return {"nodes": nodes, "edges": edges}
