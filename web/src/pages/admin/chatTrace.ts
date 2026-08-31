import type { ChatTraceStep, ChatTurnTrace } from './types'

const STEP_LABELS: Record<string, string> = {
  turn_start: 'Turn 开始',
  llm_request: 'LLM 请求',
  llm_response: 'LLM 响应',
  tool_call: '工具调用',
  timing: '阶段耗时',
  tool_retry: '工具重试',
  mock_agent: '模拟代理',
  summarize_fallback: '总结降级',
  reply_count_corrected: '结果数校正',
}

const PHASE_LABELS: Record<string, string> = {
  tool_select: '工具选择',
  summarize: '结果总结',
}

const STAGE_LABELS: Record<string, string> = {
  llm_tool_select: 'LLM 工具选择',
  match: '匹配查询',
  apply_match_response: '应用匹配结果',
  llm_summarize: 'LLM 结果总结',
  sse_candidates: '候选结果推送',
  persist: '会话持久化',
  total: 'Turn 总耗时',
}

export function traceStepLabel(step: ChatTraceStep) {
  const base = STEP_LABELS[step.type] || step.type || '未知步骤'
  const detail = step.type === 'timing'
    ? STAGE_LABELS[String(step.stage || '')] || step.stage
    : step.type.startsWith('llm_')
      ? PHASE_LABELS[String(step.phase || '')] || step.phase
      : step.type === 'tool_call'
        ? step.name
        : undefined
  return detail ? `${base} · ${detail}` : base
}

export function summarizeTraces(turns: ChatTurnTrace[]) {
  const models = new Set<string>()
  let stepCount = 0
  let toolCallCount = 0
  let totalMs = 0
  let errorCount = 0
  for (const turn of turns) {
    if (turn.model) models.add(turn.model)
    stepCount += turn.steps?.length || 0
    toolCallCount += (turn.steps || []).filter((step) => step.type === 'tool_call').length
    const turnTotal = Number(turn.timings?.total || 0)
    if (Number.isFinite(turnTotal)) totalMs += turnTotal
    if (turn.error) errorCount += 1
  }
  return { turnCount: turns.length, stepCount, toolCallCount, totalMs, errorCount, models: [...models] }
}

export function formatDuration(ms?: number | null) {
  if (ms === undefined || ms === null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)} s`
}

export function stepPayload(step: ChatTraceStep) {
  const { type: _type, ts: _ts, ...payload } = step
  return payload
}
