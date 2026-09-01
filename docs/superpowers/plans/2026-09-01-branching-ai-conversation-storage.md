# 分支化 AI 对话存储、加载与生成任务实施计划

## 文档状态

- 日期：2026-09-01
- 状态：实施中
- 范围：用户端 AI 对话、管理端会话档案、严格匹配快照、生成 Trace、旧数据迁移
- 前置结论：本文中的产品语义、分支行为、快照生命周期、客户端与管理端加载方式已经逐项确认

## 实施状态（2026-09-01）

| 阶段 | 状态 | 说明 |
|---|---|---|
| 阶段 0：契约、基线与灰度开关 | 进行中 | V2 配置、领域枚举、状态契约、TurnCommand 和契约测试已完成；性能基线待记录 |
| 阶段 1：添加数据库结构 | 已完成 | 增量迁移、迁移顺序、真实 PostgreSQL 重复执行、循环外键和级联删除测试已通过 |
| 阶段 2 | 已完成 | 命令仓储、共享查询、签名游标、不可变保护和 100 并发验收已落地 |
| 阶段 3 | 已完成 | 完整冻结排名、消息强关联、共享分页和容量验证已落地 |
| 阶段 4 | 已完成 | 持久 Worker、租约重试、DB Trace、Redis Stream 和无连接完成验收已落地 |
| 阶段 5 | 已完成 | 用户 V2 资源 API、停止/重连事件、元数据修改和不可恢复删除已落地 |
| 阶段 6 | 已完成 | 客户端分支树、路径缓存、任务恢复、消息快照和不可恢复删除已落地 |
| 阶段 7～10 | 待实施 | 按本文顺序继续 |

## 背景

当前长期对话以 `app.chats` 单行中的 `messages_json`、`candidates_json` 和
`state_json` 保存。完整匹配排名另存于 `app.match_runs`，聊天消息只在 JSON 中保存
`match_result_id`，两者没有数据库级关系。管理端详情还会按 `session_id` 扫描本地
JSON Trace 文件。

现有结构存在以下限制：

- 回溯会直接覆盖后续消息，无法保留或展示历史分支。
- 消息、状态和匹配引用埋在 JSON 中，不能建立外键、稳定分页或按消息查询。
- 客户端和服务端每轮重复保存会话，存在重复写入和标题覆盖。
- 恢复会话时只能读取候选预览；管理端不读取完整 `match_runs`。
- `match_runs` 只冻结候选 ID、排名和得分，候选资料变化后不能复现当时页面。
- 管理端列表为计算消息数而读取并解析完整 `messages_json`。
- 本地 Trace 无法在多实例环境中成为可靠权威来源，也难以随会话原子删除。
- AI 生成依赖当前 SSE 请求；刷新或短暂断网会终止生成。

本计划把线性 JSON 会话改造成不可变消息树，并把生成任务、匹配快照和 Trace 都关联到
具体消息。PostgreSQL 是长期权威来源，Redis 只承担运行时 Session 和实时事件流。

## 已确认的产品语义

### 会话与分支

- 一个 `chat` 是长期会话入口，包含一棵分支树。
- 一个 `branch` 表示一条可继续的对话路径；会话保存 `active_branch_id`。
- 打开历史会话默认加载最后一次聊天所在的活跃分支。
- 只查看其他分支不会改变活跃分支；在该分支发送消息后才将它设为活跃分支。
- 从分支中间继续、编辑旧用户消息、重新生成 AI 回复和并发发送都会创建新分支。
- 原消息与原分支永不因回溯、编辑或重新生成而被覆盖。
- 分支可归档，不单独硬删除；整个会话经不可恢复确认后立即硬删除。
- 系统自动生成分支名称，用户可以重命名。

### 回溯、编辑与重新生成

- 从 AI 消息继续：保留该 AI 消息，新用户消息以它为父节点。
- 编辑用户消息：从该用户消息的父节点分叉，创建新用户消息，并记录原消息引用。
- 重新生成 AI 回复：从同一用户消息创建新的 AI 回复分支，并记录原 AI 消息引用。
- 每个分支显式保存分叉原因、分叉位置、来源消息、操作者和时间。
- 检测到客户端提交的父消息已不是分支头时，不覆盖也不报普通冲突；自动从客户端看到的
  旧节点创建 `concurrent_send` 分支。

### 消息与状态

- 历史消息进入终态后不可修改；编辑和重新生成只创建新消息。
- 每条消息保存版本化的 `state_after_json`，确保从任意节点准确恢复 AI 状态。
- AI 消息状态包括 `generating`、`completed`、`stopped` 和 `failed`。
- 停止和失败尝试进入消息树；管理端可查看，客户端显示安全状态说明。
- 一条 AI 消息最多关联一个成功的完整匹配快照。
- 一个分支同时最多存在一个 `queued/running` 生成任务。

### 匹配快照

- 被历史消息引用的匹配快照与消息同生命周期，不再按固定天数过期。
- 完整快照冻结排名、得分、当时允许展示的候选资料、命中项和推荐解释。
- 历史页面同时查询候选当前状态，但当前状态不得改变历史排名或总数。
- 快照详情按消息访问并按页加载；打开会话时不传输全部候选。

### 加载与界面

- 会话列表只返回摘要并使用游标分页。
- 打开会话时加载完整的轻量分支拓扑和当前分支最近一页消息。
- 更早消息从分支头向祖先方向使用游标分页。
- 其他分支只在被选择时加载消息路径；公共祖先消息按 `message_id` 复用。
- 客户端提供消息旁快速分支切换和完整分支树面板。
- 管理端采用“分支树 / 当前消息路径 / 消息详情”三栏布局。
- 管理端仅在选择 AI 消息时懒加载匹配快照或 Trace。

### 生成任务与 Trace

- AI 生成任务独立于 SSE 连接；刷新或短暂断网后可以重新订阅。
- PostgreSQL 保存任务权威状态，独立 Worker 领取任务，Redis Stream 推送实时事件。
- 只有用户主动停止才设置 `stopped`；网络断开不自动停止任务。
- Trace 完全迁入数据库，不再写入或读取本地 JSON Trace。
- Trace 使用“生成记录 + 步骤明细”两级结构，不重复保存完整消息正文和最终回复。

