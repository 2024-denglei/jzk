-- 管理员账号新增、停用与恢复审计。
CREATE TABLE IF NOT EXISTS admin.admin_account_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    target_admin_id BIGINT REFERENCES admin.admin_users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL CHECK (action IN ('create', 'disable', 'restore')),
    operator_id     BIGINT REFERENCES admin.admin_users(id),
    reason          TEXT,
    before_data     JSONB,
    after_data      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_admin_account_audit_target
    ON admin.admin_account_audit_logs (target_admin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_account_audit_operator
    ON admin.admin_account_audit_logs (operator_id, created_at DESC);

