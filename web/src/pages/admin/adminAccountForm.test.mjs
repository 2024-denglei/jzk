import test from 'node:test'
import assert from 'node:assert/strict'
import { adminCreateValidationErrors } from './adminAccountForm.ts'

test('explains why a seven-character password cannot create an administrator', () => {
  const errors = adminCreateValidationErrors({
    username: 'tongxiaobo',
    password: '1234567',
    confirmPassword: '1234567',
    displayName: '童子凡',
  })
  assert.deepEqual(errors, ['初始密码至少需要 8 位，当前 7 位'])
})

test('accepts a complete valid administrator form', () => {
  const errors = adminCreateValidationErrors({
    username: 'tongxiaobo',
    password: '12345678',
    confirmPassword: '12345678',
    displayName: '童子凡',
  })
  assert.deepEqual(errors, [])
})