## 目标

- 可靠保存和重放包含任意分支的用户 AI 对话。
- 客户端与管理端对同一会话得到完全一致的分支拓扑和消息路径。
- 从任意允许的消息节点准确恢复当时 AI 状态并创建新分支。
- 每条匹配 AI 消息都能分页查看当时完整且不可变的排名快照。
- 支持多窗口并发、幂等重试、生成停止、Worker 崩溃接管和 SSE 重连。
- 所有长期数据以 PostgreSQL 为权威来源，Redis 故障不得造成历史数据丢失。
- 会话列表和详情不读取无关大 JSON，不一次加载全部分支、消息、候选或 Trace。
- 用户硬删除会话后，原始内容不可通过客户端、管理端或缓存重新访问。
- 在不丢失现有可恢复数据的前提下渐进迁移，最终删除旧 JSON 会话存储和本地 Trace 代码。

## 非目标

- 本计划不修改匹配算法、特征权重或 LLM 提示词业务策略。
- 第一版不支持单独硬删除消息或分支。
- 第一版不支持多人共同编辑同一用户会话。
- 第一版不把图片、文件或音频二进制存入消息表；语音输入仍转成文本。
- 第一版不保证恢复现有存储中已经被回溯操作删除的数据。
- 第一版不引入 Celery；任务领取由 PostgreSQL Worker 实现。
- Redis Stream 不是长期审计来源，不永久保存 Token 事件。

## 目标架构

```text
React 用户端 / 管理端
        │
        ├─ 会话摘要游标分页
        ├─ 分支树元数据
        ├─ 单分支消息游标分页
        ├─ 按消息读取匹配结果页
        └─ 按 AI 消息读取 Trace（仅管理端）
        │
        ▼
FastAPI
  ├─ ConversationCommandService
  │    ├─ 追加消息 / 自动建分支 / 幂等检查
  │    ├─ 创建 GenerationRun
  │    └─ 硬删除会话 + Outbox
  ├─ ConversationQueryService
  │    ├─ 用户所有权视图
  │    └─ 管理员授权视图
  └─ Generation Event API
             │
             ├──────── Redis Stream：实时事件、短期重放
             │
             ▼
       Generation Worker
       ├─ PostgreSQL SKIP LOCKED 领取任务
       ├─ 从消息父链与状态快照重建上下文
       ├─ 调用 LLM / 匹配服务
       ├─ 定期保存部分输出与心跳
       └─ 原子完成消息、快照、Trace、分支头
             │
             ▼
PostgreSQL
  chats ── chat_branches ── chat_messages ── match_runs ── match_run_items
                              │
                              └─ ai_generation_runs ── ai_generation_steps
```

## 数据模型

### `app.chats`

迁移后只保存会话级元数据：

```sql
id                BIGINT PRIMARY KEY
user_id           BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE
title             TEXT NOT NULL
active_branch_id  UUID
branch_count      INTEGER NOT NULL DEFAULT 0
message_count     INTEGER NOT NULL DEFAULT 0
storage_version   SMALLINT NOT NULL DEFAULT 1
created_at        TIMESTAMPTZ NOT NULL
updated_at        TIMESTAMPTZ NOT NULL
```

约束：

- 新会话 `storage_version=2`。
- `active_branch_id` 必须属于同一个 `chat`；使用服务层事务校验，并尽可能使用复合外键保证。
- 列表索引使用 `(user_id, updated_at DESC, id DESC)`。
- `title` 只在首次有效用户消息时自动生成一次，后续仅显式重命名可修改。
- 迁移稳定前保留旧 `session_id/messages_json/candidates_json/state_json`，最终清理阶段删除。

### `app.chat_branches`

```sql
id                       UUID PRIMARY KEY
chat_id                  BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE
parent_branch_id         UUID
forked_from_message_id   UUID
derived_from_message_id  UUID
name                     TEXT NOT NULL
system_name              TEXT NOT NULL
fork_reason              TEXT NOT NULL
head_message_id          UUID
version                  INTEGER NOT NULL DEFAULT 0
is_archived              BOOLEAN NOT NULL DEFAULT FALSE
created_by               TEXT NOT NULL
created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
```

`fork_reason` 第一版允许：

```text
root
rewind_continue
edit_resend
regenerate
concurrent_send
```

约束：

- 根分支的父分支、分叉消息和来源消息为空。
- 非根分支的父分支不能为空；编辑第一条用户消息时允许分叉消息为空，其他分叉位置必须属于同一 `chat`。
- `derived_from_message_id` 仅用于编辑和重新生成来源；与首条派生消息保持一致。
- `head_message_id` 必须属于同一 `chat`，并位于该分支路径上。
- `version` 用于分支头乐观并发控制。
- 索引：`(chat_id, created_at, id)`、`(chat_id, parent_branch_id)`。

### `app.chat_messages`

```sql
id                       UUID PRIMARY KEY
chat_id                  BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE
created_in_branch_id     UUID NOT NULL REFERENCES app.chat_branches(id) ON DELETE CASCADE
parent_message_id        UUID
derived_from_message_id  UUID
role                     TEXT NOT NULL
status                   TEXT NOT NULL
content                  TEXT NOT NULL DEFAULT ''
content_format           TEXT NOT NULL DEFAULT 'markdown'
state_schema_version     SMALLINT NOT NULL
state_after_json         JSONB NOT NULL DEFAULT '{}'::jsonb
state_recoverable        BOOLEAN NOT NULL DEFAULT TRUE
match_run_id             UUID REFERENCES app.match_runs(id)
depth                    INTEGER NOT NULL CHECK (depth >= 0)
client_request_id        UUID
created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
completed_at             TIMESTAMPTZ
```

约束：

