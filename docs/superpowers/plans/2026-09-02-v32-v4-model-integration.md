# V3.2 架构 / V4 best-MAE 模型替换实施计划

## 文档状态

- 日期：2026-09-02
- 状态：待实施
- 目标：用 `models/best_mae_model_v4.pt` 替换默认 v2 排序模型
- 数据源：继续使用现有 PostgreSQL `donor.donors`，不引入压缩包内 CSV 作为运行时数据源
- 回滚：保留旧 `best_model_v2.pt` 和 v2 推理代码，通过配置切回

## 已验证的输入材料

本计划基于以下材料完成核验：

- 新 checkpoint：`models/best_mae_model_v4.pt`
- 上游完整源码包：外层工作区 `sperm_match_v32_api_local.zip`
- checkpoint SHA-256：`6ffa19eb2c377830e43dd2942bb3cfdce4fe6d62d7ff8a10a285d26cd7988944`
- checkpoint 标识：
  - `model_name=sperm-match-v4-tender-multitask`
  - `checkpoint_role=best_mae`
  - `best_epoch=33`
  - `max_attr=11`
  - 47 个模型字段、5 个类型编号、3 个约束编号
- 上游 6 个契约、编码和模型测试已在本项目 Python 环境全部通过。
- 上游引擎已在 CPU 成功加载该 checkpoint 和 20,000 人样例库，并完成真实排序请求。
- 压缩包和项目中的 checkpoint 哈希一致。

新模型不是 v2 校准器的增量权重，不能只改文件路径。它使用字段、类型、约束和值嵌入，属性 Transformer，双输出头以及 7 维全局特征；必须同步移植训练一致的编码器和模型类。

## 核心集成决策

### 1. 采用进程内 Ranker，不启动第二个 API

只移植上游的模型和特征编码能力，在现有 `Ranker` 接口内完成推理。现有 `/api/match`、认证、PostgreSQL 查询、审计、结果快照和分页保持为唯一业务链路。

不复制以下内容：

- 上游 `.venv`
- 20,000 人捐精人 CSV
- 5,000 条 Profile CSV
- 上游 FastAPI 服务和启动脚本
- Notebook、训练输出目录和重复 checkpoint

这样不会出现 PostgreSQL 与 CSV 两份候选库不一致，也不会新增内部 HTTP 调用和第二套鉴权/健康检查。

### 2. 严格保留训练时的前 300 候选池

上游正式流程是：must 过滤 → 规则分预排序 → 前 300 人进入模型 → 按 `ranking_score` 排序 → 用 `match_score` 展示分数。

现有系统会保存全部 must 合格人员的排名，但不能给第 301 名以后伪造“模型排名”。实施后采用以下语义：

- `filtered_count`：PostgreSQL must 严格过滤后的全部人数。
- `total`：实际进入并完成模型排序的人数，最大为 300。
- `ranked_refs` 和 `snapshot_items`：只保存模型真正排过的候选，数量与 `total` 一致。
- 完整排名分页：最多浏览 300 人；不会把规则分候选混入模型排名。
- `prefer_hits`：在这批模型候选池内统计，并明确返回分母。

必须修改当前 `execute_match()` 中 `total = filtered_count` 的假设，改为以实际排名引用数量为结果集总数。数据库结构无需迁移，`MatchResultMeta.total` 本身可以表达排名池数量。

曾用同一 profile 对上游样例库做过验证：如果跳过前 300 预选而直接对全部 7,107 名合格者推理，模型 Top-5 中有 4 人来自规则分 300 名之外，结果与上游正式流程明显不同。因此不能为了保留全量分页而擅自改为全库模型推理。

### 3. 保持双头模型的分数语义

- 排名主键：`ranking_score` 降序。
- 对外 `score` / `match_pct`：使用 `match_score`。
- 同分规则：规则启发分降序，再按 donor `code` 升序，保持上游确定性。
- 不使用 `match_score` 直接排序，也不把 `ranking_score` 当匹配百分比展示。

