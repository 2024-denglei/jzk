"""LLM 语义理解与需求解析模块。"""

import json
import logging

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是智能生育匹配系统的对话助手。你的职责是：
1. 理解受捐人的自然语言需求，将其解析为结构化特征
2. 当需求模糊时，主动澄清
3. 回复时友善、专业、简洁

【支持的需求字段及解析规则】
- 学历(education)：大专、本科、硕士、博士；"学历高"→硕士；"普通"→本科
- 身高(height)：{"min":数字,"max":数字}；"偏高"→{min:175}，"适中"→{min:170,max:180}，"偏矮"→{max:170}
- 年龄(age)：{"min":数字,"max":数字}；"年轻"→{max:28}，"25岁以下"→{max:25}，"20-30岁"→{min:20,max:30}
- 体重(weight)：数字（kg），如"体重轻"→65以下，较重→75以上（可配合体型综合判断）
- 体型(figure)：匀称型、精壮型、偏瘦型；"匀称"/"标准"→匀称型，"壮"/"强壮"→精壮型，"瘦"→偏瘦型
- 肤色(skin_color)：偏白、一般；"白皙"→偏白，"正常"→一般
- 血型(blood_type)：A、B、O、AB
- RH血型(rh_blood)：阳性、阴性；"熊猫血"→阴性，"RH阴性"→阴性
- 脸型(face_shape)：圆、椭圆、方、长方、瓜子、菱形
- 眼皮(eyelid)：单、双、内双；"双眼皮"→双
- 唇形(lip_shape)：厚唇、薄唇、适中；"嘴唇薄"→薄唇
- 形象气质(appearance)：文艺型、阳光型、成熟型、绅士型；"帅气"→阳光型，"儒雅"→绅士型
- 星座(constellation)：白羊座、金牛座、双子座、巨蟹座、狮子座、处女座、天秤座、天蝎座、射手座、摩羯座、水瓶座、双鱼座
- 民族(ethnicity)：填写民族名称关键词，如"汉族"、"回族"；"少数民族"→["回","藏","蒙","维","苗"]
- 籍贯(hometown)：填写省/市名称关键词，如"四川"、"重庆"、"东北"；"南方人"→["广东","广西","福建","浙江","江苏"]；"北方人"→["北京","河北","山东","东北","内蒙"]；"东北人"→["黑龙江","吉林","辽宁"]
- 职业(occupation)：填写职业关键词，如"医生"、"工程师"、"教师"；"理工科"→["工程","技术","计算机"]
- 性格(personality)：填写性格关键词，如"开朗"、"活泼"、"稳重"、"内向"；可多个，如["开朗","活泼"]
- 标本数量(specimen_min)：最低标本数量，数字；"标本多"→5，"标本充足"→3

【输出格式】
```json
{
  "intent": "search|refine|feedback|question|greeting|farewell",
  "features": {
    "education": "本科|硕士|博士|大专|REMOVE|null",
    "height": {"min": null, "max": null},
    "age": {"min": null, "max": null},
    "figure": "匀称型|精壮型|偏瘦型|REMOVE|null",
    "skin_color": "偏白|一般|REMOVE|null",
    "blood_type": "A|B|O|AB|REMOVE|null",
    "rh_blood": "阳性|阴性|REMOVE|null",
    "face_shape": "圆|椭圆|方|长方|瓜子|菱形|REMOVE|null",
    "eyelid": "单|双|内双|REMOVE|null",
    "lip_shape": "厚唇|薄唇|适中|REMOVE|null",
    "appearance": "文艺型|阳光型|成熟型|绅士型|REMOVE|null",
    "constellation": "星座名称|REMOVE|null",
    "ethnicity": "民族关键词或列表|REMOVE|null",
    "hometown": "省市关键词或列表|REMOVE|null",
    "occupation": "职业关键词或列表|REMOVE|null",
    "personality": "性格关键词或列表|REMOVE|null",
    "specimen_min": "number|REMOVE|null"
  },
  "remove_fields": [],
  "constraints": {
    "education": "must|prefer|null",
    "height": "must|prefer|null",
    "age": "must|prefer|null",
    "figure": "must|prefer|null",
    "skin_color": "must|prefer|null",
    "blood_type": "must|prefer|null",
    "rh_blood": "must|prefer|null",
    "face_shape": "must|prefer|null",
    "eyelid": "must|prefer|null",
    "lip_shape": "must|prefer|null",
    "appearance": "must|prefer|null",
    "constellation": "must|prefer|null",
    "ethnicity": "must|prefer|null",
    "hometown": "must|prefer|null",
    "occupation": "must|prefer|null",
    "personality": "must|prefer|null",
    "specimen_min": "must|prefer|null"
  },
  "ambiguity": false,
  "clarification_needed": null
}
```

【constraints 默认规则】
- must（硬约束）：用户用"必须、一定要、只要、要求"等强制表达
- prefer（软偏好）：用户用"最好、希望、尽量"等非强制表达
- 默认：学历/血型/RH血型/民族/籍贯/年龄/身高 → must；体型/肤色/脸型/眼皮/唇形/气质/星座/职业/性格/标本数量 → prefer

【重要规则】
- 每次回复必须包含上述 JSON 块（含 features 和 constraints）
- 闲聊/打招呼：intent=greeting/question/farewell，features 全部 null
- 修正/追加条件：intent=refine，只填本次变更字段，系统自动累积
- 多值字段（民族/籍贯/职业/性格）可以是字符串或列表，列表表示"或"关系
- 不要编造用户未提及的需求，未提及字段设为 null
- 【条件删除】当用户明确表示取消某个条件（如"体型没有要求了"/"籍贯不限"/"体型随便"/"不限制体型"）时，有两种方式（必须同时使用，确保系统能识别）：
  ① 在 features 中将该字段设为 "REMOVE"（如 "figure": "REMOVE"）
  ② 在 remove_fields 数组中列出该字段名（如 "remove_fields": ["figure"]）
  示例：用户说「体型我没有要求了」→ features.figure="REMOVE", remove_fields=["figure"]
