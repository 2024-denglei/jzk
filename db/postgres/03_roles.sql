-- 角色与授权（开发环境密码来自 Docker 环境变量；生产请改密后执行）
-- 注意：\getenv 仅在 psql 可用；Docker init 用 DO 块读 current_setting

DO $$
DECLARE
  app_pw TEXT := COALESCE(NULLIF(current_setting('jzk.app_password', true), ''), 'jzk_app_dev');
  admin_pw TEXT := COALESCE(NULLIF(current_setting('jzk.admin_password', true), ''), 'jzk_admin_dev');
  ro_pw TEXT := COALESCE(NULLIF(current_setting('jzk.readonly_password', true), ''), 'jzk_ro_dev');
  mig_pw TEXT := COALESCE(NULLIF(current_setting('jzk.migrator_password', true), ''), 'jzk_migrator_dev');
BEGIN
  -- Docker 入口会注入环境变量到进程，但 PG 会话无自动映射；开发默认密码见下方。
  -- 若已存在角色则只确保权限。
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jzk_migrator') THEN
    EXECUTE format('CREATE ROLE jzk_migrator LOGIN PASSWORD %L', mig_pw);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jzk_app') THEN
    EXECUTE format('CREATE ROLE jzk_app LOGIN PASSWORD %L', app_pw);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jzk_admin_api') THEN
    EXECUTE format('CREATE ROLE jzk_admin_api LOGIN PASSWORD %L', admin_pw);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jzk_readonly') THEN
    EXECUTE format('CREATE ROLE jzk_readonly LOGIN PASSWORD %L', ro_pw);
  END IF;
END $$;

-- 开发简化：单一应用连接常用 jzk_app，并授予较宽权限（生产可拆分 app/admin URL）
GRANT CONNECT ON DATABASE jzk TO jzk_app, jzk_admin_api, jzk_readonly, jzk_migrator;

GRANT USAGE ON SCHEMA donor, admin, app TO jzk_app, jzk_admin_api, jzk_readonly, jzk_migrator;

-- migrator：全表 DDL（部署后应禁用登录）
GRANT ALL ON SCHEMA donor, admin, app TO jzk_migrator;
GRANT ALL ON ALL TABLES IN SCHEMA donor, admin, app TO jzk_migrator;
GRANT ALL ON ALL SEQUENCES IN SCHEMA donor, admin, app TO jzk_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor, admin, app GRANT ALL ON TABLES TO jzk_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor, admin, app GRANT ALL ON SEQUENCES TO jzk_migrator;

-- app：读写 app；只读 donor；不碰 admin 写
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO jzk_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA app TO jzk_app;
GRANT SELECT ON ALL TABLES IN SCHEMA donor TO jzk_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jzk_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO jzk_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor GRANT SELECT ON TABLES TO jzk_app;

-- admin_api：donor 读写 + 审计；admin 读写；app 只读
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA donor TO jzk_admin_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA donor TO jzk_admin_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA admin TO jzk_admin_api;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA admin TO jzk_admin_api;
GRANT SELECT ON ALL TABLES IN SCHEMA app TO jzk_admin_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jzk_admin_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor GRANT USAGE, SELECT ON SEQUENCES TO jzk_admin_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA admin GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO jzk_admin_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA admin GRANT USAGE, SELECT ON SEQUENCES TO jzk_admin_api;

-- readonly
GRANT SELECT ON ALL TABLES IN SCHEMA donor, admin, app TO jzk_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA donor, admin, app GRANT SELECT ON TABLES TO jzk_readonly;

-- 开发便利：postgres 超级用户建的表默认属主是 postgres，上面对 ALL TABLES 的 GRANT 在 init 时已覆盖。
-- 应用开发可用 postgres 连接串，或使用：
--   postgresql://jzk_app:jzk_app_dev@localhost:5432/jzk
