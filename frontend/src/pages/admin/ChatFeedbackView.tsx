import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminPageShellClass } from './adminLayout'
import { ErrorNotice } from './AdminUi'
import { formatTime } from './adminFormat'
import { feedbackDetailPath } from './chat/adminChatState'
import {
  adminChatFeedbackApi,
  type AdminFeedbackFilters,
  type AdminFeedbackItem,
  type AdminFeedbackSummary,
} from './chat/adminChatFeedbackApi'

const DEFAULT_FILTERS: AdminFeedbackFilters = { rating: 'dislike', userId: '', dateFrom: '', dateTo: '' }
const EMPTY_SUMMARY: AdminFeedbackSummary = { likes: 0, dislikes: 0, recent_dislikes: 0 }

export function ChatFeedbackView() {
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [items, setItems] = useState<AdminFeedbackItem[]>([])
  const [summary, setSummary] = useState(EMPTY_SUMMARY)
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (reset: boolean) => {
    setLoading(true)
    setError('')
    try {
      const page = await adminChatFeedbackApi.list(filters, reset ? null : cursor)
      setItems((current) => reset ? page.items : [...current, ...page.items])
      setCursor(page.next_cursor)
      setHasMore(page.has_more)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '反馈记录加载失败')
    } finally {
      setLoading(false)
    }
  }, [cursor, filters])

  useEffect(() => {
    void adminChatFeedbackApi.summary().then(setSummary).catch(() => undefined)
  }, [])

  useEffect(() => {
    setCursor(null)
    void load(true)
  // load changes with cursor; filters are the intended refresh trigger.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  function updateFilter<Key extends keyof AdminFeedbackFilters>(key: Key, value: AdminFeedbackFilters[Key]) {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  return <div className={adminPageShellClass()}>
    <div>
      <h1 className="text-xl font-semibold text-[#203149]">对话反馈</h1>
      <p className="mt-1 text-xs text-[#7d899b]">查看用户对具体 AI 回复的喜欢与不喜欢，并定位到完整会话执行记录。</p>
    </div>

    <div className="grid gap-3 sm:grid-cols-3">
      <SummaryCard label="不喜欢" value={summary.dislikes} icon="ri-thumb-down-line" tone="bg-rose-50 text-rose-600" />
      <SummaryCard label="最近 7 天不喜欢" value={summary.recent_dislikes} icon="ri-alarm-warning-line" tone="bg-amber-50 text-amber-700" />
      <SummaryCard label="喜欢" value={summary.likes} icon="ri-thumb-up-line" tone="bg-emerald-50 text-emerald-700" />
    </div>

    <section className="overflow-hidden rounded-xl border border-[#dce4ee] bg-white">
      <div className="flex flex-wrap items-end gap-3 border-b border-[#e4eaf1] bg-[#fbfcfe] px-4 py-3">
        <label className="text-[10px] text-[#758297]">反馈类型<select value={filters.rating} onChange={(event) => updateFilter('rating', event.target.value as AdminFeedbackFilters['rating'])} className="mt-1 block h-9 rounded-lg border border-[#d8e0ea] bg-white px-3 text-xs text-[#34445b]"><option value="dislike">不喜欢</option><option value="like">喜欢</option><option value="">全部</option></select></label>
        <label className="text-[10px] text-[#758297]">用户 UID<input value={filters.userId} inputMode="numeric" onChange={(event) => updateFilter('userId', event.target.value.replace(/\D/g, ''))} className="mt-1 block h-9 w-32 rounded-lg border border-[#d8e0ea] px-3 text-xs" placeholder="全部用户" /></label>
        <label className="text-[10px] text-[#758297]">开始日期<input type="date" value={filters.dateFrom} onChange={(event) => updateFilter('dateFrom', event.target.value)} className="mt-1 block h-9 rounded-lg border border-[#d8e0ea] px-3 text-xs" /></label>
        <label className="text-[10px] text-[#758297]">结束日期<input type="date" value={filters.dateTo} onChange={(event) => updateFilter('dateTo', event.target.value)} className="mt-1 block h-9 rounded-lg border border-[#d8e0ea] px-3 text-xs" /></label>
        <button type="button" onClick={() => setFilters(DEFAULT_FILTERS)} className="h-9 rounded-lg border border-[#d8e0ea] px-3 text-xs text-[#68768a]">重置</button>
      </div>

      {error ? <div className="p-4"><ErrorNotice message={error} /></div> : null}
      {!error && !loading && items.length === 0 ? <div className="py-16 text-center text-xs text-[#96a1b0]">当前筛选条件下暂无反馈</div> : null}
      {items.length ? <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-xs">
        <thead className="bg-[#f7f9fc] text-[10px] text-[#7c899b]"><tr><th className="px-4 py-3">反馈</th><th className="px-4 py-3">用户</th><th className="px-4 py-3">会话位置</th><th className="px-4 py-3">AI 回复摘要</th><th className="px-4 py-3">反馈时间</th><th className="px-4 py-3 text-right">操作</th></tr></thead>
        <tbody className="divide-y divide-[#e8edf3]">{items.map((item) => <tr key={item.message_id} className="hover:bg-[#f9fbfd]">
          <td className="px-4 py-3"><FeedbackBadge rating={item.rating} /></td>
          <td className="px-4 py-3"><div className="font-medium text-[#304159]">{item.user_display}</div><div className="mt-1 font-mono text-[9px] text-[#929dac]">UID {item.user_id}</div></td>
          <td className="px-4 py-3"><div className="font-mono font-medium text-[#405169]">Session #{item.chat_id}</div><div className="mt-1 text-[10px] text-[#8793a4]">{item.branch_name}</div></td>
          <td className="max-w-md px-4 py-3 text-[11px] leading-5 text-[#59677b]"><div className="line-clamp-2">{item.message_preview || '（无正文）'}</div></td>
          <td className="whitespace-nowrap px-4 py-3 text-[10px] text-[#7f8b9c]">{formatTime(item.updated_at)}</td>
          <td className="px-4 py-3 text-right"><Link to={feedbackDetailPath(item)} className="inline-flex h-8 items-center gap-1 rounded-lg bg-[#edf5ff] px-3 text-[10px] font-medium text-[#1677ff] hover:bg-[#dcecff]">查看会话<i className="ri-arrow-right-line" /></Link></td>
        </tr>)}</tbody>
      </table></div> : null}
      {loading ? <div className="py-5 text-center text-xs text-[#8c98a9]">正在加载反馈…</div> : null}
      {hasMore && !loading ? <button type="button" onClick={() => void load(false)} className="w-full border-t border-[#e8edf3] py-3 text-xs font-medium text-[#1677ff]">加载更多</button> : null}
    </section>
  </div>
}

function SummaryCard({ label, value, icon, tone }: { label: string; value: number; icon: string; tone: string }) {
  return <div className="flex items-center gap-3 rounded-xl border border-[#dce4ee] bg-white p-4"><span className={`flex h-10 w-10 items-center justify-center rounded-xl ${tone}`}><i className={icon} /></span><div><div className="text-2xl font-semibold text-[#26374e]">{value}</div><div className="text-[10px] text-[#8490a1]">{label}</div></div></div>
}

function FeedbackBadge({ rating }: { rating: AdminFeedbackItem['rating'] }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[9px] font-semibold ${rating === 'dislike' ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-700'}`}><i className={rating === 'dislike' ? 'ri-thumb-down-fill' : 'ri-thumb-up-fill'} />{rating === 'dislike' ? '不喜欢' : '喜欢'}</span>
}
