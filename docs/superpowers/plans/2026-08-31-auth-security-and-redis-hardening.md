# 登录鉴权安全与 Redis 加固实施计划

## 实施状态（2026-08-31）

本计划的应用代码主体已经按阶段完成，相关提交如下：

| 阶段 | 状态 | 提交 |
|---|---|---|
| 生产安全配置止血 | 已完成 | `2f3dee7` |
| 会话所有权与接口鉴权 | 已完成 | `82300a6` |
| Redis 防爆破与验证码尝试限制 | 已完成 | `3847de6` |
| Access Token / Refresh Session 改造 | 已完成 | `c2f53a0` |
| Redis 临时会话、连接池与通用安全加固 | 已完成 | `6fe3925` |

已经落地的关键能力包括：生产配置拒绝不安全默认值、用户绑定会话、登录与验证码原子限流、短期 Access Token、Refresh Token 哈希存储/轮换/撤销/重放检测、前端凭证内存化、Redis 跨实例临时会话、PostgreSQL/Redis 连接池、CORS 白名单、安全响应头、密码强度和上传体积限制。

以下事项依赖部署环境或第三方服务，不能仅通过仓库代码完成，仍需在上线前执行：

- 选定并接入真实短信服务商，配置密钥、发送失败回滚和服务商故障演练。
- 在生产网络关闭 Redis 公网端口，启用 ACL、认证和 TLS，并执行 Redis 故障/主从切换测试。
- 配置真实生产域名、随机密钥和非默认管理员凭证，轮换 JWT 密钥使旧 7 天 Bearer Token 失效。
- 接入组织现有监控/告警平台，采集 401、403、429、Refresh 重放、Redis、数据库连接池和会话冲突指标。
- 在预发布环境执行浏览器端到端、并发压测、多实例切换及上线/回滚演练。
- 管理员 TOTP/MFA 保持为后续增强项。

## 目标

在不改变现有用户、管理员和业务数据权威来源的前提下，修复当前登录鉴权链路中的生产配置风险、会话越权、防爆破缺失和凭证撤销不完整问题，并将 Redis 用于适合的临时状态与原子计数场景。

最终目标：

- PostgreSQL 继续保存用户、密码哈希、管理员、角色、长期对话和审计记录。
- Redis 保存验证码、限流计数、Refresh Session 和临时对话会话。
- Access Token 缩短到 15～30 分钟，只保存在前端内存。
- Refresh Token 使用 `HttpOnly + Secure + SameSite` Cookie，并支持轮换和主动撤销。
- 所有临时对话会话必须绑定用户，任何接口都不能只凭 `session_id` 访问或修改会话。
- 用户和管理员的改密、停用、强制下线及登出操作都能可靠撤销相关凭证。

## 当前状态与主要风险

当前实现具有以下基础能力：

- 用户密码使用 bcrypt 哈希保存。
- 用户和管理员使用 HS256 JWT，通过 `Authorization: Bearer <token>` 访问接口。
- 用户令牌包含 `token_version`，改密、找回密码、停用和强制下线可以令旧令牌失效。
- 管理端在每次请求中查询当前管理员状态和角色，再执行细粒度权限判断。
- Redis 已用于验证码 TTL、发送冷却和一次性原子消费。

需要解决的问题：

1. 生产环境仍可能使用占位 JWT 密钥、默认管理员凭证，并向客户端返回测试验证码。
2. 内存对话会话只按 `session_id` 索引，没有绑定 `user_id`。
3. `/api/feedback` 和 `/api/session/{session_id}` 没有登录与所有权校验。
4. 密码登录、管理员登录和验证码校验缺少失败次数限制。
5. 用户端和管理端 JWT 存在 `localStorage`，有效期为 7 天。
6. 管理员改密不要求旧密码，也不会撤销已签发令牌。
7. PostgreSQL 每次请求新建连接，没有连接池。
8. 开发 Compose 将无认证 Redis 端口映射到宿主机，不能直接用于生产。

## 范围与非目标

### 本计划范围

