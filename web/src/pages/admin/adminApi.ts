let adminAccessToken: string | null = null

if (typeof localStorage !== 'undefined') localStorage.removeItem('jzk_admin_token')

type AdminAuthPayload<T = unknown> = {
  access_token: string
  admin: T
}

let refreshPromise: Promise<AdminAuthPayload | null> | null = null

export function setAdminToken(token: string | null) {
  adminAccessToken = token
}

export async function refreshAdminSession<T = unknown>(): Promise<AdminAuthPayload<T> | null> {
  if (!refreshPromise) {
    refreshPromise = fetch('/api/admin/refresh', {
      method: 'POST',
      credentials: 'include',
    })
      .then(async (response) => {
        if (!response.ok) {
          setAdminToken(null)
          return null
        }
        const data = await response.json() as AdminAuthPayload
        setAdminToken(data.access_token)
        return data
      })
      .catch(() => {
        setAdminToken(null)
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise as Promise<AdminAuthPayload<T> | null>
}

export async function logoutAdminSession() {
  try {
    await fetch('/api/admin/logout', { method: 'POST', credentials: 'include' })
  } finally {
    setAdminToken(null)
  }
}

export async function adminFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (adminAccessToken) headers.set('Authorization', `Bearer ${adminAccessToken}`)
  if (!(init.body instanceof FormData) && !headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json')
  }
  let response = await fetch(path, { ...init, headers, credentials: 'include' })
  if (response.status === 401 && retry && path !== '/api/admin/refresh') {
    const refreshed = await refreshAdminSession()
    if (refreshed) {
      const retryHeaders = new Headers(headers)
      retryHeaders.set('Authorization', `Bearer ${adminAccessToken}`)
      response = await fetch(path, { ...init, headers: retryHeaders, credentials: 'include' })
    }
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      setAdminToken(null)
      window.dispatchEvent(new Event('admin-unauthorized'))
    }
    throw new Error((data as { detail?: string }).detail || response.statusText || '请求失败')
  }
  return data as T
}

export function postAdmin<T>(path: string, body?: unknown) {
  return adminFetch<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}
