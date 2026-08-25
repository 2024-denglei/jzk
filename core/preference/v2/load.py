from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch

from .features import CONTEXT_FEATURE_NAMES, ContextScaler
from .model import V2MonotonicCalibrator
from .settings import AppConfig


def load_v2_engine(
    checkpoint_path: Path,
    config_path: Path,
    force_cpu: bool = True,
):
    if not checkpoint_path.is_file():
        raise FileNotFoundError(f"找不到模型文件：{checkpoint_path}")
    device = torch.device("cpu" if force_cpu or not torch.cuda.is_available() else "cuda")
    raw: Any = torch.load(checkpoint_path, map_location=device, weights_only=False)
    config = AppConfig.load(config_path)
    if not isinstance(raw, dict):
        raise TypeError("Checkpoint 必须是 dict")

    if {"context_mean", "context_std", "context_feature_names"} <= set(raw):
        names = list(raw["context_feature_names"])
        if names != list(CONTEXT_FEATURE_NAMES):
            raise ValueError("Checkpoint 上下文字段与当前代码不一致")
        scaler = ContextScaler(
            feature_names=names,
            mean=np.asarray(raw["context_mean"], dtype=np.float64),
            scale=np.asarray(raw["context_std"], dtype=np.float64),
        )
    elif "context_scaler" in raw:
        scaler = ContextScaler.from_dict(raw["context_scaler"])
    else:
        raise KeyError("Checkpoint 缺少 context_mean/std 或 context_scaler")

    state = raw.get("model_state_dict") or raw.get("state_dict")
    if not isinstance(state, dict):
        raise KeyError("Checkpoint 缺少 model_state_dict/state_dict")
    hidden = raw.get("model_hidden_dims")
    if hidden:
        config.model.context_hidden_dims = list(hidden)
    dropout = raw.get("model_dropout")
    if dropout is not None:
        config.model.dropout = float(dropout)
    model = V2MonotonicCalibrator(len(scaler.feature_names), config.model)
    model.load_state_dict(state, strict=True)
    model.to(device).eval()
    return model, scaler, config, device