- `role` 第一版允许 `user`、`assistant`、`system`。
- `status` 第一版允许 `generating`、`completed`、`stopped`、`failed`。
- 用户消息写入即为 `completed`；AI 占位消息先为 `generating`。
- 同一 `chat` 内的父消息和派生来源必须属于同一 `chat`。
- 根欢迎消息可无父消息；其他消息必须有父消息。
- `depth = parent.depth + 1`，由命令服务计算并在事务内校验。
- `client_request_id` 对用户消息幂等，唯一约束建议为 `(chat_id, client_request_id)` 且忽略空值。
- `match_run_id` 对非空值唯一；只有 `completed` AI 消息可以关联 `ready` 快照。
- `match_run_id` 外键使用可延迟的 `NO ACTION`，禁止清理仍被消息引用的快照，同时允许整会话或整账号事务按正确顺序完成级联删除。
- 消息进入 `completed/stopped/failed` 后，数据库触发器或仓储层禁止修改内容、父关系、状态快照和匹配引用；删除仅允许通过整会话级联。
- 索引：`(chat_id, parent_message_id)`、`(created_in_branch_id, created_at, id)`、`match_run_id`。

状态快照第一版只保存：

```json
{
  "state_schema_version": 1,
  "parsed_features": {},
  "constraints": {},
  "dialogue_state": "collecting",
  "pending_relaxations": [],
  "preference_profile": null,
  "latest_match_run_id": null
}
```

消息历史和候选详情不得写入 `state_after_json`。

### `app.match_runs`

保留现有表名，扩展快照构建状态和来源：

```sql
id                       UUID PRIMARY KEY
user_id                  BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE
profile_json             JSONB NOT NULL
profile_hash             TEXT NOT NULL
model_version            TEXT NOT NULL
dataset_version          TEXT NOT NULL
total                    INTEGER NOT NULL
status                   TEXT NOT NULL DEFAULT 'building'
snapshot_schema_version  SMALLINT NOT NULL DEFAULT 1
snapshot_source          TEXT NOT NULL DEFAULT 'native'
prefer_hits              JSONB NOT NULL DEFAULT '[]'::jsonb
created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
ready_at                 TIMESTAMPTZ
```

- `status` 允许 `building`、`ready`、`failed`。
- `snapshot_source` 允许 `native`、`legacy_backfill`。
- 新读取接口只返回 `ready` 快照。
- 被 `chat_messages.match_run_id` 引用的快照不参与 TTL 清理。
- 现有 `donor_ids/scores` 数组在迁移期保留，完成明细回填和读切换后删除。

### `app.match_run_items`

```sql
match_run_id             UUID NOT NULL REFERENCES app.match_runs(id) ON DELETE CASCADE
rank                     INTEGER NOT NULL CHECK (rank > 0)
donor_id                 BIGINT NOT NULL
score                    REAL NOT NULL
donor_code_snapshot      TEXT NOT NULL
donor_snapshot_json      JSONB NOT NULL
match_explanation_json   JSONB NOT NULL DEFAULT '{}'::jsonb
snapshot_schema_version  SMALLINT NOT NULL
PRIMARY KEY (match_run_id, rank)
UNIQUE (match_run_id, donor_id)
```

- `donor_snapshot_json` 只允许保存匹配发生时客户端可展示字段。
- 不保存后台私密字段、模型原始请求或无关捐献者字段。
- `match_explanation_json` 保存字段命中、偏好命中、解释和必要的分项得分。
- 分页按 `(match_run_id, rank)` 范围查询。
- 读取当前状态时单独按当前页 donor ID 批量查询主表，不过滤历史项，不改变 rank。

### `app.ai_generation_runs`

```sql
id                    UUID PRIMARY KEY
user_id               BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE
chat_id               BIGINT NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE
branch_id             UUID NOT NULL REFERENCES app.chat_branches(id) ON DELETE CASCADE
user_message_id       UUID NOT NULL REFERENCES app.chat_messages(id) ON DELETE CASCADE
assistant_message_id  UUID NOT NULL UNIQUE REFERENCES app.chat_messages(id) ON DELETE CASCADE
client_request_id     UUID NOT NULL
status                TEXT NOT NULL
model                 TEXT
prompt_version        TEXT
prompt_hash           TEXT
cancel_requested_at   TIMESTAMPTZ
lease_owner           TEXT
lease_expires_at      TIMESTAMPTZ
heartbeat_at          TIMESTAMPTZ
attempt_count         INTEGER NOT NULL DEFAULT 0
error_type            TEXT
error_message_safe    TEXT
timings_json          JSONB NOT NULL DEFAULT '{}'::jsonb
queued_at             TIMESTAMPTZ NOT NULL DEFAULT now()
started_at            TIMESTAMPTZ
finished_at           TIMESTAMPTZ
UNIQUE (chat_id, client_request_id)
```

- 状态允许 `queued`、`running`、`completed`、`stopped`、`failed`。
- 同一分支最多一个 `queued/running` 任务，使用部分唯一索引保证。
- Worker 只领取 `queued` 或租约已过期且可重试的 `running` 任务。
- `error_message_safe` 不保存堆栈、密钥、Token、完整模型响应或敏感内部信息。

### `app.ai_generation_steps`

```sql
id             BIGSERIAL PRIMARY KEY
generation_id  UUID NOT NULL REFERENCES app.ai_generation_runs(id) ON DELETE CASCADE
step_order     INTEGER NOT NULL
step_type      TEXT NOT NULL
payload_json   JSONB NOT NULL DEFAULT '{}'::jsonb
created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
elapsed_ms     REAL
UNIQUE (generation_id, step_order)
```

- 保存模型配置摘要、输入消息 ID、Token 计数、工具调用参数、裁剪后的工具结果和耗时。
- 不复制完整消息正文、最终 AI 回复、系统提示词正文或供应商原始请求响应包。
- 管理端按 `generation_id` 分页或分段读取。

### 删除审计与 Outbox

新增最小删除审计表，只保存：用户 ID、原会话 ID、删除时间、删除前分支数、消息数、
匹配快照数和请求 ID，不保存标题、消息正文、候选资料或 Trace。

新增通用 Outbox 表，至少支持：

```text
chat_deleted
generation_event_cleanup
orphan_match_run_cleanup
```

Outbox 消费必须幂等；数据库删除提交后，即使 Redis 暂时不可用，任何读取接口也必须先以
PostgreSQL 所有权和存在性校验为准。

## API 设计

### 用户端读取

建议新增资源化接口，旧 `/api/user/chats` 在迁移期作为兼容层：

