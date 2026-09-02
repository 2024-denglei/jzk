# Docker 一键启动

## 启动

1. 首次使用时准备配置：`cp .env.example .env`。
2. 至少修改 `.env` 中的 `LLM_API_KEY`、`JWT_SECRET`、管理员密码和评分服务 token。
3. 在项目根目录运行：

   ```bash
   docker compose up -d --build
   ```

4. 查看状态与日志：

   ```bash
   docker compose ps
   docker compose logs -f app scorer
   ```

浏览器访问 `http://localhost:8010`。停止服务使用 `docker compose down`；该命令保留数据库数据。只有确认要删除全部 PostgreSQL 和 Redis 数据时才使用 `docker compose down -v`。

Compose 使用固定数据卷 `postgres_jzk_pg_data` 和 `postgres_jzk_redis_data`，可直接继承仓库旧版数据库 Compose 创建的数据。

## 可选 Worker

需要持久聊天生成和 Outbox Worker 时运行：

```bash
docker compose --profile workers up -d --build
```

容器内服务通过 `postgres`、`redis` 和 `scorer` 名称互联。Compose 会覆盖 `.env` 中面向宿主机的连接地址，因此无需手工修改 `DATABASE_URL`、`REDIS_URL` 或 `MATCH_SCORER_URL`。
