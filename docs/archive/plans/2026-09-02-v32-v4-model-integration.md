# V4 匹配评分独立服务实施计划

## 文档状态

- 日期：2026-09-02
- 状态：已实施（2026-09-02）
- 本次修订：由“主应用进程内加载模型”改为“主应用编排 + 独立评分服务”
- 目标：用独立服务承载 `best_mae_model_v4.pt`、训练一致编码器和排序算法，今后替换模型时不改 LLM 工具契约和主业务流程
- 数据源：继续使用现有 PostgreSQL `donor.donors`
- 回滚：保留旧 v2 进程内排序器作为显式应急后端，不做请求内静默降级

## 已验证的输入材料

本计划基于以下材料完成核验：

- 新 checkpoint：`models/best_mae_model_v4.pt`
- 上游源码包：外层工作区 `sperm_match_v32_api_local.zip`
- checkpoint SHA-256：`6ffa19eb2c377830e43dd2942bb3cfdce4fe6d62d7ff8a10a285d26cd7988944`
- checkpoint 标识：
  - `model_name=sperm-match-v4-tender-multitask`
  - `checkpoint_role=best_mae`
  - `best_epoch=33`
  - `max_attr=11`
  - 47 个模型字段、5 个类型编号、3 个约束编号
- 上游 6 个契约、编码和模型测试已在本项目 Python 环境全部通过。
- 上游引擎已在 CPU 成功加载 checkpoint 和 20,000 人样例库，并完成真实排序请求。
- 压缩包和项目中的 checkpoint 哈希一致。

新 checkpoint 不是 v2 校准器的增量权重。它使用字段、类型、约束和值嵌入，属性 Transformer，双输出头以及 7 维全局特征。因此发布单元必须包含“模型代码 + 特征编码 + checkpoint”，不能只热替换 `.pt` 文件。

## 总体架构

```text
LLM
  │ submit_preference_profile（只提交完整画像）
  ▼
主应用工具执行器 / execute_match
  ├─ 画像校验、权限和请求审计
  ├─ PostgreSQL must 严格过滤
  ├─ 提取候选 ID、code 和画像涉及字段
  │
  │ POST /v1/rank
  ▼
独立 Match Scorer
  ├─ 规则分预选前 300
  ├─ 训练一致特征编码
  ├─ V4 双头模型推理
  └─ 返回严格排名、分数、字段解释和真实模型版本
  │
  ▼
主应用
  ├─ 将结果映射回 PostgreSQL donor 行
  ├─ 冻结排名与展示快照
  ├─ 分页、停用候选补位和 refresh
  └─ 向工具返回人数、Top 预览和结果集 ID
```

### LLM 工具边界

`submit_preference_profile` 的公开 JSON Schema 保持不变。LLM 只提交用户画像，不接收以下参数：

- 候选人列表或 donor ID
- 模型地址、模型版本或 checkpoint 路径
- 数据库连接信息
- candidate pool、设备或推理批量等内部参数

当前 `dialogue/generation_processor.py` 调用 `execute_match()` 的位置保留为唯一工具业务入口。工具不分别编排“查询数据库”和“调用评分服务”，避免模型看到候选敏感数据，也避免绕过快照、权限和审计。

### 主应用职责

- 校验 `PreferenceProfile` 和用户权限。
- 根据 must 条件构造参数化 SQL，并查询当前 active donor。
- 无结果时执行现有 bottleneck 诊断，不调用评分服务。
- 将数据库行转换为稳定的候选传输契约，只发送画像需要的字段。
- 调用评分服务并严格校验返回值。
- 保存 `RankedCandidateRef`、展示快照、模型版本和数据集版本。
- 提供 `/api/match`、结果分页、refresh 和对话工具回执。
- 不包含 V4 的模型类、哈希编码、Token 构造或双头排序规则。

### 评分服务职责

