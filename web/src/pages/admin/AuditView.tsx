import { useEffect, useState } from 'react'
import { adminFetch } from './adminApi'
import { ErrorNotice, PageHeader } from './AdminUi'
import { formatTime } from './adminFormat'
import type { DonorAuditRow, PageData } from './types'

export function AuditView() {
  const [data, setData] = useState<PageData<DonorAuditRow>>({ items: [], total: 0, page: 1, page_size: 50 })
  const [error, setError] = useState('')
  useEffect(() => { adminFetch<PageData<DonorAuditRow>>('/api/admin/audit?page=1&page_size=50').then(setData).catch((err) => setError(err instanceof Error ? err.message : '审计记录加载失败')) }, [])
  return <div><PageHeader title="操作审计" description="查看捐献者档案的创建、修改及启停操作。用户账号操作记录在对应用户档案中查看。" />{error ? <ErrorNotice message={error} /> : null}<div className="overflow-hidden rounded-xl border border-[#dce4ee] bg-white"><table className="w-full min-w-[720px] text-left text-xs"><thead className="bg-[#f7f9fc] text-[#667389]"><tr><th className="px-4 py-3 font-medium">时间</th><th className="px-4 py-3 font-medium">捐献者代号</th><th className="px-4 py-3 font-medium">操作</th><th className="px-4 py-3 font-medium">操作人</th></tr></thead><tbody className="divide-y divide-[#e5eaf1]">{data.items.map((item) => <tr key={item.id}><td className="px-4 py-3">{formatTime(item.created_at)}</td><td className="px-4 py-3 font-medium text-[#1d4f91]">{item.donor_code}</td><td className="px-4 py-3">{item.action}</td><td className="px-4 py-3">{item.operator_id || '—'}</td></tr>)}</tbody></table>{!data.items.length ? <div className="py-16 text-center text-sm text-[#9aa5b5]">暂无审计记录</div> : null}</div></div>
}
