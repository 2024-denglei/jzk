import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminFetch, postAdmin } from './adminApi'
import { ErrorNotice, PageHeader, Pagination, StatusBadge } from './AdminUi'
import { formatTime } from './adminFormat'
import { UserControlDialog, type UserControlAction } from './UserControlDialog'
import type { PageData, UserArchive, UserSummary } from './types'

const EMPTY_SUMMARY: UserSummary = { total: 0, active: 0, disabled: 0, today_new: 0 }

export function UsersView() {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<UserSummary>(EMPTY_SUMMARY)
  const [data, setData] = useState<PageData<UserArchive>>({ items: [], total: 0, page: 1, page_size: 20 })
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [control, setControl] = useState<{ user: UserArchive; action: UserControlAction } | null>(null)
  const [controlBusy, setControlBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '20' })
      if (query) params.set('q', query)
      if (status) params.set('status', status)
      const [nextSummary, nextData] = await Promise.all([
        adminFetch<UserSummary>('/api/admin/users/summary'),
        adminFetch<PageData<UserArchive>>(`/api/admin/users?${params}`),
      ])
      setSummary(nextSummary)
      setData(nextData)
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户档案加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, query, status])

  useEffect(() => {
    void load()
  }, [load])

  async function confirmControl(reason: string) {
    if (!control) return
    setControlBusy(true)
    setError('')
    try {
      await postAdmin(`/api/admin/users/${control.user.id}/${control.action}`, { reason })
      setControl(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setControlBusy(false)
    }
  }

  const cards = [
    { label: '用户总数', value: summary.total, icon: 'ri-group-line', color: 'text-[#1677ff]', bg: 'bg-blue-50' },
    { label: '正常用户', value: summary.active, icon: 'ri-user-follow-line', color: 'text-emerald-600', bg: 'bg-emerald-50' },
    { label: '已停用', value: summary.disabled, icon: 'ri-user-unfollow-line', color: 'text-rose-600', bg: 'bg-rose-50' },
    { label: '今日新增', value: summary.today_new, icon: 'ri-user-add-line', color: 'text-violet-600', bg: 'bg-violet-50' },
  ]

  return (
    <div>
      <PageHeader title="用户档案" description="统一查看用户资料、账号状态、收藏、浏览历史和 AI 会话记录。" />
      {error ? <ErrorNotice message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="rounded-xl border border-[#dce4ee] bg-white p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-[#738096]">{card.label}</div>
                <div className="mt-2 text-2xl font-semibold text-[#132238]">{card.value}</div>
              </div>
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${card.bg} ${card.color}`}><i className={`${card.icon} text-xl`} /></div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 rounded-xl border border-[#dce4ee] bg-white">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setPage(1)
            setQuery(draft.trim())
          }}
          className="flex flex-wrap gap-2 border-b border-[#e2e8f0] p-3"
        >
          <div className="relative min-w-[240px] flex-1 lg:max-w-sm">
            <i className="ri-search-line absolute left-3 top-2.5 text-sm text-[#9ba6b6]" />
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="用户 ID、昵称、手机号或邮箱"
              className="h-9 w-full rounded-lg border border-[#d9e1ec] pl-9 pr-3 text-xs outline-none focus:border-[#1677ff]"
            />
          </div>
          <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs text-[#4d5c72] outline-none">
            <option value="">全部状态</option>
            <option value="active">正常</option>
            <option value="disabled">已停用</option>
          </select>
          <button type="submit" className="h-9 rounded-lg bg-[#1677ff] px-4 text-xs font-medium text-white">查询</button>
          <button type="button" onClick={() => { setDraft(''); setQuery(''); setStatus(''); setPage(1) }} className="h-9 px-3 text-xs text-[#6d798c]">重置</button>
        </form>

        <div className="overflow-x-auto">
          <table className="min-w-[1050px] w-full text-left text-xs">
            <thead className="bg-[#f7f9fc] text-[#667389]">
              <tr>
                <th className="px-4 py-3 font-medium">用户</th>
                <th className="px-4 py-3 font-medium">联系方式</th>
                <th className="px-4 py-3 font-medium">注册时间</th>
                <th className="px-4 py-3 font-medium">最近登录</th>
                <th className="px-4 py-3 text-center font-medium">收藏</th>
                <th className="px-4 py-3 text-center font-medium">历史</th>
                <th className="px-4 py-3 text-center font-medium">会话</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e5eaf1]">
              {data.items.map((user) => (
                <tr key={user.id} className="transition hover:bg-[#f8fbff]">
                  <td className="px-4 py-3">
                    <button onClick={() => navigate(`/admin/users/${user.id}`)} className="text-left">
                      <div className="font-medium text-[#1d4f91]">{user.nickname || '未设置昵称'}</div>
                      <div className="mt-1 text-[11px] text-[#98a3b2]">UID {user.id}</div>
                    </button>
                  </td>
                  <td className="px-4 py-3 text-[#526177]"><div>{user.phone || '—'}</div><div className="mt-1 text-[11px] text-[#8794a6]">{user.email}</div></td>
                  <td className="px-4 py-3 text-[#526177]">{formatTime(user.created_at)}</td>
                  <td className="px-4 py-3 text-[#526177]">{formatTime(user.last_login_at)}</td>
                  <td className="px-4 py-3 text-center">{user.favorite_count}</td>
                  <td className="px-4 py-3 text-center">{user.history_count}</td>
                  <td className="px-4 py-3 text-center">{user.chat_count}</td>
                  <td className="px-4 py-3"><StatusBadge status={user.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <button onClick={() => navigate(`/admin/users/${user.id}`)} className="mr-3 text-[#1677ff]">查看</button>
                    <button onClick={() => setControl({ user, action: 'kick' })} className="mr-3 text-amber-600">下线</button>
                    <button onClick={() => setControl({ user, action: user.status === 'active' ? 'disable' : 'enable' })} className={user.status === 'active' ? 'text-rose-600' : 'text-emerald-600'}>
                      {user.status === 'active' ? '停用' : '恢复'}
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && data.items.length === 0 ? <tr><td colSpan={9} className="py-16 text-center text-sm text-[#9aa5b5]">没有符合条件的用户</td></tr> : null}
              {loading ? <tr><td colSpan={9} className="py-16 text-center text-sm text-[#8c98aa]">正在加载用户档案…</td></tr> : null}
            </tbody>
          </table>
        </div>
        <Pagination page={page} pageSize={data.page_size || 20} total={data.total} onChange={setPage} />
      </div>

      {control ? (
        <UserControlDialog
          action={control.action}
          userName={`${control.user.nickname || '用户'}（UID ${control.user.id}）`}
          busy={controlBusy}
          onClose={() => setControl(null)}
          onConfirm={(reason) => void confirmControl(reason)}
        />
      ) : null}
    </div>
  )
}