- 启动时加载模型代码、checkpoint 和 checkpoint 元数据。
- 接收已经过 must SQL 过滤的候选，不查询业务数据库。
- 对传入候选再次校验 must 条件，发现调用方/服务语义漂移时失败并记录数量指标。
- 执行训练一致的规则分预排序，选择前 300 人。
- 构造 Token、运行模型、按 `ranking_score` 排序。
- 返回 `match_score`、`ranking_score`、字段解释和模型身份。
- 不负责用户认证、业务数据库、结果快照、分页和对话状态。
- 不持久化请求画像或候选人数据，不在日志中输出原始 payload。

### 为什么不让评分服务直接查数据库

评分服务一旦拥有数据库访问，就会同时耦合 donor schema、权限、active 状态、审计和模型代码，后续替换模型仍需理解主业务数据层。由主应用完成 must SQL 过滤，可以把评分服务保持为无状态计算服务，并将数据库凭据限制在主应用。

## 服务契约 v1

### 排名请求

```http
POST /v1/rank
Authorization: Bearer <internal-service-token>
Content-Type: application/json
```

```json
{
  "contract_version": "1",
  "request_id": "uuid",
  "profile": {
    "schema_version": "1.0",
    "attributes": {}
  },
  "candidates": [
    {
      "donor_id": 123,
      "code": "A260001",
      "attributes": {
        "height_cm": 180,
        "education": "硕士"
      },
      "business": {
        "specimen_count": 10
      }
    }
  ]
}
```

约束：

- `request_id` 由主应用生成，供幂等重试和跨服务 Trace 使用。
- `donor_id` 必须为本次请求内唯一正整数；`code` 用于训练一致的稳定同分顺序。
- `attributes` 只包含画像实际涉及的模型字段。
- 年龄使用主应用计算后的整数 `age`，不发送出生日期。
- `business` 只承载不进入模型 Token 的库存类字段。
- 不发送完整 donor 档案、状态、创建人、更新时间或未参与本次匹配的医疗字段。
- 第一版设置候选数量和请求体上限；超过限制返回 413，不接受无限 payload。

### 排名响应

```json
{
  "contract_version": "1",
  "request_id": "uuid",
  "model": {
    "name": "sperm-match-v4-tender-multitask",
    "version": "v32-v4-best-mae",
    "checkpoint_role": "best_mae",
    "checkpoint_epoch": 33,
    "checkpoint_sha256": "6ffa19..."
  },
  "eligible_count": 7107,
  "ranked_count": 300,
  "items": [
    {
      "donor_id": 123,
      "rank": 1,
      "match_score": 0.93,
      "ranking_score": 0.96,
      "heuristic_score": 0.91,
      "field_scores": []
    }
  ],
  "timings": {
    "preselect_ms": 0,
    "encode_ms": 0,
    "model_ms": 0,
    "sort_ms": 0
  }
}
```

主应用必须验证：

- 响应 `request_id` 和契约版本与请求一致。
- donor ID 全部来自本次候选集，且不得重复。
- `rank` 从 1 连续递增，条数不超过 candidate pool。
- 三种分数均为有限数；匹配分和排名分位于 `[0, 1]`。
- `eligible_count` 等于主应用发送的候选数量。
- 模型名称、版本、checkpoint role 和 SHA-256 不为空。
- 非法响应按上游服务错误处理，不生成部分快照。

### 错误响应

统一返回稳定错误码，不让主应用解析自然语言：

```json
{
  "error": {
    "code": "PROFILE_TOO_WIDE",
    "message": "模型最多支持 11 个属性",
    "retryable": false
  }
}
```

建议映射：

- 400/422：契约错误、未知字段、属性超过 11 个、权重非法。
- 401/403：内部服务凭据错误。
- 413：候选数量或请求体超过上限。
- 503：checkpoint 未加载、设备故障或服务未就绪。
- 504：推理超过服务端截止时间。

主应用将可修正画像错误映射为工具可重试错误；基础设施错误向 `/api/match` 返回 503，不要求 LLM 修改画像重试。

## 排序与结果语义

### 前 300 候选池

正式流程保持为：

```text
PostgreSQL must 过滤
→ 评分服务规则分预排序全部合格者
→ 取前 300
→ V4 推理
→ ranking_score 排序
→ match_score 展示
```

