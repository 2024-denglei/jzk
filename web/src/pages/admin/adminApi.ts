export const ADMIN_TOKEN_KEY = 'jzk_admin_token'

export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem(ADMIN_TOKEN_KEY)
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData) && !headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...init, headers })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem(ADMIN_TOKEN_KEY)
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
