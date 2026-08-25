# 打分排序接口

### 打分排序接口

- 接口：`/v1/rank`
- Method-Type：POST
- 数据格式：Json
- 调用方：对话匹配服务（我方）
- 接口说明：对 **must 过滤后的捐精人** 按偏好画像打分并排序。候选代号来自 `POST /v1/filter`。我方只传代号；你们按 `code` 查同一张捐精人表取特征值。口语转换、合法值约束均在我方完成；本接口不筛人、不猜近义词。

另提供健康检查：`GET /health`，成功返回 `{"ok": true, "model": "heuristic-v1"}`。

---

#### 请求参数


| 参数             | 类型       | 必须  | 描述                                                |
| -------------- | -------- | --- | ------------------------------------------------- |
| request_id     | String   | Y   | 追踪 id                                             |
| schema_version | String   | Y   | 固定 `"1.0"`                                        |
| top_k          | Integer  | N   | 返回前 K 名；`0` 或缺省 = 全部返回                            |
| profile        | Object   | Y   | 已校验的偏好画像，见下表                                      |
| donors         | String[] | Y   | must 过滤后的代号列表，如 `["A2600001","A2600002"]`，允许 `[]` |


**profile**


| 参数             | 类型     | 必须  | 描述                |
| -------------- | ------ | --- | ----------------- |
| schema_version | String | Y   | 固定 `"1.0"`        |
| attributes     | Object | Y   | 本轮完整偏好。没出现的字段不要打分 |


**attributes 里每个字段**


| 参数         | 类型       | 必须               | 描述                                                     |
| ---------- | -------- | ---------------- | ------------------------------------------------------ |
| type       | String   | Y                | 取值类型：`range`（数值区间）/ `enum`（封闭枚举）/ `keyword`（开放文本，子串模糊） |
| constraint | String   | Y                | `must` 或 `prefer`。打分公式相同，只是 weight 不同                  |
| weight     | Number   | Y                | `[0, 1]`                                               |
| range      | Object   | type=range 时必填   | `{ "min": 175.0, "max": null }`，min/max 至少一个非 null     |
| values     | String[] | type=enum 时必填    | 库内合法值，多项为「或」。精确匹配                                      |
| keywords   | String[] | type=keyword 时必填 | 子串匹配用的词                                                |
| match      | String   | type=keyword 时选填 | `any`（默认，或）/ `all`（且）                                  |


`type` 由列名决定，见文末对照表，不要混用。  

- `range`：库内值为 Number  
- `enum` / `keyword`：库内值为 String

区间列（`type=range`）：`height_cm` `weight_kg` `bmi` `marriage_age` `age`。  
封闭列（`type=enum`）：血型、学历、职业、吸烟史等，取值已是库内原文。  
籍贯 `hometown`：`type=keyword`。用户只要提了籍贯，上游固定 `constraint=must`，用子串硬过滤（「重庆」匹配「重庆市…」）；滤完的人这项分都是 1，不再当偏好去拉开名次。没有匹配到则 0 人，不自动放宽。

> **说明：**  
>
> 1. `donors` 只含 `code`。按代号查库取身高、学历等，不要再做 must 过滤，不要补名单外的人。
> 2. 某 `code` 在库中不存在：整单失败，`error.code = DONOR_NOT_FOUND`。
> 3. 某字段为空则该项分 0，该人仍要返回。`donors` 为空：`ok=true` 且 `ranked=[]`。
> 4. `top_k=0` 时 `ranked` 人数必须等于 `donors`。
> 5. 封闭列精确匹配。籍贯：子串匹配，且入参里若出现则必为 must（我方已过滤）。
> 6. 总分：`score = Σ(s_f × weight_f) / Σ weight_f`，`s_f ∈ [0,1]`。排序：score 降序，同分保持 `donors` 原顺序。
> 7. 学历、肤色按等级距离打分（硕士目标：硕士 > 博士 = 本科 > 大专）。身高仅 min=175 时：185 > 180 > 175 > 170。年龄同理（仅 min=25 时：30 > 28 > 25 > 22）。

---



#### 响应结构


| 参数         | 类型      | 必须  | 描述                   |
| ---------- | ------- | --- | -------------------- |
| ok         | Boolean | Y   | 成功 `true`            |
| request_id | String  | Y   | 回显                   |
| model      | String  | Y   | 实现名，如 `heuristic-v1` |
| ranked     | Array   | Y   | 已按得分降序               |


**ranked[] 每一项**


| 参数           | 类型      | 必须  | 描述                   |
| ------------ | ------- | --- | -------------------- |
| code         | String  | Y   | 与入参同一人               |
| score        | Number  | Y   | 总分 `[0, 1]`，建议 4 位小数 |
| rank         | Integer | Y   | 从 1 开始               |
| field_scores | Array   | Y   | 画像中每个字段一条            |


**field_scores[] 每一项**


