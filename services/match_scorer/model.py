from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import torch
import torch.nn.functional as F
from torch import nn


@dataclass(frozen=True)
class ModelConfig:
    embedding_dim: int = 64
    num_heads: int = 4
    num_transformer_layers: int = 2
    dropout: float = 0.12
    hash_buckets: int = 4096
    global_feature_dim: int = 7
    numeric_token_dim: int = 10

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ModelConfig":
        source = dict(raw or {})
        return cls(**{
            name: source.get(name, field.default)
            for name, field in cls.__dataclass_fields__.items()
        })


class TenderAlignedV32(nn.Module):
    """Architecture used by the V4 tender-multitask checkpoint."""

    def __init__(
        self,
        cfg: ModelConfig,
        field_count: int,
        type_count: int,
        constraint_count: int,
    ):
        super().__init__()
        d = cfg.embedding_dim
        self.cfg = cfg
        self.field_embedding = nn.Embedding(field_count + 1, d, padding_idx=0)
        self.type_embedding = nn.Embedding(type_count, d, padding_idx=0)
        self.constraint_embedding = nn.Embedding(
            constraint_count, d, padding_idx=0
        )
        self.value_embedding = nn.Embedding(
            cfg.hash_buckets + 1, d, padding_idx=0
        )
        self.value_relation = nn.Sequential(
            nn.Linear(d * 2, d), nn.SiLU(), nn.LayerNorm(d)
        )

        def type_encoder() -> nn.Sequential:
            return nn.Sequential(
                nn.Linear(cfg.numeric_token_dim, d),
                nn.SiLU(),
                nn.LayerNorm(d),
                nn.Dropout(cfg.dropout),
                nn.Linear(d, d),
            )

        self.range_encoder = type_encoder()
        self.enum_encoder = type_encoder()
        self.keyword_encoder = type_encoder()
        self.boolean_encoder = type_encoder()
        self.input_norm = nn.LayerNorm(d)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=cfg.num_heads,
            dim_feedforward=d * 3,
            dropout=cfg.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer,
            num_layers=cfg.num_transformer_layers,
            norm=nn.LayerNorm(d),
            enable_nested_tensor=False,
        )
        self.attention_pool = nn.Sequential(
            nn.Linear(d, d // 2), nn.Tanh(), nn.Linear(d // 2, 1)
        )

        def output_head() -> nn.Sequential:
            return nn.Sequential(
                nn.Linear(d + cfg.global_feature_dim, d),
                nn.SiLU(),
                nn.LayerNorm(d),
                nn.Dropout(cfg.dropout),
                nn.Linear(d, d // 2),
                nn.SiLU(),
                nn.Linear(d // 2, 1),
            )

        self.score_head = output_head()
        self.rank_head = output_head()
        self.penalty_raw = nn.Parameter(torch.tensor(-10.0))

    def forward(self, batch: dict[str, torch.Tensor]):
        numeric = batch["numeric"]
        original_shape = numeric.shape[:2]
        b, c, fields, _ = numeric.shape
        flat_numeric = numeric.reshape(b * c, fields, -1)
        flat_type = batch["type_ids"].reshape(b * c, fields)
        flat_mask = batch["mask"].reshape(b * c, fields)

        branches = torch.stack([
            self.range_encoder(flat_numeric),
            self.enum_encoder(flat_numeric),
            self.keyword_encoder(flat_numeric),
            self.boolean_encoder(flat_numeric),
        ], dim=-2)
        type_one_hot = F.one_hot(
            (flat_type - 1).clamp(0, 3), num_classes=4
        ).to(flat_numeric.dtype)
        typed = (branches * type_one_hot.unsqueeze(-1)).sum(dim=-2)

        field_ids = batch["field_ids"].reshape(b * c, fields)
        constraint_ids = batch["constraint_ids"].reshape(b * c, fields)
        target_ids = batch["target_ids"].reshape(b * c, fields)
        actual_ids = batch["actual_ids"].reshape(b * c, fields)
        target_value = self.value_embedding(target_ids)
        actual_value = self.value_embedding(actual_ids)
        relation = self.value_relation(torch.cat([
            torch.abs(target_value - actual_value),
            target_value * actual_value,
        ], dim=-1))

        token = (
            typed
            + self.field_embedding(field_ids)
            + self.type_embedding(flat_type)
            + self.constraint_embedding(constraint_ids)
            + 0.25 * (target_value + actual_value)
            + 0.50 * relation
        )
        weight = flat_numeric[..., 1].clamp(0.0, 1.0)
        token = self.input_norm(token) * (0.5 + weight.unsqueeze(-1))
        token = token.masked_fill(~flat_mask.unsqueeze(-1), 0.0)
        encoded = self.transformer(token, src_key_padding_mask=~flat_mask)

        attention_logits = self.attention_pool(encoded).squeeze(-1)
        attention_logits = attention_logits + 0.35 * torch.log(weight + 0.05)
        attention_logits = attention_logits.masked_fill(~flat_mask, -1e4)
        attention = torch.softmax(attention_logits, dim=-1)
        fused = torch.sum(encoded * attention.unsqueeze(-1), dim=1)

        global_features = batch["global"].reshape(b * c, -1)
        head_input = torch.cat([fused, global_features], dim=-1)
        score_residual = torch.tanh(self.score_head(head_input).squeeze(-1))
        rank_residual = torch.tanh(self.rank_head(head_input).squeeze(-1))
        baseline = global_features[:, 0].clamp(1e-4, 1.0 - 1e-4)
        mismatch = global_features[:, 1].clamp(0.0, 1.0)
        baseline_logit = torch.logit(baseline)
        penalty_strength = F.softplus(self.penalty_raw)
        match_score = torch.sigmoid(
            baseline_logit + score_residual - penalty_strength * mismatch
        )
        ranking_score = torch.sigmoid(
            baseline_logit
            + 0.50 * score_residual
            + 1.25 * rank_residual
            - penalty_strength * mismatch
        )
        soft_cap = (1.0 - 0.20 * mismatch).clamp(0.0, 1.0)
        return (
            match_score.reshape(*original_shape),
            ranking_score.reshape(*original_shape),
            attention.reshape(b, c, fields),
            soft_cap.reshape(*original_shape),
            score_residual.reshape(*original_shape),
            rank_residual.reshape(*original_shape),
        )
