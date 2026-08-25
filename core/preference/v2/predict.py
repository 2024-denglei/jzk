from __future__ import annotations

import numpy as np
import torch

from .model import V2MonotonicCalibrator


@torch.inference_mode()
def predict_arrays(
    model: V2MonotonicCalibrator,
    heuristic_score: np.ndarray,
    max_weighted_mismatch: np.ndarray,
    context: np.ndarray,
    device: torch.device,
    batch_size: int,
) -> dict[str, np.ndarray]:
    model.eval()
    outputs: dict[str, list[np.ndarray]] = {
        "prediction": [],
        "calibration_scale": [],
        "learned_penalty_strength": [],
        "context_bias": [],
        "penalized_base": [],
    }
    total = len(heuristic_score)
    if total == 0:
        empty = np.zeros((0,), dtype=np.float32)
        return {key: empty.copy() for key in outputs}
    for start in range(0, total, batch_size):
        stop = min(start + batch_size, total)
        h = torch.as_tensor(
            heuristic_score[start:stop], dtype=torch.float32, device=device
        )
        mismatch = torch.as_tensor(
            max_weighted_mismatch[start:stop], dtype=torch.float32, device=device
        )
        ctx = torch.as_tensor(context[start:stop], dtype=torch.float32, device=device)
        pred, params = model(h, mismatch, ctx, return_parameters=True)
        outputs["prediction"].append(pred.cpu().numpy())
        outputs["calibration_scale"].append(params["scale"].cpu().numpy())
        outputs["learned_penalty_strength"].append(params["penalty"].cpu().numpy())
        outputs["context_bias"].append(params["bias"].cpu().numpy())
        outputs["penalized_base"].append(params["penalized_base"].cpu().numpy())
    return {key: np.concatenate(parts) for key, parts in outputs.items()}
