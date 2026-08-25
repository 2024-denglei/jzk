# 未登录内容隔离与 AI JWT 校验

**日期：** 2026-08-25  
**状态：** 待用户确认规格全文  
**范围：** 未登录只能看捐献者小卡片；详情与 AI 对话必须登录（JWT）

## 背景

站点已有邮箱注册/登录与 JWT（`Authorization: Bearer`，7 天有效）。但当前：

- 列表页、详情页、`GET /api/donors/{code}` 均可匿名访问完整档案（含健康史、遗传病、婚育等）
- `GET /api/featured`、`POST /api/search` 返回的 `donor_info` 也是全字段
- `/api/chat`、`/api/chat/stream`、abort、rewind 可不带 token；流式接口只是**可选**解析 JWT 用于落库

需求：未登录只能看外面的小卡片；看详情必须登录；AI 助手必须 JWT 验证。

## 已确认决策

| 项 | 选择 |
|---|---|
| 隔离方式 | 前后端一起隔离（不只挡页面） |
| 未登录可见 | 首页、关于、登录/注册、捐献者列表小卡片、条件筛选 |
| 点卡片 | 跳转 `/login?next=/donors/:code`，登录后回到该详情 |
| 直链详情 | 未登录同样先登录，再回到该详情 |
| AI 顾问栏 | 未登录可看欢迎语；一点发送（或语音开始）就跳登录 |
| 欢迎语 | 前端写死，未登录不调用对话接口 |
| 列表 JSON | 公开接口只返回卡片字段，不含详情敏感字段 |
| 登录后对话候选人 | 可以返回完整 `donor_info`（已通过 JWT） |
| 详情接口 | `GET /api/donors/{code}` 必须 JWT |
| 对话接口 | `/api/chat`、`/api/chat/stream`、abort、rewind 必须 JWT |

## 非范围

- 改卡片视觉样式或增减卡片上已有展示项
- 改 JWT 有效期、刷新令牌、OAuth
- 未登录禁用条件筛选
- 管理端鉴权（已独立 JWT）
- 把内存对话 session 绑定到用户（现有按 `session_id` 查找的方式保持不变）
- 语音云服务（`/api/voice/transcribe`、`synthesize` 仍为预留；能力探测接口保持公开）

## 公开 vs 需登录

```text
匿名可访问
  页面：/  /about  /login  /register  /donors（列表）
  接口：GET /api/featured
        POST /api/search
        POST /api/auth/login|register
        GET /api/voice/capabilities

必须 JWT（用户令牌，kind 不是 admin）
  页面：/donors/:code  /user  （以及真正使用顾问）
  接口：GET /api/donors/{code}
        POST /api/chat
        POST /api/chat/stream
        POST /api/chat/abort
        POST /api/chat/rewind
        现有 /api/user/* 、/api/auth/me 等（不变）
```

无 token 或 token 无效：HTTP 401，`detail` 为 `未登录` 或 `无效令牌`（沿用 `get_current_user_id`）。

## 卡片字段（公开列表唯一允许的 donor_info）

与当前 `DonorCard` 展示一致，公开接口的 `donor_info` **只含**：

- `id`、`code`
- `education`、`height`、`blood_type`、`age`
- `ethnicity`、`hometown`、`figure`、`personality`、`occupation`
- `specimen_count`、`availability`

候选人外层仍可有：`score`、`match_pct`、`reason`、`match_level`、`field_match`。

**禁止**出现在未登录响应中的字段包括但不限于：Rh、星座、脸型/眼皮/肤色/唇型/鼻梁/发色发型发量/胡须、体重 BMI、爱好分项、喝酒吸烟、病史、性史、婚育、遗传病、检测原文、备注。

实现：在 `core/data_loader.py` 增加 `to_card_donor_info(info: dict) -> dict`，从完整 `get_donor_display_info` 结果中只保留上表键。`GET /api/featured` 与 `POST /api/search` 在返回前对每条 `donor_info` 调用它。

对话流在用户已 JWT 验证后，候选人可以继续用完整 `get_donor_display_info`，无需裁剪。

## 后端改动

### 详情

`GET /api/donors/{code}` 增加 `user_id: int = Depends(get_current_user_id)`。鉴权失败不查库、不记 `open_detail` 反馈。

### 对话

- `POST /api/chat`：`Depends(get_current_user_id)`
- `POST /api/chat/stream`、`abort`、`rewind`：同样强制用户 JWT；删除「可选解析 token」作为唯一鉴权路径
- 流式接口继续用已验证的 `user_id` 做对话落库（现有 `_maybe_persist`）

