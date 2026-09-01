import assert from 'node:assert/strict'
import test from 'node:test'

test('令牌只保存在内存，过期时清除并通知 AuthContext 退出', async () => {
  const store = new Map([['jzk_token', 'old-token']])
  let dispatched = null
  let writes = 0
  globalThis.localStorage = {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => { writes += 1; store.set(key, value) },
    removeItem: (key) => store.delete(key),
  }
  globalThis.CustomEvent = class {
    constructor(type, init) { this.type = type; this.detail = init?.detail }
  }
  globalThis.window = { dispatchEvent: (event) => { dispatched = event } }

  const { expireUserSession, getToken, setToken, USER_SESSION_EXPIRED_EVENT } = await import('./api.ts')
  setToken('memory-only-token')
  assert.equal(getToken(), 'memory-only-token')
  expireUserSession('账号已停用')

  assert.equal(getToken(), null)
  assert.equal(writes, 0)
  assert.equal(store.has('jzk_token'), false)
  assert.equal(dispatched.type, USER_SESSION_EXPIRED_EVENT)
  assert.equal(dispatched.detail, '账号已停用')
})

test('结构化 API 错误保留稳定错误码', async () => {
  const { ApiError, extractApiError } = await import('./api.ts')
  const error = extractApiError({
    detail: { code: 'MATCH_SNAPSHOT_EXPIRED', message: '匹配快照已过期' },
  }, 410)
  assert.ok(error instanceof ApiError)
  assert.equal(error.status, 410)
  assert.equal(error.code, 'MATCH_SNAPSHOT_EXPIRED')
  assert.equal(error.message, '匹配快照已过期')
})
