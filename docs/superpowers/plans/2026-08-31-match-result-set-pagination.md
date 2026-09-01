# 匹配结果集与候选详情分页实施计划

## 背景

当前匹配流程会对所有符合必要条件的候选人完成排序，并为每一位候选人组装完整的 `donor_info`、`field_scores`、`field_match` 等详情。随后 `/api/match` 才根据 `top_k` 截断返回内容。

当“硕士、身高 175 以上”匹配到 4,303 人时，这种结构产生了三个问题：

- 匹配层为全部 4,303 人组装重对象，即使最终只返回前 100 人也会浪费内存和 CPU。
- 全量候选详情进入 Redis 临时会话后超过 2 MB 会话上限。
- 全量结果通过 SSE 发送给浏览器，会增加响应时间、网络流量和前端内存占用。

提交 `102b5e7` 已将聊天返回详情临时限制为前 100 人，并保留总匹配人数。这是安全止血措施，不应成为长期业务上限。

## 目标

- 匹配逻辑仍对全部候选人完成排序，不丢失第 101 名之后的结果。
- 全量结果仅保存紧凑的 `donor_id + rank + score`，不保存完整候选详情。
- Redis 保存绑定用户的临时匹配结果集，支持稳定分页、成员校验和自动过期。
- 首次匹配和后续分页只为当前页候选人组装卡片详情。
- 聊天侧展示真实总人数，并允许用户分页浏览全部结果。
- 反馈接口允许反馈结果集中任意候选人，而不是只允许前 100 人。
- Redis 结果过期后能够安全地重新执行匹配，不影响 PostgreSQL 中的长期对话。

## 非目标

- 本阶段不修改模型算法、特征权重或排序结果。
- 本阶段不把捐精人主数据迁入 Redis。
- 本阶段不允许客户端提交任意候选 ID 批量查询详情。
- 第一版不永久保存每一次匹配的全部排名快照；如有合规审计要求，再增加 PostgreSQL 匹配快照表。

## 核心设计结论

不让匹配模型把全部完整候选详情返回给 API 或前端。模型层输出紧凑排名引用，应用层将完整排名存入 Redis，并按页从 PostgreSQL 加载当前需要展示的候选详情。

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
              Redis MatchResultStore
                       │ result_set_id
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

jzk:match-result:{result_set_id}:rank
  ZSET score=rank, member=donor_id

jzk:match-result:{result_set_id}:scores
  HASH donor_id -> match_score

jzk:match-result-subject:{user_id}
  ZSET score=expires_at, member=result_set_id
```

说明：

- 排名 ZSET 使用 `rank` 而不是匹配得分作为 Redis score，保证翻页顺序与模型顺序完全一致。
- 匹配得分单独保存在 HASH 中。
- `ZSCORE rank donor_id` 可用于反馈成员校验。
- `ZRANGE start stop WITHSCORES` 用于稳定分页。
- meta 必须保存 `owner_user_id`，读取时同时校验 key、meta 和当前登录用户。
- 创建结果集使用 pipeline/Lua，确保 meta、rank、scores 和 TTL 不出现部分写入。

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

- 用户访问结果时可以刷新空闲 TTL，但不得超过绝对最大生命周期。
- 新建结果集前清理用户索引中的过期成员。
- 超过每用户上限时删除最旧结果集，或返回明确的容量异常；第一版建议删除最旧结果集。
- Redis 不可用时匹配结果创建和分页失败关闭，返回 503，不退回全量详情响应。

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
- 旧 `top_k` 暂时保留；新聊天调用改用 `page_size`，不再把 `top_k` 当业务总量。
- 前端迁移完成后删除 `candidates` 兼容字段和聊天专用 `CHAT_MATCH_TOP_K` 止血逻辑。

### 分页读取

新增：

```http
GET /api/match/results/{result_set_id}?cursor={cursor}&limit=20
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
- `limit` 最大 50。
- 结果集不存在或不属于当前用户统一返回 404。
- 属于当前用户但已过期可以返回 410，并附带可重新匹配的稳定错误码 `MATCH_RESULT_EXPIRED`。
- PostgreSQL 查询必须包含 `status = 'active'`；已停用候选不再返回。
- 当前页有停用候选时继续向后读取少量排名，尽量补足页面，并返回实际 `items` 数量。
- 批量查询后按照 Redis rank 重新排序，不能依赖 SQL 默认顺序。

### 重新生成结果集

