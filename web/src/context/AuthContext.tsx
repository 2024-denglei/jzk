import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, getToken, setToken } from '../lib/api'
import type { User } from '../types'

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, nickname?: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  updateNickname: (nickname: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const token = getToken()
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await api.get<User>('/api/auth/me')
      setUser(me)
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

  const login = useCallback(async (email: string, password: string) => {
    const data = await api.post<{ access_token: string; user: User }>('/api/auth/login', { email, password })
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const register = useCallback(async (email: string, password: string, nickname = '') => {
    const data = await api.post<{ access_token: string; user: User }>('/api/auth/register', {
      email,
      password,
      nickname,
    })
    setToken(data.access_token)
    setUser(data.user)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const updateNickname = useCallback(async (nickname: string) => {
    const me = await api.patch<User>('/api/auth/me', { nickname })
    setUser(me)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refresh, updateNickname }),
    [user, loading, login, register, logout, refresh, updateNickname],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
