let accessToken: string | null = null

if (typeof localStorage !== 'undefined') localStorage.removeItem('jzk_token')

export const USER_SESSION_EXPIRED_EVENT = 'user-session-expired'

type AuthPayload<T = unknown> = {
  access_token: string
  user: T
}

let refreshPromise: Promise<AuthPayload | null> | null = null

export class ApiError extends Error {
  readonly status: number
  readonly code?: string

  constructor(
    message: string,
    status: number,
    code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function extractApiError(data: unknown, status: number): ApiError {
  const detail = (data as { detail?: unknown } | null)?.detail
  if (detail && typeof detail === 'object') {
    const value = detail as { code?: unknown; message?: unknown }
    return new ApiError(
      typeof value.message === 'string' ? value.message : '请求失败',
      status,
      typeof value.code === 'string' ? value.code : undefined,
    )
  }
  return new ApiError(typeof detail === 'string' ? detail : '请求失败', status)
}

export function getToken(): string | null {
  return accessToken
}

export function setToken(token: string | null) {
  accessToken = token
}

export function expireUserSession(detail = '登录已失效，请重新登录') {
  setToken(null)
  window.dispatchEvent(new CustomEvent(USER_SESSION_EXPIRED_EVENT, { detail }))
}

export async function refreshAccessToken<T = unknown>(): Promise<AuthPayload<T> | null> {
  if (!refreshPromise) {
    refreshPromise = fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
      .then(async (response) => {
        if (!response.ok) {
          setToken(null)
          return null
        }
        const data = await response.json() as AuthPayload
        setToken(data.access_token)
        return data
      })
      .catch(() => {
        setToken(null)
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise as Promise<AuthPayload<T> | null>
}

const NO_AUTO_REFRESH = new Set([
  '/api/auth/login',
  '/api/auth/phone-login',
  '/api/auth/register',
  '/api/auth/refresh',
  '/api/auth/logout',
  '/api/auth/send-code',
  '/api/auth/reset-password',
])

export async function authFetch(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (response.status === 401 && retry && !NO_AUTO_REFRESH.has(path.split('?')[0])) {
    const refreshed = await refreshAccessToken()
    if (refreshed) response = await authFetch(path, init, false)
  }
  return response
}

export async function logoutUserSession() {
  try {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
  } finally {
    setToken(null)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await authFetch(path, { ...init, headers })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const error = extractApiError(data, res.status)
    if (res.status === 401) expireUserSession(error.message || '登录已失效，请重新登录')
    throw error
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'DELETE', body: body !== undefined ? JSON.stringify(body) : undefined }),
}
