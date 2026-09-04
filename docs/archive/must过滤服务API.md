# must 过滤接口

### must 过滤接口

- 接口：`/v1/filter`
- Method-Type：POST
- 数据格式：Json
- 调用方：对话匹配服务（我方）
- 接口说明：按偏好画像里的 **must** 字段对同一张捐精人表做 SQL 硬过滤，只返回代号。口语转换、合法值约束在我方完成；本接口不打分、不猜近义词、不自动放宽 must。`prefer` 字段忽略，不要写进 WHERE。

出参 `codes` 原样交给打分排序接口 `POST /v1/rank` 的 `donors`。

另提供健康检查：`GET /health`，成功返回 `{"ok": true, "service": "filter-v1"}`。

---

#### 请求参数


| 参数             | 类型     | 必须  | 描述                           |
| -------------- | ------ | --- | ---------------------------- |
| request_id     | String | Y   | 追踪 id                        |
| schema_version | String | Y   | 固定 `"1.0"`                   |
| profile        | Object | Y   | 已校验的偏好画像，结构与打分接口相同           |


**profile**


| 参数             | 类型     | 必须  | 描述                         |
| -------------- | ------ | --- | -------------------------- |
| schema_version | String | Y   | 固定 `"1.0"`                 |
| attributes     | Object | Y   | 本轮完整偏好。过滤时只看 `constraint=must` 的项 |


**attributes 里每个字段**


| 参数         | 类型       | 必须               | 描述                                                     |
| ---------- | -------- | ---------------- | ------------------------------------------------------ |
| type       | String   | Y                | `range` / `enum` / `keyword`，由列名决定，见文末对照表              |
| constraint | String   | Y                | `must` 或 `prefer`。仅 `must` 参与过滤                       |
| weight     | Number   | Y                | `[0, 1]`。本接口不使用                                       |
| range      | Object   | type=range 时必填   | `{ "min": 175.0, "max": null }`，min/max 至少一个非 null     |
| values     | String[] | type=enum 时必填    | 库内合法值，多项为「或」。精确匹配                                      |
| keywords   | String[] | type=keyword 时必填 | 子串匹配用的词                                                |
| match      | String   | type=keyword 时选填 | `any`（默认，或）/ `all`（且）                                  |


区间列（`type=range`）：`height_cm` `weight_kg` `bmi` `marriage_age` `age`。  
封闭列（`type=enum`）：血型、学历、职业、吸烟史等，取值已是库内原文。  
籍贯 `hometown`：`type=keyword`。用户只要提了籍贯，上游固定 `constraint=must`；即使用户说「最好」，入参里也会是 must。

> **说明：**
>
> 1. 只过滤 `status = 'active'` 的人。不要返回停用记录。
> 2. 多个 must 字段之间是 **且**（AND）。同一 enum 的 `values` 是 **或**（IN）。
> 3. `prefer`、`weight` 一律忽略。没有 must 时：WHERE 只有 `status = 'active'`，返回全部在库可用代号。
> 4. 某列为空（NULL / 空串）：该 must 条件不成立，此人淘汰。
> 5. 封闭列：`col IN (values)`，字符串精确相等，不归一、不近义。籍贯：`col ILIKE '%keyword%'`（子串）；`match=any` 为多个词 OR，`match=all` 为 AND。
> 6. 区间：`col >= min` 和/或 `col <= max`。`age` 直接比「年龄」列（周岁整数），不要再现场用出生日期计算。
> 7. 命中 0 人：`ok=true` 且 `codes=[]`，**不要**自动去掉某个 must。同时返回 `bottlenecks`，便于顾问告诉用户哪条太严。
> 8. 返回全部命中代号，不要截断、不要分页。顺序建议按 `code` 升序，便于对账；打分接口会重新排序。
> 9. 不要猜近义词，不要补画像里没有的条件。

---

#### 过滤规则（SQL 语义）


| type    | 条件写法 | 示例 |
| ------- | -------- | ---- |
| range   | `col >= :min` 且/或 `col <= :max` | 身高 175 以上 → `height_cm >= 175` |
| enum    | `col IN (:v1, :v2, …)` | 血型 O → `abo_blood IN ('O')` |
| keyword | `col ILIKE '%' \|\| :kw \|\| '%'`，多词按 `match` 连接 | 籍贯重庆 → `hometown ILIKE '%重庆%'` |

