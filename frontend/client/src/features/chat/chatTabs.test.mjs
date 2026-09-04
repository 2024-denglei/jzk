import assert from 'node:assert/strict'
import test from 'node:test'
import { closeTabState, nextDraftBranchName, replaceDraftTab, shouldShowWorkspaceTabs } from './chatTabs.ts'

const main = { key: 'main', branchId: 'main', name: '主线', closable: false }
const branch1 = { key: 'b1', branchId: 'b1', name: '分支1', closable: true }

test('分支名称按持久分支和待发送分支连续编号', () => {
  assert.equal(nextDraftBranchName(0, 0), '分支1')
  assert.equal(nextDraftBranchName(2, 1), '分支4')
})

test('待发送标签持久化后沿用服务端分支名称', () => {
  const draft = { key: 'draft:1', branchId: 'main', name: '分支1', closable: true }
  assert.deepEqual(replaceDraftTab([main, draft], draft.key, 'b1', '分支1'), [main, branch1])
})

test('关闭活动分支回到左侧标签且主线不可关闭', () => {
  assert.deepEqual(closeTabState([main, branch1], 'b1', 'b1'), {
    tabs: [main], nextActiveKey: 'main',
  })
  assert.deepEqual(closeTabState([main, branch1], 'main', 'main'), {
    tabs: [main, branch1], nextActiveKey: 'main',
  })
})

test('仅打开主线时不展示工作区标签栏', () => {
  assert.equal(shouldShowWorkspaceTabs([main]), false)
  assert.equal(shouldShowWorkspaceTabs([main, branch1]), true)
  assert.equal(shouldShowWorkspaceTabs([]), false)
})
