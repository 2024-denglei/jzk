-- 普通管理员操作申请与超级管理员审批。
CREATE TABLE IF NOT EXISTS admin.operation_requests (
    id                  BIGSERIAL PRIMARY KEY,
    requester_id        BIGINT NOT NULL REFERENCES admin.admin_users(id),
    action              TEXT NOT NULL,
    target_type         TEXT NOT NULL CHECK (target_type IN ('donor', 'user')),
    target_id           TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    before_snapshot     JSONB,
    reason              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'approved', 'rejected', 'cancelled', 'failed')),
    reviewer_id         BIGINT REFERENCES admin.admin_users(id),
    review_comment      TEXT,
    reviewed_at         TIMESTAMPTZ,
    executed_at         TIMESTAMPTZ,
    execution_error     TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operation_requests_status
    ON admin.operation_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operation_requests_requester
    ON admin.operation_requests (requester_id, created_at DESC);

