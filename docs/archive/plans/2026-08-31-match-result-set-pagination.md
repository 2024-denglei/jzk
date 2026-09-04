# 匹配结果集与候选详情分页实施计划

## 背景

当前匹配流程会对所有符合必要条件的候选人完成排序，并为每一位候选人组装完整的 `donor_info`、`field_scores`、`field_match` 等详情。随后 `/api/match` 才根据 `top_k` 截断返回内容。

当“硕士、身高 175 以上”匹配到 4,303 人时，这种结构产生了三个问题：

- 匹配层为全部 4,303 人组装重对象，即使最终只返回前 100 人也会浪费内存和 CPU。
- 全量候选详情进入 Redis 临时会话后超过 2 MB 会话上限。
- 全量结果通过 SSE 发送给浏览器，会增加响应时间、网络流量和前端内存占用。

提交 `102b5e7` 已将聊天返回详情临时限制为前 100 人，并保留总匹配人数。这是安全止血措施，不应成为长期业务上限。

## 实施状态（2026-09-01）

核心方案已落地：严格快照、Redis 在线结果集、只组装当前页、签名游标与页码直达、聊天结果引用、全结果成员反馈校验和 React 懒加载均已实现。迁移期仍保留 `/api/match.candidates` 第一页兼容字段；待调用方稳定后再删除该重复字段。

真实数据基准“硕士、身高 175 以上”结果如下：

| 指标 | 实测 |
|---|---:|
| 全量排名 | 4,303 |
| 首次详情 | 20 |
| 第二页首位 rank | 21 |
| PostgreSQL 单快照行 | 14,832 bytes |
| Redis 在线结果集 | 278,952 bytes |

最初的 Redis `ZSET + HASH` 结构实测为 663,138 bytes，超过 500 KB 目标，因此在线结构改为按物理顺序保存 rank 的 `LIST(id:score)` 加用于 O(1) 成员校验的 `SET(donor_id)`。PostgreSQL 严格快照结构未变。

## 目标

- 匹配逻辑仍对全部候选人完成排序，不丢失第 101 名之后的结果。
- 全量结果仅保存紧凑的 `donor_id + rank + score`，不保存完整候选详情。
- Redis 保存绑定用户的临时匹配结果集，支持稳定分页、成员校验和自动过期。
- PostgreSQL 使用紧凑数组持久保存严格排名快照，Redis 过期后仍能恢复当时的排名和得分。
- 首次匹配和后续分页只为当前页候选人组装卡片详情。
- 聊天侧展示真实总人数，并允许用户分页浏览全部结果。
- 反馈接口允许反馈结果集中任意候选人，而不是只允许前 100 人。
- Redis 结果过期后能够从 PostgreSQL 严格快照恢复，不需要重新运行模型。

## 非目标

- 本阶段不修改模型算法、特征权重或排序结果。
- 本阶段不把捐精人主数据迁入 Redis。
- 本阶段不允许客户端提交任意候选 ID 批量查询详情。
- 本阶段不为每次匹配保存候选人的完整字段快照；历史页面仍按候选 ID 加载当前允许展示的详情。
- 本阶段不保证还原候选人当时的学历、库存、状态等可变字段，只保证排名、ID、得分和决策上下文可复现。

## 核心设计结论

不让匹配模型把全部完整候选详情返回给 API 或前端。模型层输出紧凑排名引用，应用层将同一份排名以两种生命周期保存：PostgreSQL 保存严格排名快照，Redis 提供低延迟在线分页。页面只从 PostgreSQL 主数据加载当前页候选详情。

```text
PreferenceProfile
      │
      ▼
硬条件 SQL 过滤 + 模型全量排序
      │
      ├─ 聚合：total、prefer_hits、模型版本、耗时
      │
      └─ 紧凑引用：[{donor_id, rank, score}, ...]
                       │
                       ▼
        ┌──────────────┴──────────────┐
        ▼                             ▼
PostgreSQL MatchRunSnapshot    Redis MatchResultStore
严格保存 ID[] + score[]        在线分页、成员校验、TTL
        │                             │
        └──────────── result_set_id ──┘
                       ▼
分页接口读取 20 个 donor_id ──► PostgreSQL 批量加载卡片详情
                       │
                       ▼
                React 分页展示
```

