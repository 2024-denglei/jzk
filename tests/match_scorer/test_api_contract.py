import asyncio

import httpx

from services.match_scorer.api_models import RankResponse
from services.match_scorer.app import create_app
from services.match_scorer.model_manifest import ModelManifest


class _FakeEngine:
    def __init__(self, _settings):
        self.manifest = ModelManifest(
            name="fake-model",
            version="fake-v1",
            checkpoint_role="test",
            checkpoint_epoch=1,
            checkpoint_sha256="a" * 64,
            max_attributes=11,
            candidate_pool=300,
            device="cpu",
        )

    def rank(self, request):
        candidate = request.candidates[0]
        return RankResponse.model_validate({
            "contract_version": "1",
            "request_id": request.request_id,
            "model": self.manifest.to_identity(),
            "eligible_count": len(request.candidates),
            "ranked_count": 1,
            "items": [{
                "donor_id": candidate.donor_id,
                "rank": 1,
                "match_score": 0.9,
                "ranking_score": 0.8,
                "heuristic_score": 1.0,
                "field_scores": [],
            }],
            "timings": {"total_ms": 1.0},
        })


def _payload():
    return {
        "contract_version": "1",
        "request_id": "api-test",
        "profile": {
            "schema_version": "1.0",
            "attributes": {
                "abo_blood": {
                    "type": "enum", "constraint": "must", "weight": 1,
                    "values": ["O"],
                }
            },
        },
        "candidates": [
            {"donor_id": 1, "code": "A1", "attributes": {"abo_blood": "O"}}
        ],
    }


def test_rank_requires_service_token(scorer_settings):
    app = create_app(scorer_settings, _FakeEngine)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://scorer.test",
            ) as client:
                unauthorized = await client.post("/v1/rank", json=_payload())
                response = await client.post(
                    "/v1/rank",
                    json=_payload(),
                    headers={"Authorization": f"Bearer {scorer_settings.token}"},
                )
                return unauthorized, response

    unauthorized, response = asyncio.run(scenario())
    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json()["model"]["version"] == "fake-v1"


def test_health_and_readiness_are_separate(scorer_settings):
    app = create_app(scorer_settings, _FakeEngine)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://scorer.test",
            ) as client:
                health = await client.get("/healthz")
                ready = await client.get("/readyz")
                return health, ready

    health, ready = asyncio.run(scenario())
    assert health.json() == {"ok": True}
    assert ready.status_code == 200
    assert ready.json()["model"]["name"] == "fake-model"


def test_request_size_is_rejected_before_parsing(scorer_settings):
    app = create_app(scorer_settings, _FakeEngine)
    async def scenario():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://scorer.test",
            ) as client:
                return await client.post(
                    "/v1/rank",
                    content=b"{}",
                    headers={
                        "content-length": str(scorer_settings.max_request_bytes + 1)
                    },
                )

    response = asyncio.run(scenario())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
