import assert from 'node:assert/strict'
import test from 'node:test'
import { createSseParser } from './generationStream.ts'

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
