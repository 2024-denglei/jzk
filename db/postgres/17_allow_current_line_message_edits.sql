-- 编辑重发只重写当前显式分支；允许事务安全清理已不可达的旧线路。

CREATE OR REPLACE FUNCTION app.protect_chat_message_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('app.allow_message_prune', true) = 'on' THEN
      RETURN OLD;
    END IF;
    -- 整会话/整用户级联仍可删除；普通请求不得直接删树节点。
    IF EXISTS (SELECT 1 FROM app.chats WHERE id = OLD.chat_id) THEN
      RAISE EXCEPTION 'chat messages can only be deleted with their chat or current branch edit'
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

COMMENT ON TABLE app.chat_messages IS
  '消息路径节点；终态不可改，编辑当前线路时原子切换分支头并清理不可达节点';
