import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { AdminShell } from './admin/AdminShell'
import { logoutAdminSession, refreshAdminSession, setAdminToken } from './admin/adminApi'
import { AdminProfileView } from './admin/AdminProfileView'
import { AdminsView } from './admin/AdminsView'
import { DashboardView } from './admin/DashboardView'
import { DonorsView } from './admin/DonorsView'
import { ImportView } from './admin/ImportView'
import type { AdminInfo } from './admin/types'
import { UserProfileView } from './admin/UserProfileView'
import { UsersView } from './admin/UsersView'
import { RequestsView } from './admin/RequestsView'
import { ChatFeedbackView } from './admin/ChatFeedbackView'
import { ADMIN_PERMISSIONS, firstAllowedAdminPath, hasAdminPermission } from './admin/adminPermissions'

export function AdminPage() {
  const location = useLocation()
  const [admin, setAdmin] = useState<AdminInfo | null>(null)
  const [checking, setChecking] = useState(true)

  const loadMe = useCallback(async () => {
    try {
      const data = await refreshAdminSession<AdminInfo>()
      setAdmin(data?.admin ?? null)
    } catch {
      setAdmin(null)
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
    const unauthorized = () => setAdmin(null)
    window.addEventListener('admin-unauthorized', unauthorized)
    return () => window.removeEventListener('admin-unauthorized', unauthorized)
  }, [loadMe])

  if (checking) return <div className="flex min-h-screen items-center justify-center bg-[#f3f6fa] text-sm text-[#718096]">正在验证管理员身份…</div>
  if (!admin) return <AdminLogin onSuccess={setAdmin} />
  if (location.pathname === '/admin' || location.pathname === '/admin/') return <Navigate to={firstAllowedAdminPath(admin.permissions)} replace />

  const userMatch = location.pathname.match(/^\/admin\/users\/(\d+)$/)
  const adminMatch = location.pathname.match(/^\/admin\/admins\/(\d+)$/)
  const allowed = (permission: string) => hasAdminPermission(admin.permissions, permission)
  let content = allowed(ADMIN_PERMISSIONS.dashboardView) ? <DashboardView /> : <ForbiddenView />
  if (adminMatch) content = allowed(ADMIN_PERMISSIONS.adminsView) ? <AdminProfileView adminId={Number(adminMatch[1])} currentAdminId={admin.id} /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/admins')) content = allowed(ADMIN_PERMISSIONS.adminsView) ? <AdminsView currentAdminId={admin.id} permissions={admin.permissions} /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/requests/review')) content = allowed(ADMIN_PERMISSIONS.requestsReview) ? <RequestsView mode="review" /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/requests/mine')) content = allowed(ADMIN_PERMISSIONS.requestsViewOwn) ? <RequestsView mode="mine" /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/chat-feedback')) content = allowed(ADMIN_PERMISSIONS.usersView) ? <ChatFeedbackView /> : <ForbiddenView />
  else if (userMatch) content = allowed(ADMIN_PERMISSIONS.usersView) ? <UserProfileView userId={Number(userMatch[1])} permissions={admin.permissions} /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/users')) content = allowed(ADMIN_PERMISSIONS.usersView) ? <UsersView permissions={admin.permissions} /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/donors')) content = allowed(ADMIN_PERMISSIONS.donorsView) ? <DonorsView permissions={admin.permissions} /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/import')) content = allowed(ADMIN_PERMISSIONS.donorsImport) ? <ImportView /> : <ForbiddenView />
  else if (location.pathname.startsWith('/admin/audit')) content = <Navigate to="/admin/admins" replace />

  return <AdminShell admin={admin} onLogout={() => { void logoutAdminSession().finally(() => setAdmin(null)) }}>{content}</AdminShell>
}

function ForbiddenView() {
  return <div className="flex min-h-[60vh] items-center justify-center"><div className="text-center"><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-rose-50 text-rose-600"><i className="ri-lock-line text-xl" /></div><h1 className="mt-4 text-lg font-semibold text-[#24344b]">无权访问该页面</h1><p className="mt-2 text-xs text-[#7d899a]">当前管理员账号没有所需权限。</p></div></div>
}

function AdminLogin({ onSuccess }: { onSuccess: (admin: AdminInfo) => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function login(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/admin/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ username, password }) })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || '登录失败')
      setAdminToken(data.access_token)
      onSuccess(data.admin)
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-[#f3f6fa] lg:grid-cols-[1.1fr_0.9fr]">
      <div className="relative hidden overflow-hidden bg-[#142641] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -left-24 top-20 h-80 w-80 rounded-full bg-[#1677ff]/12 blur-2xl" />
        <div className="absolute -bottom-32 right-0 h-96 w-96 rounded-full bg-cyan-300/8 blur-3xl" />
        <div className="relative flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#1677ff] text-lg font-bold">智</div><div><div className="text-lg font-semibold">智育管理平台</div><div className="text-xs text-white/45">运营管理后台</div></div></div>
        <div className="relative max-w-xl"><div className="text-sm font-medium text-[#72aefc]">ADMIN WORKSPACE</div><h1 className="mt-4 text-4xl font-semibold leading-tight">集中管理用户档案与<br />捐精人运营数据</h1><p className="mt-5 max-w-md text-sm leading-7 text-white/55">查看用户账号、收藏、浏览历史和 AI 会话，维护捐精人档案，并保留完整的管理操作记录。</p></div>
        <div className="relative text-xs text-white/30">智育匹配 · 管理系统</div>
      </div>
      <div className="flex items-center justify-center px-5 py-12">
        <form onSubmit={login} className="w-full max-w-sm rounded-2xl border border-[#dbe3ed] bg-white p-7 shadow-sm">
          <div className="mb-7 lg:hidden"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#1677ff] font-bold text-white">智</div></div>
          <h2 className="text-2xl font-semibold text-[#17263b]">管理端登录</h2><p className="mt-2 text-xs text-[#7d899a]">使用独立管理员账号进入运营工作台</p>
          <label className="mt-7 block text-xs font-medium text-[#44536a]">用户名<input value={username} onChange={(event) => setUsername(event.target.value)} className="mt-2 h-11 w-full rounded-lg border border-[#d7e0ea] px-3 text-sm outline-none focus:border-[#1677ff] focus:ring-2 focus:ring-[#1677ff]/10" /></label>
          <label className="mt-4 block text-xs font-medium text-[#44536a]">密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 h-11 w-full rounded-lg border border-[#d7e0ea] px-3 text-sm outline-none focus:border-[#1677ff] focus:ring-2 focus:ring-[#1677ff]/10" /></label>
          {error ? <div className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</div> : null}
          <button disabled={busy || !username || !password} className="mt-6 h-11 w-full rounded-lg bg-[#1677ff] text-sm font-medium text-white transition hover:bg-[#0868e8] disabled:opacity-50">{busy ? '正在登录…' : '登录管理后台'}</button>
        </form>
      </div>
    </div>
  )
}
