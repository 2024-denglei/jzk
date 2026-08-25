"""运行时捐精人匹配缓存刷新。"""

from __future__ import annotations

import logging

from core.data_loader import load_donor_data
from core.feature_engine import FeatureEncoder

logger = logging.getLogger(__name__)


def refresh_donor_cache(app) -> dict:
    """从官方库重载 donor_df / FeatureEncoder，并更新 chat 依赖。"""
    donor_df = load_donor_data()
    encoder = FeatureEncoder(donor_df)
    encoder.encode_all()

    app.state.donor_df = donor_df
    app.state.encoder = encoder

    # 同步对话接口依赖
    try:
        from api.chat import inject_dependencies as inject_chat_deps
        from api.chat_stream import inject_dependencies as inject_stream_deps

        sm = getattr(app.state, "session_manager", None)
        llm = getattr(app.state, "llm_client", None)
        if sm is not None:
            inject_chat_deps(sm, encoder, donor_df, llm)
            inject_stream_deps(sm, encoder, donor_df, llm)
    except Exception as e:
        logger.warning("刷新对话依赖时出现问题: %s", e)

    shape = encoder.feature_matrix.shape if encoder.feature_matrix is not None else (0, 0)
    logger.info("捐精人缓存已刷新: rows=%s features=%s", len(donor_df), shape)
    return {"rows": len(donor_df), "feature_shape": list(shape)}