- 用户和管理员登录、刷新、登出、改密及凭证撤销。
- 手机验证码生成、发送、校验和防滥用。
- 用户对话会话的所有权、临时存储和多实例一致性。
- Redis、CORS、连接池、安全响应头和鉴权审计。
- 兼容旧 Bearer Token 的渐进迁移与回滚方案。

### 第一版非目标

- 不更换 PostgreSQL 中现有用户主键和业务表关系。
- 不把用户、管理员或长期对话权威数据迁入 Redis。
- 不在第一版接入第三方 OAuth。
- 管理员 TOTP/MFA 作为后续增强，不阻塞本计划主体上线。

## 目标架构

```text
React Web
  ├─ Access Token：15～30 分钟，仅保存在内存
  └─ Refresh Token：HttpOnly + Secure + SameSite Cookie
                         │
                         ▼
FastAPI 鉴权层
  ├─ PostgreSQL
  │    ├─ 用户、密码哈希、状态、token_version
  │    ├─ 管理员、角色、状态、token_version
  │    ├─ 长期对话与用户业务数据
  │    └─ 安全审计记录
  └─ Redis
       ├─ 验证码、发送冷却和校验尝试次数
       ├─ 用户/IP/管理员登录限流
       ├─ Refresh Session 与轮换状态
       └─ 绑定 user_id 的临时对话会话
```

## 全局约束

- 用户和管理员数据以 PostgreSQL 为权威来源，Redis 不得成为唯一长期数据源。
- Redis 中的手机号、邮箱等标识优先使用带服务端 pepper 的 HMAC，不直接作为明文 key。
- Redis 不可用时，验证码、限流和刷新操作失败关闭；不得绕过安全校验继续执行。
- 所有 401、403、429 响应使用统一结构，前端不得依赖具体数据库状态推断账号是否存在。
- 不在日志、Trace、异常、审计详情中记录密码、完整 Token、验证码、Cookie 或完整手机号。
- 所有安全配置必须通过环境变量注入，生产环境不得使用源码默认值兜底。
- 每个阶段独立提交、独立发布并可回滚，不进行一次性大爆炸式重构。

---

## 阶段一：生产配置与基础设施止血（P0）

**主要文件：**

- 修改：`config.py`
- 修改：`.env.example`
- 修改：`api/auth_utils.py`
- 修改：`db/postgres/docker-compose.yml`
- 新增测试：`tests/test_security_config.py`

- [ ] 增加 `ENVIRONMENT=development|test|production` 配置。
- [ ] 生产环境未配置 `JWT_SECRET` 时拒绝启动。
- [ ] 拒绝 `change-me-in-production`、内置默认字符串和长度不足的 JWT 密钥。
- [ ] 生产环境强制 `EXPOSE_TEST_VERIFICATION_CODE=0`。
- [ ] 生产环境拒绝默认管理员用户名或默认管理员密码。
- [ ] `.env.example` 明确区分开发示例与生产必填项，不放入可直接用于生产的固定凭证。
- [ ] Redis 连接配置支持用户名、密码、TLS、连接池大小和超时。
- [ ] 生产部署不向公网映射 Redis 6379，仅允许应用所在私网访问。
- [ ] 为 Redis 配置 ACL；生产环境使用托管 Redis 时启用传输加密。
- [ ] 启动日志只报告安全配置是否合格，不打印任何密钥值。

**发布动作：**

- 生成至少 32 字节的随机 JWT 密钥。
- 修改引导管理员凭证。
- 关闭测试验证码回传。
- 轮换 JWT 密钥时明确通知所有现有用户需要重新登录。

**验收标准：**

- 生产环境使用占位密钥、默认管理员密码或测试验证码开关时，应用启动失败并给出明确原因。
- 公网无法直接连接 Redis。
- 仓库和应用日志中不存在真实密钥、验证码和完整 Token。

---

## 阶段二：修复会话越权与接口鉴权（P0）

**主要文件：**

- 修改：`dialogue/session.py`
- 修改：`api/chat.py`
- 修改：`api/chat_stream.py`
- 修改：`api/feedback.py`
- 修改：`api/user.py`
- 修改：`api/chat_persist.py`
- 新增/修改测试：`tests/test_auth_isolation.py`
- 新增测试：`tests/test_chat_session_ownership.py`