- `filtered_count`：主应用 must 过滤后的全部合格人数。
- `total` / `ranked_count`：完成模型排名的人数，最大 300。
- `ranked_refs` 和 `snapshot_items`：只保存模型真正排过的候选。
- 完整排名分页：最多浏览 300 人，不混入未经过模型的规则分候选。
- `prefer_hits`：在模型候选池内统计，并返回清晰分母。

必须修改当前 `execute_match()` 中 `total = filtered_count` 的假设。数据库结构无需迁移，`MatchResultMeta.total` 可直接表达模型排名池数量。

已用相同 profile 对上游样例库验证：如果绕过前 300 预选而直接推理全部 7,107 名合格者，模型 Top-5 中有 4 人来自规则分 300 名之外，结果与上游正式流程明显不同。因此不能为了保留全量分页而擅自全库推理。

### 双头模型分数

- 排名主键：`ranking_score` 降序。
- 对外 `score` / `match_pct`：使用 `match_score`。
- 同分规则：`heuristic_score` 降序，再按 donor `code` 升序。
- 不把 `ranking_score` 当匹配百分比展示。

### `specimen_count` 库存字段

当前画像支持 `specimen_count`，但 checkpoint 的 `field_to_id` 不包含它。

第一版规则：

- `must`：主应用继续用 PostgreSQL 严格过滤。
- `prefer`：作为 `business.specimen_count` 发送，参与评分服务的业务预排序和字段解释，不进入 Transformer Token。
- 模型最终分相同时，使用库存偏好相似度和实际库存作稳定次级排序。
- 画像只有库存字段时，主应用走现有启发式业务排序，不调用空 Token 模型。

后续如果要求库存偏好直接影响模型分数，必须把它加入训练数据并重新训练，不能为当前 checkpoint 临时增加随机字段嵌入。

## 配置设计

### 主应用

```text
MATCH_SCORING_BACKEND=http
MATCH_SCORER_URL=http://127.0.0.1:8020
MATCH_SCORER_CONTRACT_VERSION=1
MATCH_SCORER_TIMEOUT_SECONDS=15
MATCH_SCORER_MAX_CANDIDATES=20000
MATCH_SCORER_TOKEN=<secret>
```

- `MATCH_SCORING_BACKEND=http` 为新默认值。
- `MATCH_SCORING_BACKEND=local_v2` 是显式应急回滚。
- 保留现有 `MATCH_API_URL` 的“整个 `/api/match` 外置”含义，不把它复用为评分服务地址。
- 生产环境必须配置服务凭据；开发和测试使用单独的非生产值。
- 不在日志、Trace、快照或工具回执里记录 token。

### 评分服务

```text
SCORER_MODEL_PATH=<服务镜像>/models/best_mae_model_v4.pt
SCORER_MODEL_VERSION=v32-v4-best-mae
SCORER_FORCE_CPU=1
SCORER_CANDIDATE_POOL=300
SCORER_MAX_CANDIDATES=20000
SCORER_MAX_REQUEST_BYTES=25000000
SCORER_RANK_SOURCE=ranking_score
SCORER_TOKEN=<same-secret>
```

- 服务启动时计算 checkpoint SHA-256，并与可选的预期哈希配置比对。
- `SCORER_RANK_SOURCE` 第一版固定为 `ranking_score`；配置仅用于明确声明和启动校验，不允许请求方覆盖。
- 模型加载失败时进程可以存活用于诊断，但 readiness 必须失败，排名接口返回 503。

## 实施阶段

### 阶段一：建立独立评分服务骨架

新增：

```text
services/match_scorer/
  __init__.py
  app.py
  api_models.py
  settings.py
  engine.py
  model.py
  encoding.py
  model_manifest.py
```

实施内容：

1. 从上游移植 `ModelConfig`、`TenderAlignedV32` 和训练一致编码逻辑。
2. 服务启动时使用 `map_location` 加载 checkpoint，`strict=True` 加载权重并切换 `eval()`。
3. 校验 checkpoint 必需键、模型名、张量维度、字段表、类型表、约束表、数值统计和 `max_attr`。
4. 不读取上游 donor/Profile CSV；训练归一化上限使用已核验值 `max_must=2`、`max_prefer=11`。
5. 提供：
   - `GET /healthz`：仅表示进程存活。
   - `GET /readyz`：表示模型已正确加载。
   - `GET /v1/model`：返回非敏感模型身份和能力限制。
   - `POST /v1/rank`：执行评分。
