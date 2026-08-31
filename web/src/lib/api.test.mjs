import assert from 'node:assert/strict'
import test from 'node:test'

test('401 会清除用户令牌并通知 AuthContext 退出', async () => {
  const store = new Map([['jzk_token', 'old-token']])
  let dispatched = null
  globalThis.localStorage = {
    getItem: (key) => store.get(key) || null,
    setItem: (key, value) => store.set(key, value),
    removeItem: (key) => store.delete(key),
  }
  globalThis.CustomEvent = class {
    constructor(type, init) { this.type = type; this.detail = init?.detail }
  }
  globalThis.window = { dispatchEvent: (event) => { dispatched = event } }

  const { expireUserSession, USER_SESSION_EXPIRED_EVENT } = await import('./api.ts')
  expireUserSession('账号已停用')

  assert.equal(store.has('jzk_token'), false)
  assert.equal(dispatched.type, USER_SESSION_EXPIRED_EVENT)
  assert.equal(dispatched.detail, '账号已停用')
})