- [ ] `SessionContext` 增加不可为空的 `owner_user_id`。
- [ ] `SessionManager` 的创建、读取、恢复、回滚和删除接口同时接收 `user_id` 与 `session_id`。
- [ ] 会话内存索引改为 `(user_id, session_id)`，或使用包含两者的稳定复合 key。
- [ ] 客户端提交已有 `session_id` 时，必须校验其属于当前用户。
- [ ] 所有权不匹配统一返回 404，避免泄漏目标会话是否存在。
- [ ] `/api/feedback` 增加 `get_current_user_id` 依赖和会话所有权校验。
- [ ] `/api/session/{session_id}` 增加 `get_current_user_id` 依赖和会话所有权校验。
- [ ] 反馈接口检查 `candidate_id` 确实存在于该会话候选列表中。
- [ ] 为反馈原因、消息历史、候选列表和会话状态增加结构与长度上限。
- [ ] `chat/abort`、`chat/rewind`、`chat/stream` 和普通 `chat` 全部使用用户绑定的会话查找。
- [ ] 长期对话的读取、恢复、更新和删除继续以 `user_id` 作为 SQL 条件。
- [ ] 发布时清空旧的进程内临时会话，禁止没有所有者的旧会话继续使用。

**必须覆盖的测试：**

- [ ] 用户 A 无法读取用户 B 的临时会话。
- [ ] 用户 A 无法继续、回滚、中止或反馈用户 B 的会话。
- [ ] 未登录请求无法访问反馈和会话详情接口。
- [ ] 用户 A 和用户 B 使用相同客户端 `session_id` 时不会共享内存状态。
- [ ] 恢复 PostgreSQL 长期对话时仍校验对话所属用户。

**验收标准：**

- 任意会话操作都同时要求合法用户身份和会话所有权。
- 现有合法用户的创建、继续、保存、恢复、回滚和中止流程保持可用。

---

## 阶段三：Redis 防爆破与验证码加固（P1）

**主要文件：**

- 修改：`api/verification_codes.py`
- 修改：`api/auth.py`
- 修改：`api/admin.py`
- 新增：`api/rate_limit.py`
- 修改：`config.py`
- 修改：`.env.example`
- 新增测试：`tests/test_auth_rate_limit.py`
- 扩展测试：`tests/test_auth_phone.py`

### 建议限制规则

| 场景 | 限制 |
|---|---|
| 用户密码登录 | 同账号或 IP：10 分钟最多失败 5 次 |
| 管理员登录 | 同账号或 IP：15 分钟最多失败 5 次，之后递增锁定 |
| 验证码发送（手机号） | 60 秒一次、每小时 5 次、每天 10 次 |
| 验证码发送（IP） | 每小时最多 20 次 |
| 验证码校验 | 单个验证码最多失败 5 次 |
| 找回密码 | 同时执行手机号和 IP 限制 |

### Redis Key 约定

```text
jzk:rate:login:account:{identifier_hmac}
jzk:rate:login:ip:{ip_hmac}
jzk:rate:admin-login:{identifier_hmac}
jzk:rate:send-code:phone:{phone_hmac}
jzk:rate:send-code:ip:{ip_hmac}
jzk:auth:code:{purpose}:{phone_hmac}
jzk:auth:code-attempts:{purpose}:{phone_hmac}
```

- [ ] 提供统一 `RateLimiter`，禁止各接口自行拼装不一致的限流逻辑。
- [ ] 使用 Redis Lua 脚本原子完成计数、TTL 设置、校验和锁定。
- [ ] 验证码错误达到 5 次后删除验证码并进入短时锁定。
- [ ] 验证码成功消费时同时删除错误次数 key。
- [ ] 发送新验证码时原子更新冷却 key 与验证码 key，避免部分写入。
- [ ] 登录成功后清除对应账号的失败计数；IP 计数按策略自然过期。
- [ ] 登录失败统一返回“账号或密码错误”，避免暴露账号是否存在。
- [ ] 验证码发送接口使用统一外部响应；真实是否发送写入安全审计，不向客户端暴露账号存在性。
- [ ] 接入真实短信服务并实现发送失败回滚；生产环境永不返回验证码。
- [ ] Redis 不可用时返回 503，不允许无保护地继续登录、发码或验码。
- [ ] 管理员连续失败触发安全审计；后续可在阈值处接入 CAPTCHA 或告警。