### 4. `specimen_count` 作为业务库存字段处理

当前画像支持 `specimen_count`，但新 checkpoint 的 `field_to_id` 不包含它，不能作为 Transformer 属性 Token 输入。

推荐规则：

- `must`：继续由 PostgreSQL 严格过滤。
- `prefer`：参与进入前 300 的业务预排序，并保留字段解释；不送入 Transformer Token。
- 最终模型分相同时，再使用该字段的偏好相似度和实际库存作稳定次级排序。
- 如果画像只有 `specimen_count`，使用现有启发式排序，不构造空 Token 的模型请求。

该处理不会伪造未训练字段的嵌入，同时保留“库存至少多少管”的业务能力。后续若要求库存偏好直接影响模型分数，需要把该字段加入训练数据后重新训练 checkpoint。

### 5. 保留 v2 作为可控回滚，不做静默降级

新增明确的后端选择配置，例如：

```text
MATCH_RANKER_BACKEND=v32
MATCH_MODEL_VERSION=v32-v4-best-mae
V32_CHECKPOINT_PATH=<项目>/models/best_mae_model_v4.pt
V32_FORCE_CPU=1
V32_CANDIDATE_POOL=300
V32_RANK_SOURCE=ranking_score
```

- 默认切到 `v32`。
- 设置 `MATCH_RANKER_BACKEND=v2` 可立即回滚旧模型。
- v32 加载或推理失败时返回 503，不在同一请求中静默改用 v2，以免快照记录的模型版本与真实模型不一致。
- 非法画像或超过模型限制返回 400，不归类成模型不可用。

## 实施阶段

### 阶段一：移植训练一致的模型与编码器

新增目录：

```text
core/preference/v32/
  __init__.py
  model.py
  encoding.py
  load.py
```

实施内容：

1. 从上游源码原样移植 `ModelConfig` 和 `TenderAlignedV32`，保持模块层级和 state dict 参数键一致。
2. 移植 `stable_bucket`、`field_similarity`、`strict_must_pass`、`CandidateEncoder` 等训练一致逻辑。
3. `load.py` 负责：
   - 按 `V32_FORCE_CPU` 选择设备。
   - 使用 `map_location` 加载 checkpoint。
   - 校验 `model_state`、`config`、`field_to_id`、`type_to_id`、`constraint_to_id`、`numeric_stats` 和 `max_attr`。
   - 校验模型名、张量维度和配置维度，发现 checkpoint 不匹配时快速失败。
   - `strict=True` 加载权重并切换 `eval()`。
4. 不让运行时依赖上游 Profile CSV；训练归一化上限固定使用已核验值：`max_must=2`、`max_prefer=11`，并允许环境变量显式覆盖。

对应测试：

- 新增 `tests/preference/test_v32_model.py`：前向输出形状和空白 padding 行为。
- 新增 `tests/preference/test_v32_encoding.py`：稳定哈希、范围/枚举/关键词相似度、must 严格性、Token 和 global 形状。
- 新增 `tests/preference/test_v32_load.py`：真实 checkpoint 加载、元数据校验、损坏/错误 checkpoint 拒绝。

### 阶段二：实现 PostgreSQL 行适配与 V32Ranker

新增：

```text
core/preference/v32_ranker.py
core/preference/ranker_factory.py
```

`V32Ranker` 实现现有 `Ranker.rank(profile, rows)` 契约，具体流程：

1. 用现有 `profile_to_v2_spec()` 的结构或新建无版本命名的 profile adapter，把 Pydantic 画像转成模型 spec。
2. 对 PostgreSQL 行做最小规范化：
   - 从 `birth_date` 计算 `age`。
   - 把 Rh `+/-` 统一为 `阳性/阴性`。
   - 把 `Decimal`、日期和数据库空值转换成编码器可接受的原生值。
   - 保留原始行对象，排序结果仍返回数据库 donor `id` 和完整展示字段。