### 为什么不直接把全部 ID 和得分返回前端

全部 ID 和得分比完整详情小很多，可以作为后端内部过渡格式，但不建议一次性暴露给前端：

- 前端仍需保存数千条数组并自行分页。
- 后续还要为数千个 ID 获取详情，容易形成大请求或 N+1 查询。
- 客户端持有全部 ID 会扩大接口滥用和枚举面。
- 结果过期、候选人停用和权限校验难以集中处理。

因此浏览器只获得当前页详情、总数、结果集 ID 和下一页游标。

结果集 ID 与 PostgreSQL `match_runs.id` 使用同一个 UUID。Redis 丢失时，应用可以用该 ID 从 PostgreSQL 快照重建在线结果集。

## 数据模型

### 排名引用

在 `core/preference` 中新增轻量结构：

```python
@dataclass(frozen=True)
class RankedCandidateRef:
    donor_id: int
    rank: int
    score: float
```

约束：

- 使用 PostgreSQL 内部 `donor_id` 做关联，不依赖用户可见代号进行数据库连接。
- `rank` 是唯一且稳定的展示顺序，不能依赖相同得分下 Redis 的默认排序。
- `score` 保存有限精度，例如小数点后 6 位。
- `field_scores` 仅在排序计算过程中用于聚合和当前页详情，不为全量结果长期保存。

### Redis Key

每个结果集使用至少 128 bit 随机 `result_set_id`，所有 key 使用相同 hash tag，便于 Redis Cluster 将同一结果集放在同一 slot：

```text
jzk:match-result:{result_set_id}:meta
  HASH owner_user_id, total, profile_json, profile_hash,
       model_version, created_at, expires_at

jzk:match-result:{result_set_id}:items
  LIST 按 rank 顺序保存 donor_id:score

jzk:match-result:{result_set_id}:members
  SET donor_id

jzk:match-result-subject:{user_id}
  ZSET score=expires_at, member=result_set_id
```

说明：

- LIST 的数组位置就是 rank，元素同时保存候选 ID 和六位小数得分，`LRANGE` 用于稳定分页。
- SET 只保存候选 ID，`SISMEMBER` 用于反馈成员校验。
- 该结构在 4,303 条真实结果上比 `ZSET + HASH` 节省约 58% Redis 内存。
- meta 必须保存 `owner_user_id`，读取时同时校验 key、meta 和当前登录用户。
- 创建结果集使用事务 pipeline，确保 meta、items、members 和 TTL 不出现部分写入。

### PostgreSQL 严格排名快照

新增迁移和表 `app.match_runs`。排名由数组位置表示，因此不需要为每位候选单独保存 `rank`，也不需要每次匹配插入数千行。

```sql
CREATE TABLE IF NOT EXISTS app.match_runs (
    id               UUID PRIMARY KEY,
    user_id          BIGINT NOT NULL REFERENCES app.users(id),
    profile_json     JSONB NOT NULL,
    profile_hash     TEXT NOT NULL,
    model_version    TEXT NOT NULL,
    dataset_version  TEXT NOT NULL,
    total            INTEGER NOT NULL CHECK (total >= 0),
    donor_ids        BIGINT[] NOT NULL,
    scores           REAL[] NOT NULL,
    prefer_hits      JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (cardinality(donor_ids) = total),
    CHECK (cardinality(scores) = total)
);

CREATE INDEX IF NOT EXISTS idx_match_runs_user_created
    ON app.match_runs (user_id, created_at DESC);
```

约束与语义：

