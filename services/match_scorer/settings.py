from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_DEV_TOKEN = "dev-match-scorer-token-change-me"


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须大于0")
    return value


@dataclass(frozen=True)
class ScorerSettings:
    model_path: Path
    model_version: str
    force_cpu: bool
    candidate_pool: int
    max_candidates: int
    max_request_bytes: int
    token: str
    expected_checkpoint_sha256: str = ""
    contract_version: str = "1"

    @classmethod
    def from_environment(cls) -> "ScorerSettings":
        root = Path(__file__).resolve().parents[2]
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        token = os.getenv("SCORER_TOKEN", DEFAULT_DEV_TOKEN)
        if environment == "production" and token == DEFAULT_DEV_TOKEN:
            raise ValueError("生产环境必须设置安全的 SCORER_TOKEN")
        return cls(
            model_path=Path(os.getenv(
                "SCORER_MODEL_PATH",
                str(root / "models" / "best_mae_model_v4.pt"),
            )).resolve(),
            model_version=os.getenv(
                "SCORER_MODEL_VERSION", "v32-v4-best-mae"
            ).strip(),
            force_cpu=os.getenv("SCORER_FORCE_CPU", "1").strip().lower()
            in {"1", "true", "yes"},
            candidate_pool=_env_int("SCORER_CANDIDATE_POOL", 300),
            max_candidates=_env_int("SCORER_MAX_CANDIDATES", 20000),
            max_request_bytes=_env_int("SCORER_MAX_REQUEST_BYTES", 25000000),
            token=token,
            expected_checkpoint_sha256=os.getenv(
                "SCORER_EXPECTED_CHECKPOINT_SHA256", ""
            ).strip().lower(),
        )

    def validate(self) -> None:
        if not self.model_version:
            raise ValueError("SCORER_MODEL_VERSION 不能为空")
        if not self.token:
            raise ValueError("SCORER_TOKEN 不能为空")
        if self.candidate_pool > self.max_candidates:
            raise ValueError("SCORER_CANDIDATE_POOL 不能大于 SCORER_MAX_CANDIDATES")
        if self.expected_checkpoint_sha256 and len(self.expected_checkpoint_sha256) != 64:
            raise ValueError("SCORER_EXPECTED_CHECKPOINT_SHA256 必须是64位十六进制")