```text
GET    /api/chats?cursor=&limit=20
GET    /api/chats/{chat_id}
GET    /api/chats/{chat_id}/branches/{branch_id}/messages?before=&limit=50
GET    /api/messages/{message_id}/match-results?page=1&limit=20
GET    /api/generations/{generation_id}
GET    /api/generations/{generation_id}/events?after=
PATCH  /api/chats/{chat_id}
PATCH  /api/chats/{chat_id}/branches/{branch_id}
DELETE /api/chats/{chat_id}
```

`GET /api/chats/{chat_id}` 返回会话摘要和扁平分支列表，不返回全部消息、候选或 Trace。

会话列表游标签名并编码 `(updated_at, chat_id)`；消息游标编码当前页最早消息的父消息 ID。
所有游标绑定用户和资源，篡改返回 400，越权统一返回 404。

### 用户端命令与生成

```text
POST /api/chats/{chat_id}/turns
POST /api/generations/{generation_id}/stop
```

创建首条消息时允许使用“新会话”命令，避免仅打开页面就持久化空会话。命令体包含：

```json
{
  "branch_id": "uuid-or-null",
  "parent_message_id": "uuid-or-null",
  "action": "append|rewind_continue|edit_resend|regenerate",
  "derived_from_message_id": "uuid-or-null",
  "content": "...",
  "client_request_id": "uuid"
}
```

命令服务在一个短事务中：

1. 校验用户、会话、分支和消息归属。
2. 对目标分支加行锁并读取 `head_message_id/version`。
3. 根据 action 创建新分支，或在分支头正常追加。
4. 若父消息已不是分支头，自动创建 `concurrent_send` 分支。
5. 创建用户消息；`regenerate` 则复用原用户消息，不重复创建用户正文。
6. 创建 `generating` AI 占位消息。
7. 创建 `queued` GenerationRun。
8. 更新分支头、活跃分支、计数和更新时间。
9. 返回最终使用的 chat、branch、message 和 generation ID，以及是否自动创建分支。

同一 `client_request_id` 重试必须返回第一次创建的相同资源，不得产生重复消息或任务。

SSE 使用带 Authorization 的 `fetch` 流，而不是原生 EventSource；支持传入最后事件 ID 重连。
事件至少包括：

```text
generation_status
token
state_checkpoint
match_ready
completed
stopped
failed
```

Token 事件不得携带全量候选。`match_ready` 只返回 AI 消息 ID、总数和第一页加载提示；候选详情
始终通过消息匹配分页接口读取。

### 管理端读取

保留现有用户档案入口，新增分支化子资源：

```text
GET /api/admin/users/{user_id}/chats?cursor=&limit=20
GET /api/admin/users/{user_id}/chats/{chat_id}
GET /api/admin/users/{user_id}/chats/{chat_id}/branches/{branch_id}/messages?before=&limit=50
GET /api/admin/users/{user_id}/messages/{message_id}/match-results?page=1&limit=20
GET /api/admin/users/{user_id}/messages/{message_id}/generation
GET /api/admin/users/{user_id}/generations/{generation_id}/steps?cursor=&limit=
```

- 管理端和用户端调用同一个 `ConversationQueryService`。
- 管理端 DTO 增加内部状态、分叉操作者、生成元数据和安全错误分类。
- 每次打开会话、匹配结果或 Trace 写管理审计，但不把消息正文复制到审计表。
- 管理员读取不得改变 `active_branch_id` 或 Redis Session。

## 服务与模块拆分

建议新增：

```text
db/chat_models.py                 领域 DTO / 枚举 / 游标结构
db/chats_repo.py                  会话、分支、消息命令仓储
db/chat_queries_repo.py          列表、分支树、消息路径查询
db/generation_runs_repo.py       任务领取、租约、状态、步骤
db/outbox_repo.py                Outbox 写入与领取
api/chats.py                     用户端 V2 会话 API
api/admin_chats.py               管理端分支化会话 API
api/generation_events.py         生成状态、停止、事件订阅
dialogue/conversation_commands.py
dialogue/conversation_queries.py
dialogue/state_schema.py          状态版本校验与升级
dialogue/generation_worker.py
dialogue/generation_events.py     Redis Stream 封装
dialogue/generation_trace.py      数据库 Trace 写入
scripts/run_generation_worker.py
scripts/run_outbox_worker.py
scripts/migrate_chat_storage_v2.py
```

逐步替换并最终删除：

```text
api/chat_persist.py
dialogue/agent_trace.py
旧 chat_stream 中直接生成和直接持久化逻辑
管理端 read_session_traces 本地文件读取
```

同步数据库调用不得直接在 FastAPI 事件循环中执行。短期可把同步仓储放入线程池；长期可评估
异步 PostgreSQL 驱动，但不把驱动替换与本次业务迁移强绑定。

## Generation Worker 设计

### 领取与租约

- 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 批量领取任务。
- 领取时设置 `lease_owner`、`lease_expires_at`、`heartbeat_at` 和递增 attempt。
- Worker 按固定间隔续租；只有租约持有者可以提交终态。
- 进程崩溃后，租约过期任务可被其他 Worker 接管。
- 达到最大尝试次数后标记 `failed`，AI 消息保留安全错误说明。
- 收到 `cancel_requested_at` 后停止模型流，保存已有正文并提交 `stopped`。

### 上下文恢复

- 从生成任务的用户消息沿 `parent_message_id` 读取最近允许数量的祖先消息。
- 从父节点 `state_after_json` 恢复状态，不依赖 Redis 中可能过期的 Session。
- Redis Session key 改为 `user_id + chat_id + branch_id`，只作活跃分支缓存。
- 状态 schema 读取必须经过版本升级器；不可升级时任务安全失败，历史仍可只读。
- 提示词上下文只包含业务允许的最近消息数量；完整历史保留在数据库但不全部发送给 LLM。

### 流式输出与检查点

- Redis Stream key 绑定 generation ID 和用户 ID，设置短期 TTL。
- Token 事件有单调递增事件 ID，重连按最后事件 ID 重放。
- Worker 定期把部分正文写入 `generating` AI 消息并更新心跳。
- Redis 故障不应让生成结果丢失；允许降级为数据库状态轮询，但记录告警。
- 客户端断开不设置取消标记。

### 匹配快照构建