| 参数         | 类型     | 必须  | 描述                              |
| ---------- | ------ | --- | ------------------------------- |
| field      | String | Y   | 如 `height_cm`                   |
| actual     | Any    | Y   | 该人实际值，缺为 `null`                 |
| target     | Any    | Y   | 回显偏好（range / values / keywords） |
| s          | Number | Y   | 该项 `[0, 1]`                     |
| weight     | Number | Y   | 回显                              |
| constraint | String | Y   | `must` / `prefer`               |


失败时 HTTP 4xx/5xx：


| 参数            | 类型      | 必须  | 描述                                                                                         |
| ------------- | ------- | --- | ------------------------------------------------------------------------------------------ |
| ok            | Boolean | Y   | `false`                                                                                    |
| request_id    | String  | Y   | 回显                                                                                         |
| error.code    | String  | Y   | `INVALID_REQUEST` / `DONOR_NOT_FOUND` / `UNAUTHORIZED` / `UNSUPPORTED_SCHEMA` / `INTERNAL` |
| error.message | String  | Y   | 失败原因                                                                                       |


`donors` 为空属于成功：`ok=true` 且 `ranked=[]`。

---



### 示例



#### 请求头

```
{
  "Authorization": "Bearer <token>",
  "Content-Type": "application/json"
}
```



#### 请求示例

用户：「必须 O 型，身高最好 175 以上，学历硕士，不要吸烟。」  
我方已将「不要吸烟」写成库内值 `"无"`，并滤出 O 型且不吸烟的人。

```
{
  "request_id": "sess-001-turn-2",
  "schema_version": "1.0",
  "top_k": 0,
  "profile": {
    "schema_version": "1.0",
    "attributes": {
      "abo_blood": { "type": "enum", "constraint": "must", "weight": 1.0, "values": ["O"] },
      "height_cm": { "type": "range", "constraint": "prefer", "weight": 0.9, "range": { "min": 175.0, "max": null } },
      "education": { "type": "enum", "constraint": "prefer", "weight": 0.5, "values": ["硕士"] },
      "smoke_history": { "type": "enum", "constraint": "must", "weight": 1.0, "values": ["无"] }
    }
  },
  "donors": ["A2600001", "A2600002"]
}
```



#### 响应示例

```
{
  "ok": true,
  "request_id": "sess-001-turn-2",
  "model": "heuristic-v1",
  "ranked": [
    {
      "code": "A2600001",
      "score": 1.0,
      "rank": 1,
      "field_scores": [
        { "field": "abo_blood", "actual": "O", "target": ["O"], "s": 1.0, "weight": 1.0, "constraint": "must" },
        { "field": "height_cm", "actual": 185.0, "target": { "min": 175.0, "max": null }, "s": 1.0, "weight": 0.9, "constraint": "prefer" },
        { "field": "education", "actual": "硕士", "target": ["硕士"], "s": 1.0, "weight": 0.5, "constraint": "prefer" },
        { "field": "smoke_history", "actual": "无", "target": ["无"], "s": 1.0, "weight": 1.0, "constraint": "must" }
      ]
    },
    {
      "code": "A2600002",
      "score": 0.8971,
      "rank": 2,
      "field_scores": [
        { "field": "abo_blood", "actual": "O", "target": ["O"], "s": 1.0, "weight": 1.0, "constraint": "must" },
        { "field": "height_cm", "actual": 175.0, "target": { "min": 175.0, "max": null }, "s": 0.8, "weight": 0.9, "constraint": "prefer" },
        { "field": "education", "actual": "本科", "target": ["硕士"], "s": 0.6667, "weight": 0.5, "constraint": "prefer" },
        { "field": "smoke_history", "actual": "无", "target": ["无"], "s": 1.0, "weight": 1.0, "constraint": "must" }
      ]
    }
  ]
}
```

A2600001 应排在 A2600002 之前。

---



#### 英文字段 ↔ Excel 列名

对照《新生成的模拟捐精人信息数据3000条》表头。`age` 对应表中「年龄」列，由「出生日期」按周岁生成。


