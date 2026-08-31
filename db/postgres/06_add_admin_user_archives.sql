-- 用户档案、账号状态和强制下线能力。
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ;
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS disabled_reason TEXT;
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'users_status_check' AND conrelid = 'app.users'::regclass
  ) THEN
    ALTER TABLE app.users
      ADD CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_status ON app.users (status);
CREATE INDEX IF NOT EXISTS idx_users_created ON app.users (created_at DESC);

ALTER TABLE app.chats ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- 只有历史数据不存在重复会话时才加唯一索引，不在自动迁移中删除用户数据。
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'app' AND indexname = 'idx_chats_user_session'
  ) AND NOT EXISTS (
    SELECT 1 FROM app.chats GROUP BY user_id, session_id HAVING COUNT(*) > 1
  ) THEN
    CREATE UNIQUE INDEX idx_chats_user_session ON app.chats (user_id, session_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS admin.user_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT REFERENCES app.users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    operator_id     BIGINT REFERENCES admin.admin_users(id),
    reason          TEXT,
    before_data     JSONB,
    after_data      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_audit_user
    ON admin.user_audit_logs (user_id, created_at DESC);
