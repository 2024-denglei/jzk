import { startTransition, useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChatPanel } from '../components/ChatPanel'
import { DonorCard, DonorCardSkeleton } from '../components/DonorCard'
import { DonorDetailPanel } from '../components/DonorDetailPanel'
import { FilterPanel } from '../components/FilterPanel'
import { useAuth } from '../context/AuthContext'
import { api, ApiError } from '../lib/api'
import { getPaginationPages, normalizeJumpPage } from '../lib/pagination'
import { cacheMatchPage, createMatchPageState } from '../lib/matchPagination'
import type { MatchPageState } from '../lib/matchPagination'
import { WORKBENCH_HEADER_HEIGHT_CLASS } from '../lib/workbenchLayout'
import type { Candidate, FilterState, FrozenMatchPage, MatchResultDescriptor } from '../types'
import { DEFAULT_PRIORITY, EMPTY_FILTERS } from '../types'
import { frozenPageToMatchResult } from '../features/chat/chatApi'

const MODE_META = {
  featured: { label: '推荐浏览', title: '全部捐献者', blurb: '按标本数量优先展示' },
  search: { label: '条件筛选', title: '筛选结果', blurb: '根据左侧条件匹配' },
  chat: { label: '对话推荐', title: '对话结果', blurb: '已根据顾问对话更新' },
} as const

/** 中间栏每页卡片数，避免一次挂载上千张 DonorCard */
const LIST_PAGE_SIZE = 12
const MATCH_PAGE_SIZE = 20

type PaginationBarProps = {
  page: number
  totalPages: number
  loading: boolean
  onPage: (page: number) => void
}

function PaginationBar({ page, totalPages, loading, onPage }: PaginationBarProps) {
  const [jumpValue, setJumpValue] = useState('')
  const pages = getPaginationPages(totalPages, page)
  const showLeadingEllipsis = (pages[0] ?? 2) > 2
  const showTrailingEllipsis = pages.length > 0 && pages[pages.length - 1] < totalPages - 1

  function submitJump(event: FormEvent) {
    event.preventDefault()
    const target = normalizeJumpPage(jumpValue, totalPages)
    if (target === null) return
    onPage(target)
    setJumpValue('')
  }

  return (
    <nav
      aria-label="列表分页"
      className="flex min-w-max items-center justify-center gap-1.5"
    >
      <button
        type="button"
        disabled={page <= 1 || loading}
        className="h-9 rounded-lg border border-line bg-white px-3 text-[12px] text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep disabled:pointer-events-none disabled:opacity-35"
        onClick={() => onPage(page - 1)}
      >
        上一页
      </button>
      <button
        type="button"
        disabled={page <= 1 || loading}
        aria-current={page === 1 ? 'page' : undefined}
        className={`h-9 rounded-lg px-3 text-[12px] transition disabled:pointer-events-none ${
          page === 1
            ? 'bg-teal-deep text-white'
            : 'border border-line bg-white text-ink-soft/70 hover:border-teal/30 hover:text-teal-deep disabled:opacity-35'
        }`}
        onClick={() => onPage(1)}
      >
        首页
      </button>
      <div className="hidden items-center gap-1.5 sm:flex">
        {showLeadingEllipsis ? (
          <span aria-hidden="true" className="px-1 text-[12px] text-ink-soft/45">…</span>
        ) : null}
        {pages.map((pageNumber) => (
          <button
            key={pageNumber}
            type="button"
            disabled={loading}
            aria-label={`第 ${pageNumber} 页`}
            aria-current={pageNumber === page ? 'page' : undefined}
            onClick={() => onPage(pageNumber)}
            className={`flex h-9 min-w-9 items-center justify-center rounded-lg text-[12px] font-medium transition disabled:pointer-events-none disabled:opacity-35 ${
              pageNumber === page
                ? 'bg-teal-deep text-white'
                : 'border border-line bg-white text-ink-soft/60 hover:border-teal/30 hover:text-teal-deep'
            }`}
          >
            {pageNumber}
          </button>
        ))}
        {showTrailingEllipsis ? (
          <span aria-hidden="true" className="px-1 text-[12px] text-ink-soft/45">…</span>
        ) : null}
      </div>
      <span className="min-w-20 text-center text-[12px] tabular-nums text-ink-soft/55 sm:hidden">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        disabled={page >= totalPages || loading}
        aria-current={page === totalPages ? 'page' : undefined}
        className={`h-9 rounded-lg px-3 text-[12px] transition disabled:pointer-events-none ${
          page === totalPages
            ? 'bg-teal-deep text-white'
            : 'border border-line bg-white text-ink-soft/70 hover:border-teal/30 hover:text-teal-deep disabled:opacity-35'
        }`}
        onClick={() => onPage(totalPages)}
      >
        尾页
      </button>
      <button
        type="button"
        disabled={page >= totalPages || loading}
        className="h-9 rounded-lg border border-line bg-white px-3 text-[12px] text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep disabled:pointer-events-none disabled:opacity-35"
        onClick={() => onPage(page + 1)}
      >
        下一页
      </button>
      <form onSubmit={submitJump} className="ml-2 hidden items-center gap-1.5 lg:flex">
        <label htmlFor="page-jump" className="text-[12px] text-ink-soft/55">跳至</label>
        <input
          id="page-jump"
          inputMode="numeric"
          value={jumpValue}
          onChange={(event) => setJumpValue(event.target.value.replace(/[^0-9]/g, ''))}
          placeholder={String(page)}
          aria-label="跳转页码"
          className="h-9 w-16 rounded-lg border border-line bg-white px-2 text-center text-[12px] tabular-nums text-ink outline-none transition focus:border-teal/50"
        />
        <span className="text-[12px] text-ink-soft/55">页</span>
        <button
          type="submit"
          disabled={loading || !jumpValue}
          className="h-9 rounded-lg border border-line bg-white px-2.5 text-[12px] text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep disabled:opacity-35"
        >
          跳转
        </button>
      </form>
    </nav>
  )
}