新增或复用匹配接口：

```http
POST /api/match/results/{result_set_id}/refresh
```

仅当前用户可操作。服务端读取旧 meta 中的画像，重新运行当前模型并返回新的 `result_set_id`。旧结果集保持到 TTL 到期，避免并发页面立即失效。

## 后端实施阶段

### 阶段一：MatchResultStore（P0）

**主要文件：**

- 新增：`core/preference/result_types.py`
- 新增：`api/match_result_store.py`
- 修改：`config.py`
- 修改：`.env.example`
- 新增：`tests/test_match_result_store.py`

- [ ] 定义 `RankedCandidateRef` 和结果集 meta 类型。
- [ ] 实现结果集创建、分页、成员校验、删除和按用户撤销。
- [ ] 使用 Lua/pipeline 原子写入并设置所有 key TTL。
- [ ] 所有读取校验 `owner_user_id`。
- [ ] 实现每用户结果集数量和单结果集候选数量限制。
- [ ] Redis 异常转换为统一 503 错误。
- [ ] 记录结果集条数、字节估算、创建耗时和分页耗时，不记录画像明文敏感值。

### 阶段二：拆分排序引用与详情组装（P0）

**主要文件：**

- 修改：`core/preference/pipeline.py`
- 修改：`core/preference/v2_ranker.py`
- 修改：`core/data_loader.py` 或新增候选详情仓储
- 修改：`api/match.py`
- 新增：`tests/preference/test_compact_match_results.py`

- [ ] 排序器输出全量轻量引用，不再立即调用 `_candidate_dict` 组装全部详情。
- [ ] 在排序过程中计算 `prefer_hits`、总数和瓶颈信息。
- [ ] 仅为第一页引用组装完整候选卡片。
- [ ] 后续页通过 PostgreSQL `WHERE id = ANY(...)` 一次批量加载。
- [ ] 批量详情结果按 Redis rank 恢复顺序。
- [ ] 保留模型版本、画像 hash 和耗时字段。
- [ ] 测试确保匹配 4,303 人时详情组装函数只调用当前页次数，而不是 4,303 次。

### 阶段三：分页 API 与权限隔离（P0）

**主要文件：**

- 修改：`api/match.py`
- 修改：`main.py`
- 新增：`api/match_results.py`（如需拆分路由）
- 新增：`tests/test_match_results_api.py`

- [ ] `POST /api/match` 创建结果集并返回第一页。
- [ ] 实现分页、刷新和主动删除接口。
- [ ] cursor 签名并校验 result ID、offset、版本和有效期。
- [ ] 用户 A 读取用户 B 结果集时返回 404。
- [ ] 结果过期返回稳定错误码，前端可触发重新匹配。
- [ ] 候选停用后分页接口不再返回该候选。
- [ ] Redis 不可用时返回 503，不返回未受控全量详情。

### 阶段四：聊天会话、回滚与反馈（P1）

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

- [ ] `SessionContext` 增加 `match_result_id`、`match_total` 和 `match_next_cursor`。
- [ ] Redis 会话仅保存结果集引用和聊天卡片预览，不保存全量候选详情。
- [ ] checkpoint/abort/rewind 同时恢复结果集引用。
- [ ] SSE `candidates` 事件返回第一页、总数、result ID 和 cursor。
- [ ] 反馈接口通过结果集成员关系校验候选，而不是检查 `session.candidates` 预览数组。
- [ ] 结果集仍必须属于当前会话用户。
- [ ] 长期聊天保存画像、总数、模型版本和少量预览，不依赖 Redis 永久存在。
- [ ] 恢复长期聊天时，结果仍有效则继续分页；已过期则提供“重新生成结果”动作。

### 阶段五：React 懒加载分页（P1）

**主要文件：**

- 修改：`web/src/types.ts`
- 修改：`web/src/components/ChatPanel.tsx`
- 修改：`web/src/components/ChatMatchCards.tsx`
- 修改：`web/src/pages/DonorsPage.tsx`
- 修改：`web/src/lib/api.ts`
- 新增/扩展前端测试

- [ ] 前端状态从 `Candidate[]` 改为 `MatchResultDescriptor`。
- [ ] 首次仅保存第一页候选和总数。
- [ ] 中间候选区切页时调用后端分页接口。
- [ ] 按 `result_set_id + cursor` 缓存已加载页面，避免重复请求。
- [ ] 翻页期间显示局部 loading，不清空已显示页面。
- [ ] 结果过期时显示“结果已过期，重新匹配”按钮。
- [ ] 文案明确“共 4,303 位，当前显示第 1～20 位”，不再声称本地已持有全部数据。
- [ ] 新对话、回溯、恢复历史和退出登录时清理无用页面缓存。

