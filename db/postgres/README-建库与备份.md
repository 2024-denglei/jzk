# 建库与备份说明（政务交付）

## 1. 目标

交付一套 **PostgreSQL** 官方库 `jzk`，并使用 Redis 保存短期手机验证码。PostgreSQL 按 schema 分域：

| Schema | 用途 |
|--------|------|
| `donor` | 捐精人主数据、导入批次、操作审计 |
| `admin` | 管理端账号 |
| `app` | 前台用户、收藏、历史、偏好、对话 |

运行时权威数据源为数据库；Excel 仅作批量导入交换格式。

## 2. 本地/演示（Docker）

```bash
cd agent/db/postgres
docker compose up -d
```

默认连接（开发）：

```
DATABASE_URL=postgresql://postgres:jzk_dev_change_me@127.0.0.1:5432/jzk
REDIS_URL=redis://127.0.0.1:6379/0
```

应用角色（可选拆分）：

```
DATABASE_URL=postgresql://jzk_app:jzk_app_dev@127.0.0.1:5432/jzk
DATABASE_ADMIN_URL=postgresql://jzk_admin_api:jzk_admin_dev@127.0.0.1:5432/jzk
```

首次启动应用会自动确保 schema 和已有数据库的手机号迁移可用，并在无管理员时创建默认 `super_admin`（用户名/密码见环境变量 `ADMIN_BOOTSTRAP_*`）。测试阶段设置 `EXPOSE_TEST_VERIFICATION_CODE=1`，验证码会直接返回客户端；接入真实短信后应关闭。

## 3. 政务侧新建库步骤

1. 安装 PostgreSQL 14+（推荐 16）。
2. 以超级用户执行：

```sql
CREATE DATABASE jzk
  WITH ENCODING 'UTF8'
       LC_COLLATE='zh_CN.UTF-8'
       LC_CTYPE='zh_CN.UTF-8'
       TEMPLATE template0;
```

（若操作系统无中文 locale，可用 `en_US.UTF-8` 或默认 locale。）

3. 连接到 `jzk`，依次执行：

- `01_init_db.sql`
- `02_schema.sql`
- 修改 `03_roles.sql` 中的默认密码后执行（或手工 `CREATE ROLE ... PASSWORD`）
- 已有数据库升级时执行 `05_add_user_phone.sql`

4. 将连接串交给应用（建议应用使用 `jzk_app` / 管理端使用 `jzk_admin_api`；`jzk_migrator` 仅部署窗口启用）。

5. 启动应用后使用管理端修改默认管理员密码。

## 4. 角色职责

| 角色 | 用途 |
|------|------|
| `jzk_migrator` | 建表/迁移；平时禁用 LOGIN |
| `jzk_app` | 前台 API：读写 `app`，只读 `donor` |
| `jzk_admin_api` | 管理 API：读写 `donor`/`admin`，读 `app` |
| `jzk_readonly` | 巡检与报表只读 |

## 5. 备份与恢复要点

每日逻辑备份示例：

```bash
pg_dump -Fc -d jzk -f "jzk_$(date +%Y%m%d).dump"
```

恢复：

```bash
pg_restore -d jzk --clean --if-exists jzk_YYYYMMDD.dump
```

建议：

- 保留至少 30 日备份，异地各一份
- 定期做恢复演练
- 生产关闭超级用户远程登录，应用仅使用最小权限角色

## 6. 从旧 SQLite 迁移

见 `agent/scripts/migrate_sqlite_to_pg.py`：将历史 `data/app.db` 用户侧数据导入 `app` schema。捐精人请用管理端「导入」或按《文本信息》模板 Excel 入库。
