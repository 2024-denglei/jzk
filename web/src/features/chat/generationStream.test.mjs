import assert from 'node:assert/strict'
import test from 'node:test'
import { createSseParser, generationProgressFromEvent } from './generationStream.ts'

test('SSE 解析器支持拆包、多行 data 和事件 ID', () => {
  const events = []
  const parser = createSseParser((event) => events.push(event))
  parser.push('id: 10-1\nevent: token\ndata: {"te')
  parser.push('xt":"你"}\n\nid: 10-2\nevent: meta\ndata: first\n')
  parser.push('data: second\n\n: keepalive\n\n')
  parser.finish()

  assert.deepEqual(events[0], { id: '10-1', event: 'token', data: { text: '你' } })
  assert.deepEqual(events[1], { id: '10-2', event: 'meta', data: { text: 'first\nsecond' } })
})

test('生成事件请求短暂断网后自动重连到终态', async () => {
  globalThis.window = {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    dispatchEvent() {},
  }
  let attempts = 0
  globalThis.fetch = async () => {
    attempts += 1
    if (attempts === 1) throw new TypeError('temporary network error')
    return new Response('event: completed\ndata: {"status":"completed"}\n\n', {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })
  }
  const { followGeneration } = await import('./generationStream.ts')
  const reconnects = []
  const status = await followGeneration('generation-1', {
    signal: new AbortController().signal,
    onEvent() {},
    onReconnect: (attempt) => reconnects.push(attempt),
  })
  assert.equal(status, 'completed')
  assert.equal(attempts, 2)
  assert.deepEqual(reconnects, [1])
})

test('Agent 事件映射为消息区域的真实运行阶段', () => {
  assert.deepEqual(generationProgressFromEvent({ event: 'generation_status', id: null, data: { status: 'queued' } }), { stage: 'queued' })
  assert.deepEqual(generationProgressFromEvent({ event: 'agent_stage', id: '1', data: { stage: 'tool_call', tool_name: 'submit_preference_profile' } }), { stage: 'tool_call', detail: 'submit_preference_profile' })
  assert.deepEqual(generationProgressFromEvent({ event: 'match_ready', id: '2', data: { total: 359 } }), { stage: 'tool_result', count: 359 })
  assert.deepEqual(generationProgressFromEvent({ event: 'token', id: '3', data: { text: '正在回复' } }), { stage: 'responding' })
})
