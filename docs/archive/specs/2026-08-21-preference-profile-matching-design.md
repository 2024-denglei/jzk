# 对话偏好画像与加权匹配

**日期：** 2026-08-21  
**状态：** 待用户确认规格全文  
**范围：** 智能对话核心算法——大模型输出偏好画像 JSON，后台先 SQL 硬过滤再按字段加权排序

## 背景

当前对话匹配由大模型抽出结构化条件后，用内存硬过滤（效果接近 SQL `WHERE`）筛人，再用整向量余弦 + 欧氏距离排序；无结果时逐步把 `must` 放宽为 `prefer`。工具 `match_donors` 的参数既是增量条件又是过滤条件，完整偏好状态不清晰。

老师要求：通过多轮对话理解用户对**每个属性**的偏好强度以及取值/范围，由后台做相似度排序。后续可能训练排序模型，替换规则打分，但输入接口应保持不变。

## 已确认决策

| 项 | 选择 |
|---|---|
| 流水线 | 先 SQL 硬过滤，再加权相似度排序 |
| 硬/软分流 | 大模型根据对话判断 `must` / `prefer`；匹配层不猜意图 |
| 偏好表示 | `constraint` + `weight`∈[0,1] |
| 多轮输出 | 每轮输出**完整画像**；取消的属性从 JSON 中消失 |
| 排序 | 按属性打分后加权平均；must 通过过滤后仍参与打分 |
| 以后换模型 | 只替换 Ranker；LLM 仍出同一份 JSON |
| 字段覆盖 | 捐精人属性字段（排除系统/检测原文） |
| 取值形态 | range / enum / keyword 三类，由字段注册表锁定 |
| 契约 | PreferenceProfile 为唯一输入；SQL 由代码生成，模型不写 SQL |
| 无结果 | 不自动放宽 must；返回空列表 + 瓶颈字段 |
| 左侧筛选 | `/api/search` 本规格不改 |

## 非范围

- 左侧条件筛选 API 与优先级放宽逻辑
- 管理端导入、建库脚本
- 前端大改版（卡片继续消费 `score` 与分项；字段名改为 schema 英文 key）
- 训练排序模型本身（只预留日志与 Ranker 接口）

## 架构

```text
用户发言
  → 对话 Agent（历史 + 上一份合法画像）
  → 完整 PreferenceProfile JSON（structured output）
  → Pydantic / JSON Schema 校验
  → 会话替换为新画像
  → HardFilter：仅 must → 参数化 SQL
  → Ranker.score(profile, donors)   // 现规则，后可换模型
  → 前端卡片
  → 训练日志 + 用户反馈事件
```

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| 对话 Agent | 判断 must/prefer、weight、取值/范围；每轮完整画像 | 不写 SQL、不列举具体捐精人 |
| Schema 校验 | 字段名、类型、枚举、weight、constraint | 不补全用户未提及的偏好 |
| HardFilter | 只把 must 编成 `WHERE`（参数绑定） | 不用 prefer 过滤 |
| Ranker | 对候选打分排序 | 不改画像 |
| 训练日志 | profile、捐精人特征、分项分、反馈 | 不让模型编标签 |

替换现有 `match_donors`：一次提交完整画像。内存 pandas 硬过滤改为对 `donor.donors` 的参数化查询。仅 `status = 'active'`。

校验失败或未产出画像：沿用上一轮合法画像，本轮不跑新匹配。`attributes` 为空：不匹配，当闲聊。

## JSON Schema（匹配层唯一输入）

信封：

```json
{
  "schema_version": "1.0",
  "attributes": {
    "<field>": { }
  }
}
```

规则：

- `schema_version` 必须为 `"1.0"`
- 每轮都是完整快照；未出现的字段视为无偏好
- 禁止未注册字段；禁止系统字段：`code`、`serial_no`、`status`、`semen_test`、`blood_test`、`chromosome_test`、`microbio_test`、`remark`
- 每个出现的属性必须同时有 `constraint`（`must` | `prefer`）和 `weight`（0–1 的数）
- 模型未表达重要程度时：`must` 填 `1.0`，`prefer` 填 `0.5`
- 全部 weight 为 0：整份非法
- structured output 约束形状，代码再校验一遍

### 三类属性

