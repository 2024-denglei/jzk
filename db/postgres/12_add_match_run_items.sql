-- 完整历史匹配快照 V2：冻结排名、可展示候选资料和匹配解释。

ALTER TABLE app.match_runs ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE app.match_runs ADD COLUMN IF NOT EXISTS snapshot_schema_version SMALLINT;
ALTER TABLE app.match_runs ADD COLUMN IF NOT EXISTS snapshot_source TEXT;
ALTER TABLE app.match_runs ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ;

-- 现有数组快照必须等待明细回填，不能被 V2 读取误认为完整资料快照。
UPDATE app.match_runs SET status = 'building' WHERE status IS NULL;
UPDATE app.match_runs SET snapshot_schema_version = 1 WHERE snapshot_schema_version IS NULL;
UPDATE app.match_runs SET snapshot_source = 'legacy_backfill' WHERE snapshot_source IS NULL;

ALTER TABLE app.match_runs ALTER COLUMN status SET DEFAULT 'building';
ALTER TABLE app.match_runs ALTER COLUMN status SET NOT NULL;
ALTER TABLE app.match_runs ALTER COLUMN snapshot_schema_version SET DEFAULT 1;
ALTER TABLE app.match_runs ALTER COLUMN snapshot_schema_version SET NOT NULL;
ALTER TABLE app.match_runs ALTER COLUMN snapshot_source SET DEFAULT 'native';
ALTER TABLE app.match_runs ALTER COLUMN snapshot_source SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'match_runs_status_check' AND conrelid = 'app.match_runs'::regclass
  ) THEN
    ALTER TABLE app.match_runs
      ADD CONSTRAINT match_runs_status_check CHECK (status IN ('building', 'ready', 'failed'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'match_runs_snapshot_version_check' AND conrelid = 'app.match_runs'::regclass
  ) THEN
    ALTER TABLE app.match_runs
      ADD CONSTRAINT match_runs_snapshot_version_check CHECK (snapshot_schema_version >= 1);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'match_runs_snapshot_source_check' AND conrelid = 'app.match_runs'::regclass
  ) THEN
    ALTER TABLE app.match_runs
      ADD CONSTRAINT match_runs_snapshot_source_check CHECK (snapshot_source IN ('native', 'legacy_backfill'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS app.match_run_items (
    match_run_id             UUID NOT NULL REFERENCES app.match_runs(id) ON DELETE CASCADE,
    rank                     INTEGER NOT NULL,
    donor_id                 BIGINT NOT NULL,
    score                    REAL NOT NULL,
    donor_code_snapshot      TEXT NOT NULL,
    donor_snapshot_json      JSONB NOT NULL,
    match_explanation_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    snapshot_schema_version  SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (match_run_id, rank),
    UNIQUE (match_run_id, donor_id),
    CHECK (rank > 0),
    CHECK (score NOT IN ('Infinity'::real, '-Infinity'::real) AND score <> 'NaN'::real),
    CHECK (length(btrim(donor_code_snapshot)) > 0),
    CHECK (snapshot_schema_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_match_runs_status_created
    ON app.match_runs (status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_match_run_items_donor
    ON app.match_run_items (match_run_id, donor_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON app.match_run_items TO jzk_app;
GRANT SELECT ON app.match_run_items TO jzk_admin_api, jzk_readonly;

COMMENT ON TABLE app.match_run_items IS
    '完整历史匹配排名明细：冻结当时允许展示的候选资料和解释';
