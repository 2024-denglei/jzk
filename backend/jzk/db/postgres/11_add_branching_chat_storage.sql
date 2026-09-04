-- 分支化长期对话 V2：只增不删，旧 chats JSON 字段继续保留供灰度回滚。

ALTER TABLE app.chats ADD COLUMN IF NOT EXISTS active_branch_id UUID;
ALTER TABLE app.chats ADD COLUMN IF NOT EXISTS branch_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app.chats ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app.chats ADD COLUMN IF NOT EXISTS storage_version SMALLINT NOT NULL DEFAULT 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_id_user ON app.chats (id, user_id);
CREATE INDEX IF NOT EXISTS idx_chats_user_updated_id
    ON app.chats (user_id, updated_at DESC, id DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chats_branch_count_check' AND conrelid = 'app.chats'::regclass
  ) THEN
    ALTER TABLE app.chats
      ADD CONSTRAINT chats_branch_count_check CHECK (branch_count >= 0);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chats_message_count_check' AND conrelid = 'app.chats'::regclass
  ) THEN
    ALTER TABLE app.chats
      ADD CONSTRAINT chats_message_count_check CHECK (message_count >= 0);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chats_storage_version_check' AND conrelid = 'app.chats'::regclass
  ) THEN
    ALTER TABLE app.chats
      ADD CONSTRAINT chats_storage_version_check CHECK (storage_version IN (1, 2));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS app.chat_branches (
    id                       UUID PRIMARY KEY,
    chat_id                  BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE,
    parent_branch_id         UUID,
    forked_from_message_id   UUID,
    derived_from_message_id  UUID,
    name                     TEXT NOT NULL,
    system_name              TEXT NOT NULL,
    fork_reason              TEXT NOT NULL,
    head_message_id          UUID,
    version                  INTEGER NOT NULL DEFAULT 0,
    is_archived              BOOLEAN NOT NULL DEFAULT FALSE,
    created_by               TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_id, id),
    CHECK (version >= 0),
    CHECK (length(btrim(name)) > 0),
    CHECK (length(btrim(system_name)) > 0),
    CHECK (fork_reason IN ('root', 'rewind_continue', 'edit_resend', 'regenerate', 'concurrent_send')),
    CHECK (created_by IN ('user', 'system')),
    CHECK (
      (fork_reason = 'root' AND parent_branch_id IS NULL
                            AND forked_from_message_id IS NULL
                            AND derived_from_message_id IS NULL)
      OR
      (fork_reason <> 'root' AND parent_branch_id IS NOT NULL
                             AND forked_from_message_id IS NOT NULL)
    ),
    CHECK (
      (fork_reason IN ('edit_resend', 'regenerate') AND derived_from_message_id IS NOT NULL)
      OR
      (fork_reason NOT IN ('edit_resend', 'regenerate') AND derived_from_message_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_chat_branches_chat_created
    ON app.chat_branches (chat_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_chat_branches_parent
    ON app.chat_branches (chat_id, parent_branch_id);

CREATE TABLE IF NOT EXISTS app.chat_messages (
    id                       UUID PRIMARY KEY,
    chat_id                  BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE,
    created_in_branch_id     UUID NOT NULL,
    parent_message_id        UUID,
    derived_from_message_id  UUID,
    role                     TEXT NOT NULL,
    status                   TEXT NOT NULL,
    content                  TEXT NOT NULL DEFAULT '',
    content_format           TEXT NOT NULL DEFAULT 'markdown',
    state_schema_version     SMALLINT NOT NULL DEFAULT 1,
    state_after_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    state_recoverable        BOOLEAN NOT NULL DEFAULT TRUE,
    match_run_id             UUID,
    depth                    INTEGER NOT NULL,
    client_request_id        UUID,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at             TIMESTAMPTZ,
    UNIQUE (chat_id, id),
    CHECK (role IN ('user', 'assistant', 'system')),
    CHECK (status IN ('generating', 'completed', 'stopped', 'failed')),
    CHECK (content_format = 'markdown'),
    CHECK (state_schema_version >= 1),
    CHECK (depth >= 0),
    CHECK ((role = 'assistant') OR status = 'completed'),
    CHECK (jsonb_typeof(state_after_json) = 'object'),
    CHECK (match_run_id IS NULL OR (role = 'assistant' AND status = 'completed')),
    CHECK (
      (status = 'generating' AND completed_at IS NULL)
      OR
      (status <> 'generating' AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_parent
    ON app.chat_messages (chat_id, parent_message_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_branch_created
    ON app.chat_messages (created_in_branch_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_match_run
    ON app.chat_messages (match_run_id) WHERE match_run_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_request
    ON app.chat_messages (chat_id, client_request_id) WHERE client_request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_match_run
    ON app.chat_messages (match_run_id) WHERE match_run_id IS NOT NULL;

-- 循环关系全部可延迟检查：Chat、Branch、Message 可在同一事务中创建或整体删除。
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_branches_parent_fk'
  ) THEN
    ALTER TABLE app.chat_branches
      ADD CONSTRAINT chat_branches_parent_fk
      FOREIGN KEY (chat_id, parent_branch_id)
      REFERENCES app.chat_branches(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_created_branch_fk'
  ) THEN
    ALTER TABLE app.chat_messages
      ADD CONSTRAINT chat_messages_created_branch_fk
      FOREIGN KEY (chat_id, created_in_branch_id)
      REFERENCES app.chat_branches(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_parent_fk'
  ) THEN
    ALTER TABLE app.chat_messages
      ADD CONSTRAINT chat_messages_parent_fk
      FOREIGN KEY (chat_id, parent_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_derived_fk'
  ) THEN
    ALTER TABLE app.chat_messages
      ADD CONSTRAINT chat_messages_derived_fk
      FOREIGN KEY (chat_id, derived_from_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_match_run_fk'
  ) THEN
    ALTER TABLE app.chat_messages
      ADD CONSTRAINT chat_messages_match_run_fk
      FOREIGN KEY (match_run_id)
      REFERENCES app.match_runs(id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_branches_fork_message_fk'
  ) THEN
    ALTER TABLE app.chat_branches
      ADD CONSTRAINT chat_branches_fork_message_fk
      FOREIGN KEY (chat_id, forked_from_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_branches_derived_message_fk'
  ) THEN
    ALTER TABLE app.chat_branches
      ADD CONSTRAINT chat_branches_derived_message_fk
      FOREIGN KEY (chat_id, derived_from_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_branches_head_message_fk'
  ) THEN
    ALTER TABLE app.chat_branches
      ADD CONSTRAINT chat_branches_head_message_fk
      FOREIGN KEY (chat_id, head_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chats_active_branch_fk'
  ) THEN
    ALTER TABLE app.chats
      ADD CONSTRAINT chats_active_branch_fk
      FOREIGN KEY (id, active_branch_id)
      REFERENCES app.chat_branches(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS app.ai_generation_runs (
    id                    UUID PRIMARY KEY,
    user_id               BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    chat_id               BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE,
    branch_id             UUID NOT NULL,
    user_message_id       UUID NOT NULL,
    assistant_message_id  UUID NOT NULL UNIQUE,
    client_request_id     UUID NOT NULL,
    status                TEXT NOT NULL DEFAULT 'queued',
    model                 TEXT,
    prompt_version        TEXT,
    prompt_hash           TEXT,
    cancel_requested_at   TIMESTAMPTZ,
    lease_owner           TEXT,
    lease_expires_at      TIMESTAMPTZ,
    heartbeat_at          TIMESTAMPTZ,
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    error_type            TEXT,
    error_message_safe    TEXT,
    timings_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    queued_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ,
    UNIQUE (chat_id, client_request_id),
    CHECK (status IN ('queued', 'running', 'completed', 'stopped', 'failed')),
    CHECK (attempt_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_generation_active_branch
    ON app.ai_generation_runs (branch_id)
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_ai_generation_claim
    ON app.ai_generation_runs (status, lease_expires_at, queued_at);
CREATE INDEX IF NOT EXISTS idx_ai_generation_chat
    ON app.ai_generation_runs (chat_id, queued_at DESC, id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ai_generation_chat_user_fk'
  ) THEN
    ALTER TABLE app.ai_generation_runs
      ADD CONSTRAINT ai_generation_chat_user_fk
      FOREIGN KEY (chat_id, user_id)
      REFERENCES app.chats(id, user_id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ai_generation_branch_fk'
  ) THEN
    ALTER TABLE app.ai_generation_runs
      ADD CONSTRAINT ai_generation_branch_fk
      FOREIGN KEY (chat_id, branch_id)
      REFERENCES app.chat_branches(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ai_generation_user_message_fk'
  ) THEN
    ALTER TABLE app.ai_generation_runs
      ADD CONSTRAINT ai_generation_user_message_fk
      FOREIGN KEY (chat_id, user_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ai_generation_assistant_message_fk'
  ) THEN
    ALTER TABLE app.ai_generation_runs
      ADD CONSTRAINT ai_generation_assistant_message_fk
      FOREIGN KEY (chat_id, assistant_message_id)
      REFERENCES app.chat_messages(chat_id, id)
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS app.ai_generation_steps (
    id             BIGSERIAL PRIMARY KEY,
    generation_id  UUID NOT NULL REFERENCES app.ai_generation_runs(id) ON DELETE CASCADE,
    step_order     INTEGER NOT NULL,
    step_type      TEXT NOT NULL,
    payload_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    elapsed_ms     REAL,
    UNIQUE (generation_id, step_order),
    CHECK (step_order >= 0),
    CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ai_generation_steps_run
    ON app.ai_generation_steps (generation_id, step_order);

CREATE TABLE IF NOT EXISTS app.chat_deletion_audit (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL,
    chat_id           BIGINT NOT NULL,
    branch_count      INTEGER NOT NULL,
    message_count     INTEGER NOT NULL,
    match_run_count   INTEGER NOT NULL,
    request_id        UUID NOT NULL UNIQUE,
    deleted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (branch_count >= 0),
    CHECK (message_count >= 0),
    CHECK (match_run_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_chat_deletion_audit_user
    ON app.chat_deletion_audit (user_id, deleted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS app.outbox_events (
    id              BIGSERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    aggregate_type  TEXT NOT NULL,
    aggregate_id    TEXT NOT NULL,
    dedupe_key      TEXT NOT NULL UNIQUE,
    payload_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    available_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by       TEXT,
    locked_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    last_error      TEXT,
    CHECK (topic IN ('chat_deleted', 'generation_event_cleanup', 'orphan_match_run_cleanup')),
    CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_claim
    ON app.outbox_events (status, available_at, id)
    WHERE status IN ('pending', 'failed');

GRANT SELECT, INSERT, UPDATE, DELETE ON
    app.chat_branches, app.chat_messages, app.ai_generation_runs,
    app.ai_generation_steps, app.chat_deletion_audit, app.outbox_events
TO jzk_app;
GRANT USAGE, SELECT ON SEQUENCE
    app.ai_generation_steps_id_seq, app.chat_deletion_audit_id_seq,
    app.outbox_events_id_seq
TO jzk_app;
GRANT SELECT ON
    app.chat_branches, app.chat_messages, app.ai_generation_runs,
    app.ai_generation_steps, app.chat_deletion_audit, app.outbox_events
TO jzk_admin_api, jzk_readonly;

COMMENT ON TABLE app.chat_branches IS 'AI 对话分支元数据；消息通过父链共享祖先，不复制正文';
COMMENT ON TABLE app.chat_messages IS '不可变消息树；仅 generating AI 消息允许阶段性更新';
COMMENT ON TABLE app.ai_generation_runs IS '与 Web 连接解耦的持久 AI 生成任务';
COMMENT ON TABLE app.ai_generation_steps IS '数据库权威 Generation Trace 步骤，不复制完整消息正文';
