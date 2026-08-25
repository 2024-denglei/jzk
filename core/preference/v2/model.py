from __future__ import annotations

import math
from typing import Sequence

import torch
from torch import nn
from torch.nn import functional as F

from .settings import ModelConfig


def _inverse_softplus(value: float) -> float:
    return math.log(math.expm1(max(value, 1e-8)))


def _logit(value: float) -> float:
    value = min(max(value, 1e-6), 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


class V2MonotonicCalibrator(nn.Module):
    """规则引导的需求条件化单调校准器。

    对固定的 query 上下文：
    - heuristic_score 增大时输出不会降低；
    - max_weighted_mismatch 增大时输出不会升高。

    上下文网络只观察 query 级统计量，不观察 donor 身份或 query_id，
    因而不会通过 ID 记忆训练集 Query。
    """

    def __init__(self, context_dim: int, config: ModelConfig | None = None):
        super().__init__()
        self.config = config or ModelConfig()
        dims: Sequence[int] = [context_dim, *self.config.context_hidden_dims]
        layers: list[nn.Module] = []
        for in_dim, out_dim in zip(dims[:-1], dims[1:]):
            layers.extend(
                [
                    nn.Linear(in_dim, out_dim),
                    nn.SiLU(),
                    nn.LayerNorm(out_dim),
                    nn.Dropout(self.config.dropout),
                ]
            )
        last_dim = dims[-1]
        self.context_encoder = nn.Sequential(*layers) if layers else nn.Identity()
        self.context_head = nn.Linear(last_dim, 3)
        nn.init.zeros_(self.context_head.weight)
        nn.init.zeros_(self.context_head.bias)

        initial_scale_extra = self.config.initial_scale - self.config.scale_min
        if initial_scale_extra <= 0:
            raise ValueError("initial_scale 必须大于 scale_min。")
        if not 0 < self.config.initial_penalty < self.config.penalty_max:
            raise ValueError("initial_penalty 必须位于 (0, penalty_max)。")
        self.global_raw = nn.Parameter(
            torch.tensor(
                [
                    _inverse_softplus(initial_scale_extra),
                    _logit(self.config.initial_penalty / self.config.penalty_max),
                    0.0,
                ],
                dtype=torch.float32,
            )
        )

    def forward(
        self,
        heuristic_score: torch.Tensor,
        max_weighted_mismatch: torch.Tensor,
        context: torch.Tensor,
        return_parameters: bool = False,
    ):
        h = heuristic_score.reshape(-1).clamp(0.0, 1.0)
        mismatch = max_weighted_mismatch.reshape(-1).clamp(0.0, 1.0)
        encoded = self.context_encoder(context)
        raw = self.context_head(encoded) + self.global_raw

        scale = self.config.scale_min + F.softplus(raw[:, 0])
        penalty = self.config.penalty_max * torch.sigmoid(raw[:, 1])
        bias = self.config.bias_limit * torch.tanh(raw[:, 2])

        penalized_base = h * (1.0 - penalty * mismatch)
        prediction = (scale * penalized_base + bias).clamp(0.0, 1.0)
        if return_parameters:
            parameters = {
                "scale": scale,
                "penalty": penalty,
                "bias": bias,
                "penalized_base": penalized_base,
            }
            return prediction, parameters
        return prediction


def weighted_huber_loss(
    prediction: torch.Tensor,
    target: torch.Tensor,
    delta: float,
    sample_weight: torch.Tensor | None = None,
) -> torch.Tensor:
    loss = F.huber_loss(
        prediction.reshape(-1),
        target.reshape(-1),
        reduction="none",
        delta=delta,
    )
    if sample_weight is not None:
        weight = sample_weight.reshape(-1)
        return (loss * weight).sum() / weight.sum().clamp_min(1e-8)
    return loss.mean()