6. 使用推理锁保护模型调用；若未来使用 GPU，一个进程只启动一个模型 worker，避免重复占用显存。

不复制或提交：

- 上游 `.venv`
- 20,000 人 donor CSV
- 5,000 条 Profile CSV
- Notebook、训练输出目录和重复 checkpoint

对应测试：

- `tests/match_scorer/test_model.py`
- `tests/match_scorer/test_encoding.py`
- `tests/match_scorer/test_checkpoint.py`
- `tests/match_scorer/test_api_contract.py`
- `tests/match_scorer/test_engine.py`

覆盖模型前向形状、稳定哈希、范围/枚举/关键词相似度、Token/global 形状、真实 checkpoint 加载、认证、请求限制、错误码和双头分数语义。

### 阶段二：实现评分服务排名流程

服务内流程：

1. 验证 contract、候选唯一性和模型属性数量。
2. 对传入候选重新检查 must；若有候选不满足 must，返回稳定契约错误，避免两边语义漂移被静默掩盖。
3. 对全部候选执行轻量 `score_only()`。
4. 按规则分降序、code 升序取前 300。
5. 只为选中候选创建 `(11, 10)` Token 并构造批量张量。
6. 在 `torch.inference_mode()` 中执行模型。
7. 按 `ranking_score`、`heuristic_score`、code 生成确定性排名。
8. 返回 `match_score`、`ranking_score`、字段解释和分阶段耗时。

增加固定输入黄金对照，保证移植后的编码数组、前 300 选择和模型输出与上游源码一致。

### 阶段三：在主应用增加评分客户端

新增：

```text
core/preference/scoring_contract.py
core/preference/scoring_client.py
core/preference/ranker_factory.py
```

实施内容：

1. 定义 `ScoringClient` 协议和 `HttpScoringClient`。
2. 使用固定 connect/read/write/pool timeout，不允许无限等待。
3. 携带内部 Bearer token、contract version 和 request ID。
4. 将 profile 与数据库行转换成最小候选 payload：
   - 只发送画像涉及字段。
   - 从 `birth_date` 计算 `age` 后只发送年龄。
   - Rh `+/-` 统一为 `阳性/阴性`。
   - 把 `Decimal`、日期和数据库空值转换为 JSON 原生值。
5. 校验响应 donor 集合、连续 rank、分数范围和模型身份，再映射回原 PostgreSQL 行。
6. 将远程 `field_scores` 转成现有 `FieldScore`，继续复用卡片、日志和快照组装。
7. 增加 `LocalV2ScoringClient` 或等价适配器，只在显式 `local_v2` 回滚模式使用。
8. 评分服务失败时不在同一请求内自动调用 v2。

异步边界：

- `execute_match()` 可保留同步领域实现，便于数据库事务和现有测试注入。
- FastAPI `/api/match` 改用同步路由或显式线程池，避免阻塞事件循环。
- `dialogue/generation_processor.py` 通过 `asyncio.to_thread()` 调用同步匹配编排。
- 不在 async 事件循环中直接运行同步 PostgreSQL 和同步 HTTP 客户端。

对应测试：

- HTTP mock transport 的成功、超时、认证失败、503、畸形响应和未知 donor 测试。
- payload 最小化测试，确认未参与画像的敏感字段不会发送。
- request ID 和模型身份透传测试。
- 显式 v2 回滚测试和“远程失败不静默降级”测试。

### 阶段四：接入 must 过滤、快照和分页

修改：

- `core/preference/pipeline.py`
- `api/match.py`
- `dialogue/generation_processor.py`
- `dialogue/agent_tools.py`
- 必要时扩展 `core/preference/result_types.py`

实施内容：

