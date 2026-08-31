import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminFetch } from './adminApi'
import { ErrorNotice, PageHeader } from './AdminUi'
import type { PageData, UserSummary } from './types'

export function DashboardView() {
  const [users, setUsers] = useState<UserSummary>({ total: 0, active: 0, disabled: 0, today_new: 0 })
  const [donors, setDonors] = useState(0)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([
      adminFetch<UserSummary>('/api/admin/users/summary'),
      adminFetch<PageData<unknown>>('/api/admin/donors?page=1&page_size=1'),
    ]).then(([userData, donorData]) => { setUsers(userData); setDonors(donorData.total) }).catch((err) => setError(err instanceof Error ? err.message : '工作台加载失败'))
  }, [])
  const cards = [
    { label: '用户总数', value: users.total, note: `今日新增 ${users.today_new}`, color: 'bg-blue-50 text-blue-600', icon: 'ri-group-line' },
    { label: '正常用户', value: users.active, note: '可正常登录使用', color: 'bg-emerald-50 text-emerald-600', icon: 'ri-user-follow-line' },
    { label: '已停用用户', value: users.disabled, note: '账号访问已阻止', color: 'bg-rose-50 text-rose-600', icon: 'ri-user-unfollow-line' },
    { label: '捐献者档案', value: donors, note: '当前档案总量', color: 'bg-violet-50 text-violet-600', icon: 'ri-archive-line' },
  ]
  return <div><PageHeader title="工作台" description="查看平台用户与捐献者档案的关键运营数据。" />{error ? <ErrorNotice message={error} /> : null}<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map((card) => <div key={card.label} className="rounded-xl border border-[#dce4ee] bg-white p-5"><div className="flex items-start justify-between"><div><div className="text-xs text-[#738096]">{card.label}</div><div className="mt-2 text-3xl font-semibold">{card.value}</div><div className="mt-2 text-[11px] text-[#8e99a9]">{card.note}</div></div><div className={`flex h-11 w-11 items-center justify-center rounded-xl ${card.color}`}><i className={`${card.icon} text-xl`} /></div></div></div>)}</div><div className="mt-4 grid gap-4 lg:grid-cols-2"><QuickLink to="/admin/users" icon="ri-user-search-line" title="管理用户档案" description="查看账号状态、收藏、浏览历史和 AI 会话。" /><QuickLink to="/admin/donors" icon="ri-archive-drawer-line" title="维护捐献者档案" description="检索、编辑、启停捐献者及查看库存。" /></div></div>
}

function QuickLink({ to, icon, title, description }: { to: string; icon: string; title: string; description: string }) {
  return <Link to={to} className="group flex items-center gap-4 rounded-xl border border-[#dce4ee] bg-white p-5 transition hover:border-[#9fc7ff] hover:shadow-sm"><div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#edf5ff] text-[#1677ff]"><i className={`${icon} text-xl`} /></div><div className="flex-1"><div className="text-sm font-medium">{title}</div><div className="mt-1 text-xs text-[#8390a2]">{description}</div></div><i className="ri-arrow-right-s-line text-[#a5afbd] transition group-hover:translate-x-0.5 group-hover:text-[#1677ff]" /></Link>
}
