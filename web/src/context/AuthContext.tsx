import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, logoutUserSession, refreshAccessToken, setToken, USER_SESSION_EXPIRED_EVENT } from '../lib/api'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (identifier: string, password: string) => Promise<void>
  loginWithCode: (phone: string, code: string) => Promise<void>
  register: (email: string, phone: string, password: string, code: string, nickname?: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  updateNickname: (nickname: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const data = await refreshAccessToken<User>()
      setUser(data?.user ?? null)
    } catch {
      setToken(null)
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const expired = () => setUser(null)
    window.addEventListener(USER_SESSION_EXPIRED_EVENT, expired)
    return () => window.removeEventListener(USER_SESSION_EXPIRED_EVENT, expired)
  }, [])

  const acceptLogin = useCallback((data: { access_token: string; user: User }) => {
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const login = useCallback(async (identifier: string, password: string) => {
    const data = await api.post<{ access_token: string; user: User }>('/api/auth/login', { identifier, password })
    acceptLogin(data)
  }, [acceptLogin])

  const loginWithCode = useCallback(async (phone: string, code: string) => {
    const data = await api.post<{ access_token: string; user: User }>('/api/auth/phone-login', { phone, code })
    acceptLogin(data)
  }, [acceptLogin])

  const register = useCallback(async (email: string, phone: string, password: string, code: string, nickname = '') => {
    const data = await api.post<{ access_token: string; user: User }>('/api/auth/register', {
      email,
      phone,
      password,
      code,
      nickname,
    })
    acceptLogin(data)
  }, [acceptLogin])

  const logout = useCallback(async () => {
    try {
      await logoutUserSession()
    } finally {
      setUser(null)
    }
  }, [])

  const updateNickname = useCallback(async (nickname: string) => {
    const me = await api.patch<User>('/api/auth/me', { nickname })
    setUser(me)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, loginWithCode, register, logout, refresh, updateNickname }),
    [user, loading, login, loginWithCode, register, logout, refresh, updateNickname],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
