-- 消息只能关联同一用户、已完整构建的匹配快照。

CREATE OR REPLACE FUNCTION app.validate_chat_message_match_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  snapshot_owner BIGINT;
  snapshot_status TEXT;
  chat_owner BIGINT;
BEGIN
  IF NEW.match_run_id IS NULL THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.match_run_id IS NOT DISTINCT FROM OLD.match_run_id THEN
    RETURN NEW;
  END IF;

  SELECT user_id, status
  INTO snapshot_owner, snapshot_status
  FROM app.match_runs
  WHERE id = NEW.match_run_id;

  SELECT user_id INTO chat_owner
  FROM app.chats
  WHERE id = NEW.chat_id;

  IF snapshot_owner IS NULL OR chat_owner IS NULL
     OR snapshot_owner <> chat_owner OR snapshot_status <> 'ready' THEN
    RAISE EXCEPTION 'chat message requires a ready match snapshot owned by the same user'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_validate_chat_message_match_snapshot ON app.chat_messages;
CREATE TRIGGER trg_validate_chat_message_match_snapshot
BEFORE INSERT OR UPDATE OF match_run_id ON app.chat_messages
FOR EACH ROW EXECUTE FUNCTION app.validate_chat_message_match_snapshot();