等价示意（参数须绑定，禁止拼字符串）：

```
SELECT code
FROM donor.donors
WHERE status = 'active'
  AND /* 每个 must 一条 AND */
ORDER BY code;
```

籍贯特殊字符：`%` `_` `\` 按 LIKE 转义后再包 `%...%`。

---

#### 响应结构


| 参数            | 类型      | 必须  | 描述                                      |
| ------------- | ------- | --- | --------------------------------------- |
| ok            | Boolean | Y   | 成功 `true`                               |
| request_id    | String  | Y   | 回显                                      |
| total         | Integer | Y   | 命中人数，等于 `codes.length`                  |
| codes         | String[] | Y   | 代号列表，如 `["A2600001","A2600002"]`        |
| bottlenecks   | Array   | N   | 仅 `total=0` 且存在 must 时必填；有命中时不要带       |


**bottlenecks[] 每一项**（一次只放松一个 must，其余 must 仍生效）


| 参数        | 类型      | 必须  | 描述                                |
| --------- | ------- | --- | --------------------------------- |
| field     | String  | Y   | 被暂时拿掉的 must 字段                    |
| recovered | Integer | Y   | 拿掉后还能筛出多少人                        |


`recovered` 从大到小排。`recovered=0` 的字段也要列出。用来回答「是哪条硬条件把人滤光了」。

失败时 HTTP 4xx/5xx：


| 参数            | 类型      | 必须  | 描述                                                                        |
| ------------- | ------- | --- | ------------------------------------------------------------------------- |
| ok            | Boolean | Y   | `false`                                                                   |
| request_id    | String  | Y   | 回显                                                                        |
| error.code    | String  | Y   | `INVALID_REQUEST` / `UNAUTHORIZED` / `UNSUPPORTED_SCHEMA` / `INTERNAL`    |
| error.message | String  | Y   | 失败原因                                                                      |


`attributes` 为空或没有任何 must：仍算成功，返回全部 `active` 代号。

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

用户：「必须 O 型，身高最好 175 以上，学历硕士，不要吸烟，籍贯重庆。」  
我方已将「不要吸烟」写成 `"无"`，籍贯固定为 must。身高、学历是 prefer，**不要**写进 WHERE。

```
{
  "request_id": "sess-001-turn-2",
  "schema_version": "1.0",
  "profile": {
    "schema_version": "1.0",
    "attributes": {
      "abo_blood": { "type": "enum", "constraint": "must", "weight": 1.0, "values": ["O"] },
      "height_cm": { "type": "range", "constraint": "prefer", "weight": 0.9, "range": { "min": 175.0, "max": null } },
      "education": { "type": "enum", "constraint": "prefer", "weight": 0.5, "values": ["硕士"] },
      "smoke_history": { "type": "enum", "constraint": "must", "weight": 1.0, "values": ["无"] },
      "hometown": { "type": "keyword", "constraint": "must", "weight": 1.0, "keywords": ["重庆"], "match": "any" }
    }
  }
}
```

对应 WHERE 示意：

```
status = 'active'
AND abo_blood IN ('O')
AND smoke_history IN ('无')
AND hometown ILIKE '%重庆%'
```

不要加 `height_cm >= 175`，不要加 `education IN ('硕士')`。

#### 响应示例（有人）

```
{
  "ok": true,
  "request_id": "sess-001-turn-2",
  "total": 2,
  "codes": ["A2600001", "A2600002"]
}
```

随后我方调用 `/v1/rank`，把上述 `codes` 放进 `donors`，画像原样带上（含 prefer）。

#### 响应示例（0 人）

```
{
  "ok": true,
  "request_id": "sess-001-turn-2",
  "total": 0,
  "codes": [],
  "bottlenecks": [
    { "field": "hometown", "recovered": 86 },
    { "field": "abo_blood", "recovered": 12 },
    { "field": "smoke_history", "recovered": 0 }
  ]
}
```

含义：三条件一起无人；若取消籍贯还能出 86 人；取消血型还能出 12 人；取消吸烟史仍是 0 人（另外两条已经滤光）。**不要**据此自动改 WHERE 再查一次当正式结果。

---

#### 英文字段 ↔ Excel 列名

与《打分排序服务API.md》同一张表、同一套 JSON 键。过滤时只用 must，匹配方式如下。


| JSON 键             | Excel 列       | type    | SQL 条件 |
| ------------------ | ------------- | ------- | -------- |
| code               | 代号            | —       | 主键，本接口返回值 |
| abo_blood          | ABO血型         | enum    | `IN` 精确 |
| rh_blood           | Rh血型          | enum    | `IN` 精确；入参已是「阳性」「阴性」 |
| ethnicity          | 民族            | enum    | `IN` 精确 |
| hometown           | 籍贯            | keyword | `ILIKE` 子串；出现即 must |
| education          | 学历            | enum    | `IN` 精确 |
| occupation         | 职业            | enum    | `IN` 精确 |
| birth_date         | 出生日期          | —       | 不进入 attributes |
| age                | 年龄            | range   | 比「年龄」列，`>= min` / `<= max` |
| constellation      | 星座            | enum    | `IN` 精确 |
| height_cm          | 身高            | range   | `>= min` / `<= max` |
| weight_kg          | 体重            | range   | 同上 |
| bmi                | BMI           | range   | 同上 |
| figure             | 体型            | enum    | `IN` 精确 |
| face_shape         | 脸型            | enum    | `IN` 精确 |
| skin_color         | 肤色            | enum    | `IN` 精确 |
| hair_color         | 发色            | enum    | `IN` 精确 |
| hair_style         | 发型            | enum    | `IN` 精确 |
| hair_volume        | 发量            | enum    | `IN` 精确 |
| eyelid             | 眼皮            | enum    | `IN` 精确 |
| nose_bridge        | 鼻梁            | enum    | `IN` 精确 |
| lip_shape          | 唇型            | enum    | `IN` 精确 |
| sideburns          | 络腮胡           | enum    | `IN` 精确 |
| mustache           | 胡须            | enum    | `IN` 精确 |
| personality        | 性格            | enum    | `IN` 精确 |
| hobby_sports       | 爱好（运动健身类）     | enum    | `IN` 精确 |
| hobby_arts         | 爱好（文化艺术类）     | enum    | `IN` 精确 |
| hobby_leisure      | 爱好（休闲娱乐类）     | enum    | `IN` 精确 |
| hobby_travel       | 爱好（旅游度假类）     | enum    | `IN` 精确 |
| hobby_reading      | 爱好（小说书籍类）     | enum    | `IN` 精确 |
| hobby_food         | 爱好（美食饮品类）     | enum    | `IN` 精确 |
| drink_history      | 喝酒史           | enum    | `IN` 精确 |
| smoke_history      | 吸烟史           | enum    | `IN` 精确 |
| personal_disease   | 个人病史          | enum    | `IN` 精确 |
| present_illness    | 现病史           | enum    | `IN` 精确 |
| past_illness       | 既往病史          | enum    | `IN` 精确 |
| surgery_history    | 手术史           | enum    | `IN` 精确 |
| personal_life_hist | 个人生活史         | enum    | `IN` 精确 |
| partners_6m        | 性伴侣（个）（最近6个月） | enum    | `IN` 精确 |
| std_history        | 性传播疾病史        | enum    | `IN` 精确 |
| marital_fertility  | 婚育史           | enum    | `IN` 精确 |
| marriage_age       | 结婚年龄（岁）       | range   | `>= min` / `<= max`；空则淘汰 |
| children_info      | 生育子女          | enum    | `IN` 精确；空则淘汰 |
| genetic_history    | 遗传病史          | enum    | `IN` 精确 |
| chromosome_disease | 染色体病          | enum    | `IN` 精确 |
| monogenic_disease  | 单基因遗传病        | enum    | `IN` 精确 |
| polygenic_disease  | 多基因遗传病        | enum    | `IN` 精确 |
| consanguinity      | 近亲婚配          | enum    | `IN` 精确 |

合法取值（血型 A/B/O/AB、吸烟史 有/无 等）与打分文档完全相同，此处不重复。
