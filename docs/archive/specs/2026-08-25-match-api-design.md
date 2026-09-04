# 统一匹配 HTTP 接口

**日期：** 2026-08-25  
**状态：** 已实现  
**范围：** 把校验后的 PreferenceProfile JSON 交给一个 HTTP 接口，由该接口内部完成 must 过滤 + 打分排序

## 背景

对话流在 `POST /api/chat/stream` 里解析大模型工具参数后，进程内调用 `run_preference_match` → `match_profile()`（SQL 硬过滤 + `HeuristicRanker`）。匹配层没有独立 HTTP，以后换成其他排序模型时，调用方必须改对话代码。

需求：做一个接口，自己完成 filter 与 rank；入参是完整偏好 JSON。对话与外部服务都走同一契约，换模型时只换接口内部实现。

画像字段、must/prefer、不自动放宽等规则沿用 `2026-08-21-preference-profile-matching-design.md`。文档中的 `POST /v1/filter`、`POST /v1/rank` **本规格不实现为两个 HTTP**。

## 已确认决策

| 项 | 选择 |
|---|---|
| 形态 | 一个接口，内部先 filter 再 rank |
| 路径 | `POST /api/match` |
| 入参 | 完整 PreferenceProfile（`schema_version` + `attributes`）+ 可选 `top_k` |
| 鉴权 | 用户 JWT（与对话、详情一致；管理员 token 拒绝） |
| 实现 | 复用 `parse_profile` + `match_profile`，不重写算法 |
| 对话 | 大模型出 JSON 后调用 `POST /api/match`（本进程 ASGI；可配 `MATCH_API_URL` 指向外部） |
| 换模型 | 只替换 Ranker / 本接口内部；请求 JSON 不变 |
| 出参 | 含 `candidates`（`donor_info`、`score`、`field_scores` 等） |
| 登录后档案 | `donor_info` 用完整 `get_donor_display_info` |
| 空 attributes | `200`，`skipped: true`，不查库 |
| 0 命中 | `200`，`candidates: []`，`bottlenecks` 说明过严字段 |
| 非法画像 | `400` |

## 非范围

- 拆成 `/v1/filter` 与 `/v1/rank` 两个 HTTP
- 左侧 `POST /api/search`
- 本接口内调用大模型
- 训练排序模型本身
- 对话改为 HTTP 回环调用 `/api/match`

## 架构

```text
调用方（对话 Agent / 外部服务）
  → JWT
  → POST /api/match { profile, top_k? }
  → parse_profile（非法 400）
  → match_profile
       → build_hard_filter_sql（仅 must）
       → HeuristicRanker.rank
  → JSON：candidates + bottlenecks
```

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `POST /api/match` | 鉴权、校验、截断 top_k、组响应 | 不理解自然语言 |
| `parse_profile` | 字段/枚举/weight 校验 | 不补全未提及偏好 |
| `match_profile` | 过滤 + 排序 | 不改画像 |
| `chat_stream` | LLM 出 JSON 后调用 `POST /api/match` | 不自己写过滤/打分 |

以后换模型：实现新的 `Ranker`，在 `match_profile` 注入；或把 `match_profile` 换成请求外部服务。HTTP 路径与 `profile` JSON 保持不变。

## 请求

`POST /api/match`  
`Authorization: Bearer <用户 JWT>`  
`Content-Type: application/json`

```json
{
  "top_k": 100,
  "profile": {
    "schema_version": "1.0",
    "attributes": {
      "abo_blood": {
        "constraint": "must",
        "weight": 1.0,
        "values": ["O"]
      },
      "height_cm": {
        "constraint": "prefer",
        "weight": 0.8,
        "range": { "min": 175, "max": null }
      }
    }
  }
}
```

| 字段 | 必须 | 说明 |
|---|---|---|
| profile | 是 | 与对话工具 `submit_preference_profile` 相同的 PreferenceProfile |
| top_k | 否 | 返回前 K 名；缺省或 `0` 表示不过滤人数（仍受匹配层自身上限若有） |

`profile` 规则与现有校验一致：`schema_version` 必须 `"1.0"`；未出现的字段视为无偏好；禁止未注册字段与系统字段；每个属性必须有 `constraint`、`weight`；range/enum/keyword 形状由字段注册表决定。

## 响应

### 有结果 `200`

```json
{
  "ok": true,
  "skipped": false,
  "match_level": "full",
  "filtered_count": 2,
  "bottlenecks": [],
  "candidates": [
    {
      "rank": 1,
      "score": 0.91,
      "match_pct": 91.0,
      "reason": "匹配：abo_blood、height_cm",
      "match_level": "full",
      "donor_info": {
        "code": "A2600001",
        "education": "硕士",
        "height": 185,
        "blood_type": "O",
        "age": 28,
        "ethnicity": "汉族",
        "hometown": "四川",
        "figure": "匀称型",
        "personality": "开朗",
        "occupation": "工程师",
        "specimen_count": 12,
        "availability": "可用"
      },
      "field_match": {
        "abo_blood": { "match": true, "user": "O", "actual": "O" },
        "height_cm": { "match": false, "user": "{'min': 175}", "actual": 185 }
      },
      "field_scores": [
        { "field": "abo_blood", "s": 1.0, "weight": 1.0, "actual": "O", "target": ["O"] },
        { "field": "height_cm", "s": 0.8, "weight": 0.8, "actual": 185, "target": { "min": 175, "max": null } }
      ]
    }
  ]
}
```

`donor_info` 实际为 `get_donor_display_info` 全字段（含健康史等）。上表只列出卡片常用键。`score` 为加权平均 ∈[0,1]；`match_pct` 为分项分均值 ×100。`filtered_count` 为硬过滤后、截断 top_k 前的人数。

### 0 命中 `200`

```json
{
  "ok": true,
  "skipped": false,
  "match_level": "none",
  "filtered_count": 0,
  "candidates": [],
  "bottlenecks": [{ "field": "abo_blood", "recovered": 120 }]
}
```

不自动放宽 must。`recovered`：将该 must 改为 prefer 后能命中的人数。

### 空画像 `200`

```json
{
  "ok": true,
  "skipped": true,
  "match_level": "none",
  "filtered_count": 0,
  "candidates": [],
  "bottlenecks": []
}
```

### 错误

| 情况 | 状态 | body |
|---|---|---|
| 未登录 / 无效令牌 / 管理员 token | 401 | `{ "detail": "未登录" }` 或 `{ "detail": "无效令牌" }` |
| profile 缺省或校验失败 | 400 | `{ "detail": "<校验信息>" }` |

## 数据流

```text
大模型 submit_preference_profile JSON
  → parse_tool_arguments
  → parse_profile（对话内）
  → match_profile
  → 卡片

外部 / 联调
  → POST /api/match（JWT + 同一份 profile）
  → parse_profile
  → match_profile
  → 同上出参
```

两条路径共用 `match_profile`。对话不改为 HTTP 自调用。

## 测试

1. 无 token → 401  
2. 管理员 JWT → 401  
3. 合法用户 JWT + 合法画像（mock 两行）→ 200，按 score 排序，含 `field_scores`  
4. 非法枚举 → 400  
5. 空 attributes → 200，`skipped: true`  
6. 过滤 0 人 → 200，`candidates: []`，有 `bottlenecks`  
7. `top_k=1` 时最多 1 条  

## 文件

- Create: `agent/api/match.py`（路由）  
- Modify: `agent/main.py` 挂载路由  
- Test: `agent/tests/test_match_api.py`  
- 不改 `core/preference/pipeline.py` 算法，除非截断 top_k 放在路由层对 `candidates[:top_k]` 切片即可  