- 匹配算法仍产生全量严格排序。
- Worker 创建 `building` MatchRun，并使用批量插入或 COPY 写 `match_run_items`。
- 每个 item 在写入时构造白名单候选展示快照和解释快照。
- 校验 rank 从 1 连续到 total、donor 不重复、score 有限、快照 schema 合法。
- 全部完成后在最终提交中把 MatchRun 设为 `ready` 并关联 AI 消息。
- 构建失败的未引用快照标记 `failed`，由清理任务删除。
- Redis 在线排名缓存可以继续保留，但只作为可丢缓存；不得再成为历史快照恢复的必要条件。

### Trace

- 每次生成只创建一个 GenerationRun。
- LLM 调用、工具调用、匹配、持久化等按 `step_order` 追加 GenerationStep。
- 输入上下文只保存消息 ID 列表、模型参数、提示词版本与哈希、Token 数量和耗时。
- 工具结果使用白名单和大小限制；禁止写入密钥、Token、验证码和未脱敏联系方式。
- 最终回复通过 `assistant_message_id` 获取，不在步骤表重复存储。

## 客户端实施

### 数据层

建议新增：

```text
web/src/features/chat/types.ts
web/src/features/chat/api.ts
web/src/features/chat/branchGraph.ts
web/src/features/chat/conversationReducer.ts
web/src/features/chat/useConversation.ts
web/src/features/chat/generationStream.ts
```

- 消息按 `message_id` 标准化缓存。
- 分支保存扁平元数据和当前已知消息路径 ID。
- 公共祖先仅存一份消息对象。
- URL 中保存 `chatId/branchId`；刷新恢复同一查看位置。
- 切换分支只替换分叉点后的路径。
- 仅发送消息或明确继续时更新活跃分支。
- SSE 重连从最后事件 ID 继续；终态后以数据库 Generation/Message 再校验一次。

### UI

拆分当前大型 `ChatPanel.tsx`：

```text
ConversationPanel
ConversationHeader
BranchTreeDrawer
BranchSwitcher
MessageTimeline
MessageBubble
GenerationStatus
MatchResultEntry
```

- 分叉消息旁显示兄弟分支快速切换。
- 分支树显示名称、原因、创建时间、最后摘要和活跃标识。
- 编辑重发、从此继续和重新生成使用不同命令 action。
- `stopped/failed/generating` 使用明确状态 UI。
- 历史匹配消息先显示 total 摘要，展开后读取第一页。
- 当前分支最新匹配自动加载第一页并恢复中间候选区。
- 用户中心会话列表改为摘要游标分页，不再一次返回全部会话。
- 删除会话必须展示不可恢复确认；成功后清除路由和本地缓存。

### 前端匹配分页

- 从 `result_set_id` 导航改为以 `message_id` 为入口。
- 页缓存 key 使用 `(message_id, page, page_size)`。
- 每项同时展示历史冻结资料和当前状态标记。
- 候选当前停用时仍保留历史排名，但禁用需要当前可用状态的业务操作。

## 管理端实施

### 页面结构

把当前 `ChatTraceView` 改为三栏：

```text
ChatBranchTree | AdminMessageTimeline | MessageInspector
```

建议新增：

```text
web/src/pages/admin/chat/AdminChatWorkspace.tsx
web/src/pages/admin/chat/AdminBranchTree.tsx
web/src/pages/admin/chat/AdminMessageTimeline.tsx
web/src/pages/admin/chat/AdminMessageInspector.tsx
web/src/pages/admin/chat/AdminGenerationTrace.tsx
web/src/pages/admin/chat/AdminMatchSnapshot.tsx
```

- 左栏展示所有分支和明确分叉原因。
- 中栏在分叉位置插入回溯、编辑、重新生成和并发事件标记。
- 右栏按所选 AI 消息加载状态快照、匹配结果或 Trace。
- 列表不加载消息 JSON；直接显示 `message_count/branch_count`。
- 分支、消息、匹配和 Trace 分别使用局部 loading，避免一个请求清空整个会话区域。
- 快速切换时使用请求 ID 或 AbortController，防止慢响应覆盖新选择。

### 管理端安全

- 沿用 `USERS_VIEW` 权限，必要时单独增加更细的 `users.chat_trace.view` 权限。
- 所有管理端子资源同时校验 URL 中 user、chat、branch/message/generation 的归属链。
- 每次敏感详情读取写审计日志。
- UI 不显示模型供应商原始错误、密钥、Token 或系统提示词正文。

## 旧数据迁移

### 可恢复范围

- 每条旧 Chat 创建一个根分支。
- `messages_json` 按原顺序拆成独立消息并建立父链。
- 旧消息中的 `match_result_id` 尽力关联现有 MatchRun。
- `state_json` 只能可靠赋给最后一条消息；更早消息设置空的版本化状态并增加迁移标记，禁止从不可靠节点继续。
- 旧 MatchRun 的数组排名回填到 `match_run_items`。
- 候选展示资料使用迁移当时允许展示的当前资料构造，设置 `snapshot_source=legacy_backfill`。
- 已被旧回溯逻辑删除的消息和分支无法恢复。
- 旧 Trace 尝试按 `session_id`、时间和消息顺序导入 GenerationRun/Step；无法可靠关联的 Trace 写入迁移报告，不伪造关联。

### 迁移脚本要求

`scripts/migrate_chat_storage_v2.py` 必须支持：

- `--dry-run`
- `--user-id`
- `--chat-id`
- `--batch-size`
- `--resume-after`
- `--verify-only`
- 每批独立事务和可重复执行
- 输出迁移数量、跳过数量、失败原因和校验摘要
- 不删除或覆盖旧 JSON 字段

幂等键建议使用旧 chat ID + 消息序号生成确定性 UUID，确保重跑不会重复创建消息和分支。

### 迁移校验

每条 Chat 至少校验：

- 旧消息数等于新根分支路径消息数。
- 消息角色和正文摘要一致。
- 父链无环、depth 连续、branch head 正确。
- 最后一条消息状态与旧 `state_json` 一致。
- 每个可用 `match_result_id` 的总数、rank、donor ID 和 score 一致。
- 新 `message_count/branch_count/active_branch_id` 正确。
- 用户归属不变。

生成全局校验报告：总会话、成功、部分迁移、失败、缺失 MatchRun、Legacy Backfill 数量和未关联 Trace 数量。

## 删除流程

