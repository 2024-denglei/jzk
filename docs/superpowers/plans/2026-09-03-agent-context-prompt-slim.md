# 顾问 Agent 上下文与系统提示词精简方案

## 文档状态

- 日期：2026-09-03
- 状态：已实施（2026-09-03）
- 目标：去掉重复提示、对齐真实 tool 回执、补上权威画像上下文，在不破坏调工具/总结正确性的前提下降低固定 prompt 开销
- 基线（`api.silra.cn` / `deepseek-v4-flash` 实测，改前）：
  - 仅 system：约 **1653** `prompt_tokens`
  - system + 全量 tool + 短用户句：约 **11864** `prompt_tokens`
- 改后实测（同网关）：
  - 仅 system：约 **854**
  - 常见路径（system + 画像快照 + 核心 tool）：约 **4484**
  - 扩展路径（system + 画像快照 + 全量 extended tool）：约 **9726**
  - 说明：processor 按用户话术/已有扩展字段动态二选一挂工具，避免核心+全量两份 schema 叠成 13k+
- 非目标：不改匹配算法、不改 PreferenceProfile 数据模型字段集合、不引入第二套对话协议

## 问题摘要

1. **重复**：`field_catalog_text()` 同时出现在 system 末尾和 tool `attributes.description`；各字段 guide / 枚举值在 catalog 与 per-field schema 再次重复；每个字段复制同一份 `constraint`/`weight` 说明。
2. **错位**：system 仍写 `top_preview`、`allowed_values`，当前 `AgentGenerationProcessor` 成功回执无 `top_preview`，失败回执无 `allowed_values`。
3. **缺失**：消息节点已有 `preference_profile` 快照，但 processor 不注入模型；跨轮只能靠最近 40 条削薄对话推断完整画像。
4. **膨胀未分层**：schema 暴露 47 字段，工具描述限制最多 11 个属性；少用字段长期占用 tools token。

## 设计原则

- **行为规则留 system，结构约束留 tools**：何时调工具、人数口径、禁止编造 → system；字段形状与枚举 → schema。
- **单一事实来源**：同一说明只保留一处；catalog 若保留，只出现一次。
- **提示词必须可被运行时兑现**：写到 prompt 里的回执字段，processor 必须返回；否则改文案。
- **权威状态进 context**：当前完整画像以独立 system 片段注入，不依赖模型从历史里「回忆」。
- **分阶段可回滚**：每阶段独立可测、可单独上线；用真实 `prompt_tokens` 对比，不只看字符数。

## 目标形态（改完后模型每轮看到什么）

```text
messages = [
  { role: system, content: AGENT_SYSTEM_PROMPT },          # 行为规则，无完整 catalog
  { role: system, content: "【当前完整偏好画像】" + json }, # 权威快照；空则明确写空对象
  ... 最近 ≤40 条 user/assistant（assistant 仍 slim）...,
  # 本轮内再 append assistant tool_calls / tool / 最终总结
]
tools = [SUBMIT_PROFILE_TOOL]  # schema 去重后仍含全部或分层字段
```

管理端 Trace：

- `input_context` 继续记录实际提交的 system / user / assistant。
- 新增的「当前画像」system 片段一并写入 Trace（与现有 `agent_message` 一致），便于后台还原。

---

## 阶段 A：对齐文案与回执（低风险，优先）

### 目的

消除「提示词承诺了运行时给不出的字段」，先修正确性，几乎不改 token。

### 改动

1. **`build_agent_system_prompt`（`dialogue/agent_tools.py`）**
   - 规则 3：`count / top_preview / prefer_hits` → `count / ranked_count / filtered_count / prefer_hits`。
   - 明确：禁止编造代号与表格；卡片由客户端展示；不要提已不存在的 `top_preview`。
   - 规则 4：`error / allowed_values` → 在阶段 C 落地前，先改为 `error`（及可选 `note`）；阶段 C 完成后再改回「error + allowed_values（若有）」。
2. **`AgentGenerationProcessor` 成功回执**
   - 保持现有字段；`note` 已含 filtered/ranked 说明，与 system 规则 6 分工：system 讲口径，note 给本轮数字，避免再复制长段 prefer 话术。
3. **测试**
   - 更新 `tests/preference/test_agent_tool.py` 中依赖旧措辞的断言。
   - 增加断言：system **不含** `top_preview`；含 `ranked_count` / `filtered_count`。

### 验收

- 相关单测通过。
- 人工看一轮 Trace：system 文案与 tool_result JSON 字段一致。

### 回滚

- 仅文案回退；无数据迁移。

