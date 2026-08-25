from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DataConfig:
    donor_file: str = "V2_捐精人主表_3000条.csv"
    profile_file: str = "V2_受捐需求Profile_1000条.csv"
    pair_file: str = "V2_训练Pair_30万条.csv"
    label_column: str = "expert_match_score"


@dataclass
class RuleConfig:
    range_scales: dict[str, float] = field(
        default_factory=lambda: {
            "age": 8.0,
            "height_cm": 10.0,
            "weight_kg": 12.0,
            "bmi": 3.5,
            "marriage_age": 8.0,
        }
    )
    default_range_scale: float = 5.0
    single_range_boundary_score: float = 0.8
    education_order: list[str] = field(
        default_factory=lambda: ["高中", "大专", "本科", "硕士", "博士"]
    )
    education_step_penalty: float = 1.0 / 3.0
    skin_color_order: list[str] = field(
        default_factory=lambda: ["偏白", "一般", "偏黑"]
    )
    skin_color_step_penalty: float = 1.0 / 3.0
    keyword_mode: str = "any"
    must_match_tolerance: float = 1e-8


@dataclass
class ModelConfig:
    context_hidden_dims: list[int] = field(default_factory=lambda: [64, 32])
    dropout: float = 0.10
    scale_min: float = 0.50
    penalty_max: float = 0.30
    bias_limit: float = 0.15
    initial_scale: float = 1.00
    initial_penalty: float = 0.10


@dataclass
class TrainingConfig:
    seed: int = 20260824
    batch_size: int = 4096
    num_workers: int = 0
    max_epochs: int = 120
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    huber_delta: float = 0.03
    early_stopping_patience: int = 12
    scheduler_patience: int = 4
    scheduler_factor: float = 0.5
    min_learning_rate: float = 1e-6
    gradient_clip_norm: float = 5.0
    balance_score_bins: bool = True
    score_bins: list[float] = field(
        default_factory=lambda: [0.0, 0.2, 0.4, 0.6, 0.8, 1.000001]
    )
    max_sample_weight: float = 3.0
    use_amp: bool = True


@dataclass
class EvaluationConfig:
    top_k: int = 5
    calibration_bins: int = 10
    prediction_batch_size: int = 16384
    make_plots: bool = True


@dataclass
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    rules: RuleConfig = field(default_factory=RuleConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        return cls(
            data=DataConfig(**raw.get("data", {})),
            rules=RuleConfig(**raw.get("rules", {})),
            model=ModelConfig(**raw.get("model", {})),
            training=TrainingConfig(**raw.get("training", {})),
            evaluation=EvaluationConfig(**raw.get("evaluation", {})),
        )

    @classmethod
    def load(cls, path: str | Path | None) -> "AppConfig":
        if path is None:
            return cls()
        with Path(path).open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def data_paths(self, data_dir: str | Path) -> dict[str, Path]:
        base = Path(data_dir)
        return {
            "donors": base / self.data.donor_file,
            "profiles": base / self.data.profile_file,
            "pairs": base / self.data.pair_file,
        }
