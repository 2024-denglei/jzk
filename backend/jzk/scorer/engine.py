from __future__ import annotations

import hashlib
import math
from pathlib import Path
import threading
import time
from typing import Any, Mapping

import numpy as np
import torch

from .api_models import (
    CandidatePayload,
    FieldScorePayload,
    RankRequest,
    RankedItem,
    RankResponse,
)
from .encoding import (
    CONSTRAINT_TO_ID_DEFAULT,
    TYPE_TO_ID_DEFAULT,
    CandidateEncoder,
    EncodedCandidate,
    FeatureMatch,
    field_similarity,
    strict_must_pass,
    target_value,
)
from .model import ModelConfig, TenderAlignedV32
from .model_manifest import ModelManifest
from .settings import ScorerSettings


class ScoringRequestError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field_score(match: FeatureMatch) -> FieldScorePayload:
    return FieldScorePayload(
        field=match.name,
        actual=match.donor_value,
        target=match.requirement,
        s=float(match.similarity),
        weight=float(match.weight),
        constraint=match.constraint,
    )


class MatchScoringEngine:
    def __init__(self, settings: ScorerSettings):
        settings.validate()
        if not settings.model_path.is_file():
            raise FileNotFoundError(f"找不到模型文件：{settings.model_path}")
        checkpoint_sha256 = _sha256(settings.model_path)
        if (
            settings.expected_checkpoint_sha256
            and checkpoint_sha256 != settings.expected_checkpoint_sha256
        ):
            raise ValueError("checkpoint SHA-256 与预期值不一致")

        self.settings = settings
        self.device = torch.device(
            "cpu"
            if settings.force_cpu or not torch.cuda.is_available()
            else "cuda"
        )
        checkpoint: Any = torch.load(
            settings.model_path,
            map_location=self.device,
            weights_only=False,
        )
        if not isinstance(checkpoint, Mapping):
            raise TypeError("Checkpoint 必须是 mapping")
        required = {
            "model_state",
            "config",
            "field_to_id",
            "type_to_id",
            "constraint_to_id",
            "numeric_stats",
            "max_attr",
        }
        missing = sorted(required - set(checkpoint))
        if missing:
            raise ValueError(f"Checkpoint 缺少字段：{missing}")
        model_name = str(checkpoint.get("model_name") or "")
        checkpoint_role = str(checkpoint.get("checkpoint_role") or "")
        if model_name != settings.expected_model_name:
            raise ValueError("Checkpoint model_name 与配置不一致")
        if checkpoint_role != settings.expected_checkpoint_role:
            raise ValueError("Checkpoint checkpoint_role 与配置不一致")

        state = checkpoint["model_state"]
        field_to_id = checkpoint["field_to_id"]
        type_to_id = checkpoint.get("type_to_id", TYPE_TO_ID_DEFAULT)
        constraint_to_id = checkpoint.get(
            "constraint_to_id", CONSTRAINT_TO_ID_DEFAULT
        )
        if not all(
            isinstance(item, Mapping)
            for item in (state, field_to_id, type_to_id, constraint_to_id)
        ):
            raise TypeError("Checkpoint 的模型状态或编号表格式错误")

        cfg = ModelConfig.from_mapping(checkpoint["config"])
        self.model = TenderAlignedV32(
            cfg,
            len(field_to_id),
            len(type_to_id),
            len(constraint_to_id),
        ).to(self.device)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        self.checkpoint = checkpoint
        self.field_to_id = dict(field_to_id)
        self.encoder = CandidateEncoder(
            field_to_id=field_to_id,
            type_to_id=type_to_id,
            constraint_to_id=constraint_to_id,
            numeric_stats=checkpoint["numeric_stats"],
            max_attr=int(checkpoint["max_attr"]),
            max_must=2,
            max_prefer=max(11, int(checkpoint["max_attr"])),
            hash_buckets=cfg.hash_buckets,
            numeric_token_dim=cfg.numeric_token_dim,
        )
        self.manifest = ModelManifest(
            name=model_name,
            version=settings.model_version,
            checkpoint_role=checkpoint_role,
            checkpoint_epoch=(
                int(checkpoint["best_epoch"])
                if checkpoint.get("best_epoch") is not None
                else None
            ),
            checkpoint_sha256=checkpoint_sha256,
            max_attributes=int(checkpoint["max_attr"]),
            candidate_pool=settings.candidate_pool,
            device=str(self.device),
        )
        self._predict_lock = threading.Lock()

    def _stack(self, selected: list[EncodedCandidate]) -> dict[str, torch.Tensor]:
        keys = [
            "numeric",
            "field_ids",
            "type_ids",
            "constraint_ids",
            "target_ids",
            "actual_ids",
            "mask",
            "global",
        ]
        arrays = {
            key: np.stack([item.arrays[key] for item in selected])
            for key in keys
        }
        return {
            "numeric": torch.from_numpy(
                arrays["numeric"].astype(np.float32)
            ).unsqueeze(0).to(self.device),
            "field_ids": torch.from_numpy(
                arrays["field_ids"].astype(np.int64)
            ).unsqueeze(0).to(self.device),
            "type_ids": torch.from_numpy(
                arrays["type_ids"].astype(np.int64)
            ).unsqueeze(0).to(self.device),
            "constraint_ids": torch.from_numpy(
                arrays["constraint_ids"].astype(np.int64)
            ).unsqueeze(0).to(self.device),
            "target_ids": torch.from_numpy(
                arrays["target_ids"].astype(np.int64)
            ).unsqueeze(0).to(self.device),
            "actual_ids": torch.from_numpy(
                arrays["actual_ids"].astype(np.int64)
            ).unsqueeze(0).to(self.device),
            "mask": torch.from_numpy(
                arrays["mask"].astype(bool)
            ).unsqueeze(0).to(self.device),
            "global": torch.from_numpy(
                arrays["global"].astype(np.float32)
            ).unsqueeze(0).to(self.device),
        }

    @staticmethod
    def _donor(candidate: CandidatePayload) -> dict[str, Any]:
        donor = dict(candidate.attributes)
        if "specimen_count" in candidate.business:
            donor["specimen_count"] = candidate.business["specimen_count"]
        donor["code"] = candidate.code
        donor["donor_id"] = candidate.donor_id
        return donor

    def _validate_request(
        self,
        request: RankRequest,
        profile: dict[str, Any],
        donors: list[dict[str, Any]],
    ) -> None:
        if len(donors) > self.settings.max_candidates:
            raise ScoringRequestError(
                "TOO_MANY_CANDIDATES",
                f"候选人数超过上限 {self.settings.max_candidates}",
            )
        ids = [candidate.donor_id for candidate in request.candidates]
        if len(ids) != len(set(ids)):
            raise ScoringRequestError("DUPLICATE_DONOR", "donor_id 不能重复")
        model_fields = set(profile["attributes"]) - {"specimen_count"}
        unknown = sorted(model_fields - set(self.field_to_id))
        if unknown:
            raise ScoringRequestError(
                "UNKNOWN_MODEL_FIELD", f"模型不支持字段：{unknown}"
            )
        if len(model_fields) > self.manifest.max_attributes:
            raise ScoringRequestError(
                "PROFILE_TOO_WIDE",
                f"模型最多支持 {self.manifest.max_attributes} 个属性",
            )
        must_specs = {
            field: spec
            for field, spec in profile["attributes"].items()
            if spec.get("constraint") == "must"
        }
        violations = []
        for donor in donors:
            if not all(
                strict_must_pass(spec, donor.get(field))
                for field, spec in must_specs.items()
            ):
                violations.append(donor["donor_id"])
                if len(violations) >= 5:
                    break
        if violations:
            raise ScoringRequestError(
                "MUST_FILTER_DRIFT",
                f"候选未通过 must 复核：{violations}",
            )

    def _all_matches(
        self,
        full_profile: dict[str, Any],
        encoded: EncodedCandidate | None,
        donor: dict[str, Any],
    ) -> list[FieldScorePayload]:
        encoded_by_field = {
            match.name: match
            for match in (encoded.feature_matches if encoded else ())
        }
        output = []
        for field, spec in full_profile["attributes"].items():
            match = encoded_by_field.get(field)
            if match is None:
                similarity = field_similarity(
                    field, spec, donor.get(field), self.encoder.numeric_stats
                )[0]
                weight = float(spec.get("weight", 0.0))
                match = FeatureMatch(
                    name=field,
                    feature_type=str(spec.get("type", "range")),
                    constraint=str(spec.get("constraint", "prefer")),
                    weight=weight,
                    similarity=float(similarity),
                    weighted_mismatch=weight * (1.0 - float(similarity)),
                    donor_value=donor.get(field),
                    requirement=target_value(spec),
                    must_pass=(
                        spec.get("constraint") != "must"
                        or strict_must_pass(spec, donor.get(field))
                    ),
                )
            output.append(_field_score(match))
        return output

    @torch.inference_mode()
    def rank(self, request: RankRequest) -> RankResponse:
        total_started = time.perf_counter()
        full_profile = request.profile.to_engine_profile()
        model_profile = {
            "schema_version": full_profile["schema_version"],
            "attributes": {
                field: spec
                for field, spec in full_profile["attributes"].items()
                if field != "specimen_count"
            },
        }
        donors = [self._donor(candidate) for candidate in request.candidates]
        self._validate_request(request, full_profile, donors)

        t0 = time.perf_counter()
        scored = [
            (self.encoder.score_only(full_profile, donor)[0], donor)
            for donor in donors
        ]
        scored.sort(key=lambda item: (-item[0], str(item[1]["code"])))
        selected_rows = scored[: min(len(scored), self.settings.candidate_pool)]
        preselect_ms = (time.perf_counter() - t0) * 1000

        if not model_profile["attributes"]:
            items = []
            for rank, (heuristic, donor) in enumerate(selected_rows, 1):
                items.append(RankedItem(
                    donor_id=int(donor["donor_id"]),
                    rank=rank,
                    match_score=float(heuristic),
                    ranking_score=float(heuristic),
                    heuristic_score=float(heuristic),
                    field_scores=self._all_matches(
                        full_profile, None, donor
                    ),
                ))
            return RankResponse(
                contract_version="1",
                request_id=request.request_id,
                model=self.manifest.to_identity(),
                eligible_count=len(donors),
                ranked_count=len(items),
                items=items,
                timings={
                    "preselect_ms": round(preselect_ms, 1),
                    "encode_ms": 0.0,
                    "model_ms": 0.0,
                    "sort_ms": 0.0,
                    "total_ms": round(
                        (time.perf_counter() - total_started) * 1000, 1
                    ),
                },
            )

        t1 = time.perf_counter()
        selected = [
            (
                heuristic,
                self.encoder.encode(model_profile, donor),
            )
            for heuristic, donor in selected_rows
        ]
        encode_ms = (time.perf_counter() - t1) * 1000

        t2 = time.perf_counter()
        with self._predict_lock:
            match_score, ranking_score, _, _, _, _ = self.model(
                self._stack([item for _, item in selected])
            )
        match_values = match_score.squeeze(0).detach().cpu().numpy()
        rank_values = ranking_score.squeeze(0).detach().cpu().numpy()
        model_ms = (time.perf_counter() - t2) * 1000

        t3 = time.perf_counter()
        sortable = []
        specimen_spec = full_profile["attributes"].get("specimen_count")
        for index, (business_heuristic, encoded) in enumerate(selected):
            donor = encoded.donor
            specimen_similarity = 0.0
            specimen_actual = 0.0
            if specimen_spec is not None:
                specimen_similarity = field_similarity(
                    "specimen_count",
                    specimen_spec,
                    donor.get("specimen_count"),
                    self.encoder.numeric_stats,
                )[0]
                try:
                    specimen_actual = float(donor.get("specimen_count") or 0)
                except (TypeError, ValueError):
                    specimen_actual = 0.0
            displayed = float(match_values[index])
            ordering = float(rank_values[index])
            if not math.isfinite(displayed) or not math.isfinite(ordering):
                raise RuntimeError("模型返回非有限分数")
            sortable.append((
                ordering,
                specimen_similarity,
                specimen_actual,
                float(business_heuristic),
                encoded,
                displayed,
            ))
        sortable.sort(key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            -item[3],
            str(item[4].donor["code"]),
        ))
        items = [
            RankedItem(
                donor_id=int(encoded.donor["donor_id"]),
                rank=rank,
                match_score=displayed,
                ranking_score=ordering,
                heuristic_score=business_heuristic,
                field_scores=self._all_matches(
                    full_profile, encoded, encoded.donor
                ),
            )
            for rank, (
                ordering,
                _specimen_similarity,
                _specimen_actual,
                business_heuristic,
                encoded,
                displayed,
            ) in enumerate(sortable, 1)
        ]
        sort_ms = (time.perf_counter() - t3) * 1000
        return RankResponse(
            contract_version="1",
            request_id=request.request_id,
            model=self.manifest.to_identity(),
            eligible_count=len(donors),
            ranked_count=len(items),
            items=items,
            timings={
                "preselect_ms": round(preselect_ms, 1),
                "encode_ms": round(encode_ms, 1),
                "model_ms": round(model_ms, 1),
                "sort_ms": round(sort_ms, 1),
                "total_ms": round(
                    (time.perf_counter() - total_started) * 1000, 1
                ),
            },
        )