`DELETE /api/chats/{chat_id}`：

1. 校验当前用户和不可恢复确认 token/request ID。
2. 锁定 Chat，统计分支、消息和快照数量。
3. 写最小删除审计。
4. 删除 Chat 前锁定并收集它引用的 MatchRun ID；在同一数据库事务中删除 Chat 及级联的分支、消息、Generation，再删除这些已经失去消息引用的 MatchRun。
5. 同事务写 Outbox `chat_deleted`。
6. 提交后立即从客户端视图消失。
7. Outbox Worker 删除 branch Session、generation Redis Stream 和相关缓存。
8. Redis 清理失败自动重试；读取接口因为 PostgreSQL Chat 已不存在而始终返回 404。

删除测试必须验证数据库不存在孤儿行，Redis 残留不可访问，审计不包含原始内容。

## 配置与运行方式

新增配置建议：

```text
CHAT_STORAGE_V2_READ_ENABLED
CHAT_STORAGE_V2_WRITE_ENABLED
CHAT_GENERATION_WORKER_ENABLED
CHAT_GENERATION_LEASE_SECONDS
CHAT_GENERATION_HEARTBEAT_SECONDS
CHAT_GENERATION_MAX_ATTEMPTS
CHAT_GENERATION_CHECKPOINT_INTERVAL_SECONDS
CHAT_GENERATION_CHECKPOINT_CHARS
CHAT_GENERATION_STREAM_TTL_SECONDS
CHAT_MESSAGE_PAGE_SIZE_DEFAULT
CHAT_MESSAGE_PAGE_SIZE_MAX
CHAT_LIST_PAGE_SIZE_DEFAULT
CHAT_BRANCH_MAX_PER_CHAT
CHAT_MESSAGE_MAX_PER_CHAT
CHAT_MESSAGE_MAX_CHARS
CHAT_MATCH_SNAPSHOT_MAX_CANDIDATES
```

- 生产环境 Worker 与 Web 独立进程运行。
- Web 进程不自行领取任务。
- 开发环境允许显式启动内嵌 Worker，但默认行为和生产一致。
- 所有安全上限达到时返回稳定错误 code，不静默截断或删除历史。

## 实施阶段

### 阶段 0：契约、基线与灰度开关（P0）

**主要文件：**

- 修改：`config.py`
- 修改：`.env.example`
- 新增：`db/chat_models.py`
- 新增：API DTO/错误 code 契约测试
- 新增：现有聊天保存与恢复基线测试

- [x] 固化 Chat、Branch、Message、Generation、MatchSnapshot DTO。
- [x] 固化 action、status、fork_reason 和错误 code。
- [x] 增加 V2 读写、Worker 灰度开关，默认关闭。
- [ ] 记录当前测试、会话列表响应体、4303 人匹配写入与分页基准。
- [ ] 明确兼容版本是首个同时支持 V1/V2 的发布，不允许直接回滚到完全不识别 V2 的旧版本。

**验收：** 开关关闭时现有行为和测试不变；所有新 DTO 有序列化和边界测试。

### 阶段 1：添加数据库结构（P0）

**主要文件：**

- 新增：`db/postgres/11_add_branching_chat_storage.sql`
- 新增：`db/postgres/12_add_match_run_items.sql`
- 修改：`db/pg.py`
- 新增：`tests/test_chat_schema.py`

- [x] 新增 Branch、Message、GenerationRun、GenerationStep、删除审计和 Outbox 表。
- [x] 扩展 Chats 和 MatchRuns，保留旧列。
- [x] 创建复合归属、父链、状态、幂等、单分支活动任务和分页索引。
- [x] 外键全部明确 ON DELETE 行为。
- [x] 迁移可重复执行；已有生产数据不被改写或删除。
- [x] 使用真实 PostgreSQL 验证级联、唯一约束和并发部分索引。

**验收：** 连续执行迁移两次无错误；旧应用仍能启动；约束拒绝跨 Chat 父消息和重复 request ID。

### 阶段 2：领域仓储与查询服务（P0）

**主要文件：**

- 新增：`db/chats_repo.py`
- 新增：`db/chat_queries_repo.py`
- 新增：`dialogue/conversation_commands.py`
- 新增：`dialogue/conversation_queries.py`
- 新增：`dialogue/state_schema.py`
- 新增：`tests/test_conversation_commands.py`
- 新增：`tests/test_conversation_queries.py`

- [x] 实现根会话、追加、回溯继续、编辑重发、重新生成和并发自动分支。
- [x] 实现终态消息不可修改和 request ID 幂等。
- [x] 实现状态 schema 校验、升级和不可恢复节点识别。
- [x] 实现会话摘要游标、扁平分支树和消息祖先游标分页。
- [x] 用一个查询服务输出用户视图和管理员视图。
- [x] 同步仓储调用通过线程池，不阻塞 FastAPI 事件循环。

**验收：** 给定同一 Branch/Message 数据，两端得到相同路径；100 个并发旧头发送全部保留且形成可解释分支。

### 阶段 3：V2 完整匹配快照（P0）

**主要文件：**

- 修改：`db/match_runs_repo.py`
- 修改：`api/match.py`
- 修改：`core/preference/pipeline.py`
- 新增：候选快照白名单与 schema 模块
- 修改：`api/match_result_store.py`
- 新增/修改：匹配快照与分页测试

- [x] 新 MatchRun 先 building、批量写 items、校验后 ready。
- [x] 冻结允许展示候选资料和解释，不写后台私密字段。
- [x] 历史分页按 rank 返回冻结资料并批量附加当前状态。
- [x] 当前停用候选仍保留历史项和 rank。
- [x] 反馈成员校验改用 `(match_run_id, donor_id)` 明细查询或 Redis 缓存。
- [x] 清理任务只删除未被消息引用的临时、failed 或超龄 building 快照。
- [x] 评估 4303 和最大 20000 项批量写入时间、表大小和索引大小。

本机开发 PostgreSQL 基准（`scripts/benchmark_match_snapshot.py`，写后清理临时数据）：

- 4303 项：写入 89.12ms，末页 2.78ms，关系增长约 2.22MiB（约 541B/项）。
- 20000 项：写入 390.18ms，末页 2.36ms，关系增长约 10.30MiB（约 540B/项）。

