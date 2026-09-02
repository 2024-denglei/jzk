import assert from 'node:assert/strict'
import test from 'node:test'
import { agentTranscriptEvents, branchOriginLabel, feedbackDetailPath, finalAgentContextEvents, flattenBranchTree, latestSystemContextEvent, layoutHorizontalBranchTree, turnExecutionEvents } from './adminChatState.ts'

test('反馈详情链接精确携带用户、Session、分支和消息', () => {
  assert.equal(
    feedbackDetailPath({ user_id: 7, chat_id: 355, branch_id: 'branch-1', message_id: 'message-9' }),
    '/admin/users/7?tab=chats&chat_id=355&branch_id=branch-1&message_id=message-9',
  )
})

const makeBranch = (id, parent, reason) => ({
  id, parent_branch_id: parent, fork_reason: reason, name: id,
  created_at: '2026-01-01', updated_at: '2026-01-01',
})

test('管理端分支树按父子层级展示并保留每种分叉原因', () => {
  const root = makeBranch('root', null, 'root')
  const rewind = makeBranch('rewind', 'root', 'rewind_continue')
  const edit = makeBranch('edit', 'rewind', 'edit_resend')
  const concurrent = makeBranch('parallel', 'root', 'concurrent_send')
  const rows = flattenBranchTree([edit, concurrent, root, rewind])

  assert.deepEqual(rows.map((row) => [row.branch.id, row.depth]), [
    ['root', 0], ['parallel', 1], ['rewind', 1], ['edit', 2],
  ])
  assert.equal(branchOriginLabel(rewind), '用户回溯后继续')
  assert.equal(branchOriginLabel(concurrent), '多窗口并发发送形成分支')
})

test('Agent 转录只按数据库真实 agent_message 步骤组装', () => {
  const events = agentTranscriptEvents([
    { id: 1, step_order: 0, step_type: 'generation_claimed', payload_json: {}, created_at: 't0' },
    { id: 2, step_order: 1, step_type: 'agent_message', created_at: 't1', payload_json: {
      role: 'system', phase: 'input_context', text: '系统提示词', attempt_count: 1,
    } },
    { id: 3, step_order: 2, step_type: 'agent_message', created_at: 't2', payload_json: {
      role: 'assistant', phase: 'tool_call', text: '', tool_calls: [
        { id: 'call-1', name: 'submit_preference_profile', arguments_text: '{"height":175}' },
      ],
    } },
    { id: 4, step_order: 3, step_type: 'agent_message', created_at: 't3', payload_json: {
      role: 'tool', phase: 'tool_result', text: '{"ok":true}', result_set_id: 'snapshot-1', count: 12,
    } },
  ])

  assert.deepEqual(events.map((event) => [event.role, event.phase]), [
    ['system', 'input_context'], ['assistant', 'tool_call'], ['tool', 'tool_result'],
  ])
  assert.equal(events[1].toolCalls[0].name, 'submit_preference_profile')
  assert.equal(events[2].resultSetId, 'snapshot-1')
  assert.equal(events[2].count, 12)
})

test('完整上下文只展示最终生成尝试，避免重试导致系统提示词和历史消息重复', () => {
  const events = finalAgentContextEvents([
    { id: 1, step_order: 1, step_type: 'agent_message', created_at: 't1', payload_json: {
      role: 'system', phase: 'input_context', text: '旧 System', attempt_count: 1,
    } },
    { id: 2, step_order: 2, step_type: 'agent_message', created_at: 't2', payload_json: {
      role: 'user', phase: 'input_context', text: '旧 User', attempt_count: 1,
    } },
    { id: 3, step_order: 3, step_type: 'agent_message', created_at: 't3', payload_json: {
      role: 'system', phase: 'input_context', text: '最终 System', attempt_count: 2,
    } },
    { id: 4, step_order: 4, step_type: 'agent_message', created_at: 't4', payload_json: {
      role: 'user', phase: 'input_context', text: '最终 User', attempt_count: 2,
    } },
    { id: 5, step_order: 5, step_type: 'agent_message', created_at: 't5', payload_json: {
      role: 'assistant', phase: 'final', text: '最终回复', attempt_count: 2,
    } },
  ])

  assert.deepEqual(events.map((event) => event.text), ['最终 System', '最终 User', '最终回复'])
  assert.equal(events.filter((event) => event.role === 'system').length, 1)
})

test('缺少重试编号的旧转录也只从最后一条系统提示词开始展示', () => {
  const events = finalAgentContextEvents([
    { id: 1, step_order: 1, step_type: 'agent_message', created_at: 't1', payload_json: {
      role: 'system', phase: 'input_context', text: '第一次 System',
    } },
    { id: 2, step_order: 2, step_type: 'agent_message', created_at: 't2', payload_json: {
      role: 'user', phase: 'input_context', text: '第一次 User',
    } },
    { id: 3, step_order: 3, step_type: 'agent_message', created_at: 't3', payload_json: {
      role: 'system', phase: 'input_context', text: '最终 System',
    } },
    { id: 4, step_order: 4, step_type: 'agent_message', created_at: 't4', payload_json: {
      role: 'user', phase: 'input_context', text: '最终 User',
    } },
  ])

  assert.deepEqual(events.map((event) => event.text), ['最终 System', '最终 User'])
})

