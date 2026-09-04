import assert from 'node:assert/strict'
import test from 'node:test'
import { WORKBENCH_HEADER_HEIGHT_CLASS } from './workbenchLayout.ts'

test('三栏工作台使用一致的一级标题栏高度', () => {
  assert.equal(WORKBENCH_HEADER_HEIGHT_CLASS, 'h-16')
})
