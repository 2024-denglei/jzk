import assert from 'node:assert/strict'
import test from 'node:test'
import {
  branchChildren,
  canCreateBranchAfterMessage,
  candidateSyncAction,
  createChatClientState,
  mergeMessagePage,
  messagesForSelectedBranch,
  nextFeedbackRating,
  patchMessage,
  previewMessagesAtBranchPoint,
  selectConversation,
  visibleMessagesForPendingAction,
} from './chatState.ts'

test('消息反馈支持选择、切换和再次点击取消', () => {
  assert.equal(nextFeedbackRating(null, 'like'), 'like')
  assert.equal(nextFeedbackRating('like', 'dislike'), 'dislike')
  assert.equal(nextFeedbackRating('dislike', 'dislike'), null)
})

const branch = (id, parent = null, active = false) => ({
  id,
  parent_branch_id: parent,
  forked_from_message_id: null,
  derived_from_message_id: null,
  name: id,
  system_name: id,
  fork_reason: parent ? 'rewind_continue' : 'root',
  head_message_id: null,
  message_count: 0,
  last_message_preview: '',
  is_active: active,
  is_archived: false,
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
})

const message = (id, depth, parent = null) => ({
  id,
  parent_message_id: parent,
  derived_from_message_id: null,
  created_in_branch_id: 'root',
  role: depth % 2 ? 'assistant' : 'user',
  status: 'completed',
  content: id,
  content_format: 'markdown',
  depth,
  state_recoverable: true,
  generation_id: null,
  match_run: null,
  created_at: '2026-01-01',
  completed_at: '2026-01-01',
})

test('生成中保留当前候选，完成后才加载最新完整快照', () => {
  const previous = { ...message('m1', 1), match_run: { total: 20 } }
  const generating = { ...message('m3', 3, 'm2'), status: 'generating' }
  assert.deepEqual(candidateSyncAction([previous, generating]), { kind: 'preserve' })

  const completed = { ...generating, status: 'completed', match_run: { total: 359 } }
  const action = candidateSyncAction([previous, completed])
  assert.equal(action.kind, 'load')
  assert.equal(action.message.id, 'm3')
  assert.deepEqual(candidateSyncAction([message('m0', 0)]), { kind: 'clear' })
})

test('终止后无快照则 clear，有历史快照则回退到上一轮匹配', () => {
  const stoppedOnly = [
    message('u1', 0),
    { ...message('a1', 1, 'u1'), status: 'stopped', match_run: null },
  ]
  assert.deepEqual(candidateSyncAction(stoppedOnly), { kind: 'clear' })

  const previous = { ...message('a0', 1, 'u0'), match_run: { total: 42 } }
  const stopped = { ...message('a2', 3, 'u2'), status: 'stopped', match_run: null }
  const action = candidateSyncAction([message('u0', 0), previous, message('u2', 2, 'a0'), stopped])
  assert.equal(action.kind, 'load')
  assert.equal(action.message.id, 'a0')
})

test('待创建分支只预览到分支点且取消所需原消息不被删除', () => {
  const messages = [
    message('m0', 0),
    message('m1', 1, 'm0'),
    message('m2', 2, 'm1'),
    message('m3', 3, 'm2'),
  ]
  const preview = previewMessagesAtBranchPoint(messages, 'm1')
  assert.deepEqual(preview.items.map((item) => item.id), ['m0', 'm1'])
  assert.equal(preview.hiddenCount, 2)
  assert.equal(messages.length, 4)

  const editFirstMessage = previewMessagesAtBranchPoint(messages, null)
  assert.deepEqual(editFirstMessage.items, [])
  assert.equal(editFirstMessage.hiddenCount, 4)
})

test('内联编辑保留完整消息列表，回溯分叉仍截断到分支点', () => {
  const messages = [
    message('m0', 0),
    message('m1', 1, 'm0'),
    message('m2', 2, 'm1'),
  ]
  const editing = visibleMessagesForPendingAction(messages, {
    action: 'edit_resend',
    parentMessageId: null,
  })
  assert.deepEqual(editing.items.map((item) => item.id), ['m0', 'm1', 'm2'])
  assert.equal(editing.hiddenCount, 0)

  const rewind = visibleMessagesForPendingAction(messages, {
    action: 'rewind_continue',
    parentMessageId: 'm1',
  })
  assert.deepEqual(rewind.items.map((item) => item.id), ['m0', 'm1'])
  assert.equal(rewind.hiddenCount, 1)
})

test('分支入口只出现在历史中的完整 AI 回复单元之后', () => {
  const user = message('m0', 0)
  const assistant = message('m1', 1, 'm0')
  const withCandidates = { ...assistant, match_run: { total: 359 } }

  assert.equal(canCreateBranchAfterMessage(user, 0, 4), false)
  assert.equal(canCreateBranchAfterMessage(assistant, 1, 4), true)
  assert.equal(canCreateBranchAfterMessage(withCandidates, 1, 4), true)
  assert.equal(canCreateBranchAfterMessage({ ...assistant, status: 'generating' }, 1, 4), false)
  assert.equal(canCreateBranchAfterMessage({ ...assistant, status: 'stopped' }, 1, 4), false)
  assert.equal(canCreateBranchAfterMessage({ ...assistant, state_recoverable: false }, 1, 4), false)
  assert.equal(canCreateBranchAfterMessage(assistant, 3, 4), false)
})

test('分支路径复用公共祖先且向上分页不产生重复消息', () => {
  const tree = {
    chat: { id: 1, active_branch_id: 'root' },
    branches: [branch('root', null, true), branch('fork', 'root')],
  }
  let state = selectConversation(createChatClientState(), tree, 'fork')
  state = mergeMessagePage(state, {
    chat_id: 1,
    branch_id: 'fork',
    items: [message('m2', 2, 'm1'), message('m3', 3, 'm2')],
    next_before: 'cursor-1',
    has_more: true,
  })
  state = mergeMessagePage(state, {
    chat_id: 1,
    branch_id: 'fork',
    items: [message('m0', 0), message('m1', 1, 'm0'), message('m2', 2, 'm1')],
    next_before: null,
    has_more: false,
  }, true)

  assert.deepEqual(messagesForSelectedBranch(state).map((item) => item.id), ['m0', 'm1', 'm2', 'm3'])
  assert.equal(Object.keys(state.messagesById).length, 4)
  assert.equal(state.pathsByBranch.fork.hasMore, false)
})

test('指定分支优先于活跃分支且生成 token 只更新目标消息', () => {
  const branches = [branch('root', null, true), branch('fork', 'root')]
  let state = selectConversation(createChatClientState(), {
    chat: { id: 1, active_branch_id: 'root' }, branches,
  }, 'fork')
  state = mergeMessagePage(state, {
    chat_id: 1,
    branch_id: 'fork',
    items: [message('m0', 0)],
    next_before: null,
    has_more: false,
  })
  state = patchMessage(state, 'm0', { content: '流式内容', status: 'generating' })

  assert.equal(state.selectedBranchId, 'fork')
  assert.equal(state.messagesById.m0.content, '流式内容')
  assert.deepEqual(branchChildren(branches).get('root').map((item) => item.id), ['fork'])
})