**验收标准：**

- 并发请求不能绕过次数限制。
- 单个验证码最多允许配置数量的错误尝试，并且只能成功消费一次。
- Redis 故障时系统不会退化为无限尝试模式。

---

## 阶段四：Access Token 与 Refresh Session 改造（P1）

**主要文件：**

- 修改：`api/auth_utils.py`
- 修改：`api/auth.py`
- 修改：`api/admin_auth.py`
- 修改：`api/admin.py`
- 新增：`api/refresh_sessions.py`
- 修改：`db/postgres/02_schema.sql`
- 新增：可重复执行的 PostgreSQL 迁移文件
- 修改：`web/src/lib/api.ts`
- 修改：`web/src/context/AuthContext.tsx`
- 修改：`web/src/pages/admin/adminApi.ts`
- 修改：`web/src/pages/AdminPage.tsx`
- 新增测试：`tests/test_refresh_sessions.py`
- 新增测试：`tests/test_admin_token_revocation.py`

### Token 设计

- Access Token：JWT，有效期 15～30 分钟。
- Access Token Claims 至少包含：`sub`、`kind`、`ver`、`iss`、`aud`、`iat`、`exp`、`jti`。
- Access Token 只保存在 React 内存，不写入 `localStorage` 或 `sessionStorage`。
- Refresh Token：至少 256 bit 的随机值，客户端仅通过 Cookie 持有。
- Cookie：`HttpOnly`、`Secure`、`SameSite=Strict`，Path 限定为刷新/登出路径。
- Redis 只保存 Refresh Token 的 SHA-256 哈希、用户/管理员 ID、版本、创建时间、过期时间和设备信息摘要。
- 普通用户 Refresh Session 建议 7～30 天；管理员建议 4～8 小时。
- 每次刷新都轮换 Refresh Token；检测旧 Token 重放时撤销同一 Token Family。

### Redis Key 约定

```text
jzk:refresh:user:{token_hash}
jzk:refresh:admin:{token_hash}
jzk:refresh-family:{family_id}
jzk:refresh-subject:user:{user_id}
jzk:refresh-subject:admin:{admin_id}
```

- [ ] 新增用户 `/api/auth/refresh`、`/api/auth/logout`、`/api/auth/logout-all`。
- [ ] 新增管理员 `/api/admin/refresh`、`/api/admin/logout`、`/api/admin/logout-all`。
- [ ] 登录响应返回短期 Access Token，并通过 `Set-Cookie` 写入 Refresh Token。
- [ ] 前端启动时调用 refresh 获取新的 Access Token，再请求 `/me`。
- [ ] 前端收到 401 时最多自动刷新一次，并对并发请求使用单飞锁，避免刷新风暴。
- [ ] 刷新失败时清空内存状态并进入登录页。
- [ ] 用户登出撤销当前 Refresh Session；全部登出撤销该用户所有 Refresh Session。
- [ ] 用户改密、找回密码、停用和强制下线同时递增 `token_version` 并撤销全部 Refresh Session。
- [ ] `admin.admin_users` 增加 `token_version` 字段。
- [ ] 管理员改密要求当前密码，成功后递增 `token_version` 并撤销全部 Refresh Session。
- [ ] 管理员停用、删除或角色发生安全敏感变化时撤销全部 Refresh Session。
- [ ] 刷新和登出接口校验 `Origin`，并保留严格 SameSite Cookie，降低 CSRF 风险。
- [ ] 用户和管理员使用不同的 Refresh Cookie 名称、Path、Redis key 空间和 Token `kind`。

### 兼容迁移