1. 继续使用现有参数化 SQL 在 PostgreSQL 执行 must 过滤。
2. 无合格候选时保留现有 bottleneck 诊断，不请求评分服务。
3. `MatchResult` 区分 `filtered_count` 与实际 `ranked_count`。
4. `execute_match()` 使用 `len(ranked_refs)` 作为结果集 `total`，同时返回完整 `filtered_count`。
5. 快照校验改为 `len(refs) == total == len(snapshot_items)`，不再要求等于 `filtered_count`。
6. 快照 `model_version` 使用评分响应中的真实版本，并同时保存或审计 checkpoint SHA-256；若现有字段不足，优先放入可扩展元数据而不是拼接到用户可见名称。
7. 分页始终读取冻结排名，不重新调用评分服务；只加载当前 donor 行补充当前状态。
8. refresh 调用当前评分服务生成新结果集，旧快照保留原模型身份。
9. 工具回执同时包含：
   - `filtered_count`：符合 must 的人数。
   - `count` / `ranked_count`：可浏览的模型排名人数。
   - 提示语明确表达“共 X 人满足硬条件，模型展示前 Y 人”，避免把 300 说成全部合格人数。
10. `submit_preference_profile` 工具 Schema 不新增评分服务参数。

对应测试：

- 4,303 人合格但只保存 300 个模型排名。
- `filtered_count > total` 时首页、cursor 和任意页跳转正确。
- 快照、分页、停用候选补位和 refresh 一致。
- 工具只提交画像，回执正确区分 must 合格人数与模型排名人数。
- 无结果时评分客户端调用次数为 0。

### 阶段五：配置、安全和可观测性

修改：

- `config.py`
- `.env.example`
- `main.py`
- 部署配置和运行说明

实施内容：

1. 校验评分 URL、timeout、candidate limit、backend 和 contract version。
2. 生产环境要求非空高强度服务 token；评分服务使用恒定时间比较认证值。
3. 跨主机部署使用 TLS 或受保护的内部网络；不把评分端口暴露到公网。
4. 日志只记录 request ID、模型版本、checkpoint 哈希短前缀、候选数量、状态码和耗时。
5. Trace 不保存候选 payload、完整画像或服务 token。
6. 主应用 `/health` 保持轻量；增加 readiness 检查评分服务连通性和 contract/model 能力。
7. 评分服务导出请求数、错误数、超时、候选数量分布、预选耗时和推理耗时指标。
8. 限制并发与请求体；服务端先检查 Content-Length，再解析大 JSON。

### 阶段六：端到端验证、发布和回滚

执行顺序：

1. 跑评分服务模型、编码、契约和引擎测试。
2. 跑主应用评分客户端、pipeline、match API、快照、分页和工具测试。
3. 跑完整 Python 测试套件。
4. 本机启动独立评分服务，使用真实 checkpoint 执行 HTTP smoke test。
5. 使用测试 PostgreSQL 完成端到端请求，核对 must 人数、模型池、卡片、快照和分页。
6. 记录 CPU 冷启动、首次推理、热推理、HTTP 传输大小和总耗时。
7. 先部署评分服务并通过 readiness，再切主应用 `MATCH_SCORING_BACKEND=http`。
8. 新旧模型用固定验收画像对照，确认 Top-5、分数、库存处理和字段解释。
9. 出现问题时显式切回 `MATCH_SCORING_BACKEND=local_v2` 并重启主应用；旧快照不变。

建议验证命令：

```bash
.venv/bin/python -m pytest tests/match_scorer -v

.venv/bin/python -m pytest \
  tests/preference \
  tests/test_match_api.py \
  tests/test_match_pagination.py \
  tests/test_match_snapshot_postgres.py \
  tests/test_generation_processor.py -v

.venv/bin/python -m pytest -q
```

## 验收标准

