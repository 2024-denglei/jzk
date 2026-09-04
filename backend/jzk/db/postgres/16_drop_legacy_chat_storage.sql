-- 分支会话 V2 最终清理：仅在全量迁移和完整快照校验通过后删除兼容列。

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'app' AND table_name = 'chats' AND column_name = 'storage_version'
  ) AND EXISTS (SELECT 1 FROM app.chats WHERE storage_version <> 2) THEN
    RAISE EXCEPTION 'cannot drop legacy chat columns while V1 chats remain';
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'app' AND table_name = 'match_runs' AND column_name = 'donor_ids'
  ) AND EXISTS (
    SELECT 1
    FROM app.match_runs run
    LEFT JOIN (
      SELECT match_run_id, COUNT(*) AS item_count, MIN(rank) AS min_rank, MAX(rank) AS max_rank
      FROM app.match_run_items
      GROUP BY match_run_id
    ) items ON items.match_run_id = run.id
    WHERE run.status = 'ready'
      AND (
        COALESCE(items.item_count, 0) <> run.total
        OR (run.total > 0 AND (items.min_rank <> 1 OR items.max_rank <> run.total))
      )
  ) THEN
    RAISE EXCEPTION 'cannot drop legacy match arrays while ready snapshots are incomplete';
  END IF;
END $$;

DROP INDEX IF EXISTS app.idx_chats_user_session;

ALTER TABLE app.chats
  DROP COLUMN IF EXISTS session_id,
  DROP COLUMN IF EXISTS messages_json,
  DROP COLUMN IF EXISTS candidates_json,
  DROP COLUMN IF EXISTS state_json;

ALTER TABLE app.match_runs
  DROP COLUMN IF EXISTS donor_ids,
  DROP COLUMN IF EXISTS scores;

ALTER TABLE app.chats ALTER COLUMN storage_version SET DEFAULT 2;
ALTER TABLE app.chats DROP CONSTRAINT IF EXISTS chats_storage_version_check;
ALTER TABLE app.chats
  ADD CONSTRAINT chats_storage_version_check CHECK (storage_version = 2);

COMMENT ON TABLE app.chats IS
  '分支化长期会话；消息正文和状态仅存 app.chat_messages';
COMMENT ON TABLE app.match_runs IS
  '完整匹配快照元数据；严格排名、资料和解释仅存 app.match_run_items';
