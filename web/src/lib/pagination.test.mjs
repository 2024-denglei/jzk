import assert from 'node:assert/strict'
import test from 'node:test'
import { getPaginationPages } from './pagination.ts'

test('首页和尾页不在数字页码中重复展示', () => {
  assert.deepEqual(getPaginationPages(1), [])
  assert.deepEqual(getPaginationPages(2), [])
  assert.deepEqual(getPaginationPages(6), [2, 3, 4, 5])
})

test('数字页码展示紧邻首页和尾页的各三页', () => {
  assert.deepEqual(getPaginationPages(8), [2, 3, 4, 5, 6, 7])
  assert.deepEqual(getPaginationPages(18), [2, 3, 4, 15, 16, 17])
})

test('异常总页数不会生成数字页码', () => {
  assert.deepEqual(getPaginationPages(0), [])
  assert.deepEqual(getPaginationPages(-3), [])
})