管理员 token（`kind=admin`）不能当作普通用户使用这些接口：`get_current_user_id` 只认 `sub` 为用户 id。保持与现网用户 JWT 一致即可（用户 token 无 `kind` 或 `kind` 不是 admin）。若 payload 带 `kind=admin`，应 401，避免管理端令牌打开用户详情/对话。

实现约定：在 `get_current_user_id` 中，若 `payload.get("kind") == "admin"` 则视为无效用户令牌（401）。这是小而明确的加固，避免两种令牌串用。

### 列表

featured / search 保持匿名可调用，但必须裁剪 `donor_info`。

## 前端改动

### 卡片与详情路由

- `DonorCard`：已登录 `to=/donors/:code`；未登录 `to=/login?next=/donors/:code`（`next` 需 `encodeURIComponent`）
- `DonorsPage`：`detailCode` 存在且 auth 已加载且无 `user` → `Navigate` 到同样的 login URL（防止收藏夹/直链绕过卡片）
- `DonorDetailPanel`：无 `user` 时不请求详情接口
- 登录成功后按已有逻辑 `navigate(next)`；默认 `next` 仍为 `/user`

### 注册带回跳

从登录页点「注册」时带上当前 `next`；注册成功后跳到该 `next`（没有则 `/user`）。登录页链到注册、注册页链回登录都保留 `next`。

### AI 顾问

- 等 `AuthContext.loading` 结束后再初始化，避免「先当匿名、登录态稍后到达」抢跑
- 未登录：不请求 `/api/chat`；展示固定欢迎语（「描述您的期望，我会帮您筛选合适的候选人。」）
- 输入框可输入；点击发送、快捷建议、语音开始 → `navigate(/login?next=当前 location.pathname+search)`
- 已登录：欢迎走 `/api/chat` 空消息；发言走 `/api/chat/stream`（带 Bearer）；abort/rewind 同样带令牌
- `ChatMatchCards` 只在登录后对话中出现，链接可直达详情

### 401

`api.ts` 在用户接口返回 401 时：清除 `jzk_token`，抛出错误。详情页捕获后跳登录。不在此处处理管理端 `jzk_admin_token`。

## 数据流

```text
未登录浏览
  GET /api/featured 或 POST /api/search
    → 卡片字段 JSON
    → DonorCard
    → 点击 → /login?next=/donors/CODE

登录后看详情
  登录拿到 access_token
    → 跳 next
    → GET /api/donors/CODE  (Bearer)
    → DonorDetailPanel 全字段

未登录点发送
  不调用对话 API
    → /login?next=/donors 或当前页
    → 登录后用户自行再发（不自动重发未发出的那句，避免误发）
```

未发出的输入：**不**在登录后自动重发。用户回到页面后可再输入。输入框内容因页面跳转丢失，可接受。

## 错误处理

| 情况 | 行为 |
|---|---|
| 匿名 GET 详情 | 401；前端跳登录并带 next |
| 匿名 POST 对话 | 401；前端本就不会发；若发了则提示未登录 |
| 过期 JWT | 401 无效令牌；清本地 token，跳登录 |
| 详情代号不存在（已登录） | 仍 404，文案不变 |
| 列表无数据 | 与现在相同的空状态 |

## 测试

新增 API 测试（pytest），覆盖：

1. 无 token 访问 `GET /api/donors/{code}` → 401
2. 有效用户 JWT 访问详情 → 200，响应含完整字段（如 `genetic_history` 键存在）
3. 管理员 JWT 访问详情或 `/api/chat` → 401
4. 无 token `POST /api/chat` 与 `/api/chat/stream` → 401
5. 无 token `GET /api/featured` → 200，且任意 `items[].donor_info` 不含敏感键（至少断言没有 `genetic_history`、`std_history`、`personal_disease`）
6. 无 token `POST /api/search`（带最少条件）→ 200，同样不含敏感键
7. `to_card_donor_info` 单测：输入全字段，输出仅卡片键

不强制上前端 E2E；实现后在浏览器走通：未登录点卡片 → 登录 → 详情；未登录点发送 → 登录；登录后对话正常。

## 模块边界

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `to_card_donor_info` | 裁剪公开 JSON | 不改匹配算法 |
| `get_current_user_id` | 强制用户 JWT；拒绝 admin kind | 不改发 token 的登录接口 |
| 详情/对话路由 | Depends 用户 JWT | 不改匹配与 Agent 内部逻辑 |
| DonorCard / DonorsPage | 未登录跳登录并带 next | 不改卡片内部排版 |
| ChatPanel | 未登录静态欢迎 + 发送跳登录 | 不改已登录流式协议 |
