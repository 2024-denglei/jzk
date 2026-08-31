import assert from 'node:assert/strict'
import test from 'node:test'
import { formatTime } from './adminFormat.ts'

test('空时间显示占位符', () => {
  assert.equal(formatTime(null), '—')
  assert.equal(formatTime(''), '—')
})

test('非法时间保留原值以便排查数据', () => {
  assert.equal(formatTime('not-a-date'), 'not-a-date')
})

test('ISO 时间转换为中文本地时间文本', () => {
  const value = formatTime('2026-08-31T12:30:00Z')
  assert.match(value, /2026/)
  assert.match(value, /12:30|08:30/)
})