- [ ] 第一版后端暂时接受现有 7 天 Bearer Token，但不再向新登录签发旧格式令牌。
- [ ] 增加兼容期指标，统计旧格式令牌剩余请求量。
- [ ] 兼容期结束后删除旧格式支持，并通过 `token_version` 或密钥轮换使残留旧令牌失效。
- [ ] 前端完成新流程后删除 `jzk_token` 和 `jzk_admin_token` 两个旧 `localStorage` 项。

**验收标准：**

- 页面刷新后可通过 HttpOnly Refresh Cookie 恢复登录。
- JavaScript 无法读取 Refresh Token。
- Access Token 过期后可以安全刷新，旧 Refresh Token 不能再次使用。
- 登出、全部登出、改密、停用和踢下线后旧 Refresh Token 均不可用。
- 用户 Token 不能访问管理端，管理员 Token 不能访问用户端。

---

## 阶段五：临时对话会话迁移到 Redis（P2）

**主要文件：**

- 修改：`dialogue/session.py`
- 新增：`dialogue/redis_session_store.py`
- 修改：`main.py`
- 修改：`config.py`
- 新增测试：`tests/test_redis_chat_sessions.py`

### Redis Key 约定

```text
jzk:chat-session:{user_id}:{session_id}
TTL = 30 分钟
```

- [ ] 抽象 `SessionStore` 接口，业务代码不直接依赖 Redis 客户端。
- [ ] Redis 会话数据必须包含 `owner_user_id`、状态版本和最后活动时间。
- [ ] 所有读取与写入同时校验 Redis key 中的用户 ID 和数据内的所有者字段。
- [ ] 每次有效操作刷新 30 分钟 TTL。
- [ ] 使用 WATCH/MULTI、Lua 或显式版本号避免并发消息相互覆盖。
- [ ] 单个用户限制活跃临时会话数量，防止无界占用 Redis。
- [ ] 为单个会话设置序列化体积上限，候选详情只保留必要字段。
- [ ] PostgreSQL 中的 `app.chats` 继续保存长期对话，不依赖 Redis 持久化配置。
- [ ] Redis 会话丢失时允许从当前用户自己的 PostgreSQL 对话恢复，但不能从其他用户记录恢复。
- [ ] 支持多进程、多实例共享同一会话，并验证实例切换后状态一致。

**验收标准：**

- 两个应用实例可以连续处理同一个用户会话。
- 不同用户即使提交相同 session ID 也不能共享状态。
- Redis 临时会话过期不影响 PostgreSQL 中已保存的长期对话。

---

## 阶段六：连接池、跨域与通用安全加固（P2）

**主要文件：**

- 修改：`db/pg.py`
- 修改：`main.py`
- 修改：`config.py`
- 修改：`.env.example`
- 新增/修改相关测试

- [ ] 引入 psycopg 连接池，并配置最小/最大连接数、获取超时和健康检查。
- [ ] 应用启动时创建连接池，关闭时优雅释放连接。
- [ ] CORS 从 `*` 改为环境变量驱动的域名白名单。
- [ ] 仅允许实际需要的 HTTP 方法和请求头。
- [ ] 生产环境强制 HTTPS，并配置 HSTS。
- [ ] 增加 CSP、`X-Content-Type-Options`、`Referrer-Policy` 和点击劫持防护。
- [ ] 为 JSON、SSE、音频和 Excel 上传设置独立请求体大小限制。
- [ ] 用户密码最低长度提高到 10～12 位，并增加常见弱密码检查。
- [ ] 管理员密码采用更严格策略；后续增加 TOTP/MFA。
- [ ] 增加登录成功/失败、刷新重放、改密、退出、强制下线和权限拒绝审计。
- [ ] 增加 Redis、连接池、401、403、429、刷新失败和会话冲突指标。

**验收标准：**

- 高并发请求不再为每次鉴权创建新的 PostgreSQL TCP 连接。
- 非白名单来源无法通过浏览器跨域调用受保护接口。
- 安全日志能定位异常登录和令牌重放，但不包含敏感凭证。

---

## 测试矩阵

### 单元测试