| JSON 键             | Excel 列       | type    | 值类型    | 匹配方式   | 本批合法值 / 说明            |
| ------------------ | ------------- | ------- | ------ | ------ | --------------------- |
| code               | 代号            | —       | String | 主键     | `A2600001` …          |
| abo_blood          | ABO血型         | enum    | String | 精确     | A / B / O / AB        |
| rh_blood           | Rh血型          | enum    | String | 精确     | 阳性 / 阴性               |
| ethnicity          | 民族            | enum    | String | 精确     | 汉族、回族、苗族、彝族、土家族、满族、侗族 |
| hometown           | 籍贯            | keyword | String | 子串，且恒为 must | 用户说「重庆」则 `keywords:["重庆"]`；匹配「重庆市…」。无命中则 0 人 |
| education          | 学历            | enum    | String | 精确（有序） | 大专 / 本科 / 硕士 / 博士     |
| occupation         | 职业            | enum    | String | 精确     | 产品运营 / 健身教练 / 公务员 / 学生 / 工程师 / 市场专员 / 建筑师 / 技术员 / 教师 / 程序员 / 设计师 / 财务专员 / 钢琴老师 / 项目经理 |
| birth_date         | 出生日期          | —       | String | 库内原文   | `YYYY-MM-DD`。不进入 `attributes` |
| age                | 年龄            | range   | Number | 区间（周岁） | 由出生日期生成：年份差，生日未到减 1。画像写 `{min,max}`，如 30 岁以下 → `{max:30}`。空则该项分 0 |
| constellation      | 星座            | enum    | String | 精确     | 白羊座 / 金牛座 / 双子座 / 巨蟹座 / 狮子座 / 处女座 / 天秤座 / 天蝎座 / 射手座 / 摩羯座 / 水瓶座 / 双鱼座 |
| height_cm          | 身高            | range   | Number | 区间     | cm                    |
| weight_kg          | 体重            | range   | Number | 区间     | kg                    |
| bmi                | BMI           | range   | Number | 区间     |                       |
| figure             | 体型            | enum    | String | 精确     | 一般 / 瘦弱 / 强壮 / 肥胖     |
| face_shape         | 脸型            | enum    | String | 精确     | 长方 / 长 / 椭圆 / 瓜子      |
| skin_color         | 肤色            | enum    | String | 精确（有序） | 偏白 / 一般 / 偏黑          |
| hair_color         | 发色            | enum    | String | 精确     | 黑 / 棕 / 杂白            |
| hair_style         | 发型            | enum    | String | 精确     | 直 / 微曲 / 卷曲           |
| hair_volume        | 发量            | enum    | String | 精确     | 一般 / 浓密 / 稀疏          |
| eyelid             | 眼皮            | enum    | String | 精确     | 单 / 双                 |
| nose_bridge        | 鼻梁            | enum    | String | 精确     | 高直 / 中直 / 低塌          |
| lip_shape          | 唇型            | enum    | String | 精确     | 一般 / 厚 / 薄            |
| sideburns          | 络腮胡           | enum    | String | 精确     | 有 / 无                 |
| mustache           | 胡须            | enum    | String | 精确     | 稠密 / 稀疏               |
| personality        | 性格            | enum    | String | 精确     | 内向 / 外向               |
| hobby_sports       | 爱好（运动健身类）     | enum    | String | 精确     | 有 / 无                 |
| hobby_arts         | 爱好（文化艺术类）     | enum    | String | 精确     | 有 / 无                 |
| hobby_leisure      | 爱好（休闲娱乐类）     | enum    | String | 精确     | 有 / 无                 |
| hobby_travel       | 爱好（旅游度假类）     | enum    | String | 精确     | 有 / 无                 |
| hobby_reading      | 爱好（小说书籍类）     | enum    | String | 精确     | 有 / 无                 |
| hobby_food         | 爱好（美食饮品类）     | enum    | String | 精确     | 有 / 无                 |
| drink_history      | 喝酒史           | enum    | String | 精确     | 有 / 无                 |
| smoke_history      | 吸烟史           | enum    | String | 精确     | 有 / 无                 |
| personal_disease   | 个人病史          | enum    | String | 精确     | 有 / 无                 |
| present_illness    | 现病史           | enum    | String | 精确     | 无 / 慢性胃炎 / 轻度痤疮 / 轻度过敏性鼻炎 / 轻度近视 |
| past_illness       | 既往病史          | enum    | String | 精确     | 无 / 扁桃体炎 / 支气管炎 / 水痘 / 甲肝（已治愈） / 疝气 / 肺炎 / 腮腺炎 / 荨麻疹 / 阑尾炎 / 骨折 / 麻疹 |
| surgery_history    | 手术史           | enum    | String | 精确     | 无 / 包皮环切术 / 扁桃体切除术 / 激光近视手术 / 疝气修补术 / 表皮囊肿切除术 / 阑尾切除术 / 鞘膜积液手术 / 骨折内固定术 |
| personal_life_hist | 个人生活史         | enum    | String | 精确     | 无（表头另列：放射性接触 / 有毒有害 / 吸毒史 / 同性恋史 / 冶游史；本批数据仅「无」） |
| partners_6m        | 性伴侣（个）（最近6个月） | enum    | String | 精确     | 0 / 1 / 2 / 3         |
| std_history        | 性传播疾病史        | enum    | String | 精确     | 本批均为「无」               |
| marital_fertility  | 婚育史           | enum    | String | 精确     | 未婚未育 / 已婚未育 / 已婚已育    |
| marriage_age       | 结婚年龄（岁）       | range   | Number | 区间     | 本批 22～35；未婚未育多为空     |
| children_info      | 生育子女          | enum    | String | 精确     | 1男 / 1女 / 2男 / 2女 / 1男1女 / 1男2女 / 2男1女；未育多为空 |
| genetic_history    | 遗传病史          | enum    | String | 精确     | 有 / 无                 |
| chromosome_disease | 染色体病          | enum    | String | 精确     | 本批均为「无」               |
| monogenic_disease  | 单基因遗传病        | enum    | String | 精确     | 本批均为「无」               |
| polygenic_disease  | 多基因遗传病        | enum    | String | 精确     | 本批均为「无」               |
| consanguinity      | 近亲婚配          | enum    | String | 精确     | 本批均为「无」               |