export function DonorsPage() {
  const { user, loading: authLoading } = useAuth()
  const { code: detailCode } = useParams<{ code?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const seedFromNav = (location.state as { askAbout?: string } | null)?.askAbout || null
  const showingDetail = Boolean(detailCode)
  const chatIdParam = searchParams.get('chatId')
  const parsedChatId = chatIdParam ? Number(chatIdParam) : NaN
  const resumeChatId = Number.isFinite(parsedChatId) ? parsedChatId : null
  const resumeBranchId = searchParams.get('branchId')

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
  const [matchPages, setMatchPages] = useState<MatchPageState | null>(null)
  const [snapshotExpired, setSnapshotExpired] = useState(false)
  const matchRequestSeq = useRef(0)

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
    if (authLoading || user || !matchPages) return
    matchRequestSeq.current += 1
    setMatchPages(null)
    if (mode === 'chat') void loadFeatured(1)
    // loadFeatured is intentionally invoked only on the authenticated -> guest transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user, matchPages, mode])

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
    matchRequestSeq.current += 1
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
      setMatchPages(null)
      setSnapshotExpired(false)
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
    matchRequestSeq.current += 1
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
      const next = data.items || []
      setItems(next)
      setTotal(next.length)
      setPage(1)
      setTotalPages(Math.max(1, Math.ceil(next.length / LIST_PAGE_SIZE)))
      const level =
        data.match_level === 'full'
          ? '完全匹配'
          : data.match_level === 'relaxed'
            ? '部分条件已放宽'
            : '按相似度排序'
      setHint(level + (data.relaxed_hint ? ` · ${data.relaxed_hint}` : ''))
      setMatchPages(null)
      setSnapshotExpired(false)
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

  const meta = MODE_META[mode]
  const pagedItems =
    mode === 'featured' || mode === 'chat'
      ? items
      : items.slice((page - 1) * LIST_PAGE_SIZE, page * LIST_PAGE_SIZE)
  const listTotalPages =
    mode === 'featured'
      ? totalPages
      : mode === 'chat' && matchPages
        ? Math.max(1, Math.ceil(matchPages.total / MATCH_PAGE_SIZE))
        : Math.max(1, Math.ceil(items.length / LIST_PAGE_SIZE))
  async function loadMatchPage(targetPage: number) {
    if (!matchPages || targetPage < 1 || targetPage > listTotalPages) return
    const cached = matchPages.pages[targetPage]
    if (cached) {
      setItems(cached)
      setPage(targetPage)
      setHint(`共 ${matchPages.total} 位，当前显示第 ${(targetPage - 1) * MATCH_PAGE_SIZE + 1}～${Math.min(targetPage * MATCH_PAGE_SIZE, matchPages.total)} 位`)
      return
    }
    const requestId = ++matchRequestSeq.current
    setLoading(true)
    setError('')
    try {
      const data = matchPages.sourceMessageId
        ? frozenPageToMatchResult(
            await api.get<FrozenMatchPage>(
              `/api/messages/${encodeURIComponent(matchPages.sourceMessageId)}/match-results?page=${targetPage}&limit=${MATCH_PAGE_SIZE}`,
            ),
            matchPages.sourceMessageId,
          )
        : await api.get<{
            result_set_id: string
            total: number
            items: Candidate[]
            next_cursor?: string | null
          }>(`/api/match/results/${encodeURIComponent(matchPages.resultSetId)}?page=${targetPage}&limit=${MATCH_PAGE_SIZE}`)
      if (requestId !== matchRequestSeq.current) return
      const nextState = cacheMatchPage(matchPages, targetPage, data.items, data.next_cursor)
      setMatchPages(nextState)
      setItems(data.items)
      setTotal(data.total)
      setPage(targetPage)
      setHint(`共 ${data.total} 位，当前显示第 ${(targetPage - 1) * MATCH_PAGE_SIZE + 1}～${Math.min(targetPage * MATCH_PAGE_SIZE, data.total)} 位`)
      setSnapshotExpired(false)
    } catch (e) {
      if (requestId === matchRequestSeq.current) {
        setSnapshotExpired(e instanceof ApiError && e.code === 'MATCH_SNAPSHOT_EXPIRED')
        setError(e instanceof Error ? e.message : '加载匹配结果失败')
      }
    } finally {
      if (requestId === matchRequestSeq.current) setLoading(false)
    }
  }

  function goToPage(targetPage: number) {
    if (targetPage === page || loading) return
    if (mode === 'featured') {
      void loadFeatured(targetPage)
    } else if (mode === 'chat' && matchPages) {
      void loadMatchPage(targetPage)
    } else {
      setPage(targetPage)
    }
  }

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
    searching,
  }

  const chatProps = {
    seedMessage,
    onSeedConsumed: () => setSeedMessage(null),
    resumeChatId,
    resumeBranchId,
    onConversationChange: (chatId: number | null, branchId: string | null) => {
      const next = new URLSearchParams(searchParams)
      if (chatId === null) next.delete('chatId')
      else next.set('chatId', String(chatId))
      if (branchId === null) next.delete('branchId')
      else next.set('branchId', branchId)
      setSearchParams(next, { replace: true })
    },
    // 新对话 / 终止后无匹配快照：回到全部捐献者，避免空的「对话结果」
    onClearCandidates: () => {
      void loadFeatured(1)
    },
    onCandidates: (cands: Candidate[], result?: MatchResultDescriptor) => {
      matchRequestSeq.current += 1
      startTransition(() => {
        const nextItems = result?.items || cands
        setItems(nextItems)
        setTotal(result?.total ?? cands.length)
        setPage(1)
        setTotalPages(
          Math.max(1, Math.ceil((result?.total ?? cands.length) / (result ? MATCH_PAGE_SIZE : LIST_PAGE_SIZE))),
        )
        setMatchPages(result ? createMatchPageState(result) : null)
        setSnapshotExpired(false)
        setHint(
          result
            ? `共 ${result.total} 位，当前显示第 1～${Math.min(result.items.length, result.total)} 位`
            : MODE_META.chat.blurb,
        )
        setLoading(false)
        // 对话快照就绪时只更新候选数据，不强制重挂整个卡片网格。
        // 这样已有卡片会原位更新，不再产生一次类似整页刷新的动画。
        setMode('chat')
        setSyncToast('已根据对话更新中间结果')
        setMobileChat(false)
      })
      if (showingDetail) navigate('/donors')
    },
  }

  async function refreshExpiredMatch() {
    if (!matchPages) return
    setLoading(true)
    setError('')
    try {
      const result = await api.post<MatchResultDescriptor>(
        `/api/match/results/${encodeURIComponent(matchPages.resultSetId)}/refresh`,
      )
      chatProps.onCandidates(result.items || [], result)
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新匹配失败')
    } finally {
      setLoading(false)
    }
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
            <div className={`flex shrink-0 items-center justify-between gap-3 border-b border-line/60 bg-white/70 px-4 backdrop-blur-sm md:px-5 ${WORKBENCH_HEADER_HEIGHT_CLASS}`}>
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
            <div className={`flex shrink-0 items-center justify-between gap-3 border-b border-line/60 bg-white/70 px-4 backdrop-blur-sm md:px-5 ${WORKBENCH_HEADER_HEIGHT_CLASS}`}>
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
              <div className="flex items-center justify-between gap-3 border-b border-amber-100 bg-amber-50/90 px-4 py-2 text-[12px] text-amber-900/80">
                <span>{error}</span>
                {snapshotExpired && matchPages ? (
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void refreshExpiredMatch()}
                    className="shrink-0 rounded-md bg-amber-900 px-2.5 py-1 font-medium text-white disabled:opacity-50"
                  >
                    重新匹配
                  </button>
                ) : null}
              </div>
            )}

            <div className="flex min-h-0 flex-1 flex-col">
              <div className="scroll-y min-h-0 flex-1 overflow-y-auto px-3 py-4 md:px-5">
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
                    {pagedItems.map((c, i) => (
                      <DonorCard
                        key={c.donor_info.code}
                        candidate={c}
                        index={(page - 1) * (mode === 'chat' && matchPages ? MATCH_PAGE_SIZE : LIST_PAGE_SIZE) + i}
                      />
                    ))}
                  </div>
                )}
              </div>

              {listTotalPages > 1 ? (
                <div className="shrink-0 border-t border-line/70 bg-white/95 px-3 py-3 shadow-[0_-6px_20px_rgba(15,61,68,0.04)] backdrop-blur-sm md:px-5">
                  <div className="overflow-x-auto">
                    <PaginationBar
                      page={page}
                      totalPages={listTotalPages}
                      loading={loading}
                      onPage={goToPage}
                    />
                  </div>
                </div>
              ) : null}
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