---

## 阶段 B：去掉重复 catalog / 压缩 schema 说明（省 token）

### 目的

在不动字段集合的前提下，去掉「同一知识说三遍」。

### 改动

1. **System 不再拼接完整 `field_catalog_text()`**
   - `build_agent_system_prompt` 末尾改为短指引，例如：
     - 字段名、类型、合法枚举以工具 parameters 为准；
     - 口语映射以各字段 description 为准；
     - 未提及字段不要写入 attributes。
   - 保留必须的业务规则（完整 snapshot、must/prefer、放宽并入、禁止编造人数）。
   - **figure / face_shape 等高风险口语映射**：不要只依赖被删的 catalog。二选一（推荐 ①）：
     1. 留在对应字段的 schema `description`（已有 figure 长说明则够用）；
     2. 或在 system 留 3～5 行「高风险映射」短列表，而不是 47 行 catalog。
2. **`openai_tool_schema()`**
   - `attributes.description` **删除** `+ field_catalog_text()`，改为一句短描述（完整快照、取消即删除、未提及不编造、最多 11 属性可在此或 tool.description 保留一处）。
   - 各字段保留：`description`（含口语映射）+ 结构（range/values/keywords）+ enum 硬约束。
   - 枚举：`items.enum` 保留；删掉 `values.description` 里再次罗列「可选值：…」以及字段 description 里重复的 `只能从可选值中选：[…]`（enum 已约束）。
3. **可选微优化（同阶段或 B.1）**
   - 评估能否用 JSON Schema `$defs` + `$ref` 抽出共用的 `constraint`/`weight`，取决于网关是否支持 `$ref`。  
     **上线前必须用真实 API 测一次**：若 `tool_choice=auto` 下模型仍能稳定产出合法 arguments，再采用；否则保持每字段内联 `_base_props()`。
4. **`field_catalog_text()`**
   - 函数保留，供管理端、文档或调试；**不再**进入默认 system / attributes.description。
   - 更新 `test_field_catalog_is_generated_from_registry`：不再要求 `text in AGENT_SYSTEM_PROMPT`。

### 预期收益（需实测）

- 去掉 system catalog ≈ 省 system 侧 ~1k tokens 量级。
- 去掉 attributes.description 内嵌 catalog ≈ 再省 tools 侧 ~1k。
- 合计固定输入有望从 ~11.8k 降到约 **9.5k–10.5k**（以网关 `prompt_tokens` 为准）。

### 验收

- 脚本或单测辅助：对 `system` / `system+tools+短 user` 打真实 completion，记录改前改后 `prompt_tokens`。
- 回归：`test_agent_tool`、`test_generation_processor`、枚举合法值测试。
- 抽 5 个对话场景人工/集成：改条件、放宽、取消、prefer 重排话术、非法枚举重试。

### 回滚

- 恢复 system `+ field_catalog_text()` 与 attributes.description 拼接即可。

---

## 阶段 C：注入权威画像 + 结构化校验错误（正确性）

### 目的

解决「跨轮不知道当前完整 PreferenceProfile」和「失败时提示词空许 `allowed_values`」。

### C1. 注入当前画像

1. 在 `AgentGenerationProcessor` 组装 messages 时，在固定 system 之后插入：

```python
{
  "role": "system",
  "content": "【当前完整偏好画像】"
    + json.dumps(
        state.get("preference_profile")
        or {"schema_version": "1.0", "attributes": {}},
        ensure_ascii=False,
      ),
}
```

2. Trace：该条记为 `agent_message`，`phase=input_context`，`role=system`（可加 `kind=preference_snapshot` 便于管理端展示；若不想扩字段，文案前缀即可区分）。
3. 管理端：`latestSystemContextEvent` 仍取「最后一条 system」时，注意不要把画像片段误当成唯一 System Prompt。  
   - 建议：固定规则 system 与画像 system 用前缀区分；UI「系统提示词」只展示规则那条；画像单独一节「当前画像快照」。
4. 与旧 `build_agent_messages` 对齐后，可标记该函数为兼容层或改为调用同一 helper，避免两套逻辑再分叉。

### C2. 失败回执结构化

1. 在 `ProfileValidationError`（或 processor catch 处）解析出字段名与允许值时，`tool_failure_payload` 增加可选：

```json
{
  "ok": false,
  "retry": true,
  "error": "...",
  "field": "figure",
  "allowed_values": ["一般", "瘦弱", "强壮", "肥胖"]
}
```