- `donor_ids[n]`、`scores[n]` 表示第 `n` 名候选及其得分。
- 得分在写入前统一量化到小数点后 6 位，使不同语言和数据库浮点表示保持一致；严格快照以量化后的值为准。
- `profile_json`、模型版本和数据集版本每次运行只保存一份。
- 不保存 `donor_info`、`field_scores` 或候选完整字段，避免重复敏感数据和存储膨胀。
- 快照中的候选后来被停用时，历史排名仍保留其 ID，但页面加载时不再展示该候选。
- 历史页面分别显示“当时匹配总数”和“当前可查看数量”，不能把被停用候选静默计入当前展示数。
- 通过 `id + user_id` 查询快照，跨用户请求统一返回 404。
- 第一版使用单表和 `(user_id, created_at)` 索引；达到容量阈值后再迁移为按月分区，避免过早增加分区主键和运维复杂度。

### 快照容量估算

以 4,303 位候选计算，`BIGINT[] + REAL[]` 的原始元素数据约 52 KB，加上画像、JSONB、数组和行开销后，单次目标控制在 60～120 KB。

| 匹配频率 | 30 天原始快照估算 | 180 天原始快照估算 |
|---|---:|---:|
| 100 次/天 | 0.18～0.36 GB | 1.1～2.2 GB |
| 1,000 次/天 | 1.8～3.6 GB | 11～22 GB |
| 10,000 次/天 | 18～36 GB | 110～220 GB |

容量规划还需考虑 WAL、备份和副本，生产磁盘预算按原始快照的 2～4 倍评估。默认在线保留 180 天；超过保留期的数据按合规要求删除或归档到冷存储。

### 容量与生命周期

建议默认值：

| 配置 | 默认值 |
|---|---:|
| `MATCH_RESULT_TTL_SECONDS` | 1800 |
| `MATCH_RESULT_MAX_LIFETIME_SECONDS` | 7200 |
| `MATCH_RESULT_MAX_ACTIVE_PER_USER` | 5 |
| `MATCH_RESULT_MAX_CANDIDATES` | 20000 |
| `MATCH_RESULT_PAGE_SIZE_DEFAULT` | 20 |
| `MATCH_RESULT_PAGE_SIZE_MAX` | 50 |
| `MATCH_SNAPSHOT_ENABLED` | true |
| `MATCH_SNAPSHOT_RETENTION_DAYS` | 180 |

- 用户访问结果时可以刷新空闲 TTL，但不得超过绝对最大生命周期。
- 新建结果集前清理用户索引中的过期成员。
- 超过每用户上限时删除最旧结果集，或返回明确的容量异常；第一版建议删除最旧结果集。
- Redis 是结果分页缓存而不是排名权威来源；Redis 不可用时从当前用户的 PostgreSQL 快照分页，禁止退回全量详情响应，并记录降级指标。
- PostgreSQL 快照写入必须在接口返回成功前提交；写入失败时不得声称已生成严格快照。
- Redis 与 PostgreSQL 无法做跨存储事务：先以幂等 UUID 写入 PostgreSQL，再写 Redis。Redis 写入失败时保留快照，重试可按同一 UUID 重建 Redis，不重复运行模型。

## API 设计

### 创建匹配结果

保留现有 `POST /api/match` 路径，兼容旧调用方，但扩展响应语义：

```json
{
  "ok": true,
  "result_set_id": "mr_...",
  "total": 4303,
  "returned_count": 20,
  "items": [],
  "candidates": [],
  "next_cursor": "opaque-cursor",
  "match_level": "full",
  "filtered_count": 4303,
  "prefer_hits": [],
  "model_version": "v2"
}
```

兼容规则：

- 迁移期同时返回 `items` 和旧字段 `candidates`，两者都只包含第一页。
- `filtered_count` 和新增 `total` 表示全部匹配数。
- `returned_count` 表示当前响应详情数。
- `result_set_id` 同时标识 PostgreSQL 严格快照和 Redis 在线结果集。
- 旧 `top_k` 暂时保留；新聊天调用改用 `page_size`，不再把 `top_k` 当业务总量。
- 前端迁移完成后删除 `candidates` 兼容字段和聊天专用 `CHAT_MATCH_TOP_K` 止血逻辑。

