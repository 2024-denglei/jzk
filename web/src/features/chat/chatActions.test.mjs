import assert from 'node:assert/strict'
import test from 'node:test'
import { buildBranchWorkspacePath, buildTurnCommand } from './chatActions.ts'

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
})

test('显式分支工作区使用独立 URL 并保留无关查询参数', () => {
  const path = buildBranchWorkspacePath('?page=3&forkFrom=old', 12, 'branch-2', 'message-8')
  assert.equal(path, '/donors?page=3&forkFrom=message-8&chatId=12&branchId=branch-2')
  assert.equal(
    buildBranchWorkspacePath(path.split('?')[1], 12, 'branch-3'),
    '/donors?page=3&chatId=12&branchId=branch-3',
  )
})
