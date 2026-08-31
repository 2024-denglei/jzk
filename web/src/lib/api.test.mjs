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