### 分页读取

新增：

```http
GET /api/match/results/{result_set_id}?cursor={cursor}&limit=20
GET /api/match/results/{result_set_id}?page=100&limit=20
```

响应：

```json
{
  "result_set_id": "mr_...",
  "total": 4303,
  "items": [],
  "next_cursor": "opaque-cursor",
  "has_more": true
}
```

分页规则：

- cursor 包含结果集 ID、下一个 rank offset 和版本，并使用服务端密钥签名，客户端不能修改页码绕过限制。
- `page` 由服务端换算为严格 rank offset，支持直接跳至任意页；不能与 cursor 同时使用。
- 页码直达只读取目标 rank 窗口，不请求前置页面，也不向浏览器暴露全量候选 ID。
- `limit` 最大 50。
- PostgreSQL 快照不存在或不属于当前用户统一返回 404。
- Redis 结果已过期但 PostgreSQL 快照仍存在时，服务端从快照数组读取当前页，并异步或按需重建 Redis 在线结果集，用户不需要重新匹配。
- PostgreSQL 快照已超过保留期时返回 410，并附带稳定错误码 `MATCH_SNAPSHOT_EXPIRED`；此时前端才提供“重新匹配”动作。
- PostgreSQL 查询必须包含 `status = 'active'`；已停用候选不再返回。
- 当前页有停用候选时继续向后读取少量排名，尽量补足页面，并返回实际 `items` 数量。
- 批量查询后按照 Redis rank 重新排序，不能依赖 SQL 默认顺序。

### 主动重新匹配

新增或复用匹配接口：

```http
POST /api/match/results/{result_set_id}/refresh
```

仅当前用户可操作。服务端从 PostgreSQL 快照读取旧画像，使用当前模型和当前有效候选重新运行，并创建新的严格快照与 `result_set_id`。旧快照按保留策略继续存在，界面应明确这是一次新的匹配运行，而不是覆盖历史结果。

## 后端实施阶段

### 阶段一：PostgreSQL 严格排名快照（P0）

**主要文件：**

- 新增：`db/postgres/10_add_match_runs.sql`
- 新增：`db/match_runs_repo.py`
- 修改：`db/pg.py`
- 修改：`config.py`
- 修改：`.env.example`
- 新增：`tests/test_match_runs_repo.py`

- [x] 新增 `app.match_runs` 表、用户时间索引和可重复执行迁移。
- [x] 使用应用生成的 UUID 作为 `match_run_id/result_set_id`。
- [x] 实现幂等创建、按用户读取、数组分页、成员校验和按保留期删除。
- [x] 使用 `BIGINT[]` 保存排名 ID，使用 `REAL[]` 保存得分，数组位置代表 rank。
- [x] 写入时校验数组长度、总数、候选上限和得分有限值。
- [x] 保存画像 hash、模型版本、数据集版本和 `prefer_hits`，不保存完整候选详情。
- [x] 快照写入成功后才允许接口返回成功。
- [x] 增加按批次清理 180 天以前快照的管理命令，避免长事务一次删除全部历史。
- [ ] 记录每日新增快照数、表大小、索引大小和清理进度。

### 阶段二：Redis MatchResultStore（P0）

**主要文件：**

- 新增：`core/preference/result_types.py`
- 新增：`api/match_result_store.py`
- 修改：`config.py`
- 修改：`.env.example`
- 新增：`tests/test_match_result_store.py`

- [x] 定义 `RankedCandidateRef` 和结果集 meta 类型。
- [x] 实现结果集创建、分页、成员校验、删除和按用户撤销。
- [x] 使用事务 pipeline 原子写入并设置所有 key TTL。
- [x] 所有读取校验 `owner_user_id`。
- [x] 实现每用户结果集数量和单结果集候选数量限制。
- [x] Redis 异常触发 PostgreSQL 快照降级读取。
- [x] Redis miss 时从当前用户的 PostgreSQL 快照恢复结果集，不重新运行模型。
- [x] PostgreSQL 快照和 Redis 结果集使用同一个 UUID。
- [ ] 记录结果集条数、字节估算、创建耗时和分页耗时，不记录画像明文敏感值。

