from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import secrets
import threading
from typing import Callable

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api_models import RankRequest, RankResponse
from .engine import MatchScoringEngine, ScoringRequestError
from .settings import ScorerSettings


logger = logging.getLogger(__name__)


class ScorerMetrics:
    """进程内非敏感计数；不保留画像或候选 payload。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = 0
        self._errors: dict[str, int] = {}
        self._eligible_total = 0
        self._eligible_max = 0
        self._ranked_total = 0
        self._timing_totals: dict[str, float] = {}

    def success(self, response: RankResponse) -> None:
        with self._lock:
            self._requests += 1
            self._eligible_total += response.eligible_count
            self._eligible_max = max(self._eligible_max, response.eligible_count)
            self._ranked_total += response.ranked_count
            for name, value in response.timings.items():
                self._timing_totals[name] = (
                    self._timing_totals.get(name, 0.0) + float(value)
                )

    def failure(self, code: str) -> None:
        with self._lock:
            self._requests += 1
            self._errors[code] = self._errors.get(code, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            successes = self._requests - sum(self._errors.values())
            return {
                "rank_requests_total": self._requests,
                "rank_success_total": successes,
                "rank_errors_total": dict(self._errors),
                "eligible_candidates_total": self._eligible_total,
                "eligible_candidates_max": self._eligible_max,
                "ranked_candidates_total": self._ranked_total,
                "timing_ms_total": dict(self._timing_totals),
            }


def _error(status: int, code: str, message: str, retryable: bool) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            }
        },
    )


class RequestSizeLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = dict(scope.get("headers") or [])
            raw_length = headers.get(b"content-length")
            if raw_length:
                try:
                    too_large = int(raw_length) > self.max_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    response = _error(
                        413, "REQUEST_TOO_LARGE", "请求体超过限制", False
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def create_app(
    settings: ScorerSettings | None = None,
    engine_factory: Callable[[ScorerSettings], MatchScoringEngine] = MatchScoringEngine,
) -> FastAPI:
    resolved = settings or ScorerSettings.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.scorer_settings = resolved
        app.state.scorer_engine = None
        app.state.scorer_load_error = None
        app.state.scorer_metrics = ScorerMetrics()
        try:
            app.state.scorer_engine = engine_factory(resolved)
        except Exception as exc:
            logger.exception("match scorer failed to load")
            app.state.scorer_load_error = f"{type(exc).__name__}: {exc}"
        yield

    application = FastAPI(
        title="JZK Match Scorer",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        RequestSizeLimitMiddleware, max_bytes=resolved.max_request_bytes
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return _error(422, "CONTRACT_VALIDATION_ERROR", str(exc), False)

    @application.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        if exc.status_code == 401:
            return _error(401, "SERVICE_UNAUTHORIZED", "服务凭证无效", False)
        if exc.status_code == 503:
            return _error(503, "MODEL_NOT_READY", "模型尚未就绪", True)
        return _error(
            exc.status_code,
            "HTTP_ERROR",
            str(exc.detail),
            exc.status_code >= 500,
        )

    def authorize(authorization: str | None) -> None:
        prefix = "Bearer "
        supplied = (
            authorization[len(prefix):]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        if not secrets.compare_digest(supplied, resolved.token):
            raise HTTPException(status_code=401, detail="invalid service credential")

    def engine(request: Request) -> MatchScoringEngine:
        loaded = getattr(request.app.state, "scorer_engine", None)
        if loaded is None:
            error = getattr(
                request.app.state,
                "scorer_load_error",
                "model is not ready",
            )
            raise HTTPException(status_code=503, detail=error)
        return loaded

    @application.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/readyz")
    async def readyz(request: Request):
        loaded = getattr(request.app.state, "scorer_engine", None)
        if loaded is None:
            return _error(503, "MODEL_NOT_READY", "模型尚未就绪", True)
        return {"ok": True, "model": loaded.manifest.to_identity().model_dump()}

    @application.get("/v1/model")
    async def model_info(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        return engine(request).manifest.to_identity().model_dump()

    @application.get("/metrics")
    async def metrics(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        return request.app.state.scorer_metrics.snapshot()

    @application.post("/v1/rank", response_model=RankResponse)
    async def rank(
        payload: RankRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        authorize(authorization)
        try:
            response = engine(request).rank(payload)
            request.app.state.scorer_metrics.success(response)
            logger.info(
                "match scorer request_id=%s model=%s checkpoint=%s "
                "eligible=%s ranked=%s timings=%s",
                payload.request_id,
                response.model.version,
                response.model.checkpoint_sha256[:12],
                response.eligible_count,
                response.ranked_count,
                response.timings,
            )
            return response
        except ScoringRequestError as exc:
            request.app.state.scorer_metrics.failure(exc.code)
            return _error(422, exc.code, str(exc), False)
        except ValueError as exc:
            request.app.state.scorer_metrics.failure("SCORING_INPUT_ERROR")
            return _error(422, "SCORING_INPUT_ERROR", str(exc), False)
        except Exception:
            request.app.state.scorer_metrics.failure("MODEL_INFERENCE_FAILED")
            logger.exception("match scorer inference failed request_id=%s", payload.request_id)
            return _error(503, "MODEL_INFERENCE_FAILED", "模型推理失败", True)

    return application


app = create_app()
