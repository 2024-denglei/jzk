# 当前结构

这份文档描述仓库**现在**怎么分层。用词见 [`CONTEXT.md`](../CONTEXT.md)，为什么这样定见 [`docs/adr/`](./adr/)。历史 plan / spec 在 [`docs/archive/`](./archive/)，不要拿它们当现状。

## 仓库

真正的 git 根是 `jzk/`。后端是可安装包 `backend/jzk/`（导入一律 `from jzk...`），前端是 `frontend/` 下三个 npm workspace，Compose 和 `.env.example` 留在仓库根。

运行中的进程由根目录 `compose.yml` 声明：`app`（`jzk.main:app`）、`scorer`（`jzk.scorer.app:app`）、`postgres`、`redis`；生成与 Outbox 两个 worker 走 `--profile workers`。打分服务与主应用目前共用同一镜像、只换启动命令，见 [ADR 0001](./adr/0001-打分服务为唯一打分权威.md)。

怎么在本机拉起来，见 [`DOCKER.md`](../DOCKER.md)。端口、密钥名、连接串不得在文档里再抄一份——`tests/test_config_consistency.py` 把「同一件事写了两遍」钉在一起。

## 后端分层

依赖只能单向流动，由 `tests/test_layering.py` 扫源码 AST 守住（函数内 lazy import 也算违规）：

| 包 | 职责 | 不得 import |
| --- | --- | --- |
| `jzk.domain` | 领域逻辑：筛选、画像、打分客户端 | `db` / `api` / `chat` / `advisor` / `matching` |
| `jzk.db` | Schema、仓储、硬过滤 SQL | `api` / `chat` / `advisor` / `matching` |
| `jzk.matching` | 执行一次匹配 | `api` / `chat` / `advisor` |
| `jzk.chat` | 对话存储与查询 | `api` / `advisor` |
| `jzk.advisor` | 顾问与生成 | `api` |
| `jzk.api` | HTTP | — |
| `jzk.scorer` | 打分进程 | 不连 Postgres |

`jzk.matching.execute_match` 是匹配的唯一入口：校验偏好画像、硬过滤、调用打分、落匹配快照。`jzk.api.match` 与 `jzk.advisor.generation_processor` 都只调它，彼此不 import。

**筛选**和**匹配**是两项独立能力（[ADR 0003](./adr/0003-筛选与匹配是两项独立能力.md)）。筛选走 `jzk.domain.screening` 与 `GET /api/search`，不经顾问、不经模型。匹配走编排层，打分只通过 `jzk.domain.preference.scoring_client` 访问 `POST /v1/rank`。

handler 里不许出现 SQL，由仓储层读写。HTTP 契约以 FastAPI 的 OpenAPI 为准：`backend/scripts/export_openapi.py` 写出 `frontend/shared/openapi.json`，`openapi-typescript` 生成 `openapi.d.ts`。CI 核对 JSON 等于 live schema、生成物没有手改。

## 前端

三个构建产物（[ADR 0005](./adr/0005-管理端与客户端是两个独立前端应用.md)）：

- `frontend/client/`：用户用的客户端，生产挂在 `/`
- `frontend/admin/`：管理员用的管理端，Vite `base` 为 `/admin/`，Router **不**设 basename（现有 `/admin/users` 等路径继续按 pathname 匹配）
- `frontend/shared/`：生成的契约类型和一层旧名字别名。不是公共工具箱，不要把 `lib/api` 抽进去

管理端源码不得打进用户 bundle。两端身份独立，不共用登录。

冻结匹配页的 TypeScript 仍是手写的：OpenAPI 里那块还是松的 `dict`。

## 数据权威

PostgreSQL 是对话、匹配快照、生成任务和 Trace 的长期权威来源。细节见 [`conversation.md`](./conversation.md)。

Redis 只承载生成事件流、验证码、限流等短期数据，不是会话存储。
