-- 修正早期开发迁移的分支形状约束，并在数据库层保护不可变消息。

ALTER TABLE app.chat_branches
  DROP CONSTRAINT IF EXISTS chat_branches_check;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_generation_user_request
  ON app.ai_generation_runs (user_id, client_request_id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chat_branches_fork_shape_check'
      AND conrelid = 'app.chat_branches'::regclass
  ) THEN
    ALTER TABLE app.chat_branches
      ADD CONSTRAINT chat_branches_fork_shape_check CHECK (
        (fork_reason = 'root' AND parent_branch_id IS NULL
                              AND forked_from_message_id IS NULL
                              AND derived_from_message_id IS NULL)
        OR
        (fork_reason <> 'root' AND parent_branch_id IS NOT NULL
                               AND (
                                 forked_from_message_id IS NOT NULL
                                 OR fork_reason = 'edit_resend'
                               ))
      );
  END IF;
END $$;

CREATE OR REPLACE FUNCTION app.protect_chat_message_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    -- 只允许由整会话/整用户级联触发删除，禁止单独删除树节点。
    IF EXISTS (SELECT 1 FROM app.chats WHERE id = OLD.chat_id) THEN
      RAISE EXCEPTION 'chat messages can only be deleted with their chat'
        USING ERRCODE = 'check_violation';
    END IF;
    RETURN OLD;
  END IF;

  IF NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.created_in_branch_id IS DISTINCT FROM OLD.created_in_branch_id
     OR NEW.parent_message_id IS DISTINCT FROM OLD.parent_message_id
     OR NEW.derived_from_message_id IS DISTINCT FROM OLD.derived_from_message_id
     OR NEW.role IS DISTINCT FROM OLD.role
     OR NEW.depth IS DISTINCT FROM OLD.depth
     OR NEW.client_request_id IS DISTINCT FROM OLD.client_request_id THEN
    RAISE EXCEPTION 'chat message tree identity is immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  IF OLD.status IN ('completed', 'stopped', 'failed') AND ROW(
       NEW.status, NEW.content, NEW.content_format, NEW.state_schema_version,
       NEW.state_after_json, NEW.state_recoverable, NEW.match_run_id, NEW.completed_at
     ) IS DISTINCT FROM ROW(
       OLD.status, OLD.content, OLD.content_format, OLD.state_schema_version,
       OLD.state_after_json, OLD.state_recoverable, OLD.match_run_id, OLD.completed_at
     ) THEN
    RAISE EXCEPTION 'terminal chat messages are immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_protect_chat_message_immutability ON app.chat_messages;
CREATE TRIGGER trg_protect_chat_message_immutability
BEFORE UPDATE OR DELETE ON app.chat_messages
FOR EACH ROW EXECUTE FUNCTION app.protect_chat_message_immutability();
