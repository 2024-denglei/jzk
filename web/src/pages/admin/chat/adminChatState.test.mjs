import assert from 'node:assert/strict'
import test from 'node:test'
import { agentTranscriptEvents, branchOriginLabel, finalAgentContextEvents, flattenBranchTree, latestAssistantMessage, layoutHorizontalBranchTree } from './adminChatState.ts'

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

test('线路上下文只取最后一轮生成，前几轮不再各自重复渲染完整输入', () => {
  const selected = latestAssistantMessage([
    { id: 'user-1', role: 'user', depth: 0 },
    { id: 'assistant-1', role: 'assistant', depth: 1 },
    { id: 'user-2', role: 'user', depth: 2 },
    { id: 'assistant-2', role: 'assistant', depth: 3 },
  ])

  assert.equal(selected?.id, 'assistant-2')
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
