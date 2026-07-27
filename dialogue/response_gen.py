"""回复生成模块：整合 LLM 回复和匹配结果。"""

import logging

from dialogue.session import SessionContext, DialogueState
from dialogue.dialogue_flow import (
    get_welcome,
    determine_next_action,
    format_results_message,
    build_feature_summary,
    CONFIRM_TEMPLATE,
)

logger = logging.getLogger(__name__)


def generate_response(
    session: SessionContext,
    nlu_result: dict,
    match_func=None,
    match_info: dict | None = None,
) -> dict:
    """生成完整回复。

    Args:
        session: 当前会话
        nlu_result: NLU 解析结果 {reply, intent, features, ambiguity, clarification_needed}
        match_func: 匹配函数 (parsed_features) -> list[dict]

    Returns:
        {
            "reply": str,
            "candidates": list[dict],
            "session_id": str,
            "state": str,
            "parsed_features": dict,
        }
    """
    intent = nlu_result["intent"]
    features = nlu_result["features"]
    constraints = nlu_result.get("constraints", {})
    remove_fields = nlu_result.get("remove_fields", [])
    ambiguity = nlu_result["ambiguity"]
    clarification = nlu_result["clarification_needed"]
    llm_reply = nlu_result["reply"]

    # 决定下一步动作
    action_info = determine_next_action(
        session, intent, features, ambiguity, clarification, constraints, remove_fields
    )
    action = action_info["action"]

    candidates = []
    final_reply = llm_reply

    if action == "farewell":
        final_reply = action_info["message"]
        session.state = DialogueState.END

    elif action == "clarify":
        # LLM 已在 reply 中包含了澄清问题
        pass

    elif action == "match":
        # 执行匹配
        if match_func:
            candidates = match_func(session.parsed_features)
            # 去重（按 donor code）
            seen_codes = set()
            unique_candidates = []
            for c in candidates:
                code = c["donor_info"].get("code", "")
                if code not in seen_codes:
                    seen_codes.add(code)
                    unique_candidates.append(c)
            candidates = unique_candidates
            session.candidates = candidates

        summary = build_feature_summary(session.parsed_features)
        n = len(candidates)

        # 判断匹配级别（优先从 match_info 取，其次从候选人中取）
        mi = match_info or {}
        match_level = mi.get("level") or (
            candidates[0].get("match_level", "full") if candidates else "full"
        )
        bottlenecks: list[str] = mi.get("bottlenecks", [])
        relaxed_fields: list[str] = mi.get("relaxed", [])

        if match_level == "full":
            final_reply = (
                f"已根据您的条件完全匹配到 {n} 位捐精人：\n{summary}\n\n"
                f"您可以查看下方卡片了解详情，也可以点击「满意」或「不满意」进行反馈。"
            )
        elif match_level == "relaxed":
            # 构建引导放宽建议
            if bottlenecks:
                suggest_lines = "\n".join(f"  • **{b}**" for b in bottlenecks)
                relax_hint = (
                    f"\n\n以下条件是造成精确匹配困难的主要原因：\n{suggest_lines}\n\n"
                    f'您可以告诉我哪项条件可以放宽（例如"学历放宽到本科也可以"），'
                    f"系统会立即重新为您精准匹配。"
                )
            else:
                relax_hint = (
                    "\n\n您可以告诉我哪些条件可以适当放宽，系统会重新为您精准匹配。"
                )
            final_reply = (
                f"当前条件组合没有完全匹配的捐精人，以下是放宽部分条件后最接近的 {n} 位推荐：\n{summary}\n\n"
                f"下方卡片显示每项条件的匹配情况，带「✓」的为已满足条件。"
                + relax_hint
            )
        else:
            if bottlenecks:
                suggest_lines = "\n".join(f"  • **{b}**" for b in bottlenecks)
                relax_hint = (
                    f"\n\n条件限制较严，主要瓶颈为：\n{suggest_lines}\n\n"
                    f"请告诉我您可以接受哪些条件放宽，以便重新为您精准匹配。"
                )
            else:
                relax_hint = "\n\n请告诉我哪些条件可以放宽，以便重新为您精准匹配。"
            final_reply = (
                f"根据当前全部条件未找到匹配的捐精人，以下是综合相似度最高的 {n} 位推荐：\n{summary}\n\n"
                f"下方仅供参考。"
                + relax_hint
            )
        session.state = DialogueState.PRESENTING

    elif action == "collect":
        # LLM 回复即可，可能会继续追问
        pass

    elif action == "chat":
        # 普通聊天/问答
        pass

    session.add_message("assistant", final_reply)

    return {
        "reply": final_reply,
        "candidates": candidates,
        "session_id": session.session_id,
        "state": session.state.value,
        "parsed_features": session.parsed_features,
    }
