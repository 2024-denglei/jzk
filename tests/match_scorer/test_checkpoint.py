EXPECTED_SHA256 = "6ffa19eb2c377830e43dd2942bb3cfdce4fe6d62d7ff8a10a285d26cd7988944"


def test_real_checkpoint_identity(scoring_engine):
    manifest = scoring_engine.manifest
    assert manifest.name == "sperm-match-v4-tender-multitask"
    assert manifest.checkpoint_role == "best_mae"
    assert manifest.checkpoint_epoch == 33
    assert manifest.checkpoint_sha256 == EXPECTED_SHA256
    assert manifest.max_attributes == 11
    assert manifest.device == "cpu"
