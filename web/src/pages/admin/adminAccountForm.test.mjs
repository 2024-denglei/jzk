import test from 'node:test'
import assert from 'node:assert/strict'
import { adminCreateValidationErrors } from './adminAccountForm.ts'

test('explains why a short password cannot create an administrator', () => {
  const errors = adminCreateValidationErrors({
    username: 'tongxiaobo',
    password: '1234567',
    confirmPassword: '1234567',
    displayName: '童子凡',
  })
  assert.deepEqual(errors, ['初始密码至少需要 12 位，当前 7 位'])
})

test('accepts a complete valid administrator form', () => {
  const errors = adminCreateValidationErrors({
    username: 'tongxiaobo',
    password: '123456789012',
    confirmPassword: '123456789012',
    displayName: '童子凡',
  })
  assert.deepEqual(errors, [])
})
