# 对话中止与消息回溯

## 决策

- 生成中再次点击发送 → 中止；本轮用户消息与模型回复不进入历史
- 回溯语义 A：保留点击的消息及之前，删除之后；恢复该节点筛选条件快照

## 实现要点

- 前端 AbortController；发送中按钮变为停止
- 后端本轮 checkpoint，断开则回滚且不 persist
- 每轮完成后消息带 `parsed_features` 快照；`POST /api/chat/rewind` 截断服务端会话
