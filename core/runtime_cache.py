"""运行时捐精人匹配缓存刷新。调用方负责把 DataFrame 从仓储取来。"""

from __future__ import annotations

import logging

from core.feature_engine import FeatureEncoder

logger = logging.getLogger(__name__)


def refresh_donor_cache(app, donor_df) -> dict:
    """用已加载的 donor_df 重建 FeatureEncoder。"""
    encoder = FeatureEncoder(donor_df)
    encoder.encode_all()

    app.state.donor_df = donor_df
    app.state.encoder = encoder

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
    logger.info("捐精人状态缓存已增量更新: code=%s status=%s", code, status)
    return True
