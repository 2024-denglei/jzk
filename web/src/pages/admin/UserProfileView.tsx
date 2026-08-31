import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { adminFetch, postAdmin } from './adminApi'
import { ChatTraceView } from './ChatTraceView'
import { EmptyState, ErrorNotice, Pagination, StatusBadge } from './AdminUi'
import { formatTime } from './adminFormat'
import { UserControlDialog, type UserControlAction } from './UserControlDialog'
import type { ChatDetail, ChatRecord, FavoriteRecord, HistoryRecord, PageData, UserArchive, UserAuditRecord } from './types'

type Tab = 'overview' | 'favorites' | 'history' | 'chats' | 'audit'

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'overview', label: '档案概览' },
  { key: 'favorites', label: '收藏记录' },
  { key: 'history', label: '浏览历史' },
  { key: 'chats', label: 'AI 会话' },
  { key: 'audit', label: '管理记录' },
]

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 20 }

export function UserProfileView({ userId }: { userId: number }) {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserArchive | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [page, setPage] = useState(1)
  const [favorites, setFavorites] = useState<PageData<FavoriteRecord>>(EMPTY_PAGE)
  const [history, setHistory] = useState<PageData<HistoryRecord>>(EMPTY_PAGE)
  const [historyKind, setHistoryKind] = useState('')
  const [chats, setChats] = useState<PageData<ChatRecord>>(EMPTY_PAGE)
  const [chatDetail, setChatDetail] = useState<ChatDetail | null>(null)
  const [audits, setAudits] = useState<PageData<UserAuditRecord>>(EMPTY_PAGE)
  const [loading, setLoading] = useState(true)
  const [tabLoading, setTabLoading] = useState(false)
  const [error, setError] = useState('')
  const [control, setControl] = useState<UserControlAction | null>(null)
  const [controlBusy, setControlBusy] = useState(false)

  const loadProfile = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setUser(await adminFetch<UserArchive>(`/api/admin/users/${userId}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : '用户档案加载失败')
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void loadProfile()
  }, [loadProfile])

  const loadTab = useCallback(async () => {
    if (tab === 'overview') return
    setTabLoading(true)
    setError('')
    try {
      const base = `/api/admin/users/${userId}`
      if (tab === 'favorites') setFavorites(await adminFetch(`${base}/favorites?page=${page}&page_size=20`))
      if (tab === 'history') {
        const kind = historyKind ? `&kind=${historyKind}` : ''
        setHistory(await adminFetch(`${base}/history?page=${page}&page_size=20${kind}`))
      }
      if (tab === 'chats') setChats(await adminFetch(`${base}/chats?page=${page}&page_size=20`))
      if (tab === 'audit') setAudits(await adminFetch(`${base}/audit?page=${page}&page_size=20`))
    } catch (err) {
      setError(err instanceof Error ? err.message : '记录加载失败')
    } finally {
      setTabLoading(false)
    }
  }, [historyKind, page, tab, userId])

  useEffect(() => {
    void loadTab()
  }, [loadTab])

  async function openChat(chatId: number) {
    setTabLoading(true)
    setError('')
    try {
      setChatDetail(await adminFetch<ChatDetail>(`/api/admin/users/${userId}/chats/${chatId}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : '会话加载失败')
    } finally {
      setTabLoading(false)
    }
  }

  async function confirmControl(reason: string) {
    if (!control) return
    setControlBusy(true)
    setError('')
    try {
      await postAdmin(`/api/admin/users/${userId}/${control}`, { reason })
      setControl(null)
      await loadProfile()
      if (tab === 'audit') await loadTab()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败')
    } finally {
      setControlBusy(false)
    }
  }

  if (loading) return <div className="py-24 text-center text-sm text-[#8793a5]">正在加载用户档案…</div>
  if (!user) return <div>{error ? <ErrorNotice message={error} /> : null}<button onClick={() => navigate('/admin/users')} className="text-sm text-[#1677ff]">返回用户档案</button></div>

  const preferenceText = user.preferences && (Object.keys(user.preferences.filters || {}).length || user.preferences.priority?.length)
    ? JSON.stringify({ filters: user.preferences.filters, priority: user.preferences.priority }, null, 2)
    : ''

  return (
    <div>
      <button onClick={() => navigate('/admin/users')} className="mb-4 inline-flex items-center gap-1 text-xs text-[#617086] hover:text-[#1677ff]"><i className="ri-arrow-left-line" />返回用户档案</button>
      {error ? <ErrorNotice message={error} /> : null}

      <section className="rounded-xl border border-[#dce4ee] bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-[#e8f2ff] text-xl font-semibold text-[#1677ff]">{(user.nickname || '用').slice(0, 1)}</div>
            <div>
              <div className="flex items-center gap-2"><h1 className="text-xl font-semibold">{user.nickname || '未设置昵称'}</h1><StatusBadge status={user.status} /></div>
              <div className="mt-1 text-xs text-[#7d899a]">UID {user.id} · 注册于 {formatTime(user.created_at)}</div>
              {user.disabled_reason ? <div className="mt-1 text-xs text-rose-600">停用原因：{user.disabled_reason}</div> : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setControl('kick')} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700"><i className="ri-logout-box-r-line mr-1" />强制下线</button>
            <button onClick={() => setControl(user.status === 'active' ? 'disable' : 'enable')} className={`rounded-lg px-3 py-2 text-xs text-white ${user.status === 'active' ? 'bg-rose-600' : 'bg-emerald-600'}`}>
              <i className={`${user.status === 'active' ? 'ri-user-unfollow-line' : 'ri-user-follow-line'} mr-1`} />{user.status === 'active' ? '停用账号' : '恢复账号'}
            </button>
          </div>
        </div>
        <div className="mt-5 grid gap-3 border-t border-[#e5eaf1] pt-4 sm:grid-cols-2 xl:grid-cols-4">
          <Info label="手机号" value={user.phone || '—'} />
          <Info label="邮箱" value={user.email || '—'} />
          <Info label="最近登录" value={formatTime(user.last_login_at)} />
          <Info label="档案更新" value={formatTime(user.updated_at)} />
        </div>
      </section>

      <section className="mt-4 overflow-hidden rounded-xl border border-[#dce4ee] bg-white">
        <div className="flex gap-1 overflow-x-auto border-b border-[#e2e8f0] px-4 pt-2">
          {TABS.map((item) => (
            <button key={item.key} onClick={() => { setTab(item.key); setPage(1); setChatDetail(null) }} className={`relative shrink-0 px-4 py-3 text-xs font-medium ${tab === item.key ? 'text-[#1677ff]' : 'text-[#68768a] hover:text-[#2b3c55]'}`}>
              {item.label}
              {tab === item.key ? <span className="absolute inset-x-3 bottom-0 h-0.5 bg-[#1677ff]" /> : null}
            </button>
          ))}
        </div>

        {tabLoading ? <div className="py-16 text-center text-sm text-[#8d99aa]">正在加载…</div> : null}
        {!tabLoading && tab === 'overview' ? (
          <div className="p-5">
            <div className="grid gap-3 sm:grid-cols-3">
              <CountCard label="收藏记录" value={user.favorite_count} icon="ri-star-line" />
              <CountCard label="浏览与匹配历史" value={user.history_count} icon="ri-eye-line" />
              <CountCard label="AI 会话" value={user.chat_count} icon="ri-chat-3-line" />
            </div>
            <div className="mt-5 rounded-lg border border-[#e2e8f0] p-4">
              <h2 className="text-sm font-medium">匹配偏好摘要</h2>
              {preferenceText ? <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-[#f6f8fb] p-3 text-xs leading-5 text-[#526177]">{preferenceText}</pre> : <p className="mt-3 text-xs text-[#96a1b0]">用户尚未保存匹配偏好。</p>}
            </div>
          </div>
        ) : null}

        {!tabLoading && tab === 'favorites' ? (
          <div>
            {favorites.items.length ? <div className="divide-y divide-[#e7ecf2]">{favorites.items.map((item) => (
              <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                <div><Link to={`/admin/donors?code=${encodeURIComponent(item.donor_code)}`} className="text-sm font-medium text-[#1677ff]">{item.donor_code}</Link><div className="mt-1 text-xs text-[#7e8a9b]">{item.ethnicity || '民族未知'} · {item.education || '学历未知'} · {item.height_cm ? `${item.height_cm}cm` : '身高未知'}</div></div>
                <div className="text-right"><StatusBadge status={item.donor_status || 'disabled'} /><div className="mt-1 text-[11px] text-[#929dab]">收藏于 {formatTime(item.created_at)}</div></div>
              </div>
            ))}</div> : <EmptyState text="该用户暂无收藏记录" />}
            <Pagination page={page} pageSize={favorites.page_size} total={favorites.total} onChange={setPage} />
          </div>
        ) : null}

        {!tabLoading && tab === 'history' ? (
          <div>
            <div className="border-b border-[#e7ecf2] px-5 py-3"><select value={historyKind} onChange={(event) => { setHistoryKind(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs"><option value="">全部类型</option><option value="browse">浏览</option><option value="search">搜索</option><option value="match">匹配</option></select></div>
            {history.items.length ? <div className="divide-y divide-[#e7ecf2]">{history.items.map((item) => <HistoryItem key={item.id} item={item} />)}</div> : <EmptyState text="该用户暂无浏览历史" />}
            <Pagination page={page} pageSize={history.page_size} total={history.total} onChange={setPage} />
          </div>
        ) : null}

        {!tabLoading && tab === 'chats' ? (
          <div className="grid min-h-[620px] lg:grid-cols-[330px_minmax(0,1fr)]">
            <div className="border-r border-[#e4eaf1] bg-white">
              {chats.items.length ? chats.items.map((chat) => (
                <button key={chat.id} onClick={() => void openChat(chat.id)} className={`block w-full border-b border-[#e8edf3] px-4 py-3 text-left transition hover:bg-[#f7faff] ${chatDetail?.id === chat.id ? 'bg-[#eef6ff]' : ''}`}>
                  <div className="mb-1 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-[#1677ff]"><i className="ri-fingerprint-line" />Session ID</div>
                  <div className="break-all font-mono text-[11px] font-medium leading-4 text-[#26364e]">{chat.session_id}</div>
                  <div className="mt-2 truncate text-[10px] text-[#68768a]">{chat.title || '未命名会话'}</div>
                  <div className="mt-1 flex justify-between text-[10px] text-[#9aa5b5]"><span>{chat.message_count} 条消息</span><span>{formatTime(chat.updated_at)}</span></div>
                </button>
              )) : <EmptyState text="暂无 AI 会话" />}
              {chats.total > chats.page_size ? <Pagination page={page} pageSize={chats.page_size} total={chats.total} onChange={setPage} /> : null}
            </div>
            <div className="min-w-0 bg-[#f8fafc]">
              {chatDetail ? <ChatTraceView chat={chatDetail} /> : <div className="flex h-full min-h-[520px] items-center justify-center text-sm text-[#9aa5b5]">从左侧选择一个 Session 查看完整 Trace</div>}
            </div>
          </div>
        ) : null}

        {!tabLoading && tab === 'audit' ? (
          <div>
            {audits.items.length ? <div className="divide-y divide-[#e7ecf2]">{audits.items.map((item) => (
              <div key={item.id} className="grid gap-2 px-5 py-4 text-xs sm:grid-cols-[140px_1fr_160px]">
                <div className="font-medium text-[#34445b]">{auditLabel(item.action)}</div>
                <div className="text-[#667389]">{item.reason || '—'}<div className="mt-1 text-[11px] text-[#9aa5b5]">操作人：{item.operator_name || `管理员 ${item.operator_id || '—'}`}</div></div>
                <div className="text-[#8b96a6] sm:text-right">{formatTime(item.created_at)}</div>
              </div>
            ))}</div> : <EmptyState text="暂无管理操作记录" />}
            <Pagination page={page} pageSize={audits.page_size} total={audits.total} onChange={setPage} />
          </div>
        ) : null}
      </section>

      {control ? <UserControlDialog action={control} userName={`${user.nickname || '用户'}（UID ${user.id}）`} busy={controlBusy} onClose={() => setControl(null)} onConfirm={(reason) => void confirmControl(reason)} /> : null}
    </div>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><div className="text-[11px] text-[#929dad]">{label}</div><div className="mt-1 text-xs font-medium text-[#35455d]">{value}</div></div>
}

function CountCard({ label, value, icon }: { label: string; value: number; icon: string }) {
  return <div className="flex items-center gap-3 rounded-lg border border-[#e1e7ef] p-4"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#edf5ff] text-[#1677ff]"><i className={icon} /></div><div><div className="text-lg font-semibold">{value}</div><div className="text-[11px] text-[#8793a4]">{label}</div></div></div>
}

function HistoryItem({ item }: { item: HistoryRecord }) {
  const labels = { browse: '浏览档案', search: '条件搜索', match: '智能匹配' }
  const payload = item.payload ? JSON.stringify(item.payload, null, 2) : ''
  return <div className="px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><span className="rounded bg-[#edf5ff] px-2 py-1 text-[11px] text-[#1677ff]">{labels[item.kind]}</span><span className="text-xs font-medium text-[#34445b]">{item.donor_code || '无指定捐献者'}</span></div><span className="text-[11px] text-[#929dab]">{formatTime(item.created_at)}</span></div>{payload ? <pre className="mt-3 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-[#f7f9fc] p-3 text-[11px] leading-5 text-[#657287]">{payload}</pre> : null}</div>
}

function auditLabel(action: UserAuditRecord['action']) {
  return { view_chat: '查看 AI 会话', kick: '强制下线', disable: '停用账号', enable: '恢复账号' }[action] || action
}
