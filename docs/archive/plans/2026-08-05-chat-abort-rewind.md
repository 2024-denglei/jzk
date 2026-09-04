# 对话中止与回溯 Implementation Plan

**Goal:** 支持流式生成中止（不落库）与按消息回溯（保留该条及之前）。

**Architecture:** 前端 AbortController + 消息快照；后端 turn checkpoint / rewind API。

### Task 1: Session checkpoint + rewind API
### Task 2: chat_stream 断开回滚
### Task 3: ChatPanel 停止发送 + 回溯 UI
