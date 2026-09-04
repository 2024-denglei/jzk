import torch

from jzk.scorer.model import ModelConfig, TenderAlignedV32


def test_forward_shapes():
    model = TenderAlignedV32(
        ModelConfig(), field_count=47, type_count=5, constraint_count=3
    )
    batch = {
        "numeric": torch.zeros(1, 3, 11, 10),
        "field_ids": torch.zeros(1, 3, 11, dtype=torch.long),
        "type_ids": torch.zeros(1, 3, 11, dtype=torch.long),
        "constraint_ids": torch.zeros(1, 3, 11, dtype=torch.long),
        "target_ids": torch.zeros(1, 3, 11, dtype=torch.long),
        "actual_ids": torch.zeros(1, 3, 11, dtype=torch.long),
        "mask": torch.zeros(1, 3, 11, dtype=torch.bool),
        "global": torch.zeros(1, 3, 7),
    }
    batch["mask"][:, :, 0] = True
    outputs = model(batch)
    assert len(outputs) == 6
    assert tuple(outputs[0].shape) == (1, 3)
    assert tuple(outputs[2].shape) == (1, 3, 11)
