import assert from 'node:assert/strict'
import test from 'node:test'
import { branchOriginLabel, flattenBranchTree } from './adminChatState.ts'

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
