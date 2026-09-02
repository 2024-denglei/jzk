import assert from 'node:assert/strict'
import test from 'node:test'
import { buildTurnCommand } from './chatActions.ts'

test('追加、回溯和编辑重发保留正确的父节点语义', () => {
  const base = { selectedBranchId: 'branch-1', branchHeadMessageId: 'head-1', content: ' 新消息 ', requestId: 'request-1' }
  assert.deepEqual(buildTurnCommand(base), {
    branch_id: 'branch-1', parent_message_id: 'head-1', action: 'append',
    derived_from_message_id: null, content: '新消息', client_request_id: 'request-1',
  })
  assert.equal(buildTurnCommand({ ...base, pending: {
    action: 'rewind_continue', parentMessageId: 'old-2', label: '回溯',
  } }).parent_message_id, 'old-2')
  const edited = buildTurnCommand({ ...base, pending: {
    action: 'edit_resend', parentMessageId: 'old-0', derivedFromMessageId: 'old-1', label: '编辑',
  } })
  assert.equal(edited.action, 'edit_resend')
  assert.equal(edited.derived_from_message_id, 'old-1')
  assert.equal(edited.parent_message_id, 'old-0')
})

test('编辑首条用户消息时父节点保持 null，不回落到分支头', () => {
  const command = buildTurnCommand({
    selectedBranchId: 'branch-1',
    branchHeadMessageId: 'assistant-head',
    pending: {
      action: 'edit_resend',
      parentMessageId: null,
      derivedFromMessageId: 'user-root',
      label: '正在编辑当前线路',
    },
    content: '编辑后的需求',
    requestId: 'request-edit-root',
  })
  assert.equal(command.action, 'edit_resend')
  assert.equal(command.parent_message_id, null)
  assert.equal(command.derived_from_message_id, 'user-root')
})