**验收：** 修改或停用候选后，历史快照资料和排名不变，只更新“当前状态”；跨用户读取仍返回 404。

### 阶段 4：GenerationRun、数据库 Trace 与 Worker（P0）

**主要文件：**

- 新增：`db/generation_runs_repo.py`
- 新增：`dialogue/generation_worker.py`
- 新增：`dialogue/generation_events.py`
- 新增：`dialogue/generation_trace.py`
- 新增：`scripts/run_generation_worker.py`
- 独立进程：`scripts/run_generation_worker.py`（不占用 Web 事件循环）
- 新增：Worker、租约、停止、接管、Redis 故障测试

- [x] 实现 queued 领取、租约、心跳、取消、重试和最大尝试次数。
- [x] 从消息父链和版本化状态恢复上下文。
- [x] 把当前 chat_stream 的 LLM、工具与匹配流程移入 Worker。
- [x] Redis Stream 发布带序号事件；数据库定期保存部分正文。
- [x] 最终提交 AI 消息、状态、MatchRun 关联；Branch head 和计数已在命令事务指向占位消息。
- [x] Trace 写 GenerationStep，不再调用本地 `AgentTrace.write_trace`。
- [x] Worker 崩溃前后的提交使用租约 fencing，旧 Worker 不得覆盖接管者结果。

**验收：** Web 重启、浏览器断网和 Worker 崩溃均不丢任务；显式停止保留部分内容；同分支最多一个活动任务。

### 阶段 5：用户端 V2 API（P0）

**主要文件：**

- 新增：`api/chats.py`
- 新增：`api/generation_events.py`
- 修改：`main.py`
- 修改：`api/feedback.py`
- 新增：V2 API 所有权、游标、幂等、删除测试

- [x] 实现摘要列表、会话/分支树、消息路径和按消息匹配分页。
- [x] 实现 turn 命令、stop、generation 状态和可重连事件流。
- [x] 实现会话/分支重命名和分支归档。
- [x] 实现整会话硬删除与 Outbox。
- [x] 所有子资源按 user → chat → branch/message/generation 完整校验。
- [x] 统一稳定错误 code 和 404 防枚举行为。

**验收：** 用户 A 无法通过任何 ID 组合读取或修改用户 B 的树、消息、匹配、任务或事件。

### 阶段 6：客户端分支化 UI（P1）

**主要文件：**

- 重构：`web/src/components/ChatPanel.tsx`
- 修改：`web/src/pages/DonorsPage.tsx`
- 修改：`web/src/pages/UserPage.tsx`
- 修改：`web/src/types.ts`
- 新增：`web/src/features/chat/*`
- 新增：分支图、Reducer、SSE 重连、分页和组件测试

- [x] 接入摘要游标列表和 branchId URL。
- [x] 实现标准化消息缓存、公共祖先复用和向上滚动分页。
- [x] 实现快速切换与完整分支树面板。
- [x] 实现继续、编辑重发、重新生成、停止和失败重试。
- [x] 实现 SSE 重连和生成中恢复。
- [x] 当前最新匹配自动加载，旧匹配按消息懒加载。
- [x] 移除客户端重复 `POST /api/user/chats` 保存。
- [x] 删除确认文案明确不可恢复。

**验收：** 回溯后两个分支都可重复加载；刷新保持当前查看分支；两个浏览器窗口并发发送不丢消息。

### 阶段 7：管理端三栏工作区（P1）

**主要文件：**

- 新增：`api/admin_chats.py`
- 修改：`api/admin_users.py`
- 修改：`db/admin_users_repo.py`
- 重构：`web/src/pages/admin/UserProfileView.tsx`
- 替换：`web/src/pages/admin/ChatTraceView.tsx`
- 新增：`web/src/pages/admin/chat/*`
- 新增：管理权限、审计、分支和 Trace UI 测试

- [ ] 管理端列表直接读取 chat 计数列，不解析消息正文。
- [ ] 实现分支树、当前路径和消息 Inspector。
- [ ] 显式展示回溯、编辑、重新生成和并发分叉事件。
- [ ] 按 AI 消息懒加载 MatchRun 与 GenerationStep。
- [ ] 分离列表、路径、匹配和 Trace 的 loading/error 状态。
- [ ] 每次敏感读取写审计。
- [ ] 删除所有管理端本地 Trace 文件读取。

**验收：** 管理员可从根到叶还原每条分支及分叉原因；查看行为不改变用户 active branch。

### 阶段 8：历史数据迁移与兼容读取（P1）

**主要文件：**

- 新增：`scripts/migrate_chat_storage_v2.py`
- 新增：迁移夹具与集成测试
- 修改：V1 兼容 API

- [ ] 实现 dry-run、批处理、断点续跑、幂等和 verify-only。
- [ ] 迁移旧 Chat 到单根分支消息树。
- [ ] 回填旧 MatchRunItems 和 legacy donor snapshot。
- [ ] 最后一条消息关联可靠 state；其他节点标记不可准确恢复。
- [ ] best-effort 导入可关联的旧 Trace，生成未关联报告。
- [ ] V1/V2 查询按 storage_version 路由，前端只消费统一 V2 DTO。
- [ ] 在预发布复制数据上完成全量迁移和抽样人工核对。

**验收：** 所有旧会话至少可读；迁移报告解释每一条部分迁移和失败记录；重跑不产生重复数据。

### 阶段 9：灰度切换与运行验证（P0 发布阶段）

- [ ] 发布同时支持 V1/V2 的兼容版本。
- [ ] 启动 Worker，但先只处理测试用户或灰度用户。
- [ ] 对内部用户启用 V2 write/read，验证任务、分支、快照和删除。
- [ ] 按用户比例扩大 V2；监控错误、队列、租约、数据库写入和 Redis Stream。
- [ ] 全量切换新用户与新对话到 V2。
- [ ] 迁移旧数据并切换旧会话读取。
- [ ] 停止旧 JSON 写入，但继续保留旧列一个稳定观察期。
- [ ] 回滚只回到兼容版本，通过开关停用 V2；不得回滚到完全不识别 V2 数据的旧二进制。

### 阶段 10：清理旧结构（P2，独立发布）

**主要文件：**

