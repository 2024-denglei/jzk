import assert from 'node:assert/strict'
import test from 'node:test'
import { formatDuration, stepPayload, summarizeTraces, traceStepLabel } from './chatTrace.ts'

test('会话 Trace 汇总 Turn、步骤、工具调用和耗时', () => {
  const summary = summarizeTraces([
    { trace_id: 't1', session_id: 's1', started_at: 'now', model: 'deepseek', timings: { total: 1200 }, error: null, steps: [{ type: 'turn_start' }, { type: 'tool_call', name: 'search' }] },
    { trace_id: 't2', session_id: 's1', started_at: 'later', model: 'deepseek', timings: { total: 800 }, error: 'failed', steps: [{ type: 'llm_response' }] },
  ])
  assert.deepEqual(summary, { turnCount: 2, stepCount: 3, toolCallCount: 1, totalMs: 2000, errorCount: 1, models: ['deepseek'] })
})

test('Trace 步骤和耗时使用可读文本', () => {
  assert.equal(traceStepLabel({ type: 'tool_call', name: 'submit_preference_profile' }), '工具调用 · submit_preference_profile')
  assert.equal(traceStepLabel({ type: 'timing', stage: 'match' }), '阶段耗时 · 匹配查询')
  assert.equal(formatDuration(525.8), '526 ms')
  assert.equal(formatDuration(9911.6), '9.91 s')
})

test('原始 payload 不重复包含步骤类型和时间', () => {
  assert.deepEqual(stepPayload({ type: 'timing', ts: 'now', stage: 'match', elapsed_ms: 10 }), { stage: 'match', elapsed_ms: 10 })
})