2. 无结构化信息时再写回 system 规则 4：`根据 error，以及 field/allowed_values（若有）修正后重试`。
3. 非法枚举单测：断言 payload 含 `allowed_values`。

### 验收

- 多轮：先提交 O 型，再只说「身高 175 以上」，模型 arguments 须同时含 `abo_blood` 与 `height_cm`（依赖注入的画像，而非只靠历史）。
- 窗口边界：构造 >40 条历史后改条件，注入仍能带上完整画像。
- 非法枚举：一次失败回执后二次 tool_call 使用合法值。

### 风险

- 多一条 system，增加少量 tokens（画像 JSON 通常远小于 catalog）。
- 管理端若只展示「最后一条 system」，会短暂把画像当成主 prompt → 必须同步 UI 区分。

---

## 阶段 D（可选）：字段分层，进一步砍 tools

### 目的

47 字段全量进 schema 是 ~1 万 tools token 的主因；对话常用远少于 11 个。

### 方案选项

| 方案 | 做法 | 收益 | 风险 |
|---|---|---|---|
| D1 常用子集默认暴露 | tool schema 只含核心 ~18 字段（外貌/学历/籍贯/血型等）；扩展字段另工具 `submit_preference_profile_extended` 或第二套 parameters | tools token 大幅下降 | 两套工具增加路由复杂度 |
| D2 动态 schema | 按对话轮次/已用字段逐步打开属性 | 首轮最省 | 实现与缓存复杂，暂不推荐 |
| D3 保持 47，只做 B/C | 实现简单 | 收益有限 | — |

**建议**：先上线 A+B+C，用一周真实 Trace 统计字段使用频率，再定 D1 白名单。不要在未看数据前删病史/遗传等字段。

### 若做 D1

- 在 `schema.py` 增加 `CORE_FIELDS` / `EXTENDED_FIELDS`。
- 默认 `openai_tool_schema(fields=CORE_FIELDS)`。
- system 一句：扩展字段（列表短名）需在用户明确提到时通过扩展工具提交。
- 匹配与校验层仍接受全量 registry，避免后端拒收。

---

## 阶段 E：清理与观测

1. 明确 `MATCH_DONORS_TOOL`、`nlu.parse_user_intent`、未调用的 `build_agent_messages` 去留；能删则删，不能删则注释「非 chat-v2 主路径」。
2. 增加轻量基准：`scripts/benchmark_dialogue_latency.py` 或新脚本记录 `prompt_tokens`（system / system+tools / 含画像）。
3. Trace 或日志定期抽检：tool 失败率、二次重试成功率、prefer 话术违规（可人工）。

---

## 实施顺序与工时估算

| 顺序 | 阶段 | 预估 | 依赖 |
|---|---|---|---|
| 1 | A 文案对齐 | 0.5d | 无 |
| 2 | B catalog/schema 去重 | 1d | A；需真实 API token 对比 |
| 3 | C 画像注入 + 结构化错误 | 1–1.5d | A；管理端展示小改 |
| 4 | E 清理与基准 | 0.5d | B/C |
| 5 | D 字段分层 | 另估 | 需用量数据 |

建议合并发布：**A+B** 一批，**C** 一批（含管理端），**D** 独立评审。

## 测试计划

- [ ] `tests/preference/test_agent_tool.py`：prompt 措辞、catalog 不再强制进 system、schema description 无整份 catalog、枚举仍硬约束
- [ ] `tests/test_generation_processor.py`：messages 含画像 system；tool 成功/失败 payload 字段；Trace `input_context` 含画像
- [ ] 新增或扩展：非法枚举 → `allowed_values` → 重试成功
- [ ] 真实网关：`prompt_tokens` 改前/改后对比（同一 model、同一短 user、`tool_choice=auto`）
- [ ] 手工：改条件 / 放宽 / 取消 / prefer 重排话术 / 长历史续聊

## 明确不做

- 不把候选人明细或 `top_preview` 卡片数据重新塞回 tool 回执（与「卡片走快照」架构冲突）。
- 不把完整历史 tool_call/tool_result 默认回放进下一轮（成本高）；权威画像注入是替代方案。
- 不强制引入 `$ref`（网关兼容未验证前）。

## 成功标准

1. system 与 tool 回执字段名一致，无 `top_preview` / 空壳 `allowed_values` 承诺（或 C 完成后真正返回）。
2. 固定输入 `prompt_tokens` 较基线 **下降**，且核心对话回归通过。
3. 跨轮提交完整 snapshot 时，模型能稳定带上注入画像中的已有条件。
4. 管理端能区分「规则 System Prompt」与「当前画像快照」，不误展示。
