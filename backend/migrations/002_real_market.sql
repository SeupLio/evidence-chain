-- 002_real_market.sql —— 接入公开真实数据（多行业、多年份、跨源）
--
-- 设计要点：
--   1) 结构化第三方数据单独成表，不和「从 PDF 抽出来的事实」混放；
--      两边的差异本身就是评测对象（跨源互证），混表会掩盖来源。
--   2) 每条都留 source_url + fetched_at，报告里可以点回原始接口。
--   3) entities 增加 tag（行业定位标签）与 market（交易所），用于多行业选择器。

ALTER TABLE entities ADD COLUMN tag TEXT NOT NULL DEFAULT '';
ALTER TABLE entities ADD COLUMN market TEXT NOT NULL DEFAULT 'A';

CREATE TABLE IF NOT EXISTS market_facts (
    market_fact_id TEXT PRIMARY KEY,
    entity_id      TEXT NOT NULL,
    field_code     TEXT NOT NULL,
    fiscal_year    INTEGER NOT NULL,
    period_end     TEXT NOT NULL,
    consolidation  TEXT NOT NULL DEFAULT 'consolidated',
    currency       TEXT NOT NULL DEFAULT 'CNY',
    value_text     TEXT NOT NULL,
    unit           TEXT NOT NULL DEFAULT 'cny',
    source         TEXT NOT NULL,
    source_field   TEXT NOT NULL,
    source_url     TEXT NOT NULL DEFAULT '',
    report_type    TEXT NOT NULL DEFAULT '年报',
    notice_date    TEXT,
    fetched_at     TEXT NOT NULL,
    raw            TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_fact
    ON market_facts (entity_id, field_code, fiscal_year, source);
CREATE INDEX IF NOT EXISTS idx_market_entity ON market_facts (entity_id, fiscal_year);

-- 产业链知识：节点与边来自 config/chains/*.yaml，落库只为统一查询与版本化
CREATE TABLE IF NOT EXISTS chain_nodes (
    node_id     TEXT PRIMARY KEY,
    industry_id TEXT NOT NULL,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    entity_id   TEXT,
    ticker      TEXT,
    degree      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chain_edges (
    edge_id     TEXT PRIMARY KEY,
    industry_id TEXT NOT NULL,
    src         TEXT NOT NULL,
    dst         TEXT NOT NULL,
    relation    TEXT NOT NULL,
    basis       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chain_ind ON chain_nodes (industry_id);