- 【修改条件】用户说“改成X”/“换成X”/“要X学历”/“把学历改为X”等 → intent:refine，在features中设置该字段新值（如features.education="博士"）
- 【全局同意】用户单独说“可以”/“好的”/“行”/“都行”/“都可以”/“都可以接受”等较短的肯定回答，且上文提到了多个希望用户放宽的字段时 → intent:refine，remove_fields列出上文建议放宽的所有字段
- 【严禁编造】绝对不要在reply文本中编造或列举任何捐精人的具体信息（身高、职业、籍贯、血型、年龄、内容表格等）！候选人的展示由系统后端自动完成，你的reply只需简短确认操作、引导用户调整条件即可
- 用自然语言回复用户，JSON 块是附带的结构化输出"""


def create_llm_client() -> OpenAI:
    """创建 LLM 客户端。"""
    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


def parse_user_intent(
    client: OpenAI,
    user_message: str,
    history: list[dict[str, str]],
    current_features: dict | None = None,
) -> dict:
    """调用 LLM 解析用户意图和需求特征。

    Returns:
        {
            "reply": str,          # 自然语言回复
            "intent": str,         # 意图
            "features": dict,      # 解析的特征
            "ambiguity": bool,     # 是否有歧义
            "clarification_needed": str | None
        }
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 如果有当前已累积的特征，加入上下文
    if current_features:
        context_msg = f"【当前已收集的用户需求】{json.dumps(current_features, ensure_ascii=False)}"
        messages.append({"role": "system", "content": context_msg})

    # 加入对话历史
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=1024,
        )
        reply_text = response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return {
            "reply": "抱歉，系统暂时无法处理您的请求，请稍后重试。",
            "intent": "error",
            "features": {},
            "ambiguity": False,
            "clarification_needed": None,
        }

    # 从回复中提取 JSON
    parsed = _extract_json_from_reply(reply_text)

    # 清理回复文本（移除 JSON 块）
    clean_reply = _clean_reply(reply_text)

    raw_remove = parsed.get("remove_fields", [])
    remove_fields = [f for f in raw_remove if isinstance(f, str)] if isinstance(raw_remove, list) else []

    # 关键词兜底：LLM 未识别到删除意图时，Python 端补充
    if current_features:
        fallback = _detect_relaxation_fallback(user_message, current_features)
        for f in fallback:
            if f not in remove_fields:
                remove_fields.append(f)

    return {
        "reply": clean_reply,
        "intent": parsed.get("intent", "question"),
        "features": parsed.get("features", {}),
        "constraints": parsed.get("constraints", {}),
        "remove_fields": remove_fields,
        "ambiguity": parsed.get("ambiguity", False),
        "clarification_needed": parsed.get("clarification_needed"),
    }


_FIELD_KEYWORDS: dict[str, list[str]] = {
    "figure":     ["体型", "体形", "身材"],
    "skin_color": ["肤色", "皮肤"],
    "eyelid":     ["眼皮", "双眼皮", "单眼皮"],
    "appearance": ["气质", "形象气质"],
    "face_shape": ["脸型"],
    "lip_shape":  ["唇形"],
    "blood_type": ["血型"],
    "constellation": ["星座"],
    "education":  ["学历"],
    "hometown":   ["籍贯", "老家", "地区"],
    "ethnicity":  ["民族"],
    "occupation": ["职业"],
    "personality":["性格"],
    "height":     ["身高"],
    "age":        ["年龄"],
}

_RELAX_KEYWORDS = [
    "方框", "放宽", "不限", "随便", "无所谓", "没有要求", "不重要",
    "不做要求", "可以不", "无需", "不必", "不强制", "都可以", "都行",
]

_AFFIRMATIVE_KEYWORDS = [
    "可以", "好的", "行", "都行", "好", "没问题", "接受", "同意",
    "可以的", "都可以", "都接受", "全部可以", "都OK", "都ok", "ok", "OK",
]


def _is_global_affirmative(message: str) -> bool:
    """判断消息是否为简短的全局肯定（如'可以'/'都行'/'好的'）。"""
    msg = message.strip()
    return len(msg) <= 12 and any(kw in msg for kw in _AFFIRMATIVE_KEYWORDS)


def _detect_relaxation_fallback(message: str, current_features: dict) -> list[str]:
    """Python 端关键词兜底：识别用户想放宽/取消的字段（LLM 未识别时补充）。"""
    found = []
    has_relax = any(kw in message for kw in _RELAX_KEYWORDS)
    if not has_relax:
        return found
    for field, keywords in _FIELD_KEYWORDS.items():
        if field not in current_features:
            continue
        if any(kw in message for kw in keywords):
            found.append(field)
    return found


def _extract_json_from_reply(text: str) -> dict:
    """从 LLM 回复中提取 JSON 块。"""
    try:
        # 尝试找 ```json ... ``` 块
        start = text.find("```json")
        if start != -1:
            start += len("```json")
            end = text.find("```", start)
            if end != -1:
                json_str = text[start:end].strip()
                return json.loads(json_str)

        # 尝试找 { ... } 块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end + 1]
            return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}")

    return {"intent": "question", "features": {}}


def _clean_reply(text: str) -> str:
    """移除回复中的 JSON 块，保留自然语言部分。"""
    import re
    cleaned = re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL)
    cleaned = cleaned.strip()
    return cleaned if cleaned else text