### 阶段三：拆分排序引用与详情组装（P0）

**主要文件：**

- 修改：`core/preference/pipeline.py`
- 修改：`core/preference/v2_ranker.py`
- 修改：`core/data_loader.py` 或新增候选详情仓储
- 修改：`api/match.py`
- 新增：`tests/preference/test_compact_match_results.py`

- [x] 排序器输出全量轻量引用，不再立即调用 `_candidate_dict` 组装全部详情。
- [x] 在排序过程中计算 `prefer_hits`、总数和瓶颈信息。
- [x] 仅为第一页引用组装完整候选卡片。
- [x] 后续页通过 PostgreSQL `WHERE id = ANY(...)` 一次批量加载。
- [x] 批量详情结果按严格 rank 恢复顺序。
- [x] 保留模型版本、画像 hash 和耗时字段。
- [x] 排序完成后先写 PostgreSQL 严格快照，再创建 Redis 在线结果集。
- [x] 测试确保匹配 4,303 人时详情组装函数只调用当前页次数，而不是 4,303 次。

### 阶段四：分页 API 与权限隔离（P0）

**主要文件：**

- 修改：`api/match.py`
- 修改：`main.py`
- 新增：`api/match_results.py`（如需拆分路由）
- 新增：`tests/test_match_results_api.py`

- [x] `POST /api/match` 创建结果集并返回第一页。
- [x] 实现分页、刷新和主动删除接口。
- [x] cursor 签名并校验 result ID、offset、版本和有效期。
- [x] 用户 A 读取用户 B 结果集时返回 404。
- [x] Redis 过期时透明回源 PostgreSQL 快照；只有快照过期才返回稳定错误码。
- [x] 候选停用后分页接口不再返回该候选。
- [x] Redis 不可用时安全降级到 PostgreSQL 数组分页，不返回未受控全量详情。

### 阶段五：聊天会话、回滚与反馈（P1）

**主要文件：**

- 修改：`dialogue/session.py`
- 修改：`dialogue/session_store.py`
- 修改：`dialogue/agent_tools.py`
- 修改：`api/chat_stream.py`
- 修改：`api/feedback.py`
- 修改：`api/chat_persist.py`
- 修改：`api/user.py`
- 扩展：`tests/test_redis_chat_sessions.py`
- 新增：`tests/test_chat_match_result_membership.py`

- [x] `SessionContext` 增加 `match_result_id`、`match_total` 和 `match_next_cursor`。
- [x] Redis 会话仅保存结果集引用和聊天卡片预览，不保存全量候选详情。
- [x] checkpoint/abort/rewind 同时恢复结果集引用。
- [x] SSE `candidates` 事件返回第一页、总数、result ID 和 cursor。
- [x] 反馈接口通过结果集成员关系校验候选，而不是检查 `session.candidates` 预览数组。
- [x] 结果集仍必须属于当前会话用户。
- [x] 长期聊天保存 `match_run_id`、总数和少量预览；严格排名由 `app.match_runs` 保存。
- [x] 恢复长期聊天时从 PostgreSQL 严格快照继续分页，并按需重建 Redis。
- [ ] 只有严格快照超过保留期时才提供“重新生成结果”动作。

### 阶段六：React 懒加载分页（P1）

**主要文件：**

- 修改：`web/src/types.ts`
- 修改：`web/src/components/ChatPanel.tsx`
- 修改：`web/src/components/ChatMatchCards.tsx`
- 修改：`web/src/pages/DonorsPage.tsx`
- 修改：`web/src/lib/api.ts`
- 新增/扩展前端测试

