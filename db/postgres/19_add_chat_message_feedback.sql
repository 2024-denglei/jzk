-- 用户对已完成 AI 回复的当前反馈；不修改不可变消息本体。

CREATE TABLE IF NOT EXISTS app.chat_message_feedback (
    message_id  UUID PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    chat_id     BIGINT NOT NULL,
    branch_id   UUID NOT NULL,
    rating      TEXT NOT NULL CHECK (rating IN ('like', 'dislike')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_message_feedback_chat_user_fk
      FOREIGN KEY (chat_id, user_id) REFERENCES app.chats(id, user_id) ON DELETE CASCADE,
    CONSTRAINT chat_message_feedback_branch_fk
      FOREIGN KEY (chat_id, branch_id) REFERENCES app.chat_branches(chat_id, id) ON DELETE CASCADE,
    CONSTRAINT chat_message_feedback_message_fk
      FOREIGN KEY (chat_id, message_id) REFERENCES app.chat_messages(chat_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_message_feedback_admin
    ON app.chat_message_feedback (rating, updated_at DESC, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_message_feedback_user
    ON app.chat_message_feedback (user_id, updated_at DESC, message_id DESC);
CREATE INDEX IF NOT EXISTS idx_chat_message_feedback_location
    ON app.chat_message_feedback (chat_id, branch_id, message_id);

CREATE OR REPLACE FUNCTION app.validate_chat_message_feedback()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  branch_head UUID;
BEGIN
  IF TG_OP = 'UPDATE' AND (
      NEW.message_id IS DISTINCT FROM OLD.message_id
      OR NEW.user_id IS DISTINCT FROM OLD.user_id
      OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
  ) THEN
    RAISE EXCEPTION 'message feedback identity is immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT branch.head_message_id INTO branch_head
  FROM app.chat_branches branch
  JOIN app.chats chat ON chat.id = branch.chat_id
  JOIN app.chat_messages message
    ON message.chat_id = chat.id AND message.id = NEW.message_id
  WHERE chat.id = NEW.chat_id
    AND chat.user_id = NEW.user_id
    AND branch.chat_id = NEW.chat_id
    AND branch.id = NEW.branch_id
    AND message.role = 'assistant'
    AND message.status = 'completed';

  IF branch_head IS NULL THEN
    RAISE EXCEPTION 'feedback target must be a completed assistant message'
      USING ERRCODE = 'check_violation';
  END IF;

  IF NOT EXISTS (
    WITH RECURSIVE path AS (
      SELECT message.id, message.parent_message_id
      FROM app.chat_messages message
      WHERE message.chat_id = NEW.chat_id AND message.id = branch_head
      UNION ALL
      SELECT parent.id, parent.parent_message_id
      FROM app.chat_messages parent
      JOIN path child ON child.parent_message_id = parent.id
      WHERE parent.chat_id = NEW.chat_id
    )
    SELECT 1 FROM path WHERE id = NEW.message_id
  ) THEN
    RAISE EXCEPTION 'feedback target is not on the selected branch path'
      USING ERRCODE = 'check_violation';
  END IF;

  NEW.updated_at := now();
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_validate_chat_message_feedback
  ON app.chat_message_feedback;
CREATE TRIGGER trg_validate_chat_message_feedback
BEFORE INSERT OR UPDATE ON app.chat_message_feedback
FOR EACH ROW EXECUTE FUNCTION app.validate_chat_message_feedback();

GRANT SELECT, INSERT, UPDATE, DELETE ON app.chat_message_feedback TO jzk_app;
GRANT SELECT ON app.chat_message_feedback TO jzk_admin_api, jzk_readonly;

COMMENT ON TABLE app.chat_message_feedback IS
  '用户对不可变 AI 回复的当前喜欢/不喜欢反馈；一条消息最多一条当前记录';