test('完整线路保留每一轮工具执行，但系统提示词只选最新版本一次', () => {
  const first = [
    { id: 1, step_order: 1, step_type: 'agent_message', created_at: 't1', payload_json: {
      role: 'system', phase: 'input_context', text: 'System v1', attempt_count: 1,
    } },
    { id: 2, step_order: 2, step_type: 'agent_message', created_at: 't2', payload_json: {
      role: 'user', phase: 'input_context', text: '第一问', attempt_count: 1,
    } },
    { id: 3, step_order: 3, step_type: 'agent_message', created_at: 't3', payload_json: {
      role: 'assistant', phase: 'tool_call', text: '执行第一次工具', attempt_count: 1,
      tool_calls: [{ id: 'call-1', name: 'match', arguments_text: '{}' }],
    } },
    { id: 4, step_order: 4, step_type: 'agent_message', created_at: 't4', payload_json: {
      role: 'tool', phase: 'tool_result', text: '{"count":10}', attempt_count: 1,
    } },
    { id: 5, step_order: 5, step_type: 'agent_message', created_at: 't5', payload_json: {
      role: 'assistant', phase: 'final', text: '第一次回复', attempt_count: 1,
    } },
  ]
  const second = [
    { id: 6, step_order: 1, step_type: 'agent_message', created_at: 't6', payload_json: {
      role: 'system', phase: 'input_context', text: 'System v2', attempt_count: 1,
    } },
    { id: 7, step_order: 2, step_type: 'agent_message', created_at: 't7', payload_json: {
      role: 'user', phase: 'input_context', text: '第一问', attempt_count: 1,
    } },
    { id: 8, step_order: 3, step_type: 'agent_message', created_at: 't8', payload_json: {
      role: 'assistant', phase: 'input_context', text: '第一次回复', attempt_count: 1,
    } },
    { id: 9, step_order: 4, step_type: 'agent_message', created_at: 't9', payload_json: {
      role: 'user', phase: 'input_context', text: '第二问', attempt_count: 1,
    } },
    { id: 10, step_order: 5, step_type: 'agent_message', created_at: 't10', payload_json: {
      role: 'assistant', phase: 'tool_call', text: '执行第二次工具', attempt_count: 1,
      tool_calls: [{ id: 'call-2', name: 'match', arguments_text: '{}' }],
    } },
    { id: 11, step_order: 6, step_type: 'agent_message', created_at: 't11', payload_json: {
      role: 'tool', phase: 'tool_result', text: '{"count":5}', attempt_count: 1,
    } },
    { id: 12, step_order: 7, step_type: 'agent_message', created_at: 't12', payload_json: {
      role: 'assistant', phase: 'final', text: '第二次回复', attempt_count: 1,
    } },
  ]

  const executions = [...turnExecutionEvents(first), ...turnExecutionEvents(second)]
  assert.equal(executions.filter((event) => event.phase === 'tool_call').length, 2)
  assert.equal(executions.filter((event) => event.phase === 'tool_result').length, 2)
  assert.deepEqual(executions.filter((event) => event.phase === 'final').map((event) => event.text), ['第一次回复', '第二次回复'])
  assert.equal(latestSystemContextEvent([first, second])?.text, 'System v2')
})

test('横向分支树按深度向右展开并让父节点位于子节点中间', () => {
  const root = makeBranch('root', null, 'root')
  const one = makeBranch('one', 'root', 'rewind_continue')
  const two = makeBranch('two', 'root', 'rewind_continue')
  const nested = makeBranch('nested', 'one', 'rewind_continue')
  const layout = layoutHorizontalBranchTree([root, one, two, nested])
  const byId = new Map(layout.nodes.map((node) => [node.branch.id, node]))

  assert.equal(byId.get('root').depth, 0)
  assert.equal(byId.get('one').depth, 1)
  assert.equal(byId.get('nested').depth, 2)
  assert.ok(byId.get('root').x < byId.get('one').x)
  assert.ok(byId.get('one').x < byId.get('nested').x)
  assert.equal(layout.edges.length, 3)
  assert.ok(byId.get('root').y > Math.min(byId.get('one').y, byId.get('two').y))
  assert.ok(layout.width >= 678)
})

test('仅主线时画布不强制留出大块空白', () => {
  const layout = layoutHorizontalBranchTree([makeBranch('root', null, 'root')])
  assert.equal(layout.nodes.length, 1)
  assert.equal(layout.edges.length, 0)
  assert.ok(layout.width < 420)
  assert.ok(layout.width >= 170)
})
