import assert from 'node:assert/strict'
import test from 'node:test'
import { isUUIDv4, randomUUID } from './uuid.ts'

test('randomUUID 返回 UUID v4 格式', () => {
  assert.ok(isUUIDv4(randomUUID()))
})

test('缺少 crypto.randomUUID 时仍可用 getRandomValues 生成 UUID', () => {
  const originalCrypto = globalThis.crypto
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      getRandomValues(array) {
        for (let i = 0; i < array.length; i += 1) {
          array[i] = (i * 17 + 3) % 256
        }
        return array
      },
    },
  })
  try {
    assert.ok(isUUIDv4(randomUUID()))
  } finally {
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: originalCrypto,
    })
  }
})