**RangeAttr**（`height_cm` `weight_kg` `bmi` `age` `specimen_count`）

```json
{
  "constraint": "must",
  "weight": 0.9,
  "range": { "min": 175, "max": null }
}
```

`min` / `max` 至少一个非 null。单位由字段约定（cm / kg / 无量纲 / 岁 / 管），JSON 不写单位。`age` 由 `birth_date` 算周岁，模型不写出生日期。

**EnumAttr**（`education` `abo_blood` `rh_blood` `figure` `skin_color` `face_shape` `eyelid` `lip_shape` `constellation`）

```json
{
  "constraint": "prefer",
  "weight": 0.7,
  "values": ["硕士", "博士"]
}
```

`values` 非空数组，元素必须属于该字段枚举；多项为「或」。

枚举取值：

| 字段 | 合法值 |
|---|---|
| education | 大专、本科、硕士、博士 |
| abo_blood | A、B、O、AB |
| rh_blood | 阳性、阴性（入库的 `+`/`-` 在匹配前规范成阳性/阴性） |
| figure | 一般、瘦弱、强壮、肥胖、匀称型、精壮型、偏瘦型 |
| skin_color | 偏白、一般、偏黑 |
| face_shape | 长方、长、椭圆、瓜子、圆、方、菱形 |
| eyelid | 单、双、内双 |
| lip_shape | 一般、厚、薄、厚唇、薄唇、适中 |
| constellation | 白羊座、金牛座、双子座、巨蟹座、狮子座、处女座、天秤座、天蝎座、射手座、摩羯座、水瓶座、双鱼座 |

**KeywordAttr**（其余捐精人属性）

```json
{
  "constraint": "must",
  "weight": 0.8,
  "keywords": ["不吸", "无吸烟"],
  "match": "any"
}
```

字段：`ethnicity` `hometown` `occupation` `personality` `hair_color` `hair_style` `hair_volume` `nose_bridge` `sideburns` `mustache` `hobby_sports` `hobby_arts` `hobby_leisure` `hobby_travel` `hobby_reading` `hobby_food` `drink_history` `smoke_history` `personal_disease` `present_illness` `past_illness` `surgery_history` `personal_life_hist` `partners_6m` `std_history` `marital_fertility` `marriage_age` `children_info` `genetic_history` `chromosome_disease` `monogenic_disease` `polygenic_disease` `consanguinity` `availability`

- `keywords` 非空字符串数组；单项最长 20 字，最多 8 个
- `match`：`any`（默认，或）| `all`（且）
- `kind` 由注册表决定，模型不能把身高写成 keywords

### 示例

用户：「必须 O 型，身高最好 175 以上（这个最重要），学历硕士就行，不要吸烟。」

```json
{
  "schema_version": "1.0",
  "attributes": {
    "abo_blood": {
      "constraint": "must",
      "weight": 1.0,
      "values": ["O"]
    },
    "height_cm": {
      "constraint": "prefer",
      "weight": 0.9,
      "range": { "min": 175, "max": null }
    },
    "education": {
      "constraint": "prefer",
      "weight": 0.5,
      "values": ["硕士"]
    },
    "smoke_history": {
      "constraint": "must",
      "weight": 1.0,
      "keywords": ["无", "不吸"],
      "match": "any"
    }
  }
}
```

硬过滤：`abo_blood`、`smoke_history`。四项都参与排序，身高权重最高。

## 硬过滤（SQL）

代码根据画像生成参数化 SQL，模型不得输出 SQL 字符串。

公共条件：`status = 'active'`。

仅 `constraint = must` 进入 `WHERE`：

| kind | 条件 |
|---|---|
| range | `col >= :min` 和/或 `col <= :max`；`age`：用 `birth_date` 计算周岁后再比较 |
| enum | `col IN (:values)`；Rh 先规范化 |
| keyword | `any`：多个 `col ILIKE '%' \|\| :kw \|\| '%'` 以 OR 连接；`all` 以 AND 连接。关键词中的 `%`、`_` 必须转义后再绑定 |

无 must 时不加偏好谓词。prefer 身高不得出现在 `WHERE`。

must 过滤后 0 行：返回空列表，并计算瓶颈——对每个 must 字段，去掉该字段后能恢复的人数，按恢复人数降序交给对话层。不自动把 must 改成 prefer。

