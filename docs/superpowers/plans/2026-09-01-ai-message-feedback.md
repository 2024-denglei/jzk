# AI 回复喜欢/不喜欢与管理端反馈追踪实现计划

## 文档状态

- 日期：2026-09-01
- 状态：待执行
- 范围：用户端 AI 回复反馈、反馈持久化、管理端反馈列表、会话消息精确跳转
- 前置能力：分支化会话、不可变消息树、管理端会话执行时间线已经上线

## 目标

在每一条已完成的 AI 最终回复下提供“喜欢”和“不喜欢”两个图标。用户可以选择、切换或取消反馈。管理端新增统一的对话反馈页面，默认查看“不喜欢”，并能从任意反馈记录准确跳转到对应用户、Session、分支和 AI 回复。

本功能必须保证：

- 反馈关联具体 AI 消息，不只关联会话或生成任务。
- 分支切换后，相同消息仍展示相同反馈；新分支产生的新回复拥有独立反馈。
- 管理端能明确看到“哪个用户对哪条 AI 回复不满意”。
- 点击“查看会话”后直接打开对应线路，并定位、高亮具体回复。
- 反馈不会修改不可变的消息正文，也不会进入模型上下文或影响匹配结果。

## 第一版产品规则

### 可反馈对象

- 只在 `role=assistant` 且 `status=completed` 的最终回复下显示反馈图标。
- 用户消息、系统消息、工具调用、工具结果、生成中、已停止和失败消息不显示反馈入口。
- 候选人卡片属于对应 AI 回复的展示附件，不单独创建反馈；反馈评价整条 AI 回复及其候选结果。
- 历史会话和当前新会话使用同一套反馈交互。

### 点击行为

- 初始状态：两个图标都未选中。
- 点击“喜欢”：保存 `like`。
- 点击“不喜欢”：保存 `dislike`。
- 点击另一个图标：直接替换原反馈，不保留旧版本。
- 再次点击当前已选图标：取消反馈并删除当前记录。
- 客户端采用乐观更新；接口失败时回滚图标状态并显示简短错误提示。
- 第一版不要求用户填写不喜欢原因，不保存反馈历史；后续可在不改变消息关联关系的前提下增加原因分类。

### 分支语义

- 反馈的业务主键是 `message_id`，因为消息是不可变节点。
- 公共祖先消息出现在多条分支中时仍是同一条消息，因此只保留一份反馈。
- 用户在某条分支上点击反馈时同时记录 `branch_id` 作为管理端定位上下文；后续从另一条分支修改同一消息的反馈时，定位分支更新为最近操作所在分支。
- 编辑重发或创建分支产生的新 AI 消息使用新的 `message_id`，不会继承原回复反馈。
- 整个会话被不可恢复删除时，相关反馈同步级联删除。

## 数据模型

新增迁移 `db/postgres/19_add_chat_message_feedback.sql`，并同步更新全新环境基线 `db/postgres/02_schema.sql`。

新增表 `app.chat_message_feedback`：

```sql
message_id   UUID PRIMARY KEY
user_id      BIGINT NOT NULL
chat_id      BIGINT NOT NULL
branch_id    UUID NOT NULL
rating       TEXT NOT NULL CHECK (rating IN ('like', 'dislike'))
created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
```

约束与索引：

- `message_id` 外键关联 `app.chat_messages(id) ON DELETE CASCADE`。
- `user_id`、`chat_id`、`branch_id` 建立对应外键；优先使用现有复合唯一键保证资源属于同一会话。
- 数据库校验函数保证：会话属于该用户、分支属于该会话、消息位于该分支路径中，并且消息是已完成的 AI 消息。
- `message_id` 作为主键，天然保证一条 AI 回复只有一个当前反馈。
- 管理端默认查询索引：`(rating, updated_at DESC, message_id DESC)`。
- 用户查询索引：`(user_id, updated_at DESC, message_id DESC)`。
- 会话定位索引：`(chat_id, branch_id, message_id)`。

不把 `rating` 直接加到 `chat_messages`：终态消息不可变，反馈属于可变的用户行为数据，应使用独立表。

## 领域契约

在 `db/chat_models.py` 增加：

- `MessageFeedbackRating`：`like | dislike`。
- `MessageFeedbackView`：`message_id`、`rating`、`updated_at`。
- `ChatMessageView.feedback`：可空反馈字段，用于历史加载时直接恢复图标状态。
- 管理端 `AdminMessageFeedbackItem` 和游标分页响应模型。

兼容规则：

- `feedback=null` 表示未反馈。
- 旧会话无需回填。
- 不以 `generation_id` 作为关联键，兼容没有完整生成记录的历史 AI 消息。

## 用户端 API

### 保存或切换反馈

```http
PUT /api/messages/{message_id}/feedback
Content-Type: application/json

{
  "branch_id": "uuid",
  "rating": "like"
}
```

返回：

```json
{
  "message_id": "uuid",
  "rating": "like",
  "updated_at": "2026-09-01T...Z"
}
```

### 取消反馈

```http
DELETE /api/messages/{message_id}/feedback
```

