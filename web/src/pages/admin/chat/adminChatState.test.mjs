import assert from 'node:assert/strict'
import test from 'node:test'
import { agentTranscriptEvents, branchOriginLabel, flattenBranchTree } from './adminChatState.ts'

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
