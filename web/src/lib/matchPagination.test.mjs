import assert from 'node:assert/strict'
import test from 'node:test'
import { cacheMatchPage, createMatchPageState } from './matchPagination.ts'

test('首次结果只缓存第一页和下一页游标', () => {
  const state = createMatchPageState({
    result_set_id: 'run-1', total: 4303, items: [{ donor_info: { code: 'D1' } }],
    next_cursor: 'cursor-2', source_message_id: 'message-1',
  })
  assert.equal(state.total, 4303)
  assert.deepEqual(Object.keys(state.pages), ['1'])
  assert.equal(state.cursors[2], 'cursor-2')
  assert.equal(state.sourceMessageId, 'message-1')
})

test('加载下一页保留旧页并记录后续游标', () => {
  const first = createMatchPageState({
    result_set_id: 'run-1', total: 40, items: [], next_cursor: 'cursor-2',
  })
  const second = cacheMatchPage(first, 2, [], 'cursor-3')
  assert.ok(1 in second.pages)
  assert.ok(2 in second.pages)
  assert.equal(second.cursors[3], 'cursor-3')
})
