import type { ChatBranchSummary } from '../../../types'

export type BranchTreeRow = { branch: ChatBranchSummary; depth: number }

export type AgentTranscriptRole = 'system' | 'user' | 'assistant' | 'tool'

export type AgentToolCall = {
  id: string
  name: string
  argumentsText: string
}

export type AgentTranscriptEvent = {
  id: number
  order: number
  role: AgentTranscriptRole
  phase: string
  text: string
  sourceMessageId: string | null
  toolCalls: AgentToolCall[]
  toolName: string | null
  toolCallId: string | null
  resultSetId: string | null
  count: number | null
  attemptCount: number | null
  createdAt: string
}

type TraceStepLike = {
  id: number
  step_order: number
  step_type: string
  payload_json: Record<string, unknown>
  created_at: string
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function agentTranscriptEvents(steps: TraceStepLike[]): AgentTranscriptEvent[] {
  const roles = new Set<AgentTranscriptRole>(['system', 'user', 'assistant', 'tool'])
  return steps.flatMap((step) => {
    if (step.step_type !== 'agent_message') return []
    const payload = step.payload_json || {}
    const role = stringValue(payload.role) as AgentTranscriptRole
    if (!roles.has(role)) return []
    const toolCalls = Array.isArray(payload.tool_calls)
      ? payload.tool_calls.flatMap((value) => {
        if (!value || typeof value !== 'object') return []
        const call = value as Record<string, unknown>
        return [{
          id: stringValue(call.id),
          name: stringValue(call.name),
          argumentsText: stringValue(call.arguments_text),
        }]
      })
      : []
    return [{
      id: step.id,
      order: step.step_order,
      role,
      phase: stringValue(payload.phase),
      text: stringValue(payload.text),
      sourceMessageId: stringValue(payload.source_message_id) || null,
      toolCalls,
      toolName: stringValue(payload.tool_name) || null,
      toolCallId: stringValue(payload.tool_call_id) || null,
      resultSetId: stringValue(payload.result_set_id) || null,
      count: typeof payload.count === 'number' ? payload.count : null,
      attemptCount: typeof payload.attempt_count === 'number' ? payload.attempt_count : null,
      createdAt: step.created_at,
    }]
  })
}

export function flattenBranchTree(branches: ChatBranchSummary[]): BranchTreeRow[] {
  const children = new Map<string | null, ChatBranchSummary[]>()
  for (const branch of branches) {
    const siblings = children.get(branch.parent_branch_id) || []
    siblings.push(branch)
    children.set(branch.parent_branch_id, siblings)
  }
  const rows: BranchTreeRow[] = []
  const visited = new Set<string>()
  function visit(parentId: string | null, depth: number) {
    for (const branch of children.get(parentId) || []) {
      if (visited.has(branch.id)) continue
      visited.add(branch.id)
      rows.push({ branch, depth })
      visit(branch.id, depth + 1)
    }
  }
  visit(null, 0)
  for (const branch of branches) {
    if (!visited.has(branch.id)) rows.push({ branch, depth: 0 })
  }
  return rows
}

export function branchOriginLabel(branch: ChatBranchSummary): string {
  const labels: Record<ChatBranchSummary['fork_reason'], string> = {
    root: '根分支',
    rewind_continue: '用户回溯后继续',
    edit_resend: '用户编辑消息后重发',
    regenerate: '用户重新生成 AI 回复',
    concurrent_send: '多窗口并发发送形成分支',
  }
  return labels[branch.fork_reason]
}
