-- 003_dataset_tag.sql —— 评测数据集隔离
--
-- 真实公开数据（巨潮年报 + 东方财富结构化）与合成回归语料必须可区分：
--   real_cninfo         真实公开年报与派生事实
--   synthetic_regression 仅用于抽取器回归的合成 PDF
-- 跨源互证只读真实语料；模板回归、冲突注入、增量隔离只读合成语料。
-- 两套赛道应使用独立 DATA_DIR，同一库混装时由 seed 入口直接拒绝。

ALTER TABLE documents ADD COLUMN dataset_tag TEXT NOT NULL DEFAULT 'real_cninfo';

CREATE INDEX IF NOT EXISTS idx_doc_dataset ON documents (dataset_tag, source_type);
