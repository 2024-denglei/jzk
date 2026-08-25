import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChatPanel } from '../components/ChatPanel'
import { DonorCard, DonorCardSkeleton } from '../components/DonorCard'
import { DonorDetailPanel } from '../components/DonorDetailPanel'
import { FilterPanel } from '../components/FilterPanel'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { Candidate, FilterState } from '../types'
import { DEFAULT_PRIORITY, EMPTY_FILTERS } from '../types'

const MODE_META = {
  featured: { label: '推荐浏览', title: '全部捐献者', blurb: '按标本数量优先展示' },
  search: { label: '条件筛选', title: '筛选结果', blurb: '根据左侧条件匹配' },
  chat: { label: '对话推荐', title: '对话结果', blurb: '已根据顾问对话更新' },
} as const

export function DonorsPage() {
  const { user, loading: authLoading } = useAuth()
  const { code: detailCode } = useParams<{ code?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const seedFromNav = (location.state as { askAbout?: string } | null)?.askAbout || null
  const showingDetail = Boolean(detailCode)
  const chatIdParam = searchParams.get('chatId')
  const [resumeChatId, setResumeChatId] = useState<number | null>(() => {
    const n = chatIdParam ? Number(chatIdParam) : NaN
    return Number.isFinite(n) ? n : null
  })

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('jzk_filter_collapsed') === '1')
  const [filters, setFilters] = useState<FilterState>({ ...EMPTY_FILTERS })
  const [priority, setPriority] = useState<string[]>([...DEFAULT_PRIORITY])
  const [items, setItems] = useState<Candidate[]>([])
  const [mode, setMode] = useState<'featured' | 'search' | 'chat'>('featured')
  const [hint, setHint] = useState('')
  const [searching, setSearching] = useState(false)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [seedMessage, setSeedMessage] = useState<string | null>(seedFromNav)
  const [error, setError] = useState('')
  const [syncToast, setSyncToast] = useState('')
  const [listKey, setListKey] = useState(0)
  const [mobileFilter, setMobileFilter] = useState(false)
  const [mobileChat, setMobileChat] = useState(false)

  useEffect(() => {
    localStorage.setItem('jzk_filter_collapsed', collapsed ? '1' : '0')
  }, [collapsed])

  useEffect(() => {
    if (seedFromNav) {
      setSeedMessage(`请帮我了解代号 ${seedFromNav} 的捐献者，并给出匹配建议`)
      setMobileChat(true)
    }
  }, [seedFromNav])

  useEffect(() => {
    if (!user) return
    void (async () => {
      try {
        const pref = await api.get<{ filters: Partial<FilterState>; priority: string[] }>(
          '/api/user/preferences',
        )
        if (pref.filters && Object.keys(pref.filters).length) {
          setFilters({ ...EMPTY_FILTERS, ...pref.filters })
        }
        if (pref.priority?.length) setPriority(pref.priority)
      } catch {
        /* ignore */
      }
    })()
  }, [user])

  useEffect(() => {
    if (!syncToast) return
    const t = setTimeout(() => setSyncToast(''), 2600)
    return () => clearTimeout(t)
  }, [syncToast])

  function flashList(nextMode: 'featured' | 'search' | 'chat', toast?: string) {
    setMode(nextMode)
    setListKey((k) => k + 1)
    if (toast) setSyncToast(toast)
  }

  async function loadFeatured(p = 1) {
    setError('')
    setLoading(true)
    try {
      const data = await api.get<{
        items: Candidate[]
        total: number
        page: number
        total_pages: number
      }>(`/api/featured?page=${p}&page_size=12`)
      setItems(data.items)
      setPage(data.page)
      setTotalPages(data.total_pages)
      setTotal(data.total)
      setHint(MODE_META.featured.blurb)
      flashList('featured')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadFeatured(1)
  }, [])

  async function doSearch() {
    const hasAny = Object.values(filters).some((v) => (Array.isArray(v) ? v.length > 0 : !!v))
    if (!hasAny) {
      setError('请至少选择一个筛选条件')
      return
    }
    setSearching(true)
    setError('')
    setLoading(true)
    try {
      const body = {
        education: filters.education.length ? filters.education : null,
        blood_type: filters.blood_type.length ? filters.blood_type : null,
        rh_blood: filters.rh_blood.length ? filters.rh_blood : null,
        height: filters.height || null,
        age: filters.age || null,
        figure: filters.figure.length ? filters.figure : null,
        skin_color: filters.skin_color.length ? filters.skin_color : null,
        face_shape: filters.face_shape.length ? filters.face_shape : null,
        eyelid: filters.eyelid.length ? filters.eyelid : null,
        lip_shape: filters.lip_shape.length ? filters.lip_shape : null,
        constellation: filters.constellation.length ? filters.constellation : null,
        hometown: filters.hometown.length ? filters.hometown : null,
        ethnicity: filters.ethnicity.length ? filters.ethnicity : null,
        occupation: filters.occupation.length ? filters.occupation : null,
        personality: filters.personality.length ? filters.personality : null,
        specimen_min: filters.specimen_min ? parseInt(filters.specimen_min, 10) : null,
        priority,
        top_k: 100,
      }
      const data = await api.post<{
        items: Candidate[]
        match_level?: string
        relaxed_hint?: string
      }>('/api/search', body)
      setItems(data.items || [])
      setTotal(data.items?.length || 0)
      setTotalPages(1)
      setPage(1)
      const level =
        data.match_level === 'full'
          ? '完全匹配'
          : data.match_level === 'relaxed'
            ? '部分条件已放宽'
            : '按相似度排序'
      setHint(level + (data.relaxed_hint ? ` · ${data.relaxed_hint}` : ''))
      flashList('search', '已根据筛选条件更新结果')
      setMobileFilter(false)
      if (user) {
        void api.post('/api/user/history', {
          kind: 'search',
          payload: { filters, priority, count: data.items?.length || 0 },
        })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '搜索失败')
    } finally {
      setSearching(false)
      setLoading(false)
    }
  }

  async function savePref() {
    if (!user) {
      setError('请先登录后再保存偏好')
      return
    }
    try {
      await api.post('/api/user/preferences', { filters, priority })
      setSyncToast('偏好已保存')
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    }
  }

  const meta = MODE_META[mode]

  const filterProps = {
    collapsed,
    onToggle: () => setCollapsed((v) => !v),
    filters,
    setFilters,
    priority,
    setPriority,
    onSearch: () => void doSearch(),
    onClear: () => {
      setFilters({ ...EMPTY_FILTERS })
      void loadFeatured(1)
    },
    onSavePref: user ? () => void savePref() : undefined,
    searching,
  }

  const chatProps = {
    seedMessage,
    onSeedConsumed: () => setSeedMessage(null),
    resumeChatId,
    onResumeConsumed: () => {
      setResumeChatId(null)
      if (searchParams.has('chatId')) {
        const next = new URLSearchParams(searchParams)
        next.delete('chatId')
        setSearchParams(next, { replace: true })
      }
    },
    onCandidates: (cands: Candidate[]) => {
      setItems(cands)
      setTotal(cands.length)
      setHint(MODE_META.chat.blurb)
      setLoading(false)
      flashList('chat', '已根据对话更新中间结果')
      setMobileChat(false)
      if (showingDetail) navigate('/donors')
    },
    onSessionPersist: (payload: {
      session_id: string
      messages: { role: string; content: string }[]
      candidates: Candidate[]
    }) => {
      if (!user) return
      void api.post('/api/user/chats', {
        session_id: payload.session_id,
        messages: payload.messages,
        candidates: payload.candidates,
      })
    },
  }

  function handleAskAbout(code: string) {
    setSeedMessage(`请帮我了解代号 ${code} 的捐献者，并给出匹配建议`)
    setMobileChat(true)
  }

  if (showingDetail && !authLoading && !user) {
    return (
      <Navigate
        to={`/login?next=${encodeURIComponent(`/donors/${detailCode}`)}`}
        replace
      />
    )
  }

  return (
    <div className="relative flex h-full min-h-0 bg-[linear-gradient(180deg,#f7fbfc_0%,#f4f8f9_40%,#eef5f6_100%)]">
      <FilterPanel {...filterProps} />

      <section className="relative flex min-w-0 flex-1 flex-col">
        {showingDetail ? (
          <>
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line/60 bg-white/70 px-4 py-3 backdrop-blur-sm md:px-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="font-display text-[17px] font-bold text-ink md:text-[18px]">
                    捐献者详情
                  </h1>
                  <span className="rounded-md bg-mist/80 px-2 py-0.5 text-[11px] font-medium text-teal-deep">
                    {detailCode}
                  </span>
                </div>
                <p className="mt-0.5 text-[11.5px] text-ink-soft/45">左右栏保持可用 · 可随时返回列表</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => navigate('/donors')}
                  className="flex h-9 items-center gap-1 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep"
                >
                  <i className="ri-arrow-left-line" />
                  返回列表
                </button>
                <button
                  type="button"
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 lg:hidden"
                  onClick={() => setMobileFilter(true)}
                >
                  <i className="ri-filter-3-line" />
                  筛选
                </button>
                <button
                  type="button"
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 xl:hidden"
                  onClick={() => setMobileChat(true)}
                >
                  <i className="ri-chat-smile-3-line" />
                  顾问
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              <DonorDetailPanel
                code={detailCode!}
                onBack={() => navigate('/donors')}
                onAskAbout={handleAskAbout}
              />
            </div>
          </>
        ) : (
          <>
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-line/60 bg-white/70 px-4 py-3 backdrop-blur-sm md:px-5">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="font-display text-[17px] font-bold text-ink md:text-[18px]">
                    {meta.title}
                  </h1>
                  <span className="rounded-md bg-mist/80 px-2 py-0.5 text-[11px] font-medium text-teal-deep">
                    {meta.label}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-[11.5px] text-ink-soft/45">
                  {hint || meta.blurb} · 点击卡片查看详情
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {mode === 'chat' && (
                  <button
                    type="button"
                    onClick={() => void loadFeatured(1)}
                    className="flex h-9 items-center gap-1 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep"
                  >
                    <i className="ri-arrow-left-line" />
                    返回列表
                  </button>
                )}
                <div className="hidden text-right sm:block">
                  <div className="text-[15px] font-semibold tabular-nums text-ink">
                    {total || items.length}
                  </div>
                  <div className="text-[10px] text-ink-soft/40">位候选人</div>
                </div>
                <button
                  type="button"
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 lg:hidden"
                  onClick={() => setMobileFilter(true)}
                >
                  <i className="ri-filter-3-line" />
                  筛选
                </button>
                <button
                  type="button"
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-[12px] font-medium text-ink-soft/70 xl:hidden"
                  onClick={() => setMobileChat(true)}
                >
                  <i className="ri-chat-smile-3-line" />
                  顾问
                </button>
              </div>
            </div>

            {error && (
              <div className="border-b border-amber-100 bg-amber-50/90 px-4 py-2 text-[12px] text-amber-900/80">
                {error}
              </div>
            )}

            <div className="scroll-y flex-1 overflow-y-auto px-3 py-4 md:px-5">
              {loading && items.length === 0 ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <DonorCardSkeleton key={i} />
                  ))}
                </div>
              ) : items.length === 0 ? (
                <div className="flex min-h-[280px] flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-white/50 px-6 text-center">
                  <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-mist text-teal-deep">
                    <i className="ri-user-search-line text-xl" />
                  </div>
                  <div className="text-[14px] font-medium text-ink-soft/70">暂无匹配结果</div>
                  <p className="mt-1 max-w-xs text-[12px] text-ink-soft/40">
                    可调整左侧条件，或向右侧顾问描述您的期望
                  </p>
                </div>
              ) : (
                <div key={listKey} className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {items.map((c, i) => (
                    <DonorCard key={c.donor_info.code} candidate={c} index={i} />
                  ))}
                </div>
              )}

              {mode === 'featured' && totalPages > 1 && (
                <div className="mt-6 flex items-center justify-center gap-1.5">
                  <button
                    type="button"
                    disabled={page <= 1 || loading}
                    className="h-9 rounded-lg border border-line bg-white px-3 text-[12px] text-ink-soft/70 disabled:opacity-35"
                    onClick={() => void loadFeatured(page - 1)}
                  >
                    上一页
                  </button>
                  {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                    let p = i + 1
                    if (totalPages > 5) {
                      const start = Math.max(1, Math.min(page - 2, totalPages - 4))
                      p = start + i
                    }
                    return (
                      <button
                        key={p}
                        type="button"
                        onClick={() => void loadFeatured(p)}
                        className={`flex h-9 min-w-9 items-center justify-center rounded-lg text-[12px] font-medium ${
                          p === page
                            ? 'bg-teal-deep text-white'
                            : 'border border-line bg-white text-ink-soft/60 hover:border-teal/30'
                        }`}
                      >
                        {p}
                      </button>
                    )
                  })}
                  <button
                    type="button"
                    disabled={page >= totalPages || loading}
                    className="h-9 rounded-lg border border-line bg-white px-3 text-[12px] text-ink-soft/70 disabled:opacity-35"
                    onClick={() => void loadFeatured(page + 1)}
                  >
                    下一页
                  </button>
                </div>
              )}
            </div>
          </>
        )}

        {syncToast && (
          <div className="animate-toast-in absolute left-1/2 top-16 z-20 -translate-x-1/2 rounded-full border border-teal/20 bg-white/95 px-4 py-1.5 text-[12px] font-medium text-teal-deep shadow-sm shadow-teal-deep/5">
            {syncToast}
          </div>
        )}
      </section>

      <ChatPanel {...chatProps} />

      {mobileFilter && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink/25 backdrop-blur-[2px]"
            aria-label="关闭"
            onClick={() => setMobileFilter(false)}
          />
          <div className="relative z-10 h-full w-[min(100%,320px)] shadow-xl shadow-ink/10">
            <FilterPanel
              {...filterProps}
              collapsed={false}
              drawer
              onToggle={() => setMobileFilter(false)}
            />
          </div>
        </div>
      )}

      {mobileChat && (
        <div className="fixed inset-0 z-50 flex justify-end xl:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink/25 backdrop-blur-[2px]"
            aria-label="关闭"
            onClick={() => setMobileChat(false)}
          />
          <div className="relative z-10 h-full w-[min(100%,420px)] shadow-xl shadow-ink/10">
            <ChatPanel {...chatProps} drawer onClose={() => setMobileChat(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
