# JZK Match Scorer

该服务只负责候选预选和模型评分，不连接 PostgreSQL。主应用负责画像校验、must 过滤、权限、审计、结果快照和分页。

开发环境启动：

```bash
SCORER_TOKEN=dev-match-scorer-token-change-me \
.venv/bin/python -m uvicorn services.match_scorer.app:app \
  --host 127.0.0.1 --port 8020
```

主应用与本服务共用同一个 `SCORER_TOKEN`，两端必须一致，因此只有这一个变量名：

```bash
MATCH_SCORING_BACKEND=http
MATCH_SCORER_URL=http://127.0.0.1:8020
SCORER_TOKEN=dev-match-scorer-token-change-me
```

检查服务：

```bash
curl http://127.0.0.1:8020/healthz
curl http://127.0.0.1:8020/readyz
```

主应用可通过 `GET /api/match/ready` 检查评分服务契约与模型能力。评分服务的
`GET /metrics` 需要相同的 Bearer token，只返回请求数、错误数、候选数与耗时，
不会记录画像或候选内容。

模型更新时，将模型代码、编码逻辑和 checkpoint 作为同一个发布单元，并设置
`SCORER_EXPECTED_MODEL_NAME`、`SCORER_EXPECTED_CHECKPOINT_ROLE` 和可选的
`SCORER_EXPECTED_CHECKPOINT_SHA256`；确认 `/readyz` 通过后再切主应用流量。

生产环境应在受保护的内部网络部署，并使用至少 32 字节的随机 token；不要把评分端口暴露到公网。