- [ ] JWT Claims、过期、类型隔离和 token_version 校验。
- [ ] Refresh Token 生成、哈希、轮换、撤销和重放检测。
- [ ] Redis 限流窗口、TTL 和 Lua 原子性。
- [ ] 验证码发送冷却、错误次数、成功消费和并发消费。
- [ ] SessionStore 所有权、版本冲突和过期行为。
- [ ] 生产配置启动校验。

### API 集成测试

- [ ] 未登录、伪造 Token、过期 Token、错误 kind 的响应。
- [ ] 两个用户之间的收藏、历史、对话和临时会话隔离。
- [ ] 普通管理员与超级管理员权限隔离。
- [ ] 用户和管理员改密后所有旧凭证失效。
- [ ] 停用和强制下线立即阻止刷新及后续业务请求。
- [ ] Redis 不可用时验证码、限流和刷新失败关闭。
- [ ] Refresh Cookie 属性符合生产要求。

### 前端与端到端测试

- [ ] 密码登录、验证码登录、注册、找回密码和退出。
- [ ] 页面刷新恢复登录。
- [ ] 多个请求同时遇到 401 时只发起一次刷新。
- [ ] 刷新失败跳转登录页且不发生无限重试。
- [ ] 管理端改密、退出和停用后的行为。
- [ ] XSS 模拟脚本无法读取 Refresh Token。

### 性能与故障测试

- [ ] 登录和鉴权压测，观察 PostgreSQL 连接池与 Redis 延迟。
- [ ] 多实例间对话会话切换测试。
- [ ] Redis 短暂不可用、主从切换和恢复测试。
- [ ] 短信服务超时、失败和重复回调测试。

## 发布顺序

1. **发布 A：安全配置止血**
   - 强制安全配置、关闭验证码回传、修改默认管理员凭证、保护 Redis。
   - JWT 密钥轮换会令现有用户重新登录，应提前通知。
2. **发布 B：会话越权修复**
   - 会话绑定用户、反馈和会话详情补鉴权、补齐双用户隔离测试。
   - 发布时清理无所有者的旧内存会话。
3. **发布 C：Redis 防爆破**
   - 上线统一限流、验证码错误次数和真实短信服务。
   - 先以监控模式核对阈值，再开启强制拦截。
4. **发布 D：Access/Refresh Token**
   - 先部署兼容新旧令牌的后端，再部署新前端，最后结束旧令牌兼容期。
5. **发布 E：Redis 对话会话与通用加固**
   - 迁移临时会话、启用多实例、连接池和安全响应头。

## 回滚策略

- 每个发布阶段使用独立 Git commit 和数据库迁移，禁止将多个安全阶段混在一个不可拆分发布中。
- 数据库迁移优先采用向前兼容的新增列、表和索引；旧代码在新增结构存在时仍应可运行。
- Access/Refresh Token 发布期间保留短期旧 Bearer Token 兼容开关；仅在确认新前端稳定后关闭。
- Redis 对话会话迁移期间可保留进程内 Store 实现作为开发回退，但生产不得在 Redis 故障时自动退回不安全的多实例内存共享假设。
- 回滚应用版本时不恢复已撤销的 Refresh Session，不回滚 token_version，不重新启用已失效凭证。
- 密钥轮换一旦执行不回退到旧密钥；必要时再次轮换新密钥并要求重新登录。

## 完成定义

本计划只有在以下条件全部满足时才算完成：

- [ ] 生产启动配置不存在占位密钥、默认管理员凭证或验证码回传。
- [ ] 所有临时会话均绑定用户，并通过双用户越权测试。
- [ ] 用户和管理员登录、验证码发送与校验均有 Redis 原子限流。
- [ ] 前端不再将用户或管理员长期凭证写入 `localStorage`。
- [ ] Refresh Token 可轮换、可撤销，并能检测重放。
- [ ] 改密、停用、强制下线和登出能够撤销相应用户或管理员的全部会话。
- [ ] 多实例环境下临时对话状态一致且不会跨用户泄漏。
- [ ] PostgreSQL 使用连接池，Redis 仅通过受控内网访问。
- [ ] 单元测试、API 集成测试、端到端测试和故障测试全部通过。
- [ ] 上线监控、审计、告警和回滚手册完成并经过演练。
