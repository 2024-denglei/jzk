# 分支化对话 V2 运行手册

分支会话已经完成全量切换和旧结构清理。PostgreSQL 是消息、状态、完整排名快照、生成任务和
Trace 的唯一长期权威来源；Redis 只保存生成实时事件以及验证码、限流等短期数据。

## 1. 必需配置

```dotenv
CHAT_STORAGE_V2_READ_ENABLED=1
CHAT_STORAGE_V2_WRITE_ENABLED=1
CHAT_STORAGE_V2_WRITE_PERCENT=100
CHAT_STORAGE_V2_WRITE_USER_IDS=
CHAT_GENERATION_WORKER_ENABLED=1
CHAT_GENERATION_WORKER_USER_IDS=
CHAT_OUTBOX_WORKER_ENABLED=1
```

Web、Generation Worker 和 Outbox Worker 应使用同一版本代码。分别启动：

```bash
python scripts/run_generation_worker.py
python scripts/run_outbox_worker.py
```

## 2. 发布门禁

每次发布前运行：

```bash
python scripts/check_chat_v2_rollout.py \
  --strict \
  --require-v1-zero \
  --require-redis \
  --max-expired-leases 0 \
  --max-outbox-backlog 100 \
  --max-oldest-outbox-seconds 300
```

门禁必须满足：无 V1 会话、过期租约、耗尽任务、孤立 generating 消息、陈旧 building 快照、
不完整 ready 快照或耗尽 Outbox 事件。Redis 不可用不会损坏长期数据，但会影响实时重连。

## 3. 发布与回滚

- 数据库迁移按 `db/postgres/01` 到 `16` 的顺序执行；`16_drop_legacy_chat_storage.sql`
  只允许在 V1=0 且完整快照校验通过时执行。
- 若新写入异常，先设置 `CHAT_STORAGE_V2_WRITE_ENABLED=0`，阻止新 Turn。
- 保持读取、Generation Worker 和 Outbox Worker 开启，让已排队任务完成，并允许停止任务或
  永久删除会话。
- 最终结构已删除 V1 JSON 列，不能回滚到旧 `/api/chat*` 或 `/api/user/chats*` 实现；回滚版本
  必须理解 V2 消息树。

## 4. 日常监控

持续观察 queued 数量和最老排队秒数、失败/重试、过期租约、Outbox backlog、陈旧 building
快照、不完整 ready 快照及孤立 generating 消息。管理端 Trace 仅查询
`app.ai_generation_steps`，不要创建或恢复本地 JSON Trace 目录。
