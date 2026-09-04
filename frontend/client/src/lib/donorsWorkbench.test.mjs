import assert from 'node:assert/strict'
import test from 'node:test'
import { donorsPathWithSearch, shouldCloseMobileChatOnSync } from './donorsWorkbench.ts'

test('自动同步对话结果时不关闭移动端聊天抽屉', () => {
  assert.equal(shouldCloseMobileChatOnSync(), false)
  assert.equal(shouldCloseMobileChatOnSync({}), false)
})

test('用户主动在中间栏查看时关闭移动端聊天抽屉', () => {
  assert.equal(shouldCloseMobileChatOnSync({ focusMiddle: true }), true)
})

test('跳转路径保留 chatId 等查询参数', () => {
  const params = new URLSearchParams('chatId=12&branchId=abc')
  assert.equal(donorsPathWithSearch('/donors', params), '/donors?chatId=12&branchId=abc')
  assert.equal(donorsPathWithSearch('/donors/A001', params), '/donors/A001?chatId=12&branchId=abc')
  assert.equal(donorsPathWithSearch('/donors', new URLSearchParams()), '/donors')
})
