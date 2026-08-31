const TOKEN_KEY = 'jzk_token'
export const USER_SESSION_EXPIRED_EVENT = 'user-session-expired'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function expireUserSession(detail = '登录已失效，请重新登录') {
  setToken(null)
  window.dispatchEvent(new CustomEvent(USER_SESSION_EXPIRED_EVENT, { detail }))
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(path, { ...init, headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (data as { detail?: string }).detail || '请求失败'
    if (res.status === 401) expireUserSession(typeof detail === 'string' ? detail : '登录已失效，请重新登录')
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