返回 `{ "ok": true }`；记录不存在时也返回成功，保证重复点击和网络重试幂等。

### 安全边界

- 两个接口都使用当前登录用户身份，不接受客户端传入 `user_id` 或 `chat_id`。
- 服务端从消息反查会话所有者，禁止对他人消息反馈，避免 IDOR。
- 保存前校验消息角色、终态状态、分支归属和分支路径。
- 不存在、无权访问和不符合反馈条件的消息统一返回安全的 404/409，不暴露其他用户资源。
- 限制单用户写入频率，防止自动化反复切换造成数据库压力。

## 数据访问层

新增 `db/chat_feedback_repo.py`，提供：

- `set_message_feedback(user_id, message_id, branch_id, rating)`：事务内校验并使用 `INSERT ... ON CONFLICT (message_id) DO UPDATE`。
- `delete_message_feedback(user_id, message_id)`：按所有者删除，幂等返回。
- `get_feedback_for_messages(user_id, message_ids)`：批量读取，禁止逐消息查询。
- `list_admin_feedback(...)`：按评分、用户和日期游标分页。
- `get_admin_feedback_summary(...)`：返回喜欢、不喜欢总数和最近不喜欢数量。

扩展 `db/chat_queries_repo.py` 的消息路径查询，批量左连接当前用户反馈，使历史消息首屏和翻页响应都带 `feedback`，不增加 N+1 查询。

## 用户端交互

修改 `web/src/features/chat/BranchingChatPanel.tsx`：

- 每条已完成 AI 回复底部右侧增加两个小图标：`ri-thumb-up-line`、`ri-thumb-down-line`。
- 使用 `title`、`aria-label`、`aria-pressed`，保证键盘和读屏可用。
- 未选择时使用低对比度；喜欢选中使用青绿色；不喜欢选中使用柔和红色。
- 图标区域与“创建分支”“完整排名”等消息操作保持同一尺寸和间距，但视觉上分组，避免误触。
- 点击后只更新当前 `message_id`，不刷新整棵会话树、不刷新候选人列表。
- 请求进行中只锁定该消息的两个反馈按钮。
- 加载历史分支时直接使用消息响应中的 `feedback` 恢复状态。

扩展 `web/src/features/chat/chatApi.ts`：

- `setFeedback(messageId, branchId, rating)`。
- `deleteFeedback(messageId)`。

在客户端状态层使用按 `message_id` 更新的纯函数，补充切换、取消和失败回滚测试。

## 管理端反馈页面

新增全局页面 `/admin/chat-feedback`，放在“用户管理”导航分组下，菜单名为“对话反馈”。第一版复用现有 `users:view` 权限，因为该权限已经允许管理员读取相同用户的完整会话内容；如果以后开放给客服角色，再拆分独立权限。

页面默认展示“不喜欢”，包含：

- 顶部统计：喜欢数量、不喜欢数量、最近 7 天不喜欢数量。
- 筛选：不喜欢/喜欢/全部、用户 UID、反馈日期。
- 列表字段：反馈类型、用户、Session ID、分支名称、AI 回复摘要、反馈时间。
- AI 回复摘要只返回截断文本；列表不加载完整消息、Trace 或完整排名。
- 每条记录提供“查看会话”，默认按反馈时间倒序并使用签名游标分页。

新增：

- `api/admin_chat_feedback.py`
- `web/src/pages/admin/ChatFeedbackView.tsx`
- `web/src/pages/admin/chat/adminChatFeedbackApi.ts`

并修改：

- `main.py`：注册管理端反馈路由。
- `web/src/pages/AdminPage.tsx`：分发 `/admin/chat-feedback`。
- `web/src/pages/admin/AdminShell.tsx`：增加菜单。
- 管理端读取列表及跳转详情都写入现有 `admin.user_audit_logs`，审计记录只保存资源 ID 和筛选条件，不复制回复正文。

## 管理端精确跳转

“查看会话”使用稳定深链：

```text
/admin/users/{user_id}?tab=chats&chat_id={chat_id}&branch_id={branch_id}&message_id={message_id}
```

需要完成以下改造：

1. `UserProfileView` 从查询参数初始化 `chats` 标签，并在切换标签时同步 URL。
2. `AdminConversationWorkspace` 接收目标 `chatId`、`branchId`、`messageId`，不依赖该会话先出现在左侧第一页。
3. 打开目标会话树并选择记录中的分支。
4. 为管理端增加按锚点加载消息上下文的接口，避免目标消息较早时连续请求几十页：

```http
GET /api/admin/users/{user_id}/conversations/{chat_id}/branches/{branch_id}/messages/{message_id}/context
```

5. 上下文接口用递归查询验证目标消息确实位于该分支路径，并返回目标前后有界消息段及继续加载游标。
6. 页面加载完成后滚动到 `data-message-id={message_id}`，使用浅黄色描边高亮；高亮数秒后减弱，但保留“当前定位消息”标识。
7. 同时加载该 AI 回复对应的真实 Agent Trace 和完整排名入口，管理员看到的仍是现有模块化执行时间线。
8. URL 参数无效或会话已被用户删除时显示“反馈对应会话已不存在”，不得跳转到其他会话代替。

