-- 001_init.sql —— 证据链原型初始结构
-- 约定：金额/比率用 TEXT 存十进制字符串；集合字段用 JSON TEXT；时间用 ISO8601 UTC。
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    entity_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    industry_id TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'peer',
    UNIQUE (exchange, ticker)
);

CREATE TABLE IF NOT EXISTS aliases (
    alias      TEXT PRIMARY KEY,
    entity_id  TEXT NOT NULL REFERENCES entities(entity_id),
    alias_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id     TEXT PRIMARY KEY,
    logical_doc_key TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    canonical_url   TEXT,
    title           TEXT NOT NULL,
    issuer          TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    published_on    TEXT,
    retrieved_at    TEXT,
    period_start    TEXT,
    period_end      TEXT,
    content_type    TEXT,
    page_count      INTEGER NOT NULL DEFAULT 0,
    local_path      TEXT NOT NULL DEFAULT '',
    parser_version  TEXT,
    tier            TEXT NOT NULL DEFAULT 'primary',
    demo_role       TEXT
);
CREATE INDEX IF NOT EXISTS idx_doc_key ON documents (logical_doc_key);
CREATE INDEX IF NOT EXISTS idx_doc_pub ON documents (published_on);

CREATE TABLE IF NOT EXISTS source_locations (
    location_id       TEXT PRIMARY KEY,
    document_id       TEXT NOT NULL REFERENCES documents(document_id),
    kind              TEXT NOT NULL,
    page_index        INTEGER,
    printed_label     TEXT,
    cell_id           TEXT,
    row_label         TEXT,
    col_label         TEXT,
    table_id          TEXT,
    table_type        TEXT,
    bbox              TEXT,
    heading_path      TEXT,
    block_index       INTEGER,
    excerpt           TEXT NOT NULL DEFAULT '',
    extractor_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_loc_doc ON source_locations (document_id, page_index);

CREATE TABLE IF NOT EXISTS facts (
    fact_id          TEXT PRIMARY KEY,
    fact_key         TEXT NOT NULL,
    key_parts        TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    field_code       TEXT NOT NULL,
    location_id      TEXT NOT NULL,
    document_id      TEXT NOT NULL,
    raw_value        TEXT NOT NULL,
    value_text       TEXT NOT NULL,
    raw_unit         TEXT NOT NULL,
    unit_scale       TEXT NOT NULL,
    currency         TEXT NOT NULL,
    precision_step   TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    audit_scope      TEXT NOT NULL,
    basis_tag        TEXT NOT NULL DEFAULT 'original',
    lineage_group    TEXT NOT NULL DEFAULT '',
    extract_status   TEXT NOT NULL DEFAULT 'OK',
    confidence_hint  TEXT NOT NULL DEFAULT 'MEDIUM',
    period_end       TEXT NOT NULL DEFAULT '',
    consolidation    TEXT NOT NULL DEFAULT 'consolidated',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_key  ON facts (fact_key);
CREATE INDEX IF NOT EXISTS idx_facts_ent  ON facts (entity_id, field_code);

CREATE TABLE IF NOT EXISTS resolutions (
    resolution_id    TEXT PRIMARY KEY,
    fact_key         TEXT NOT NULL,
    field_code       TEXT,
    period_end       TEXT,
    chosen_fact_id   TEXT,
    candidate_ids    TEXT NOT NULL DEFAULT '[]',
    decision         TEXT NOT NULL,
    confidence       TEXT NOT NULL,
    reason           TEXT NOT NULL,
    policy_version   TEXT NOT NULL,
    observed_values  TEXT NOT NULL DEFAULT '[]',
    conflict_ids     TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_res_key ON resolutions (fact_key);

CREATE TABLE IF NOT EXISTS issues (
    issue_id      TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    severity      TEXT NOT NULL,
    key           TEXT NOT NULL,
    candidate_ids TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'OPEN',
    context       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issue_key ON issues (key);

CREATE TABLE IF NOT EXISTS metric_results (
    result_id      TEXT PRIMARY KEY,
    metric_key     TEXT NOT NULL,
    metric_code    TEXT NOT NULL,
    formula_id     TEXT NOT NULL,
    formula_version INTEGER NOT NULL,
    entity_id      TEXT NOT NULL,
    fiscal_year    INTEGER NOT NULL,
    value_text     TEXT,
    display        TEXT,
    unit           TEXT NOT NULL,
    status         TEXT NOT NULL,
    inputs         TEXT NOT NULL DEFAULT '[]',
    input_refs     TEXT NOT NULL DEFAULT '[]',
    compare_scope  TEXT NOT NULL DEFAULT 'single',
    confidence     TEXT NOT NULL,
    missing_reason TEXT,
    computed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_metric_key ON metric_results (metric_key);

CREATE TABLE IF NOT EXISTS industry_facts (
    industry_fact_id TEXT PRIMARY KEY,
    industry_id      TEXT NOT NULL,
    code             TEXT NOT NULL,
    label            TEXT NOT NULL,
    value_text       TEXT NOT NULL,
    unit             TEXT NOT NULL,
    geography        TEXT,
    period           TEXT,
    stat_scope       TEXT,
    definition       TEXT,
    source_location  TEXT NOT NULL,
    document_id      TEXT NOT NULL,
    confidence       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id   TEXT PRIMARY KEY,
    type      TEXT NOT NULL,
    label     TEXT NOT NULL,
    entity_id TEXT,
    meta      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id          TEXT PRIMARY KEY,
    edge_key         TEXT NOT NULL,
    src              TEXT NOT NULL,
    dst              TEXT NOT NULL,
    relation         TEXT NOT NULL,
    scope            TEXT NOT NULL,
    evidence_refs    TEXT NOT NULL DEFAULT '[]',
    effective_period TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'VERIFIED',
    note             TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    claim_version_id TEXT PRIMARY KEY,
    claim_key        TEXT NOT NULL,
    kind             TEXT NOT NULL,
    template         TEXT NOT NULL,
    slots            TEXT NOT NULL DEFAULT '{}',
    reference_ids    TEXT NOT NULL DEFAULT '[]',
    verdict          TEXT NOT NULL,
    section_key      TEXT NOT NULL,
    text             TEXT NOT NULL,
    findings         TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_sec ON claims (section_key);

CREATE TABLE IF NOT EXISTS reports (
    report_id       TEXT PRIMARY KEY,
    entity_id       TEXT NOT NULL,
    head_version_no INTEGER,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_versions (
    report_id         TEXT NOT NULL,
    version_no        INTEGER NOT NULL,
    base_version_id   TEXT,
    input_fingerprint TEXT NOT NULL,
    as_of             TEXT NOT NULL,
    workflow_version  TEXT NOT NULL,
    state             TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    label             TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (report_id, version_no)
);

CREATE TABLE IF NOT EXISTS section_versions (
    section_version_id TEXT NOT NULL,
    section_key        TEXT NOT NULL,
    report_id          TEXT NOT NULL,
    version_no         INTEGER NOT NULL,
    content            TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    claim_ids          TEXT NOT NULL DEFAULT '[]',
    -- 同一份章节内容可以在多个版本里复用：section_version_id 相同，版本行不同
    PRIMARY KEY (report_id, version_no, section_key)
);
CREATE INDEX IF NOT EXISTS idx_sec_ver ON section_versions (report_id, version_no);

CREATE TABLE IF NOT EXISTS version_objects (
    report_id   TEXT NOT NULL,
    version_no  INTEGER NOT NULL,
    object_type TEXT NOT NULL,
    object_id   TEXT NOT NULL,
    PRIMARY KEY (report_id, version_no, object_type, object_id)
);

CREATE TABLE IF NOT EXISTS dependencies (
    snapshot_id     TEXT NOT NULL,
    source_key      TEXT NOT NULL,
    dependent_key   TEXT NOT NULL,
    dependency_type TEXT NOT NULL DEFAULT 'value'
);
CREATE INDEX IF NOT EXISTS idx_dep_src ON dependencies (snapshot_id, source_key);
CREATE INDEX IF NOT EXISTS idx_dep_dst ON dependencies (snapshot_id, dependent_key);

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    job_kind        TEXT NOT NULL,
    report_id       TEXT,
    status          TEXT NOT NULL,
    idempotency_key TEXT,
    budget          TEXT NOT NULL DEFAULT '{}',
    payload         TEXT NOT NULL DEFAULT '{}',
    result          TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    heartbeat_at    TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_run_idem ON runs (idempotency_key);

CREATE TABLE IF NOT EXISTS run_events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    event      TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS questions (
    question_id      TEXT PRIMARY KEY,
    report_id        TEXT NOT NULL,
    version_no       INTEGER NOT NULL,
    question         TEXT NOT NULL,
    answer           TEXT NOT NULL,
    refs             TEXT NOT NULL DEFAULT '[]',
    intent           TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_findings (
    finding_id       TEXT PRIMARY KEY,
    claim_version_id TEXT NOT NULL,
    code             TEXT NOT NULL,
    severity         TEXT NOT NULL,
    detail           TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
