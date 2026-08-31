import assert from 'node:assert/strict'
import test from 'node:test'
import { getPaginationPages } from './pagination.ts'

test('首页和尾页不在数字页码中重复展示', () => {
  assert.deepEqual(getPaginationPages(1, 1), [])
  assert.deepEqual(getPaginationPages(2, 1), [])
  assert.deepEqual(getPaginationPages(6, 3), [2, 3, 4, 5])
})

test('数字页码随着当前页向前滑动', () => {
  assert.deepEqual(getPaginationPages(18, 1), [2, 3, 4, 5, 6, 7])
  assert.deepEqual(getPaginationPages(18, 8), [6, 7, 8, 9, 10, 11])
})

test('接近尾页时数字页码自动贴边', () => {
  assert.deepEqual(getPaginationPages(18, 16), [12, 13, 14, 15, 16, 17])
  assert.deepEqual(getPaginationPages(18, 18), [12, 13, 14, 15, 16, 17])
})

test('异常总页数不会生成数字页码', () => {
  assert.deepEqual(getPaginationPages(0, 1), [])
  assert.deepEqual(getPaginationPages(-3, 1), [])
})