## 管理端 API

### 反馈列表

```http
GET /api/admin/chat-feedback?rating=dislike&user_id=&date_from=&date_to=&cursor=&limit=20
```

列表项至少返回：

```json
{
  "message_id": "uuid",
  "rating": "dislike",
  "user_id": 123,
  "user_display": "用户昵称或 UID",
  "chat_id": 355,
  "branch_id": "uuid",
  "branch_name": "分支 1",
  "message_preview": "回复摘要……",
  "updated_at": "2026-09-01T...Z"
}
```

### 反馈统计

```http
GET /api/admin/chat-feedback/summary
```

统计查询与列表查询都不能解析 Trace、状态快照或排名 JSON，只访问反馈表和必要的用户、会话、分支、消息摘要字段。

## 实施阶段

### 阶段 1：契约与数据库

- 新增反馈枚举、响应模型和迁移。
- 更新全新数据库基线和迁移顺序测试。
- 用真实 PostgreSQL 验证迁移可重复执行、跨用户写入被拒绝、非 AI 消息被拒绝、会话删除级联清理。

### 阶段 2：用户反馈仓储与 API

- 实现设置、切换、取消和批量加载。
- 将反馈合并进消息路径响应。
- 增加鉴权、归属、幂等和并发更新测试。

### 阶段 3：客户端交互

- 添加喜欢/不喜欢图标和乐观更新。
- 覆盖当前会话、历史会话、分支公共消息、新分支独立消息等场景。
- 确认反馈操作不触发中间候选列表刷新。

### 阶段 4：管理端反馈列表

- 增加管理 API、统计、游标分页、筛选和敏感读取审计。
- 增加全局反馈页面与导航入口，默认筛选“不喜欢”。

### 阶段 5：会话深链与消息定位

- 增加锚点上下文查询。
- 让用户档案、会话工作区和 URL 查询参数双向同步。
- 完成自动选择 Session、分支、目标消息，高亮并加载该轮 Agent 详情。

### 阶段 6：回归与上线

- 执行完整后端测试、前端测试、TypeScript 构建和 lint。
- 先执行数据库迁移，再部署后端，最后发布用户端和管理端。
- 不需要历史数据回填；上线前所有消息默认未反馈。
- 上线后检查反馈写入错误率、管理列表查询耗时和深链定位失败率。

## 测试清单

### 后端

- 只能反馈本人会话中已完成的 AI 消息。
- 喜欢可切换为不喜欢，同一消息始终只有一条当前记录。
- 再次点击已选项后删除反馈，重复删除仍成功。
- 并发 PUT 最终只保留一条合法记录。
- 公共祖先消息从不同分支操作不会产生重复反馈。
- 消息分页批量返回反馈，不发生 N+1。
- 管理列表默认只返回不喜欢，筛选和游标无重复、无遗漏。
- 普通用户不能访问管理接口；无 `users:view` 权限的管理员返回 403。
- 深链上下文拒绝不属于目标分支的消息。
- 删除会话后消息、反馈和相关管理列表项全部消失。

### 前端

- 只有已完成 AI 回复显示反馈图标。
- 未选、喜欢、不喜欢、请求中和失败回滚状态正确。
- 历史分支加载后能恢复反馈状态。
- 在公共祖先消息上切换分支不会丢失反馈。
- 管理列表筛选、分页和空状态正确。
- 点击“查看会话”生成完整深链并精确高亮目标回复。
- 直接刷新深链页面仍能恢复相同 Session、分支和消息。

### 手工验收

1. 用户对主线第一条 AI 回复点击“不喜欢”。
2. 管理员在“对话反馈”默认列表中看到该用户和回复摘要。
3. 点击“查看会话”，页面打开正确用户的 AI 会话标签。
4. 自动选中正确 Session 和分支，并高亮同一条 AI 回复。
5. 管理员展开该轮模块，能查看系统提示词、用户消息、模型回复、工具调用、工具结果和排名快照。
6. 用户将“不喜欢”切换为“喜欢”后，该记录从管理端“不喜欢”筛选中消失，并出现在“喜欢”筛选中。
7. 用户取消反馈后，管理端不再显示该记录。

## 非目标

- 第一版不收集文字评价、不提供举报或客服工单。
- 第一版不保留用户切换反馈的历史版本。
- 第一版不根据喜欢/不喜欢自动调整模型提示词、匹配算法或用户偏好。
- 第一版不对工具调用、工具结果或单个候选人分别评分。
- 第一版不展示公开点赞数，也不允许管理员代替用户修改反馈。

## 完成标准

- 用户能在每条已完成 AI 回复下可靠地设置、切换和取消喜欢/不喜欢。
- 反馈以 `message_id` 为唯一评价对象，并与分支上下文正确关联。
- 管理端可按用户和评分查询反馈，默认快速发现不满意回复。
- 任意反馈都能通过稳定 URL 打开正确会话线路并定位到具体 AI 回复。
- 会话硬删除、权限、审计、分页和性能行为符合现有分支化会话架构。
- 全部新增测试及项目现有回归测试通过。
