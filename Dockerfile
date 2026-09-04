FROM node:22-alpine AS web-builder

WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # 装进系统环境而不是 /app/.venv，这样 compose 里各服务的 `python ...` 启动
    # 命令无需感知虚拟环境路径。
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# --locked 会在 pyproject.toml 改了却没重新锁定时直接失败，镜像因此不可能装出
# 一套与 uv.lock 不一致的依赖。--no-dev 把 pytest 等开发依赖挡在镜像外。
COPY pyproject.toml uv.lock ./
RUN pip install --upgrade pip \
    && pip install "uv==0.11.28" \
    && uv sync --locked --no-dev \
    && pip uninstall -y uv

COPY . ./
COPY --from=web-builder /build/web/dist ./web/dist

EXPOSE 8010 8020

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
