import { formatDuration, stepPayload, summarizeTraces, traceStepLabel } from './chatTrace'
import { formatTime } from './adminFormat'
import type { ChatDetail, ChatMessage, ChatTraceStep, ChatTurnTrace } from './types'

export function ChatTraceView({ chat }: { chat: ChatDetail }) {
  const turns = chat.turns || []
  const summary = summarizeTraces(turns)

  return (
    <div className="flex h-full min-h-[620px] flex-col bg-[#f6f8fb]">
      <header className="border-b border-[#dfe6ef] bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#1677ff]">
              <i className="ri-node-tree" />Session Trace
            </div>
            <div className="mt-1 break-all font-mono text-sm font-semibold text-[#21324a]">{chat.session_id}</div>
            <div className="mt-1 text-[10px] text-[#8b97a8]">创建于 {formatTime(chat.created_at)} · 更新于 {formatTime(chat.updated_at)}</div>
          </div>
          {turns.length ? (
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              <MetaBadge label={`${summary.turnCount} Turns`} />
              <MetaBadge label={`${summary.stepCount} Steps`} />
              <MetaBadge label={`${summary.toolCallCount} 次工具调用`} tone="blue" />
              <MetaBadge label={formatDuration(summary.totalMs)} tone={summary.errorCount ? 'red' : 'green'} />
            </div>
          ) : null}
        </div>
        {summary.models.length ? <div className="mt-2 text-[10px] text-[#778499]">模型：<span className="font-mono text-[#45546a]">{summary.models.join(', ')}</span></div> : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
        {turns.length ? (
          <div className="space-y-5">
            {turns.map((turn, index) => <TurnCard key={turn.trace_id || `${turn.started_at}-${index}`} turn={turn} index={index} />)}
          </div>
        ) : (
          <FallbackConversation messages={chat.messages} />
        )}
      </div>
    </div>
  )
}

function TurnCard({ turn, index }: { turn: ChatTurnTrace; index: number }) {
  const toolCount = (turn.steps || []).filter((step) => step.type === 'tool_call').length
  return (
    <section className="overflow-hidden rounded-xl border border-[#dce4ee] bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
      <div className="border-b border-[#e5ebf2] bg-[#fbfcfe] px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 gap-3">
            <div className="flex h-9 min-w-9 items-center justify-center rounded-lg bg-[#e8f2ff] font-mono text-xs font-semibold text-[#1677ff]">T{index + 1}</div>
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#7c899b]">Turn {index + 1}</div>
              <div className="mt-1 text-sm font-medium leading-5 text-[#27374e]">{turn.user_message || '（无用户输入）'}</div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            <MetaBadge label={`${turn.steps?.length || 0} Steps`} />
            {toolCount ? <MetaBadge label={`${toolCount} Tools`} tone="blue" /> : null}
            <MetaBadge label={formatDuration(turn.timings?.total)} tone={turn.error ? 'red' : 'green'} />
          </div>
        </div>
        <div className="mt-3 grid gap-1.5 border-t border-[#edf1f5] pt-2 text-[10px] text-[#8a96a7] sm:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 break-all">Trace ID：<span className="font-mono text-[#56657a]">{turn.trace_id}</span></div>
          <div>{formatTime(turn.started_at)}{turn.model ? ` · ${turn.model}` : ''}</div>
        </div>
      </div>

      {turn.error ? <div className="border-b border-red-100 bg-red-50 px-5 py-3 text-xs text-red-700"><i className="ri-error-warning-line mr-1" />{turn.error}</div> : null}

      <div className="px-4 py-4 sm:px-5">
        <div className="relative space-y-0 before:absolute before:bottom-4 before:left-[15px] before:top-4 before:w-px before:bg-[#dce5ef]">
          {(turn.steps || []).map((step, stepIndex) => <TraceStepRow key={`${step.type}-${step.ts || stepIndex}-${stepIndex}`} step={step} index={stepIndex} />)}
        </div>
        {!turn.steps?.length ? <div className="py-6 text-center text-xs text-[#9aa5b5]">该 Turn 没有保存 Trace Step</div> : null}
      </div>

      {(turn.parsed_features && Object.keys(turn.parsed_features).length) || (turn.constraints && Object.keys(turn.constraints).length) ? (
        <div className="grid gap-3 border-t border-[#e8edf3] bg-[#fafbfd] px-4 py-4 sm:grid-cols-2 sm:px-5">
          {turn.parsed_features && Object.keys(turn.parsed_features).length ? <PayloadPanel title="最终偏好画像" data={turn.parsed_features} /> : null}
          {turn.constraints && Object.keys(turn.constraints).length ? <PayloadPanel title="最终约束" data={turn.constraints} /> : null}
        </div>
      ) : null}

      {turn.final_reply ? (
        <div className="border-t border-[#e5ebf2] px-4 py-4 sm:px-5">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#68768a]"><i className="ri-chat-3-line text-[#1677ff]" />最终回复</div>
          <div className="whitespace-pre-wrap rounded-lg border border-[#dfe7f0] bg-[#f8fafc] px-3 py-2.5 text-xs leading-5 text-[#425168]">{turn.final_reply}</div>
        </div>
      ) : null}
    </section>
  )
}

function TraceStepRow({ step, index }: { step: ChatTraceStep; index: number }) {
  const visual = stepVisual(step)
  return (
    <div className="relative grid grid-cols-[32px_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
      <div className={`relative z-10 flex h-8 w-8 items-center justify-center rounded-full border ${visual.circle}`}>
        <i className={visual.icon} />
      </div>
      <div className="min-w-0 pt-0.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-xs font-semibold text-[#304159]">{traceStepLabel(step)}</div>
            <div className="mt-0.5 text-[10px] text-[#9aa5b5]">Step {index + 1}{step.ts ? ` · ${formatTime(step.ts)}` : ''}</div>
          </div>
          {typeof step.elapsed_ms === 'number' ? <span className="rounded bg-[#f0f4f8] px-2 py-1 font-mono text-[10px] text-[#627086]">{formatDuration(step.elapsed_ms)}</span> : null}
        </div>
        <StepContent step={step} />
      </div>
    </div>
  )
}

function StepContent({ step }: { step: ChatTraceStep }) {
  if (step.type === 'llm_request') {
    return (
      <div className="mt-2 rounded-lg border border-[#e1e7ef] bg-[#fbfcfe] p-3">
        <div className="flex flex-wrap gap-3 text-[10px] text-[#778499]"><span>模型：<b className="font-mono font-medium text-[#49586d]">{step.model || '—'}</b></span><span>上下文：<b className="font-medium text-[#49586d]">{step.messages?.length || 0} 条消息</b></span></div>
        <details className="mt-2">
          <summary className="cursor-pointer text-[11px] font-medium text-[#1677ff]">查看完整消息上下文</summary>
          <MessageContext messages={step.messages || []} />
        </details>
      </div>
    )
  }
  if (step.type === 'llm_response') {
    return (
      <div className="mt-2 space-y-2">
        {step.content ? <div className="whitespace-pre-wrap rounded-lg border border-[#dfe7f0] bg-[#fbfcfe] px-3 py-2.5 text-[11px] leading-5 text-[#4a596e]">{step.content}</div> : null}
        {Array.isArray(step.tool_calls) && step.tool_calls.length ? <PayloadPanel title="LLM 返回的工具调用" data={step.tool_calls} /> : null}
      </div>
    )
  }
  if (step.type === 'tool_call') {
    return (
      <div className="mt-2 grid gap-3 xl:grid-cols-2">
        <PayloadPanel title="调用参数" data={step.arguments} accent="blue" />
        <PayloadPanel title="工具结果" data={step.result} accent="green" />
      </div>
    )
  }
  if (step.type === 'timing') {
    const metrics = Object.entries(stepPayload(step)).filter(([key]) => !['stage', 'elapsed_ms'].includes(key))
    return metrics.length ? (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {metrics.map(([key, value]) => <span key={key} className="rounded-md border border-[#e1e7ef] bg-[#fafbfd] px-2 py-1 font-mono text-[10px] text-[#647287]">{key}: {formatCompact(value)}</span>)}
      </div>
    ) : null
  }
  return <div className="mt-2"><PayloadPanel title="步骤详情" data={stepPayload(step)} /></div>
}

function MessageContext({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="mt-2 space-y-2">
      {messages.map((message, index) => (
        <div key={`${message.role || 'unknown'}-${index}`} className="overflow-hidden rounded-lg border border-[#e2e8f0] bg-white">
          <div className="border-b border-[#edf1f5] bg-[#f7f9fc] px-3 py-1.5 font-mono text-[10px] uppercase text-[#68768a]">{message.role || 'unknown'}</div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-3 py-2 text-[10px] leading-4 text-[#526177]">{message.content || '（空内容）'}</pre>
          {message.tool_calls ? <div className="border-t border-[#edf1f5] p-2"><PayloadPanel title="tool_calls" data={message.tool_calls} /></div> : null}
        </div>
      ))}
    </div>
  )
}

function PayloadPanel({ title, data, accent = 'slate' }: { title: string; data: unknown; accent?: 'slate' | 'blue' | 'green' }) {
  const colors = {
    slate: 'border-[#e1e7ef] bg-[#f8fafc] text-[#68768a]',
    blue: 'border-blue-100 bg-blue-50/50 text-blue-700',
    green: 'border-emerald-100 bg-emerald-50/50 text-emerald-700',
  }
  return (
    <div className={`min-w-0 overflow-hidden rounded-lg border ${colors[accent]}`}>
      <div className="border-b border-current/10 px-3 py-1.5 text-[10px] font-semibold">{title}</div>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-white/70 px-3 py-2 text-[10px] leading-4 text-[#4c5b70]">{stringify(data)}</pre>
    </div>
  )
}

function FallbackConversation({ messages }: { messages: ChatMessage[] }) {
  return (
    <div>
      <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700"><i className="ri-information-line mr-1" />该历史会话没有结构化 Trace，以下展示数据库中保留的消息。</div>
      <div className="space-y-3">
        {messages.map((message, index) => {
          const user = message.role === 'user'
          return <div key={`${message.role}-${index}`} className={`rounded-xl border p-4 ${user ? 'border-blue-100 bg-blue-50/60' : 'border-[#e1e7ef] bg-white'}`}><div className="text-[10px] font-semibold uppercase tracking-wider text-[#7b8798]">{user ? 'User' : 'Assistant'} · Message {index + 1}</div><div className="mt-2 whitespace-pre-wrap text-xs leading-5 text-[#3f4f65]">{message.content || '（空消息）'}</div></div>
        })}
        {!messages.length ? <div className="py-20 text-center text-sm text-[#9aa5b5]">该会话没有已保存的消息或 Trace</div> : null}
      </div>
    </div>
  )
}

function MetaBadge({ label, tone = 'slate' }: { label: string; tone?: 'slate' | 'blue' | 'green' | 'red' }) {
  const colors = { slate: 'bg-[#f0f4f8] text-[#617087]', blue: 'bg-blue-50 text-blue-700', green: 'bg-emerald-50 text-emerald-700', red: 'bg-red-50 text-red-700' }
  return <span className={`rounded-md px-2 py-1 font-medium ${colors[tone]}`}>{label}</span>
}

function stepVisual(step: ChatTraceStep) {
  if (step.type === 'tool_call') return { icon: 'ri-tools-line', circle: 'border-blue-200 bg-blue-50 text-blue-600' }
  if (step.type === 'llm_request') return { icon: 'ri-arrow-right-up-line', circle: 'border-violet-200 bg-violet-50 text-violet-600' }
  if (step.type === 'llm_response') return { icon: 'ri-brain-line', circle: 'border-indigo-200 bg-indigo-50 text-indigo-600' }
  if (step.type === 'timing') return { icon: 'ri-timer-line', circle: 'border-amber-200 bg-amber-50 text-amber-600' }
  if (step.type.includes('error') || step.type.includes('retry')) return { icon: 'ri-error-warning-line', circle: 'border-red-200 bg-red-50 text-red-600' }
  return { icon: 'ri-git-commit-line', circle: 'border-slate-200 bg-slate-50 text-slate-600' }
}

function stringify(value: unknown) {
  if (value === undefined) return '—'
  if (typeof value === 'string') return value || '（空字符串）'
  try { return JSON.stringify(value, null, 2) }
  catch { return String(value) }
}

function formatCompact(value: unknown) {
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(1)
  if (typeof value === 'string') return value
  return stringify(value).replace(/\s+/g, ' ').slice(0, 120)
}
