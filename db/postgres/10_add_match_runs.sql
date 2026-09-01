CREATE TABLE IF NOT EXISTS app.match_runs (
    id               UUID PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    profile_json     JSONB NOT NULL,
    profile_hash     TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    dataset_version  TEXT NOT NULL,
    total            INTEGER NOT NULL CHECK (total >= 0),
    donor_ids        BIGINT[] NOT NULL,
    scores           REAL[] NOT NULL,
    prefer_hits      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (cardinality(donor_ids) = total),
    CHECK (cardinality(scores) = total)
);

CREATE INDEX IF NOT EXISTS idx_match_runs_user_created
    ON app.match_runs (user_id, created_at DESC);

COMMENT ON TABLE app.match_runs IS
    '严格匹配排名快照：数组位置表示排名，不重复保存候选详情';

