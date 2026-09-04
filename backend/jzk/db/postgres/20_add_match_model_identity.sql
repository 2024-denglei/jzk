ALTER TABLE app.match_runs
    ADD COLUMN IF NOT EXISTS model_checkpoint_sha256 TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN app.match_runs.model_checkpoint_sha256 IS
    '评分服务实际加载 checkpoint 的 SHA-256；旧快照为空字符串';