- [x] 前端新增 `MatchResultDescriptor` 和分页状态。
- [x] 首次仅保存第一页候选和总数。
- [x] 中间候选区切页时调用后端分页接口。
- [x] 支持首页、尾页、数字页码和输入页码直达，分页栏固定在候选区底部。
- [x] 按结果集和页游标缓存已加载页面，避免重复请求。
- [x] 翻页期间显示局部 loading，不清空已显示页面。
- [x] Redis 缓存过期对前端透明；严格快照过期时显示“重新匹配”动作。
- [x] 文案明确“共 4,303 位，当前显示第 1～20 位”，不再声称本地已持有全部数据。
- [x] 新对话、回溯、恢复历史和退出登录时清理无用页面缓存。

### 阶段七：移除止血兼容与优化（P2）

- [x] 移除聊天固定前 100 的业务限制与 `CHAT_MATCH_TOP_K` 配置。
- [ ] 停止在 `/api/match` 返回重复的 `items`/`candidates` 兼容字段。
- [x] 删除 `matchBagsRef` 中保存全量候选的旧逻辑。
- [ ] 对 Redis 结果集启用压缩前先通过真实数据评估；没有收益时不增加复杂度。
- [ ] 根据指标调整 TTL、每用户结果集上限和页大小。
- [ ] 根据实际增长决定是否将 `app.match_runs` 改为按月分区或迁移冷快照。

## 测试计划

### 单元测试

- [ ] PostgreSQL `donor_ids[]` 与 `scores[]` 长度一致，数组位置严格代表排名。
- [ ] 4,303 条快照写入、分页、成员查询和幂等重试正确。
- [ ] 快照只能由所属用户读取，跨用户按不存在处理。
- [ ] Redis miss 能从 PostgreSQL 快照恢复且不重新运行模型。
- [ ] 4,303 条引用创建后顺序、总数和得分保持正确。
- [ ] 相同 score 的候选仍严格按 rank 稳定分页。
- [ ] 页边界无重复、无遗漏。
- [ ] owner 校验、TTL、过期清理和每用户上限。
- [ ] 候选成员校验支持第 101 名之后的候选。
- [ ] cursor 被修改、跨结果集复用或过期时拒绝。
- [ ] 全量排序不会为全部候选组装详情对象。

### API 集成测试

- [ ] 创建结果返回真实 total 和第一页。
- [ ] 连续翻页可以遍历完整结果集。
- [ ] 用户 A 不能访问用户 B 的结果集和候选详情。
- [ ] 已停用候选不会在后续页中出现。
- [ ] Redis 故障时创建、分页和反馈从 PostgreSQL 严格快照安全降级，且不会返回全量详情。
- [ ] Redis 过期后从 PostgreSQL 快照恢复原始排名和得分。
- [ ] 严格快照超过保留期后返回稳定错误码，并可主动创建一次新匹配。
- [ ] 候选详情变化不会修改历史快照中的 ID、排名和得分。

### 前端测试

- [ ] 聊天首次只渲染预览卡片。
- [ ] 中间区域按页加载并缓存。
- [ ] 总数与当前返回数量分别显示。
- [ ] 分页失败可以重试，不丢失当前页。
- [ ] Redis 缓存过期时分页无感恢复，严格快照过期时可重新匹配。
- [ ] 快速切页时旧请求不会覆盖新页面。

### 性能验收

使用 20,000 条现有数据和“硕士、身高 175 以上”基准条件：

- [ ] 总匹配数保持 4,303，排序顺序与改造前一致。
- [ ] 首次响应候选详情不超过 20～50 条。
- [ ] 首次 JSON/SSE 响应目标小于 200 KB。
- [ ] 4,303 条紧凑 Redis 结果集目标小于 500 KB。
- [ ] 4,303 条 PostgreSQL 严格快照目标控制在 60～120 KB。
- [ ] Redis 临时会话本身目标小于 200 KB。
- [ ] 分页接口 P95 目标小于 300 ms（以预发布环境实测为准）。
- [ ] 连续翻页期间后端内存不随累计页数无界增长。

## 可观测性

新增指标或结构化日志：

