# 前端

三个 npm workspace：`client`（用户）、`admin`（管理员）、`shared`（生成的 HTTP 契约）。约定见 [`docs/architecture.md`](../docs/architecture.md) 与 [ADR 0005](../docs/adr/0005-管理端与客户端是两个独立前端应用.md)。

```bash
npm run dev:client   # 用户端
npm run dev:admin    # 管理端，路径仍是 /admin/...
npm run build
```

改了后端响应形状之后，先导出 OpenAPI 再生成 TypeScript：

```bash
uv run --locked --directory backend python scripts/export_openapi.py
npm run generate:api
```