### 阶段六：移除止血兼容与优化（P2）

- [ ] 前后端稳定后移除聊天固定前 100 的业务限制。
- [ ] 停止在 `/api/match` 返回重复的 `items`/`candidates` 兼容字段。
- [ ] 删除 `matchBagsRef` 中保存全量候选的旧逻辑。
- [ ] 对 Redis 结果集启用压缩前先通过真实数据评估；没有收益时不增加复杂度。
- [ ] 根据指标调整 TTL、每用户结果集上限和页大小。

## 测试计划

### 单元测试

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
- [ ] Redis 故障时创建、分页、反馈全部失败关闭。
- [ ] 结果集过期后能够使用保存画像重新匹配。

### 前端测试

- [ ] 聊天首次只渲染预览卡片。
- [ ] 中间区域按页加载并缓存。
- [ ] 总数与当前返回数量分别显示。
- [ ] 分页失败可以重试，不丢失当前页。
- [ ] 结果过期可重新匹配。
- [ ] 快速切页时旧请求不会覆盖新页面。

### 性能验收

使用 20,000 条现有数据和“硕士、身高 175 以上”基准条件：

- [ ] 总匹配数保持 4,303，排序顺序与改造前一致。
- [ ] 首次响应候选详情不超过 20～50 条。
- [ ] 首次 JSON/SSE 响应目标小于 200 KB。
- [ ] 4,303 条紧凑 Redis 结果集目标小于 500 KB。
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

日志只记录 result ID 的短摘要、用户内部 ID、数量、耗时和模型版本，不记录完整画像、手机号或候选敏感详情。

## 发布与兼容顺序

1. **发布 A：结果集 Store 和指标**
   - 后端写入 Redis 结果集，但继续返回当前前 100 兼容响应。
2. **发布 B：分页 API**
   - 增加分页读取，旧前端不受影响。
3. **发布 C：新前端**
   - 聊天和中间列表改用 result ID + cursor。
4. **发布 D：反馈和会话切换**
   - 成员校验改用结果集，Redis 会话移除全量候选。
5. **发布 E：移除旧兼容**
   - 删除固定前 100、全量 match bag 和重复响应字段。

每一步使用独立提交并可单独回滚。

## 回滚策略

- 增加 `MATCH_RESULT_PAGING_ENABLED` 功能开关。
- 新后端在兼容期继续返回旧 `candidates` 第一页字段。
- 新前端若没有收到 `result_set_id`，回退到当前前 100 展示逻辑。
- 回滚不得重新启用“把全部完整候选写入 Redis 会话”的旧行为。
- Redis 结果集是临时数据，回滚时可以让其自然过期，无需数据迁移。
- PostgreSQL 主数据和现有长期聊天结构保持向前兼容。

## 需要产品确认的决策

实施前需要确认一个产品语义：历史聊天恢复时，是否必须还原当时完全一致的全部排名。

- **建议方案：重新匹配。** PostgreSQL 保存画像、模型版本、总数和前 20 位预览；Redis 过期后使用当前有效候选和当前模型重新生成结果，界面提示“结果已更新”。存储成本低，也能自动排除已停用候选。
- **严格快照方案：永久保留。** 新增 PostgreSQL `match_runs` 与 `match_run_items`，保存每次运行的全部 donor ID、rank、score 和模型版本。可审计、可复现，但数据量和治理成本明显更高。

如果没有明确合规要求，第一版采用“重新匹配”，严格快照作为后续增强。

## 完成定义

- [ ] 匹配 4,303 人时不再生成或传输 4,303 份完整候选详情。
- [ ] 用户可以分页浏览完整排名，而不是被限制在前 100 人。
- [ ] Redis 只保存紧凑排名引用，并绑定用户、TTL 和容量限制。
- [ ] 反馈、回溯和恢复流程支持第 101 名之后的候选。
- [ ] 两个用户之间结果集完全隔离。
- [ ] 候选停用后不会通过历史结果继续展示。
- [ ] API、前端、性能和 Redis 故障测试通过。
- [ ] 新旧接口兼容发布和回滚演练完成。
