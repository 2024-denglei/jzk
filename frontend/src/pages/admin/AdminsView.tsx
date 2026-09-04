import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminFetch, postAdmin } from './adminApi'
import { adminPageShellClass } from './adminLayout'
import { AdminStatus, ErrorNotice, PageHeader, Pagination, StickyTableCard } from './AdminUi'
import { adminRoleLabel, formatTime } from './adminFormat'
import type { AdminRecord, PageData } from './types'
import { ADMIN_PERMISSIONS, hasAdminPermission } from './adminPermissions'
import { AdminCreateDialog, AdminStateDialog, type AdminCreateValues } from './AdminAccountDialogs'

export function AdminsView({ currentAdminId, permissions }: { currentAdminId: number; permissions: string[] }) {
  const navigate = useNavigate()
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PageData<AdminRecord>>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [stateChange, setStateChange] = useState<{ admin: AdminRecord; action: 'delete' | 'restore' } | null>(null)
  const [busy, setBusy] = useState(false)
  const canManage = hasAdminPermission(permissions, ADMIN_PERMISSIONS.adminsManage)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '20' })
      if (query) params.set('q', query)
      if (status) params.set('status', status)
      setData(await adminFetch(`/api/admin/admins?${params}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : '管理员信息加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, query, status])

  useEffect(() => { void load() }, [load])

  async function createAdmin(values: AdminCreateValues) {
    setBusy(true); setError(''); setMessage('')
    try {
      await postAdmin('/api/admin/admins', values)
      setCreateOpen(false); setMessage('管理员账号已创建。'); await load()
    } catch (err) { setError(err instanceof Error ? err.message : '管理员创建失败') }
    finally { setBusy(false) }
  }

  async function changeState(reason: string) {
    if (!stateChange) return
    setBusy(true); setError(''); setMessage('')
    try {
      if (stateChange.action === 'delete') await adminFetch(`/api/admin/admins/${stateChange.admin.id}`, { method: 'DELETE', body: JSON.stringify({ reason }) })
      else await postAdmin(`/api/admin/admins/${stateChange.admin.id}/restore`, { reason })
      setMessage(stateChange.action === 'delete' ? '管理员已删除并停止访问。' : '管理员账号已恢复。')
      setStateChange(null); await load()
    } catch (err) { setError(err instanceof Error ? err.message : '管理员状态修改失败') }
    finally { setBusy(false) }
  }

  return (
    <div className={adminPageShellClass()}>
      <div className="shrink-0">
        <PageHeader title="管理员中心" description="按管理员查看账号资料、操作统计和审计记录。" />
        {error ? <ErrorNotice message={error} /> : null}
        {message ? <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
      </div>
      <StickyTableCard
        toolbar={(
          <form onSubmit={(event) => { event.preventDefault(); setQuery(draft.trim()); setPage(1) }} className="flex flex-wrap gap-2 border-b border-[#e2e8f0] p-3">
            <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索管理员姓名或账号" className="h-9 min-w-[240px] flex-1 rounded-lg border border-[#d9e1ec] px-3 text-xs outline-none focus:border-[#1677ff]" />
            <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs">
              <option value="">全部状态</option><option value="active">正常</option><option value="disabled">已停用</option>
            </select>
            <button className="h-9 rounded-lg bg-[#1677ff] px-4 text-xs text-white">查询</button>
            {canManage ? <button type="button" onClick={() => setCreateOpen(true)} className="h-9 rounded-lg border border-[#9fc7ff] px-4 text-xs text-[#1677ff]">新增管理员</button> : null}
          </form>
        )}
        footer={<Pagination page={page} pageSize={data.page_size} total={data.total} onChange={setPage} />}
      >
        <table className="w-full min-w-[1040px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[#f7f9fc] text-[#667389]"><tr><th className="px-4 py-3 font-medium">管理员</th><th className="px-4 py-3 font-medium">登录账号</th><th className="px-4 py-3 font-medium">角色</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">档案操作</th><th className="px-4 py-3 font-medium">用户操作</th><th className="px-4 py-3 font-medium">管理员操作</th><th className="px-4 py-3 font-medium">最近操作</th><th className="px-4 py-3 font-medium">操作</th></tr></thead>
          <tbody className="divide-y divide-[#e5eaf1]">
            {data.items.map((item) => (
              <tr key={item.id} className="hover:bg-[#f8fbff]">
                <td className="px-4 py-3"><div className="flex items-center gap-2.5"><div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#e8f2ff] font-semibold text-[#1677ff]">{(item.display_name || item.username).slice(0, 1)}</div><div><div className="font-medium text-[#293a52]">{item.display_name || '未设置姓名'}{item.id === currentAdminId ? <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 text-[9px] text-blue-600">当前账号</span> : null}</div><div className="mt-0.5 text-[10px] text-[#929dab]">ID {item.id}</div></div></div></td>
                <td className="px-4 py-3 font-mono text-[#536177]">{item.username}</td>
                <td className="px-4 py-3">{adminRoleLabel(item.role)}</td>
                <td className="px-4 py-3"><AdminStatus active={item.is_active} /></td>
                <td className="px-4 py-3 tabular-nums">{item.donor_operation_count}</td>
                <td className="px-4 py-3 tabular-nums">{item.user_operation_count}</td>
                <td className="px-4 py-3 tabular-nums">{item.admin_operation_count}</td>
                <td className="px-4 py-3 text-[#768397]">{formatTime(item.last_operation_at)}</td>
                <td className="whitespace-nowrap px-4 py-3"><button type="button" onClick={() => navigate(`/admin/admins/${item.id}`)} className="mr-3 font-medium text-[#1677ff]">查看详情</button>{canManage && item.id !== currentAdminId ? <button type="button" onClick={() => setStateChange({ admin: item, action: item.is_active ? 'delete' : 'restore' })} className={item.is_active ? 'text-rose-600' : 'text-emerald-600'}>{item.is_active ? '删除' : '恢复'}</button> : null}</td>
              </tr>
            ))}
            {loading ? <tr><td colSpan={9} className="py-16 text-center text-sm text-[#8c98aa]">正在加载管理员信息…</td></tr> : null}
            {!loading && !data.items.length ? <tr><td colSpan={9} className="py-16 text-center text-sm text-[#9aa5b5]">暂无管理员</td></tr> : null}
          </tbody>
        </table>
      </StickyTableCard>
      {createOpen ? <AdminCreateDialog busy={busy} onClose={() => setCreateOpen(false)} onConfirm={(values) => void createAdmin(values)} /> : null}
      {stateChange ? <AdminStateDialog admin={stateChange.admin} action={stateChange.action} busy={busy} onClose={() => setStateChange(null)} onConfirm={(reason) => void changeState(reason)} /> : null}
    </div>
  )
}
