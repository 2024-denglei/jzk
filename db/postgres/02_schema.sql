-- 全量表结构（donor / admin / app）

SET search_path TO public;

-- ========== admin ==========
CREATE TABLE IF NOT EXISTS admin.admin_users (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL DEFAULT 'donor_admin'
                    CHECK (role IN ('super_admin', 'donor_admin')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE admin.admin_users IS '管理端账号（与前台用户分离）';

-- ========== donor ==========
CREATE TABLE IF NOT EXISTS donor.donors (
    id                  BIGSERIAL PRIMARY KEY,
    serial_no           BIGINT UNIQUE,
    code                TEXT NOT NULL UNIQUE,

    -- 业务字段（对齐《文本信息》模板）
    abo_blood           TEXT,
    rh_blood            TEXT,
    ethnicity           TEXT,
    hometown            TEXT,
    education           TEXT,
    occupation          TEXT,
    birth_date          DATE,
    constellation       TEXT,
    height_cm           INTEGER,
    weight_kg           NUMERIC(6, 2),
    bmi                 NUMERIC(6, 2),
    figure              TEXT,
    face_shape          TEXT,
    skin_color          TEXT,
    hair_color          TEXT,
    hair_style          TEXT,
    hair_volume         TEXT,
    eyelid              TEXT,
    nose_bridge         TEXT,
    lip_shape           TEXT,
    sideburns           TEXT,
    mustache            TEXT,
    personality         TEXT,
    hobby_sports        TEXT,
    hobby_arts          TEXT,
    hobby_leisure       TEXT,
    hobby_travel        TEXT,
    hobby_reading       TEXT,
    hobby_food          TEXT,
    drink_history       TEXT,
    smoke_history       TEXT,
    personal_disease    TEXT,
    present_illness     TEXT,
    past_illness        TEXT,
    surgery_history     TEXT,
    personal_life_hist  TEXT,
    partners_6m         TEXT,
    std_history         TEXT,
    marital_fertility   TEXT,
    marriage_age        TEXT,
    children_info       TEXT,
    genetic_history     TEXT,
    chromosome_disease  TEXT,
    monogenic_disease   TEXT,
    polygenic_disease   TEXT,
    consanguinity       TEXT,

    -- 系统/运营字段
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'disabled')),
    availability        TEXT DEFAULT '可用',
    specimen_count      INTEGER NOT NULL DEFAULT 0,
    semen_test          TEXT,
    blood_test          TEXT,
    chromosome_test     TEXT,
    microbio_test       TEXT,
    remark              TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES admin.admin_users(id),
    updated_by          BIGINT REFERENCES admin.admin_users(id)
);

CREATE INDEX IF NOT EXISTS idx_donors_status ON donor.donors (status);
CREATE INDEX IF NOT EXISTS idx_donors_availability ON donor.donors (availability);
CREATE INDEX IF NOT EXISTS idx_donors_specimen ON donor.donors (specimen_count DESC);

COMMENT ON TABLE donor.donors IS '捐精人档案主表';

CREATE TABLE IF NOT EXISTS donor.import_batches (
    id              BIGSERIAL PRIMARY KEY,
    filename        TEXT NOT NULL DEFAULT '',
    operator_id     BIGINT REFERENCES admin.admin_users(id),
    success_count   INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    error_summary   JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS donor.audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    donor_id        BIGINT REFERENCES donor.donors(id) ON DELETE SET NULL,
    donor_code      TEXT,
    action          TEXT NOT NULL,
    operator_id     BIGINT REFERENCES admin.admin_users(id),
    before_data     JSONB,
    after_data      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_donor ON donor.audit_logs (donor_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON donor.audit_logs (created_at DESC);

-- ========== app（前台，对齐原 SQLite） ==========
CREATE TABLE IF NOT EXISTS app.users (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    nickname        TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.favorites (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    donor_code      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, donor_code)
);

CREATE TABLE IF NOT EXISTS app.history (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    donor_code      TEXT,
    payload         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.preferences (
    user_id         BIGINT PRIMARY KEY REFERENCES app.users(id) ON DELETE CASCADE,
    filters_json    TEXT NOT NULL DEFAULT '{}',
    priority_json   TEXT NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.chats (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '对话',
    messages_json   TEXT NOT NULL DEFAULT '[]',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    state_json      TEXT NOT NULL DEFAULT '{}',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chats_user ON app.chats (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON app.favorites (user_id);
CREATE INDEX IF NOT EXISTS idx_history_user ON app.history (user_id);
