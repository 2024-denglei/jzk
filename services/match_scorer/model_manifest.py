from __future__ import annotations

from dataclasses import dataclass

from .api_models import ModelIdentity


@dataclass(frozen=True)
class ModelManifest:
    name: str
    version: str
    checkpoint_role: str
    checkpoint_epoch: int | None
    checkpoint_sha256: str
    max_attributes: int
    candidate_pool: int
    device: str

    def to_identity(self) -> ModelIdentity:
        return ModelIdentity(**self.__dict__)
