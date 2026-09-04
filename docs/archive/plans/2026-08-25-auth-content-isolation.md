# 未登录内容隔离与 AI JWT 校验 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 未登录只能看到捐献者小卡片；详情与 AI 对话必须带用户 JWT。

**Architecture:** 公开列表用 `to_card_donor_info` 裁剪字段；详情与对话路由 `Depends(get_current_user_id)`；前端卡片/发送跳 `/login?next=...`。

**Tech Stack:** FastAPI、python-jose JWT、pytest、React + React Router。

规格：`docs/superpowers/specs/2026-08-25-auth-content-isolation-design.md`

## 文件

- Create: `tests/test_card_donor_info.py`
- Create: `tests/test_auth_isolation.py`
- Modify: `core/data_loader.py`（卡片裁剪）
- Modify: `api/auth_utils.py`（拒绝 admin kind）
- Modify: `api/donors.py`、`api/chat.py`、`api/chat_stream.py`、`api/search.py`、`main.py`
- Modify: `web/src/lib/api.ts`、`DonorCard.tsx`、`DonorsPage.tsx`、`DonorDetailPanel.tsx`、`ChatPanel.tsx`、`LoginPage.tsx`、`RegisterPage.tsx`

---

### Task 1: 卡片字段裁剪

**Files:** `core/data_loader.py`, `tests/test_card_donor_info.py`

- [ ] 写失败测试 `to_card_donor_info`：只保留卡片键，丢掉 `genetic_history` 等
- [ ] 实现 `CARD_DONOR_KEYS` + `to_card_donor_info`
- [ ] pytest 通过

### Task 2: 用户 JWT 拒绝管理员令牌

**Files:** `api/auth_utils.py`, `tests/test_auth_isolation.py`

- [ ] 写失败测试：用户 token 返回 id；admin kind 与缺 token 为 401
- [ ] 改 `get_current_user_id`
- [ ] pytest 通过

### Task 3: 详情与对话接口强制 JWT

**Files:** `api/donors.py`, `api/chat.py`, `api/chat_stream.py`, `tests/test_auth_isolation.py`

- [ ] TestClient：无 token 访问详情/chat/stream/abort/rewind → 401；admin token 访问详情/chat → 401
- [ ] 路由加 `Depends(get_current_user_id)`，删除 stream 里可选解析
- [ ] pytest 通过

### Task 4: 公开列表裁剪 donor_info

**Files:** `main.py`, `api/search.py`

- [ ] featured / search 返回前调用 `to_card_donor_info`
- [ ] 单测：对假的完整 info 裁剪后无敏感键（可放在 test_card_donor_info）

### Task 5: 前端隔离

**Files:** 见上 web 列表

- [ ] 卡片未登录跳 login?next=详情
- [ ] 直链详情未登录 Navigate
- [ ] 详情无 user 不请求
- [ ] ChatPanel：loading 结束前不调对话；未登录静态欢迎；发送/语音/建议跳登录
- [ ] 登录/注册互带 next；401 清 `jzk_token`
- [ ] 已登录 chat 请求带 Bearer（改 welcome/new chat 用 `api.post`）

### Task 6: 验证

- [ ] `pytest tests/test_card_donor_info.py tests/test_auth_isolation.py -v`
- [ ] 浏览器：未登录点卡片 → 登录 → 详情；未登录发送 → 登录；登录后对话
