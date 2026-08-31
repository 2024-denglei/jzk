import assert from 'node:assert/strict'
import test from 'node:test'
import { getPaginationPages } from './pagination.ts'

test('页数不超过六页时展示全部页码', () => {
  assert.deepEqual(getPaginationPages(1), [1])
  assert.deepEqual(getPaginationPages(6), [1, 2, 3, 4, 5, 6])
})

test('页数超过六页时展示首页三页和末尾三页', () => {
  assert.deepEqual(getPaginationPages(7), [1, 2, 3, 5, 6, 7])
  assert.deepEqual(getPaginationPages(18), [1, 2, 3, 16, 17, 18])
})

test('异常总页数至少返回第一页', () => {
  assert.deepEqual(getPaginationPages(0), [1])
  assert.deepEqual(getPaginationPages(-3), [1])
})
