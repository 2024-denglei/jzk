# 分支化 AI 对话存储与加载架构

## 权威数据关系

`app.chats` 只保存会话级摘要和活跃分支；`app.chat_branches` 保存分支拓扑；
`app.chat_messages` 保存终态不可修改的消息父链和每个节点之后的可恢复状态。只有用户明确回溯
继续或并发旧头发送才创建可见分支。编辑用户消息会原子切换当前分支 head，并删除不再被任何
显式分支引用的旧消息、生成记录和排名快照；如果旧路径仍被其他显式分支引用，则该分支保持不变。
客户端和管理端都不展示编辑版本历史，“重新生成 AI 回复”命令已经移除。

AI 消息通过 `chat_messages.match_run_id` 关联 `app.match_runs`。完整排名、当时允许展示的供体资料
和匹配解释按 rank 存在 `app.match_run_items`，因此加载任意历史 AI 消息都能复现完整冻结快照，
不依赖供体当前资料，也不依赖 Redis。

生成由 `app.ai_generation_runs` 持久排队，Generation Worker 领取、续租、重试并更新 AI 消息；
每一步 Trace 写入 `app.ai_generation_steps`。其中 `agent_message` 按真实请求顺序保存经密钥脱敏的
System、User、Assistant、Tool Call 和 Tool Result，供有用户查看权限的管理端还原当时实际提交给
模型的上下文；候选人详情仍只通过工具结果中的 `result_set_id` 关联冻结排名快照，不复制进 Trace。
Redis Stream 只用于 token/event 实时推送和断线续传，
Outbox 负责会话硬删除或当前线路编辑后的 Stream 与孤立排名快照清理。

## 客户端加载

1. `GET /api/chats` 使用 `(updated_at, id)` 签名游标加载会话摘要，不读取消息正文。
2. `GET /api/chats/{chat_id}` 加载完整分支拓扑，不加载每个分支的全部消息。
3. `GET /api/chats/{chat_id}/branches/{branch_id}/messages` 沿选定 head 的父链分页加载。
4. 仅当用户展开排名时，`GET /api/messages/{message_id}/match-results` 分页加载冻结快照。
5. 生成中通过 generation event Stream 重连；刷新页面后仍可从 PostgreSQL 恢复任务和消息状态。

查看其他分支不会改变 `active_branch_id`；只有在该路径发送新 Turn 后才更新活跃分支。整个会话
必须带 `confirm_irreversible=true` 和幂等 `request_id` 才能立即硬删除，删除后不可恢复。
创建分支和打开已有分支都在 AI 助手内部使用线路标签页；根线路固定为“主线”，其他线路按
创建顺序显示为“分支1、分支2……”。切换标签加载对应分支路径，关闭标签只关闭客户端视图，
不会删除数据库分支；待创建标签提交第一条消息后才原子写入分支树。分支点只能是状态可恢复的
已完成 AI 消息，不能选用户消息、生成中、已停止或失败消息。候选人工具结果与 AI 文本共用同一条
assistant 消息并由 `match_run_id` 绑定，因此前端把分支入口放在候选人结果之后，后端将二者作为
不可拆分的完整回复单元校验。

## 管理端加载

管理端使用 `/api/admin/users/{user_id}/conversations` 下的同构接口和同一查询服务加载列表、
分支树与消息路径。它可从根到叶看到显式分叉原因和每条当前线路；用户编辑只呈现修改后的
当前内容，不形成伪分支。会话列表使用 `Session #{chat.id}` 作为稳定标题。完整排名按消息懒加载，
数据库 Trace 按 generation 懒加载，并按真实 Agent 消息顺序展示。每次敏感读取写入管理审计，审计只保存资源定位和分页参数，
不复制消息、排名或 Trace 正文。

## 已移除的兼容结构

- `app.chats.session_id/messages_json/candidates_json/state_json`
- `app.match_runs.donor_ids/scores`
- `/api/chat*`、`/api/user/chats*` 和旧管理端线性会话接口
- Redis 临时 Session、Redis 排名结果兼容 key
- 本地 JSON Trace 代码、配置和文件

当前 API、客户端和管理端只支持 `storage_version=2`。
