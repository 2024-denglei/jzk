-- 持久生成任务状态机：身份字段不可变，终态不可重新打开。

CREATE OR REPLACE FUNCTION app.protect_generation_run_state()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.chat_id IS DISTINCT FROM OLD.chat_id
     OR NEW.branch_id IS DISTINCT FROM OLD.branch_id
     OR NEW.user_message_id IS DISTINCT FROM OLD.user_message_id
     OR NEW.assistant_message_id IS DISTINCT FROM OLD.assistant_message_id
     OR NEW.client_request_id IS DISTINCT FROM OLD.client_request_id THEN
    RAISE EXCEPTION 'generation run identity is immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'queued' AND NEW.status IN ('running', 'stopped', 'failed'))
       OR
       (OLD.status = 'running' AND NEW.status IN ('queued', 'completed', 'stopped', 'failed'))
     ) THEN
    RAISE EXCEPTION 'invalid generation status transition: % -> %', OLD.status, NEW.status
      USING ERRCODE = 'check_violation';
  END IF;

  IF OLD.status IN ('completed', 'stopped', 'failed') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'terminal generation runs are immutable'
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_protect_generation_run_state ON app.ai_generation_runs;
CREATE TRIGGER trg_protect_generation_run_state
BEFORE UPDATE ON app.ai_generation_runs
FOR EACH ROW EXECUTE FUNCTION app.protect_generation_run_state();
