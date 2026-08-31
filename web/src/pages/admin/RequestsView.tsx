import { useCallback, useEffect, useState } from 'react'
import { adminFetch, postAdmin } from './adminApi'
import { adminPageShellClass } from './adminLayout'
import { ErrorNotice, PageHeader, Pagination, StickyTableCard } from './AdminUi'
import { formatTime } from './adminFormat'
import type { OperationRequestRecord, PageData } from './types'

const ACTION_LABELS: Record<OperationRequestRecord['action'], string> = {
  donor_create: '新增捐精人档案', donor_update: '修改捐精人档案', donor_status: '变更捐精人状态',
  user_kick: '强制用户下线', user_disable: '停用用户账号', user_enable: '恢复用户账号',
}

const STATUS_LABELS = { pending: '待审核', processing: '执行中', approved: '已通过', rejected: '已驳回', cancelled: '已撤销', failed: '执行失败' }

export function RequestsView({ mode }: { mode: 'mine' | 'review' }) {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PageData<OperationRequestRecord>>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState<OperationRequestRecord | null>(null)
  const [review, setReview] = useState<{ item: OperationRequestRecord; action: 'approve' | 'reject' } | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '20' })
      if (status) params.set('status', status)
      const path = mode === 'mine' ? `/api/admin/requests/mine?${params}` : `/api/admin/requests?${params}`
      setData(await adminFetch(path))
    } catch (err) { setError(err instanceof Error ? err.message : '申请记录加载失败') }
    finally { setLoading(false) }
  }, [mode, page, status])

  useEffect(() => { void load() }, [load])

  async function cancel(item: OperationRequestRecord) {
    setBusy(true); setError(''); setMessage('')
    try { await postAdmin(`/api/admin/requests/${item.id}/cancel`); setMessage(`申请 #${item.id} 已撤销。`); await load() }
    catch (err) { setError(err instanceof Error ? err.message : '撤销失败') }
    finally { setBusy(false) }
  }

  async function submitReview() {
    if (!review) return
    setBusy(true); setError(''); setMessage('')
    try {
      await postAdmin(`/api/admin/requests/${review.item.id}/${review.action}`, { comment: comment.trim() })
      setMessage(`申请 #${review.item.id} ${review.action === 'approve' ? '已批准并执行' : '已驳回'}。`)
      setReview(null); setComment(''); await load()
    } catch (err) { setError(err instanceof Error ? err.message : '审批失败') }
    finally { setBusy(false) }
  }

  return (
    <div className={adminPageShellClass()}>
      <div className="shrink-0">
        <PageHeader title={mode === 'mine' ? '我的申请' : '操作审批'} description={mode === 'mine' ? '查看自己提交的业务操作申请及审批结果。' : '审核普通管理员提交的业务变更，批准后由系统自动执行。'} />
        {error ? <ErrorNotice message={error} /> : null}
        {message ? <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
      </div>
      <StickyTableCard
        toolbar={<div className="flex items-center justify-between border-b border-[#e2e8f0] p-3"><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs"><option value="">全部状态</option>{Object.entries(STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="text-xs text-[#8a96a7]">共 {data.total} 条申请</span></div>}
        footer={<Pagination page={page} pageSize={data.page_size} total={data.total} onChange={setPage} />}
      >
        <table className="w-full min-w-[980px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[#f7f9fc] text-[#667389]"><tr><th className="px-4 py-3 font-medium">申请</th>{mode === 'review' ? <th className="px-4 py-3 font-medium">申请人</th> : null}<th className="px-4 py-3 font-medium">目标</th><th className="px-4 py-3 font-medium">理由</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">提交时间</th><th className="px-4 py-3 font-medium">操作</th></tr></thead>
          <tbody className="divide-y divide-[#e5eaf1]">
            {data.items.map((item) => <tr key={item.id} className="hover:bg-[#f8fbff]"><td className="px-4 py-3"><div className="font-medium text-[#293a52]">{ACTION_LABELS[item.action]}</div><div className="mt-1 text-[10px] text-[#929dab]">#{item.id}</div></td>{mode === 'review' ? <td className="px-4 py-3">{item.requester_name || `管理员 ${item.requester_id}`}</td> : null}<td className="px-4 py-3 font-mono">{item.target_type === 'user' ? `UID ${item.target_id}` : item.target_id}</td><td className="max-w-xs truncate px-4 py-3 text-[#657287]" title={item.reason}>{item.reason}</td><td className="px-4 py-3"><RequestStatus status={item.status} /></td><td className="px-4 py-3 text-[#7d899a]">{formatTime(item.created_at)}</td><td className="whitespace-nowrap px-4 py-3"><button onClick={() => setSelected(item)} className="mr-3 text-[#1677ff]">详情</button>{mode === 'mine' && item.status === 'pending' ? <button disabled={busy} onClick={() => void cancel(item)} className="text-rose-600">撤销</button> : null}{mode === 'review' && item.status === 'pending' ? <><button onClick={() => { setReview({ item, action: 'approve' }); setComment('') }} className="mr-3 text-emerald-600">批准</button><button onClick={() => { setReview({ item, action: 'reject' }); setComment('') }} className="text-rose-600">驳回</button></> : null}</td></tr>)}
            {loading ? <tr><td colSpan={mode === 'review' ? 7 : 6} className="py-16 text-center text-sm text-[#8c98aa]">正在加载申请…</td></tr> : null}
            {!loading && !data.items.length ? <tr><td colSpan={mode === 'review' ? 7 : 6} className="py-16 text-center text-sm text-[#9aa5b5]">暂无申请记录</td></tr> : null}
          </tbody>
        </table>
      </StickyTableCard>
      {selected ? <RequestDetail item={selected} onClose={() => setSelected(null)} /> : null}
      {review ? <ReviewDialog action={review.action} item={review.item} comment={comment} busy={busy} onComment={setComment} onClose={() => setReview(null)} onConfirm={() => void submitReview()} /> : null}
    </div>
  )
}

function RequestStatus({ status }: { status: OperationRequestRecord['status'] }) {
  const color = { pending: 'bg-amber-50 text-amber-700', processing: 'bg-blue-50 text-blue-700', approved: 'bg-emerald-50 text-emerald-700', rejected: 'bg-rose-50 text-rose-700', cancelled: 'bg-slate-100 text-slate-600', failed: 'bg-red-50 text-red-700' }[status]
  return <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${color}`}>{STATUS_LABELS[status]}</span>
}

function RequestDetail({ item, onClose }: { item: OperationRequestRecord; onClose: () => void }) {
  return <div className="fixed inset-0 z-50 flex justify-end bg-[#0b1729]/45"><div className="h-full w-full max-w-2xl overflow-y-auto bg-white p-6 shadow-2xl"><div className="flex justify-between"><div><h2 className="text-lg font-semibold">申请 #{item.id}</h2><p className="mt-1 text-xs text-[#7d899a]">{ACTION_LABELS[item.action]} · {formatTime(item.created_at)}</p></div><button onClick={onClose} className="h-8 w-8 rounded-lg text-xl text-[#7f8b9d] hover:bg-[#f1f5f9]"><i className="ri-close-line" /></button></div><div className="mt-5 grid gap-3 rounded-xl border border-[#e2e8f0] p-4 text-xs sm:grid-cols-2"><Info label="申请人" value={item.requester_name || `管理员 ${item.requester_id}`} /><Info label="目标" value={item.target_type === 'user' ? `UID ${item.target_id}` : item.target_id} /><Info label="状态" value={STATUS_LABELS[item.status]} /><Info label="审批人" value={item.reviewer_name || '—'} /><div className="sm:col-span-2"><Info label="申请理由" value={item.reason} /></div>{item.review_comment ? <div className="sm:col-span-2"><Info label="审批意见" value={item.review_comment} /></div> : null}{item.execution_error ? <div className="sm:col-span-2"><Info label="执行错误" value={item.execution_error} /></div> : null}</div><JsonBlock title="申请执行数据" value={item.payload} /><JsonBlock title="申请时数据快照" value={item.before_snapshot} /></div></div>
}

function ReviewDialog({ action, item, comment, busy, onComment, onClose, onConfirm }: { action: 'approve' | 'reject'; item: OperationRequestRecord; comment: string; busy: boolean; onComment: (value: string) => void; onClose: () => void; onConfirm: () => void }) {
  const rejecting = action === 'reject'
  return <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0b1729]/45 px-4"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl"><h2 className="text-base font-semibold">{rejecting ? '驳回' : '批准并执行'}申请 #{item.id}</h2><p className="mt-2 text-xs leading-5 text-[#6f7c90]">{ACTION_LABELS[item.action]}，目标 {item.target_id}。{rejecting ? '请说明驳回原因。' : '批准后系统将立即执行，并检查数据是否在申请后发生变化。'}</p><textarea autoFocus value={comment} onChange={(event) => onComment(event.target.value)} placeholder={rejecting ? '驳回原因（至少 2 个字）' : '审批意见（可选）'} className="mt-4 h-24 w-full resize-none rounded-lg border border-[#d8e0eb] px-3 py-2 text-sm outline-none focus:border-[#1677ff]" /><div className="mt-4 flex justify-end gap-2"><button disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs">取消</button><button disabled={busy || (rejecting && comment.trim().length < 2)} onClick={onConfirm} className={`rounded-lg px-4 py-2 text-xs font-medium text-white disabled:opacity-45 ${rejecting ? 'bg-rose-600' : 'bg-emerald-600'}`}>{busy ? '处理中…' : rejecting ? '确认驳回' : '批准并执行'}</button></div></div></div>
}

function JsonBlock({ title, value }: { title: string; value: unknown }) { return <section className="mt-4"><h3 className="mb-2 text-sm font-medium">{title}</h3><pre className="max-h-80 overflow-auto rounded-lg bg-[#f6f8fb] p-3 text-[11px] leading-5 text-[#526177]">{JSON.stringify(value || {}, null, 2)}</pre></section> }
function Info({ label, value }: { label: string; value: string }) { return <div><div className="text-[10px] text-[#929dad]">{label}</div><div className="mt-1 break-words text-xs text-[#35455d]">{value}</div></div> }

