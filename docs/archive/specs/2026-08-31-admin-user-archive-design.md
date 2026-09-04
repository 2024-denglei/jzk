# 管理端用户档案与账号控制设计

日期：2026-08-31

## 1. 目标

在现有管理端中增加完整的用户档案管理能力，并将管理端改造成独立后台工作台。管理员可以：

- 检索和查看用户档案；
- 查看用户收藏、浏览/搜索/匹配历史；
- 查看用户与 AI 的历史会话内容；
- 强制用户下线；
- 停用和恢复用户账号；
- 查看上述管理操作留下的审计记录。

本期不实现实名认证审核，也暂不区分 `super_admin` 与普通管理员。所有已登录管理员拥有相同的用户档案查看与账号控制权限。

## 2. 范围

### 2.1 本期包含

- 独立的 `/admin/*` 管理端布局和导航；
- 用户档案统计、列表、筛选和服务端分页；
- 用户档案详情；
- 收藏记录、历史记录和 AI 会话记录；
- 账号强制下线、停用、恢复；
- 用户管理审计；
- 保留现有捐献者档案、Excel 导入和捐献者审计功能。

### 2.2 本期不包含

- 实名认证及审核流程；
- 管理员角色差异化授权；
- 管理员编辑用户收藏、历史或会话内容；
- 物理删除用户；
- 将旧 JSON 会话拆分迁移成逐消息关系表。

## 3. 信息架构

管理端使用左侧深色导航、顶部身份栏和浅色内容区。

```text
工作台
用户管理
  └─ 用户档案
捐献者管理
  ├─ 档案列表
  └─ Excel 导入
数据中心
  └─ 操作审计
```

用户档案详情使用以下标签页：

```text
档案概览｜收藏记录｜浏览历史｜AI 会话｜管理记录
```

## 4. 数据模型

### 4.1 `app.users` 扩展字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | TEXT | `active` 或 `disabled` |
| `token_version` | INTEGER | 登录凭证版本，用于强制下线 |
| `last_login_at` | TIMESTAMPTZ | 最近成功登录时间 |
| `updated_at` | TIMESTAMPTZ | 档案更新时间 |
| `disabled_at` | TIMESTAMPTZ | 最近停用时间 |
| `disabled_reason` | TEXT | 最近停用原因 |

### 4.2 `app.chats` 扩展字段

增加 `created_at`，用于区分会话创建和最后更新时间；增加 `(user_id, session_id)` 唯一索引，使现有 upsert 语义在数据库层得到保证。

现有会话以 JSON 保存，并最多保留最近 40 条消息。本期后台按现状只读展示，不改变用户端会话保存上限。

### 4.3 `admin.user_audit_logs`

记录用户账号管理和敏感数据查看动作：

| 字段 | 说明 |
|---|---|
| `user_id` | 被操作用户 |
| `action` | `view_chat`、`kick`、`disable`、`enable` |
| `operator_id` | 管理员 |
| `reason` | 操作原因 |
| `before_data` / `after_data` | 账号状态变化快照 |
| `created_at` | 操作时间 |

查看 AI 会话详情时写入 `view_chat`，账号控制操作必须写入原因和状态快照。

## 5. 登录凭证失效机制

用户 JWT 增加 `ver` 字段，对应 `app.users.token_version`。

- 登录成功时查询当前版本并签发 JWT；
- 每次访问受保护接口时查询用户的 `status` 与 `token_version`；
- JWT 版本和数据库版本不一致时返回 401；
- 强制下线：`token_version + 1`，账号仍为 `active`；
- 停用账号：状态改为 `disabled`，同时 `token_version + 1`；
- 恢复账号：状态改为 `active`，用户需要重新登录。

密码登录和验证码登录都拒绝 `disabled` 用户。

## 6. 管理端 API

```text
GET  /api/admin/users/summary
GET  /api/admin/users
GET  /api/admin/users/{user_id}
GET  /api/admin/users/{user_id}/favorites
GET  /api/admin/users/{user_id}/history
GET  /api/admin/users/{user_id}/chats
GET  /api/admin/users/{user_id}/chats/{chat_id}
GET  /api/admin/users/{user_id}/audit

POST /api/admin/users/{user_id}/kick
POST /api/admin/users/{user_id}/disable
POST /api/admin/users/{user_id}/enable
```

所有列表接口支持 `page`、`page_size`，用户列表额外支持关键词、状态和注册时间筛选。历史接口支持 `kind=browse|search|match`。

用户详情返回档案基础数据和收藏、历史、会话数量，不返回密码哈希。管理端界面默认对手机号和邮箱做部分脱敏。

## 7. 页面交互

### 7.1 用户档案列表

- 指标卡：用户总数、正常用户、已停用用户、今日新增；
- 查询：用户 ID、昵称、手机号或邮箱；
- 状态筛选：全部、正常、已停用；
- 表格：用户、联系方式、注册时间、最近登录、收藏数、历史数、会话数、状态、操作；
- 行操作：查看档案、强制下线、停用/恢复。

### 7.2 用户档案详情

- 顶部显示昵称、用户 ID、账号状态、注册和登录时间；
- 账号控制操作使用确认弹窗，停用与强制下线要求填写原因；
- 收藏记录可跳转到对应捐献者档案；
- 浏览历史按类型筛选，并以摘要形式展示 payload；
- AI 会话采用会话列表和聊天气泡详情；
- 管理记录展示操作、管理员、原因和时间。

## 8. 安全和审计

- 管理端接口统一使用管理员 JWT；
- 管理端永不返回 `password_hash`；
- AI 会话只读，每次查看详情记录审计；
- 账号状态变更和强制下线必须二次确认；
- 本期所有管理员权限一致，但 API 结构保留未来增加角色校验的空间。

## 9. 测试与验收

- 正常用户可通过密码和验证码登录；
- 停用用户不能登录或访问受保护接口；
- 强制下线后旧 JWT 立即失效，重新登录可恢复访问；
- 管理员可以分页检索用户并读取档案关联数据；
- 管理员不能读取其他用户范围之外的错误会话 ID；
- 查看会话、强制下线、停用和恢复均写入审计；
- 前端构建、代码检查和后端测试全部通过。
