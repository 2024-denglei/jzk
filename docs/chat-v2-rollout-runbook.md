# 分支化对话 V2 灰度发布手册

本文只描述兼容版本之后的发布操作。旧 JSON 字段和 MatchRun 数组在阶段 10 前不得删除；
本地 JSON Trace 不读取、不迁移，新 Trace 只写 PostgreSQL GenerationStep。

## 1. 先发布兼容版本

Web 首次发布建议：

```dotenv
CHAT_STORAGE_V2_READ_ENABLED=1
CHAT_STORAGE_V2_WRITE_ENABLED=0
CHAT_GENERATION_WORKER_ENABLED=0
CHAT_OUTBOX_WORKER_ENABLED=1
```

此状态下 V1 会话通过统一 V2 DTO 只读展示，V2 会话照常读取、停止和永久删除，但不能创建新
Turn。不要回滚到完全不识别 `storage_version=2` 的旧二进制。

启动 Outbox Worker：

```bash
python scripts/run_outbox_worker.py
```

## 2. 迁移前检查

```bash
python scripts/migrate_chat_storage_v2.py --dry-run --batch-size 100
python scripts/migrate_chat_storage_v2.py --batch-size 100
python scripts/migrate_chat_storage_v2.py --verify-only --batch-size 100
```

迁移脚本使用 `DATABASE_MIGRATOR_URL`，逐 Chat 提交，支持 `--resume-after`、`--user-id` 和
`--chat-id`。保存输出 JSON；任何 `failed` 都必须先处理。`partial` 必须能由 warnings 解释。

## 3. 内部用户灰度

先只允许明确用户，并让 Worker 使用相同范围：

```dotenv
CHAT_STORAGE_V2_WRITE_ENABLED=1
CHAT_STORAGE_V2_WRITE_PERCENT=0
CHAT_STORAGE_V2_WRITE_USER_IDS=101,205
CHAT_GENERATION_WORKER_ENABLED=1
CHAT_GENERATION_WORKER_USER_IDS=101,205
```

`CHAT_STORAGE_V2_ROLLOUT_SALT` 上线后保持不变，避免百分比分桶重排。内部阶段需同时限制新版
前端的可见用户；范围外用户会收到稳定错误 `CHAT_STORAGE_V2_WRITE_NOT_IN_ROLLOUT`。

## 4. 扩大比例

内部验证通过后，先清空 `CHAT_GENERATION_WORKER_USER_IDS`，让 Worker 能处理所有已获准写入
用户的任务，再依次将写比例改为 `5 → 25 → 50 → 100`。每一级至少检查：

```bash
python scripts/check_chat_v2_rollout.py \
  --require-redis \
  --max-expired-leases 0 \
  --max-outbox-backlog 100 \
  --max-oldest-outbox-seconds 300
```

同时观察 queued 数量和最老排队秒数、失败/重试、过期租约、Outbox、陈旧 building 快照、
不完整 ready 快照及孤立 generating 消息。

## 5. 全量切换门禁

完成旧会话迁移和抽样人工核对后运行：

```bash
python scripts/migrate_chat_storage_v2.py --verify-only --batch-size 100
python scripts/check_chat_v2_rollout.py --strict --require-v1-zero --require-redis
```

严格门禁通过、V1 写流量为 0 且稳定观察期完成之前，不执行阶段 10 清理。

## 6. 回滚

异常时先设置 `CHAT_STORAGE_V2_WRITE_ENABLED=0`，阻止新 Turn；保持 read、Generation Worker
和 Outbox Worker 开启，让已排队任务完成，并允许用户停止或永久删除已有会话。运行状态检查和
`migrate_chat_storage_v2.py --verify-only` 定位问题。回滚目标只能是本兼容版本，不能回写旧
JSON 覆盖 V2 树。
