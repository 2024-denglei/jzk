"""对话流程状态机：管理对话各阶段流转。"""

import logging

from dialogue.session import DialogueState, SessionContext

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = (
    "您好！欢迎使用智能生育匹配系统。\n"
    "您可以告诉我您对捐精人的期望，例如：\n"
    "• 学历要求（大专/本科/硕士/博士）\n"
    "• 身高范围（如175cm以上）\n"
    "• 体型偏好（匀称型/精壮型/偏瘦型）\n"
    "• 肤色偏好（偏白/一般）\n"
    "• 血型、脸型、形象气质等\n\n"
    "您可以一次说出多个条件，也可以分多次补充。请问您有什么需求？"
)

CONFIRM_TEMPLATE = "根据您的描述，我已为您整理了以下需求：\n{feature_summary}\n\n请确认是否正确？如需修改请直接告诉我。如果没问题，我将为您开始匹配。"

NO_RESULT_MESSAGE = "很抱歉，根据您的条件暂未找到完全匹配的捐精人。您可以尝试放宽部分条件，例如扩大身高范围或调整学历要求。"

FEEDBACK_PROMPT = "以上是为您推荐的匹配结果。您可以对每位捐精人点击「满意」或「不满意」进行反馈，也可以告诉我您想调整哪些条件重新匹配。"


def get_welcome(session: SessionContext) -> str:
    """返回欢迎语并设置状态。"""
    session.state = DialogueState.COLLECTING
    session.add_message("assistant", WELCOME_MESSAGE)
    return WELCOME_MESSAGE


def build_feature_summary(features: dict) -> str:
    """将解析后的特征构建为可读摘要。"""
    lines = []
    label_map = {
        "education": "学历",
        "height": "身高",
        "age": "年龄",
        "figure": "体型",
        "skin_color": "肤色",
        "blood_type": "血型",
        "rh_blood": "RH血型",
        "face_shape": "脸型",
        "eyelid": "眼皮",
        "lip_shape": "唇形",
        "appearance": "形象气质",
        "constellation": "星座",
        "ethnicity": "民族",
        "hometown": "籍贯",
        "occupation": "职业",
        "personality": "性格",
        "specimen_min": "标本数量",
    }

    for key, label in label_map.items():
        val = features.get(key)
        if val is None:
            continue
        if key == "height" and isinstance(val, dict):
            h_min = val.get("min")
            h_max = val.get("max")
            if h_min and h_max:
                lines.append(f"• {label}：{h_min}-{h_max}cm")
            elif h_min:
                lines.append(f"• {label}：≥{h_min}cm")
            elif h_max:
                lines.append(f"• {label}：≤{h_max}cm")
        elif key == "age" and isinstance(val, dict):
            a_min = val.get("min")
            a_max = val.get("max")
            if a_min and a_max:
                lines.append(f"• {label}：{a_min}-{a_max}岁")
            elif a_min:
                lines.append(f"• {label}：≥{a_min}岁")
            elif a_max:
                lines.append(f"• {label}：≤{a_max}岁")
        elif key == "specimen_min" and val:
            lines.append(f"• {label}：≥{val}管")
        elif isinstance(val, list) and val:
            lines.append(f"• {label}：{'或'.join(str(v) for v in val)}")
        elif val:
            lines.append(f"• {label}：{val}")

    return "\n".join(lines) if lines else "（暂无明确需求条件）"


def determine_next_action(
    session: SessionContext,
    intent: str,
    features: dict,
    ambiguity: bool,
    clarification_needed: str | None,
    constraints: dict | None = None,
    remove_fields: list | None = None,
) -> dict:
    """根据当前状态和意图，决定下一步动作。

    Returns:
        {
            "action": "collect" | "confirm" | "match" | "present" | "clarify" | "refine" | "farewell" | "chat",
            "message": str | None  （仅部分 action 需要附带系统消息）
        }
    """
    # 歧义 → 需要澄清
    if ambiguity and clarification_needed:
        session.state = DialogueState.COLLECTING
        return {"action": "clarify", "message": None}

    # 告别
    if intent == "farewell":
        session.state = DialogueState.END
        return {"action": "farewell", "message": "感谢您使用智能生育匹配系统，祝您一切顺利！再见！"}

    has_new_features = _has_any_feature(features)
    has_removals = bool(remove_fields)

    # 当处于 PRESENTING 状态时：有新特征/删除操作 OR 意图为 refine/search → 更新并重匹配
    if session.state == DialogueState.PRESENTING and (
        has_new_features or has_removals or intent in ("search", "refine")
    ):
        session.update_features(features, constraints, remove_fields)
        if _has_enough_features(session.parsed_features):
            session.state = DialogueState.MATCHING
            return {"action": "match", "message": None}
        session.state = DialogueState.COLLECTING
        return {"action": "collect", "message": None}

    # 闲聊/问题
    if intent in ("greeting", "question"):
        return {"action": "chat", "message": None}

    # 反馈
    if intent == "feedback":
        session.state = DialogueState.FEEDBACK
        return {"action": "chat", "message": None}

    # 修正需求
    if intent == "refine":
        session.update_features(features, constraints, remove_fields)
        if _has_enough_features(session.parsed_features):
            session.state = DialogueState.MATCHING
            return {"action": "match", "message": None}
        session.state = DialogueState.COLLECTING
        return {"action": "collect", "message": None}

    # 首次搜索意图
    if intent == "search":
        session.update_features(features, constraints, remove_fields)
        if _has_enough_features(session.parsed_features):
            session.state = DialogueState.MATCHING
            return {"action": "match", "message": None}
        else:
            session.state = DialogueState.COLLECTING
            return {"action": "collect", "message": None}

    return {"action": "chat", "message": None}


def _has_any_feature(features: dict) -> bool:
    """判断 features 字典中是否有任何非空值或删除操作（REMOVE）。"""
    if not features:
        return False
    for key, val in features.items():
        if val is None:
            continue
        if val == "REMOVE":
            return True  # 删除操作也算一次有效变更
        if key == "height" and isinstance(val, dict):
            if val.get("min") or val.get("max"):
                return True
        elif val:
            return True
    return False


def _has_enough_features(features: dict) -> bool:
    """判断是否有足够的特征进行匹配（至少1个有效特征即可）。"""
    return _has_any_feature(features)


def format_results_message(results: list[dict]) -> str:
    """将匹配结果格式化为对话消息。"""
    if not results:
        return NO_RESULT_MESSAGE

    lines = [f"为您找到 {len(results)} 位匹配的捐精人：\n"]
    for i, r in enumerate(results, 1):
        d = r["donor_info"]
        lines.append(
            f"**{i}. 编号 {d['code']}**\n"
            f"   学历：{d['education']} | 身高：{d['height']}cm | "
            f"体型：{d['figure']} | 肤色：{d['skin_color']}\n"
            f"   血型：{d['blood_type']} | 形象气质：{d['appearance']}\n"
            f"   {r['reason']}\n"
        )
    lines.append(f"\n{FEEDBACK_PROMPT}")
    return "\n".join(lines)
