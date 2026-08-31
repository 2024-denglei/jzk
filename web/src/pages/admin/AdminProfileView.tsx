import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminFetch } from './adminApi'
import { AdminStatus, ErrorNotice, Pagination } from './AdminUi'
import { adminRoleLabel, auditActionLabel, formatTime } from './adminFormat'
import type { AdminAuditRecord, AdminRecord, PageData } from './types'

const EMPTY_AUDIT: PageData<AdminAuditRecord> = { items: [], total: 0, page: 1, page_size: 30 }

export function AdminProfileView({ adminId, currentAdminId }: { adminId: number; currentAdminId: number }) {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<AdminRecord | null>(null)
  const [audits, setAudits] = useState<PageData<AdminAuditRecord>>(EMPTY_AUDIT)
  const [source, setSource] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProfile = useCallback(async () => {
    try { setProfile(await adminFetch(`/api/admin/admins/${adminId}`)) }
    catch (err) { setError(err instanceof Error ? err.message : '管理员资料加载失败') }
  }, [adminId])

  const loadAudit = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page), page_size: '30' })
    if (source) params.set('source', source)
    try { setAudits(await adminFetch(`/api/admin/admins/${adminId}/audit?${params}`)) }
    catch (err) { setError(err instanceof Error ? err.message : '操作审计加载失败') }
  }, [adminId, page, source])

  useEffect(() => {
    setLoading(true); setError('')
    Promise.all([loadProfile(), loadAudit()]).finally(() => setLoading(false))
  }, [loadAudit, loadProfile])

  if (loading && !profile) return <div className="py-24 text-center text-sm text-[#8793a5]">正在加载管理员资料…</div>
  if (!profile) return <div>{error ? <ErrorNotice message={error} /> : null}<button onClick={() => navigate('/admin/admins')} className="text-sm text-[#1677ff]">返回管理员中心</button></div>

  return (
    <div>
      <button onClick={() => navigate('/admin/admins')} className="mb-4 inline-flex items-center gap-1 text-xs text-[#617086] hover:text-[#1677ff]"><i className="ri-arrow-left-line" />返回管理员中心</button>
      {error ? <ErrorNotice message={error} /> : null}
      <section className="rounded-xl border border-[#dce4ee] bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-[#e8f2ff] text-xl font-semibold text-[#1677ff]">{(profile.display_name || profile.username).slice(0, 1)}</div>
            <div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold">{profile.display_name || '未设置姓名'}</h1><AdminStatus active={profile.is_active} />{profile.id === currentAdminId ? <span className="rounded bg-blue-50 px-2 py-1 text-[10px] text-blue-600">当前登录管理员</span> : null}</div><div className="mt-1 font-mono text-xs text-[#7d899a]">{profile.username} · Admin ID {profile.id}</div></div>
          </div>
          <span className="rounded-lg border border-[#dbe5f2] bg-[#f7faff] px-3 py-2 text-xs font-medium text-[#365478]">{adminRoleLabel(profile.role)}</span>
        </div>
        <div className="mt-5 grid gap-3 border-t border-[#e5eaf1] pt-4 sm:grid-cols-2 xl:grid-cols-5">
          <Info label="全部操作" value={String(profile.operation_count)} />
          <Info label="捐精人档案操作" value={String(profile.donor_operation_count)} />
          <Info label="用户管理操作" value={String(profile.user_operation_count)} />
          <Info label="最近操作" value={formatTime(profile.last_operation_at)} />
          <Info label="创建时间" value={formatTime(profile.created_at)} />
        </div>
        {profile.action_counts?.length ? <div className="mt-4 flex flex-wrap gap-2 border-t border-[#edf1f5] pt-4">{profile.action_counts.map((item) => <span key={`${item.source}-${item.action}`} className="rounded-md bg-[#f1f5f9] px-2.5 py-1.5 text-[10px] text-[#5e6d82]">{auditActionLabel(item.action, item.source)} <b className="ml-1 tabular-nums text-[#34445b]">{item.count}</b></span>)}</div> : null}
      </section>

      <section className="mt-4 overflow-hidden rounded-xl border border-[#dce4ee] bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e2e8f0] px-5 py-3">
          <div><h2 className="text-sm font-semibold text-[#27364d]">操作审计</h2><p className="mt-1 text-[10px] text-[#8b97a8]">仅显示该管理员执行的操作。</p></div>
          <select value={source} onChange={(event) => { setSource(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs"><option value="">全部业务</option><option value="donor">捐精人档案</option><option value="user">用户管理</option></select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-xs">
            <thead className="bg-[#f7f9fc] text-[#667389]"><tr><th className="px-4 py-3 font-medium">时间</th><th className="px-4 py-3 font-medium">业务</th><th className="px-4 py-3 font-medium">操作</th><th className="px-4 py-3 font-medium">操作对象</th><th className="px-4 py-3 font-medium">原因</th><th className="px-4 py-3 font-medium">数据详情</th></tr></thead>
            <tbody className="divide-y divide-[#e5eaf1]">{audits.items.map((item) => <AuditRow key={`${item.source}-${item.record_id}`} item={item} />)}{!audits.items.length ? <tr><td colSpan={6} className="py-16 text-center text-sm text-[#9aa5b5]">该管理员暂无操作记录</td></tr> : null}</tbody>
          </table>
        </div>
        <Pagination page={page} pageSize={audits.page_size} total={audits.total} onChange={setPage} />
      </section>
    </div>
  )
}

function AuditRow({ item }: { item: AdminAuditRecord }) {
  const hasDetails = item.before_data != null || item.after_data != null
  return <tr className="align-top hover:bg-[#f8fbff]"><td className="whitespace-nowrap px-4 py-3 text-[#758296]">{formatTime(item.created_at)}</td><td className="px-4 py-3"><span className={`rounded px-2 py-1 text-[10px] ${item.source === 'donor' ? 'bg-violet-50 text-violet-700' : 'bg-blue-50 text-blue-700'}`}>{item.source === 'donor' ? '捐精人档案' : '用户管理'}</span></td><td className="px-4 py-3 font-medium text-[#34445b]">{auditActionLabel(item.action, item.source)}</td><td className="px-4 py-3"><div className="font-medium text-[#45546a]">{item.target_name || '—'}</div>{item.target_id ? <div className="mt-0.5 font-mono text-[10px] text-[#9aa5b5]">ID {item.target_id}</div> : null}</td><td className="max-w-[260px] px-4 py-3 text-[#68768a]">{item.reason || '—'}</td><td className="px-4 py-3">{hasDetails ? <details><summary className="cursor-pointer text-[#1677ff]">查看变更</summary><div className="mt-2 grid w-[520px] max-w-[65vw] gap-2 sm:grid-cols-2"><JsonBox title="变更前" value={item.before_data} /><JsonBox title="变更后" value={item.after_data} /></div></details> : <span className="text-[#a0aaba]">—</span>}</td></tr>
}

function JsonBox({ title, value }: { title: string; value: unknown }) {
  return <div className="overflow-hidden rounded-lg border border-[#e1e7ef]"><div className="border-b border-[#e8edf3] bg-[#f7f9fc] px-2 py-1 text-[10px] text-[#788599]">{title}</div><pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words p-2 text-[10px] leading-4 text-[#536177]">{value == null ? '—' : JSON.stringify(value, null, 2)}</pre></div>
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[11px] text-[#929dad]">{label}</div><div className="mt-1 text-xs font-medium text-[#35455d]">{value}</div></div>
}