- 新增：`db/postgres/13_drop_legacy_chat_storage.sql`
- 删除：`api/chat_persist.py`
- 删除：`dialogue/agent_trace.py`
- 修改：旧 chat/user/admin API、测试、文档和配置

- [ ] 确认 V1 写流量为 0，迁移校验完成且观察期无回滚。
- [ ] 删除 Chats 的 session/messages/candidates/state JSON 字段。
- [ ] 删除 MatchRuns 的 donor_ids/scores 数组。
- [ ] 删除本地 Trace 读写、目录配置和相关测试。
- [ ] 删除旧恢复、旧回溯和重复保存接口。
- [ ] 删除不再使用的 Redis Session/result 兼容 key。
- [ ] 更新架构文档、备份恢复文档和运维手册。

**验收：** 全仓库搜索不再存在旧 JSON 会话持久化或本地 Trace 生产路径；数据库无遗留兼容列。

## 测试计划

### 数据库与仓储

- 根分支、父分支、消息父链和跨 Chat 归属约束。
- depth 连续、无环、head 属于路径。
- 终态消息不可修改。
- `client_request_id` 幂等。
- 每分支单活动任务约束。
- 删除 Chat 后所有子表无孤儿。
- MatchRun rank 连续、donor 唯一、item 数等于 total。

### 分支行为

- 从 AI 消息继续形成正确分支。
- 编辑用户消息从其父节点分叉，并保留原消息。
- 重新生成产生新的 AI 消息分支。
- 并发旧头发送自动产生兄弟分支。
- 查看分支不改 active，发送后才更新 active。
- 归档分支默认隐藏但可恢复。
- 公共祖先在不同分支路径中 ID 完全一致。

### 生成任务

- 提交命令与网络重试只创建一个任务。
- Worker SKIP LOCKED 不重复领取。
- 租约续期、过期接管和 fencing。
- 浏览器断开后任务继续。
- stop 保存部分正文并进入终态。
- Worker 崩溃后恢复或安全失败。
- Redis 不可用时历史数据不丢失，事件流可降级。
- 同分支第二个任务被约束拒绝或按旧头自动分支。

### 加载与权限

- 会话摘要游标稳定且无重复遗漏。
- 消息祖先游标在分支追加后仍稳定。
- 用户与管理员查询同一分支得到相同消息 ID 顺序。
- 任何跨用户 chat/branch/message/match/generation ID 组合返回 404。
- 匹配分页通过 message ID 校验关联。
- 管理审计不含正文或敏感 Trace payload。

### 匹配快照

- 4303 和最大候选规模完整写入、分页和删除。
- 修改候选主数据后历史冻结资料不变。
- 停用候选保留历史 rank，并显示当前不可用。
- building/failed 快照不可读取。
- 被消息引用快照不被清理。
- Legacy Backfill 明确标识且不伪装原始时间快照。

### 前端

- 扁平 Branch 列表正确组装树。
- 分支切换只替换分叉点后路径。
- URL 刷新恢复 chat/branch。
- SSE 断线按事件 ID 重连且 Token 不重复。
- 生成终态以数据库结果校准。
- 匹配按消息分页缓存不会串到其他消息。
- 删除后清理路由、消息和候选缓存。

### 迁移

- 空聊天、只有欢迎语、普通聊天、多次匹配、损坏 JSON、缺失 MatchRun、重复 session_id。
- 中断后续跑和脚本重跑。
- 旧消息数、角色、正文、匹配排名和最终状态校验。
- 未关联 Trace 和不可靠状态进入报告，不阻断其他会话迁移。

## 性能与容量验收

使用真实或脱敏生产规模数据验证：

- 20 条会话摘要响应不读取 Message、MatchItem 或 Trace 表大字段。
- 200 分支拓扑可以在单次轻量响应中返回。
- 50 条消息页不包含候选详情和 Trace payload。
- 4303 项和 20000 项 MatchRun 批量写入、第一页、尾页和任意页读取。
- 100 个并发旧头发送全部保留，无死锁、重复任务或消息丢失。
- Generation 队列高峰下 Web 请求不执行 LLM 或长事务。
- 删除大 Chat 时评估并限制事务锁时间；必须在接口成功返回前完成数据库硬删除，不以软删除或延迟物理清理替代已确认的不可恢复语义。

记录并监控：

- 会话列表、分支树、消息页、匹配页查询耗时和 payload 大小。
- 队列深度、排队时间、运行时间、租约过期和重试次数。
- Redis Stream 重连、丢失和降级次数。
- MatchRun item 数、快照字节量和写入耗时。
- Outbox backlog、删除清理延迟和失败次数。
- 每用户 Chat、Branch、Message 和永久 MatchItem 增长速度。

## 发布与回滚原则

- 所有 schema 变更先增后删，旧列只在独立最终阶段删除。
- 首个兼容版本同时识别 V1/V2；灰度期间只通过开关切换，不依赖数据库降级。
- 新 V2 数据写入后，回滚目标必须是兼容版本，不能回滚到完全不认识消息树的旧版本。
- Worker 可独立停用；停用时 queued 任务保留，不由 Web 进程接管。
- 若 V2 写路径异常，关闭新任务入口并保留已有 V2 数据，不能回写覆盖旧 JSON。
- MatchRunItems 或迁移异常时停止灰度并运行 verify-only，禁止删除旧数组和 JSON。
- 最终 drop migration 必须在备份、恢复演练、全量校验和观察期完成后单独审批执行。

## 完成定义

- 新会话不再写 `messages_json/candidates_json/state_json`。
- 用户回溯、编辑、重新生成和并发发送均形成可重载分支。
- 客户端和管理端展示相同分支拓扑和消息路径。
- 任意新 AI 匹配消息可以查看完整冻结排名、资料和解释。
- 生成任务可跨刷新、断网和 Worker 重启恢复。
- Trace 只存 PostgreSQL，不存在本地 JSON Trace 生产路径。
- 会话列表、消息、匹配和 Trace 都按设计懒加载与分页。
- 用户硬删除后原始会话内容不可访问，且无数据库孤儿数据。
- 旧会话迁移结果有完整报告，无法恢复内容被明确标记而非伪造。
- 旧 JSON 会话列、数组快照兼容列和本地 Trace 代码在最终阶段安全删除。