## 打分（当前 Ranker）

对硬过滤后的每一行、画像中的每一个属性计算 `s_f ∈ [0, 1]`，must 与 prefer 都算。

**Range**（`σ`：身高 10cm，体重 8kg，BMI 3，年龄 5 岁，标本 3 管）

必须同时满足：区间外越远越低；区间内「刚好踩线」低于更舒适的值（例如 must 为 ≥175 时，180 高于 175）。

- 仅 min：理想点 `ideal = min + σ`。`x >= min` 时 `s = 0.8 + 0.2 * clamp((x - min) / σ, 0, 1)`（175→0.8，185→1）；`x < min` 时 `s = 0.8 * max(0, 1 - (min - x) / σ)`
- 仅 max：对称，`ideal = max - σ`；踩线 max 为 0.8，降到 `max - σ` 为 1，超出 max 则从 0.8 衰减到 0
- min 与 max 都有：区间内 `s = 1`；区间外用离最近端点的距离、以 `σ` 衰减到 0

**Enum**

- 无序（血型、脸型、眼皮、唇型、星座、Rh）：命中 `values` 为 1，否则 0
- 有序：学历 大专=1 < 本科=2 < 硕士=3 < 博士=4；肤色 偏黑=1 < 一般=2 < 偏白=3。`s = 1 - |rank(实际) - rank(目标)| / max_rank_gap`（对称距离，不是「越高越好」）。`values` 多项时取与实际最接近的一档。`max_rank_gap` 为该字段最大等级差（学历 3，肤色 2）
- 实际值不在枚举表：`s = 0`

**Keyword**

- `any`：命中任一关键词为 1，否则 0
- `all`：全部命中为 1，否则 0
- 列值为 NULL：`s = 0`（must 已在 SQL 排除不匹配行）

**总分**

```text
score = Σ (s_f × weight_f) / Σ weight_f
```

只对画像中出现的属性求和。排序：`score` 降序，同分按 `specimen_count` 降序。

返回给前端：总分、各字段 `field_scores`（字段、实际值、目标、s_f、weight、constraint），便于展示与训练。

不再使用整向量余弦/欧氏融合，不再做渐进放宽。

`Ranker` 接口：`score(profile, donor_features) -> (total, field_scores)`。以后训练模型实现同一接口，HardFilter 与 PreferenceProfile 不变。

## 异常处理

| 情况 | 行为 |
|---|---|
| JSON 非法（缺字段、多余字段、枚举超范围、weight 越界、range 全空、全 0 权重） | 整份丢弃，沿用上一轮合法画像；不跑新匹配；请用户说清楚 |
| 模型未产出画像 | 同上，当闲聊 |
| `attributes` 为空 | 不匹配 |
| must 过滤 0 人 | 空列表 + 瓶颈字段 |
| LLM / 数据库失败 | 明确错误，不编造候选人 |

## 训练日志

每次成功匹配写一条 turn；用户反馈另写事件，用 `session_id + donor_code` 对齐。大模型不写标签。

Turn：`schema_version`、完整 `preference_profile`、过滤后人数、返回给前端的有序列表。每个候选人：`code`、画像用到的属性原值、`field_scores`、`score`、`rank`。

事件：满意、不满意、打开详情、收藏（带时间）。满意、收藏为正例；不满意为负例；打开详情为弱正例。

不记录检测原文与备注。存储格式（JSONL 或表）实现时选择，导出必须能按 turn 得到上述字段。

## 测试

先写锁行为的测试，再改匹配路径。

- 校验：合法画像通过；非法枚举、多余字段、空 range 拒绝
- SQL：仅 must 出现在 WHERE；prefer 的 `height_cm` 不得生成 `height_cm >=`
- 打分：仅下限 175 时 185 > 180 > 175 > 170；目标仅为硕士时 硕士 > 博士 = 本科 > 大专（对称等级距离）
- 0 人 must：空结果且带瓶颈，不自动放宽
- 取消属性：下一轮 JSON 无该字段后，SQL 与打分均不含它

## 成功标准

- 对话只通过合法 PreferenceProfile 驱动匹配
- must 决定候选集，weight 决定顺序，结果可解释到字段
- 同一份 JSON 可直接作为以后排序模型的查询特征
- 旧 `match_donors` 增量参数不再作为匹配输入
