"""运行时捐精人匹配缓存刷新。"""

from __future__ import annotations

import logging

from core.data_loader import load_donor_data
from core.feature_engine import FeatureEncoder

logger = logging.getLogger(__name__)


def _inject_chat_dependencies(app, encoder, donor_df) -> None:
    """让对话接口切换到同一份最新运行时数据。"""
    try:
        from api.chat import inject_dependencies as inject_chat_deps
        from api.chat_stream import inject_dependencies as inject_stream_deps

        sm = getattr(app.state, "session_manager", None)
        llm = getattr(app.state, "llm_client", None)
        async_llm = getattr(app.state, "async_llm_client", None)
        if sm is not None:
            inject_chat_deps(sm, encoder, donor_df, llm)
            inject_stream_deps(sm, encoder, donor_df, async_llm)
    except Exception as e:
        logger.warning("刷新对话依赖时出现问题: %s", e)


def refresh_donor_cache(app) -> dict:
    """从官方库重载 donor_df / FeatureEncoder，并更新 chat 依赖。"""
    donor_df = load_donor_data()
    encoder = FeatureEncoder(donor_df)
    encoder.encode_all()

    app.state.donor_df = donor_df
    app.state.encoder = encoder

    _inject_chat_dependencies(app, encoder, donor_df)

    shape = encoder.feature_matrix.shape if encoder.feature_matrix is not None else (0, 0)
    logger.info("捐精人缓存已刷新: rows=%s features=%s", len(donor_df), shape)
    return {"rows": len(donor_df), "feature_shape": list(shape)}


def update_donor_status_cache(app, code: str, status: str) -> bool:
    """只更新状态列，避免启停操作重建完整特征矩阵。"""
    donor_df = getattr(app.state, "donor_df", None)
    encoder = getattr(app.state, "encoder", None)
    if donor_df is None or encoder is None or "代号" not in donor_df.columns or "状态" not in donor_df.columns:
        return False

    matched = donor_df["代号"].astype(str) == str(code)
    if not matched.any():
        return False

    updated_df = donor_df.copy()
    updated_df.loc[matched, "状态"] = status
    encoder.df = updated_df
    app.state.donor_df = updated_df
    _inject_chat_dependencies(app, encoder, updated_df)
    logger.info("捐精人状态缓存已增量更新: code=%s status=%s", code, status)
    return True