3. 校验模型属性数量不超过 checkpoint 的 `max_attr=11`；禁止静默截断属性。
4. 对全部 SQL 合格行执行轻量 `score_only()`，按上游规则确定前 300 人。
5. 只为选中候选创建 `(11, 10)` Token，堆叠成批量张量。
6. 在 `torch.inference_mode()` 和推理锁内执行双头模型。
7. 按 `ranking_score` 排序，但把 `match_score` 放入现有返回元组的 score 位置。
8. 把 `FeatureMatch` 转成现有 `FieldScore`，继续复用候选卡片、快照和日志组装。
9. 记录 `preselect_ms`、`encode_ms`、`model_ms`、`sort_ms`、`eligible_rows` 和 `model_pool_rows`。

`ranker_factory.py` 负责单例、加载错误缓存和后端选择。随后把以下直接导入 v2 的位置改为使用工厂：

- `core/preference/pipeline.py`
- `api/match.py`
- 相关测试 monkeypatch 路径

保留 `core/preference/v2_ranker.py`，只作为显式回滚后端。

对应测试：

- 新增 `tests/preference/test_v32_ranker.py`：
  - 确认只推理规则分前 300 人。
  - 确认排序用 `ranking_score`、展示用 `match_score`。
  - 确认规则分和 code 的稳定同分顺序。
  - 确认年龄、Rh、Decimal 和缺失值转换。
  - 确认字段解释与现有 `FieldScore` 契约一致。
  - 确认只有库存字段时走业务排序。
  - 确认超过 11 个模型字段时返回明确错误。
- 增加一组固定输入的黄金对照测试，保证移植后的编码数组和模型输出与上游源码一致。

### 阶段三：调整结果集、快照和分页语义

修改：

- `core/preference/pipeline.py`
- `api/match.py`
- 必要时扩展 `core/preference/result_types.py`

实施内容：

1. `MatchResult` 明确区分 `filtered_count` 与实际 `ranked_count`。
2. `match_profile()` 仍对 PostgreSQL 返回的全部合格行计数，但只为 V32Ranker 返回的最多 300 人建立引用和快照。
3. `execute_match()` 使用 `len(ranked_refs)` 作为 `total`，并继续返回完整 `filtered_count`。
4. 创建结果集时校验 `len(refs) == total == len(snapshot_items)`，不再要求等于 `filtered_count`。
5. 详情分页仍从冻结快照读取，rank 和 score 不重新计算；重新加载当前 donor 行只用于补充展示和字段解释。
6. refresh 操作使用当前配置模型生成新的结果集，旧快照保留原 `model_version`。

对应测试：

- 修改 `tests/preference/test_compact_match_results.py`，覆盖 4,303 人合格但只保存 300 个模型排名的情况。
- 修改 `tests/test_match_api.py` 和 `tests/test_match_pagination.py`：
  - `filtered_count > total` 合法。
  - 首页、cursor 和任意页跳转不重复、不越过 300 人排名池。
  - 快照条数与排名池一致。
- 保留 v2 测试，验证回滚模式仍能保存全量 v2 排名。

### 阶段四：配置、错误边界和可观测性

修改：

- `config.py`
- `.env.example`
- `api/match.py`
- `main.py`

实施内容：

1. 增加 V32 配置并校验 candidate pool、设备和 rank source。
2. 引入通用 `RankerUnavailable` 和 `RankerInputError`：
   - checkpoint 缺失、权重不兼容、设备错误 → 503。
   - 属性超限、模型不支持的请求 → 400。
3. `/health` 增加不含敏感数据的模型状态：backend、model name、checkpoint role、epoch、device、candidate pool；健康检查不得加载捐精人 CSV。
4. 模型版本从实际加载的 checkpoint 元数据和后端配置生成，写入新快照；避免只依赖可能写错的字符串环境变量。
5. 日志不得输出完整画像、checkpoint 张量或 donor 敏感字段，只记录耗时、数量和模型版本。

