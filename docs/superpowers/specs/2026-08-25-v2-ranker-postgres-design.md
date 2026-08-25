# 用 V2 模型替换启发式排序（数据走 PostgreSQL）

**日期：** 2026-08-25  
**状态：** 已实现  
**范围：** `POST /api/match` 与对话匹配的排序层，从 `HeuristicRanker` 换成同学 V2 规则分 + 单调校准模型；must 过滤与捐精人读取继续用 `donor.donors`

## 背景

同学项目 `sperm_match_v2_api_local` 已验证：`POST /v1/rank` + `best_model_v2.pt` 可用。它从 CSV 读 3000 人，must 过滤后按规则分取最多 300 人进模型。

智育匹配已有统一接口 `POST /api/match`：校验 PreferenceProfile → SQL must 过滤 → `HeuristicRanker` → `candidates`。对话经本进程 ASGI 调用该接口。

目标：排序换成 V2，人从 PostgreSQL 读，HTTP 路径与画像 JSON 不变。

## 已确认决策

| 项 | 选择 |
|---|---|
| 接入形态 | 方案 1：在 agent 内实现 `V2CalibratedRanker`（`Ranker` 接口） |
| 数据 | SQL 查 `donor.donors`，不读 CSV |
| 过滤 | 沿用 `build_hard_filter_sql`（仅 must + `status = active`） |
| 进模型人数 | 过滤后全部，不截 300 |
| 独立 V2 HTTP | 不调用、不改同学服务 |
| 运行时依赖 | 不依赖 `sperm_match_v2_api_local` 目录 |
| 权重 | 拷贝到智育匹配项目根下 `models/best_model_v2.pt`（与 `main.py` 同级）；可用 `V2_CHECKPOINT_PATH` 覆盖 |
| Scaler | 用 checkpoint 内 `context_mean` / `context_std`，不需要 Profile CSV |
| 缺模型 | `/api/match` 与对话匹配返回 503，不回退启发式 |
| `top_k` | `0` = 过滤后全部返回；`>0` 只截断响应，不减少排序人数 |
| 左侧筛选 | `POST /api/search` 不改 |
| `MATCH_API_URL` | 若配置了外部 URL，对话仍打外部；未配置时走本进程 V2 Ranker |

## 非范围

- 训练、评估、同学仓库的 FastAPI
- 把 CSV 再接到线上
- 自动放宽 must
- 改 PreferenceProfile 字段注册表（keyword 仍由你们校验，Ranker 侧按 keyword 打分）
- 改 JWT / 卡片字段隔离

## 架构

```text
POST /api/match { profile, top_k? }   # JWT 不变
  → parse_profile                      # 非法 400
  → 空 attributes → skipped, 不查库
  → build_hard_filter_sql + fetch      # donor.donors
  → 0 行 → candidates=[], bottlenecks，不调模型
  → V2CalibratedRanker.rank(全部行)
       PreferenceProfile → V2 attributes 规则
       DB 行 → 打分字典（age 由 birth_date）
       规则分 + max_weighted_mismatch
       best_model_v2.pt 批量校准
       按模型分降序（同分：规则分，再 specimen_count）
  → donor_info = get_donor_display_info（库内真实库存字段）
  → top_k>0 时只切 candidates 列表
```

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `POST /api/match` | 鉴权、校验、top_k 截断、503 加载失败 | 不读 CSV |
| `match_profile` | SQL 过滤后注入 `V2CalibratedRanker` | 不改画像 |
| `V2CalibratedRanker` | 规则分 + 模型校准 + 排序 | 不执行 must 过滤 |
| `HeuristicRanker` | 保留给旧单测 | 默认线上不用 |
| `chat_stream` | 仍 `invoke_match_endpoint` | 不感知 Ranker 实现 |

进程启动（或首次匹配前）加载模型一次，CPU。`requirements.txt` 增加 `torch`（与同学仓库相同上界：`>=2.2,<3`）。

拷入 agent 的推理代码（可放 `core/preference/v2/`）包括：规则打分、`V2MonotonicCalibrator`、上下文特征名、checkpoint 兼容加载、`predict_arrays`、`config_v2.json` 规则段。不拷训练 CLI、CSV Engine、`/v1/rank`。

## 画像与库行映射

PreferenceProfile → V2 spec：

- `RangeAttr` → `{type: range, constraint, weight, range}`
- `EnumAttr` → `{type: enum, constraint, weight, values}`
- `KeywordAttr` → `{type: keyword, constraint, weight, keywords, match_mode: any\|all}`（来自 `match`）

库行 → 打分字典：键与同学 CSV 一致（`abo_blood`、`height_cm`、`sideburns` 等）。`age` 用现有 `_calc_age(birth_date)`。Rh 规范为「阳性 / 阴性」。`specimen_count` / `availability` / `status` / 检验类字段不进入模型输入，只出现在 `donor_info`。

未知画像字段仍由 `parse_profile` 拒绝，到不了 Ranker。

## 响应字段

- `filtered_count`：SQL 命中人数（截断 top_k 之前）
- 每人 `score`、`match_pct`：模型校准分（`match_pct = round(score * 100, 2)`）
- `field_scores[].s`：规则层相似度，用于解释
- 响应级 `match_level`：有候选为 `full`，否则 `none`（与现接口一致）
- 候选人级 `match_level`：可用 V2 的 full/high/medium/low
- `reason`：按规则命中/不足拼中文，逻辑对齐同学 `_reason`

## 错误

| 情况 | 行为 |
|---|---|
| 画像非法 | 400 |
| 空 attributes | 200，`skipped: true` |
| SQL 0 人 | 200，空 candidates + bottlenecks，不调模型 |
| 权重缺失/加载失败/推理异常 | 503，`detail` 说明原因；不改 session 启发式结果 |
| 单行某字段缺失 | 该项规则分 0，该人仍排序 |

## 测试

- 单元：Range/Enum/Keyword 转 V2 spec；生日 → age；hometown keywords 走子串而非精确相等
- 单元：0 行不调用 `predict_arrays`
- 有权重时：`match-api-request.json` 打 `/api/match`（需用户 JWT）；`filtered_count` 等于库内 must 条件（样例为 O 型）且 `status=active` 的人数，不必等于 CSV 的 1168
- Top 应偏向高身高且学历为硕士/博士的 O 型；代号以库为准
- `/api/search` 现有测试仍通过

## 配置

| 变量 | 默认 | 含义 |
|---|---|---|
| `V2_CHECKPOINT_PATH` | `<项目根>/models/best_model_v2.pt` | 权重路径 |
| `V2_CONFIG_PATH` | `core/preference/v2/config_v2.json` | 规则配置 |
| `V2_FORCE_CPU` | `1` | 强制 CPU |

## 落地文件（实现时）

- 新增：`core/preference/v2/`（推理模块 + `config_v2.json`）
- 新增：`core/preference/v2_ranker.py`（`V2CalibratedRanker`）
- 新增：`models/best_model_v2.pt`（从同学仓库拷贝）
- 修改：`core/preference/pipeline.py` 默认 ranker
- 修改：`api/match.py` 将加载失败转为 503
- 修改：`requirements.txt`、`.env.example`
- 新增测试：`tests/preference/test_v2_ranker.py` 等
