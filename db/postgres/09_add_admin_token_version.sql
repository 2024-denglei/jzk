-- 管理员会话版本，用于改密、停用和强制撤销旧凭证。
ALTER TABLE admin.admin_users
    ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
