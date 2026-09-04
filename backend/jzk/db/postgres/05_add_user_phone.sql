-- 为已有数据库增加手机号登录能力；历史账号允许暂时没有手机号。
ALTER TABLE app.users ADD COLUMN IF NOT EXISTS phone TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone_unique
    ON app.users (phone)
    WHERE phone IS NOT NULL;