- `match_result_total`
- `match_result_compact_bytes`
- `match_result_create_ms`
- `match_result_page_ms`
- `match_result_expired_total`
- `match_result_owner_denied_total`
- `match_result_redis_error_total`
- `match_detail_hydrated_count`
- `match_snapshot_write_ms`
- `match_snapshot_bytes`
- `match_snapshot_restore_total`
- `match_snapshot_expired_total`
- `match_snapshot_table_bytes`

日志只记录 result ID 的短摘要、用户内部 ID、数量、耗时和模型版本，不记录完整画像、手机号或候选敏感详情。

## 发布与兼容顺序

1. **发布 A：严格快照表与双写**
   - 部署新增表和索引；后端写 PostgreSQL 紧凑快照，同时继续返回当前前 100 兼容响应。
2. **发布 B：Redis 结果集与快照回源**
   - 写入 Redis 在线结果集，并验证 Redis miss 可以从 PostgreSQL 恢复。
3. **发布 C：分页 API**
   - 增加分页读取，旧前端不受影响。
4. **发布 D：新前端**
   - 聊天和中间列表改用 result ID + cursor。
5. **发布 E：反馈和会话切换**
   - 成员校验改用结果集，Redis 会话移除全量候选。
6. **发布 F：移除旧兼容**
   - 删除固定前 100、全量 match bag 和重复响应字段。

每一步使用独立提交并可单独回滚。

## 回滚策略

- 增加 `MATCH_RESULT_PAGING_ENABLED` 功能开关。
- 增加独立 `MATCH_SNAPSHOT_ENABLED` 开关；关闭分页时仍可保留已写入快照，不删除历史数据。
- 新后端在兼容期继续返回旧 `candidates` 第一页字段。
- 新前端若没有收到 `result_set_id`，回退到当前前 100 展示逻辑。
- 回滚不得重新启用“把全部完整候选写入 Redis 会话”的旧行为。
- Redis 结果集是临时数据，回滚时可以让其自然过期。
- `app.match_runs` 是只新增的向前兼容表；应用回滚不得删除表或已写快照。
- PostgreSQL 快照写入已经成功但 Redis 写入失败时，允许后续重建 Redis，不回滚快照。
- 快照保留期清理一旦执行不可恢复；清理任务需独立开关并支持 dry-run 统计。

## 已确认的历史恢复语义

本计划采用严格排名与决策快照：

- PostgreSQL 保存完整有序的候选 ID 数组、得分数组、画像、模型版本和数据集版本。
- Redis 过期后恢复同一个快照，不重新运行模型，因此历史排名和得分保持一致。
- 候选详情不做重复快照，历史查看时从当前 PostgreSQL 主表加载，并过滤已停用候选。
- 界面同时显示“当时匹配总数”和“当前可查看数量”，避免把当前详情误认为完整历史数据快照。
- 用户主动点击“重新匹配”时创建新的 `match_run_id`，旧运行记录不被覆盖。

默认在线保留 180 天。是否需要超过 180 天的冷归档由后续合规与运营要求决定，但不影响当前表结构和结果集 API。

## 完成定义

- [ ] 匹配 4,303 人时不再生成或传输 4,303 份完整候选详情。
- [ ] 用户可以分页浏览完整排名，而不是被限制在前 100 人。
- [ ] Redis 只保存紧凑排名引用，并绑定用户、TTL 和容量限制。
- [ ] PostgreSQL 以紧凑数组保存严格排名快照，不重复保存完整候选详情。
- [ ] Redis 过期后能够恢复同一排名快照，不重新运行模型。
- [ ] 反馈、回溯和恢复流程支持第 101 名之后的候选。
- [ ] 两个用户之间结果集完全隔离。
- [ ] 候选停用后不会通过历史结果继续展示。
- [ ] API、前端、性能和 Redis 故障测试通过。
- [ ] 快照增长、WAL、备份容量和 180 天清理任务通过预发布评估。
- [ ] 新旧接口兼容发布和回滚演练完成。