### 阶段五：回归、性能验证和切换

执行顺序：

1. 跑 V32 单元和黄金对照测试。
2. 跑现有 preference、match API、快照和分页测试。
3. 跑完整 Python 测试套件。
4. 使用测试 PostgreSQL 数据做端到端请求，核对：
   - must 过滤人数。
   - 模型池最多 300 人。
   - 首页候选、完整排名和快照内容一致。
   - refresh 后生成新模型版本快照。
5. 分别用 `MATCH_RANKER_BACKEND=v32` 和 `v2` 做一次启动及请求 smoke test。
6. 记录 CPU 冷加载、首次推理和热推理耗时；性能门禁以无超时和内存稳定为主，不写容易抖动的毫秒级单测断言。
7. 默认配置切到 v32，重启服务并检查 `/health` 与一条真实匹配请求。

建议验证命令：

```bash
.venv/bin/python -m pytest \
  tests/preference/test_v32_model.py \
  tests/preference/test_v32_encoding.py \
  tests/preference/test_v32_load.py \
  tests/preference/test_v32_ranker.py -v

.venv/bin/python -m pytest \
  tests/preference \
  tests/test_match_api.py \
  tests/test_match_pagination.py \
  tests/test_match_snapshot_postgres.py -v

.venv/bin/python -m pytest -q
```

## 验收标准

- 默认请求实际加载 `best_mae_model_v4.pt`，模型加载错误不会被吞掉。
- 同一组 profile/候选输入的编码数组和双头输出与上游源码一致。
- PostgreSQL 仍是唯一在线候选数据源。
- must 过滤行为与当前系统一致。
- 规则预选严格限制为前 300，排序使用 `ranking_score`，展示使用 `match_score`。
- API 同时正确返回全部合格人数 `filtered_count` 和模型排名人数 `total`。
- 快照、cursor 分页、任意页跳转、停用候选补位及 refresh 均保持一致性。
- 新快照记录准确模型版本；旧快照不受替换影响。
- `MATCH_RANKER_BACKEND=v2` 可以无代码改动回滚。
- 相关测试和完整回归全部通过。

## 风险与边界

### best-MAE 不等于最佳 Top-5

用户指定的 checkpoint 是 `best_mae`。其中验证 MAE 很低，但 checkpoint 内记录的 `top1_agreement` 约为 0.385、`top5_recall` 约为 0.482。实施时按用户提供的模型切换，不擅自换成上游 README 推荐的 balanced checkpoint；上线验收应同时观察实际 Top-5，而不能只看分数误差。

### 训练画像覆盖范围有限

checkpoint 注册了 47 个字段，但随包提供的 5,000 条训练 Profile 实际只出现 28 个字段，keyword 类型主要出现在 `hometown`。医疗史等低频或未出现字段即使存在字段编号，也不能据此宣称排序质量已经充分训练。第一版保证输入、推理和解释契约正确；模型质量需要业务样例或专家集另行验收。

### 模型最多接收 11 个属性

超过 11 个模型属性必须返回明确的 400，不能截断或随机选字段。对话工具提示和画像提交校验需要同步告诉调用方该限制。

### 不提交大体积上游工程

最终代码提交只包含必要源码、测试和 1.6 MB checkpoint。外层 238 MB ZIP、上游虚拟环境和两份 CSV 不进入应用仓库，也不成为生产运行依赖。

## 预计提交拆分

1. `移植 V32 模型和训练一致编码器`
2. `接入 PostgreSQL 候选并实现 V32 排序器`
3. `区分过滤人数与模型排名池快照`
4. `增加模型切换配置和运行状态`
5. `补齐 V32 端到端回归并默认启用新模型`