- `submit_preference_profile` 仍只接收画像，LLM 看不到候选 payload 和服务配置。
- PostgreSQL 是唯一在线候选数据源，评分服务没有数据库凭据。
- 主应用完成 must 过滤；零候选时不调用评分服务。
- 评分服务实际加载 `best_mae_model_v4.pt`，返回可审计的版本和 checkpoint SHA-256。
- 编码数组、规则预选和双头输出与上游源码一致。
- 规则预选严格限制前 300；排序使用 `ranking_score`，展示使用 `match_score`。
- API 正确区分 `filtered_count` 和 `total/ranked_count`。
- 快照、分页、停用补位和 refresh 保持一致。
- 工具能准确告诉 LLM“must 合格人数”和“模型排名人数”。
- 未参与画像的 donor 字段不会发送到评分服务，候选 payload 不进入日志或 Trace。
- 评分服务不可用时返回明确 503，不生成半成品快照、不静默降级。
- 显式 `local_v2` 后端可以回滚。
- 相关测试和完整回归全部通过。

## 风险与边界

### best-MAE 不等于最佳 Top-5

用户指定的 checkpoint 是 `best_mae`。checkpoint 内验证 MAE 很低，但 `top1_agreement` 约为 0.385、`top5_recall` 约为 0.482。上线验收必须观察真实 Top-5，不能只看分数误差；本次不擅自替换为上游 README 推荐的 balanced checkpoint。

### 训练画像覆盖范围有限

checkpoint 注册 47 个字段，但随包提供的 5,000 条训练 Profile 实际只出现 28 个字段，keyword 类型主要出现在 `hometown`。第一版保证契约、编码、推理和解释正确，不据此宣称所有医疗字段都已充分训练。

### 模型最多接收 11 个属性

超过 11 个模型属性返回明确 400/422，不能静默截断。对话工具提示和画像校验需同步告诉调用方该限制。

### 服务调用增加新的故障点

独立 HTTP 调用会增加网络延迟、超时和部署依赖。通过 readiness、固定 timeout、最小 payload、明确错误码、指标和显式回滚控制风险；第一版不实现复杂熔断或请求内自动降级。

### 不提交大体积上游工程

最终提交只包含必要源码、测试和 1.6 MB checkpoint。外层 238 MB ZIP、上游虚拟环境和两份 CSV 不进入应用仓库，也不成为生产运行依赖。

## 预计提交拆分

1. `建立 V4 独立评分服务和模型契约`
2. `移植训练一致编码器并加载 V4 checkpoint`
3. `为主应用增加安全的评分服务客户端`
4. `接入 must 过滤并区分模型排名池快照`
5. `保持工具契约并补充跨服务状态反馈`
6. `补齐端到端回归和显式 v2 回滚`

## 实施结果

- 已建立无数据库权限的独立 `services.match_scorer` 服务，并加载指定的
  `best_mae_model_v4.pt`；实际模型身份、epoch 与 SHA-256 均通过校验。
- 主应用保留 PostgreSQL must 过滤，通过最小候选契约调用 HTTP 评分客户端；
  `MATCH_SCORING_BACKEND=local_v2` 仅作为显式重启回滚选项。
- 评分服务按规则分预选最多 300 人，V4 使用 `ranking_score` 排序、
  `match_score` 展示，并返回字段解释、模型身份和分阶段耗时。
- 快照保存真实模型版本与 checkpoint SHA-256；分页只读取冻结展示快照，
  不重复评分。API 和工具回执已区分 `filtered_count` 与 `ranked_count/total`。
- 已增加认证、请求体上限、稳定错误码、模型 readiness、主应用依赖 readiness、
  非敏感运行指标和生产 token 校验。
- 全量 Python 回归：230 passed、22 skipped；跳过项是需要独立 PostgreSQL 测试库的
  集成用例和原有条件性用例。
- 真实 HTTP 冒烟测试通过：独立进程成功加载 checkpoint，`/readyz`、`/v1/model`
  和 `/v1/rank` 均返回 200；两条虚构候选的热推理 `model_ms` 约 20.9 ms。
- 已验证但未采用 `asyncio.to_thread` / AnyIO 线程池包装持久生成任务：当前
  Python 3.14 测试进程在线程池回收阶段会卡住。`/api/match` 已改为 FastAPI 同步路由，
  可由框架隔离阻塞调用；持久生成 worker 仍保持原同步执行方式，待运行时线程模型升级。
