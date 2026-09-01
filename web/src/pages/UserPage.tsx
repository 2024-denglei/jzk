import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { ChatV2Summary, FilterState } from '../types'
import { chatApi } from '../features/chat/chatApi'

type Tab = 'account' | 'favorites' | 'history' | 'chats' | 'prefs'

export function UserPage() {
  const { user, loading, logout, updateNickname } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('account')
  const [nickname, setNickname] = useState('')
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [msg, setMsg] = useState('')
  const [favorites, setFavorites] = useState<{ donor_code: string; created_at: string }[]>([])
  const [history, setHistory] = useState<
    { id: number; kind: string; donor_code: string | null; created_at: string; payload?: unknown }[]
  >([])
  const [chats, setChats] = useState<ChatV2Summary[]>([])
  const [chatCursor, setChatCursor] = useState<string | null>(null)
  const [chatHasMore, setChatHasMore] = useState(false)
  const [prefs, setPrefs] = useState<{ filters: Partial<FilterState>; priority: string[] }>({
    filters: {},
    priority: [],
  })

  useEffect(() => {
    if (user) setNickname(user.nickname)
  }, [user])

  useEffect(() => {
    if (!user) return
    void (async () => {
      if (tab === 'favorites') {
        const data = await api.get<{ items: typeof favorites }>('/api/user/favorites')
        setFavorites(data.items)
      } else if (tab === 'history') {
        const data = await api.get<{ items: typeof history }>('/api/user/history')
        setHistory(data.items)
      } else if (tab === 'chats') {
        const data = await chatApi.list()
        setChats(data.items)
        setChatCursor(data.next_cursor)
        setChatHasMore(data.has_more)
      } else if (tab === 'prefs') {
        const data = await api.get<typeof prefs>('/api/user/preferences')
        setPrefs(data)
      }
    })()
  }, [tab, user])

  if (loading) return <div className="p-10 text-center text-sm text-ink-soft/50">加载中…</div>
  if (!user) return <Navigate to="/login?next=/user" replace />

  async function saveNickname(e: FormEvent) {
    e.preventDefault()
    await updateNickname(nickname)
    setMsg('昵称已更新')
  }

  async function changePassword(e: FormEvent) {
    e.preventDefault()
    await api.post('/api/auth/change-password', { old_password: oldPw, new_password: newPw })
    setOldPw('')
    setNewPw('')
    await logout()
    navigate('/login')
  }

  async function loadMoreChats() {
    if (!chatCursor) return
    const data = await chatApi.list(chatCursor)
    setChats((current) => [...current, ...data.items])
    setChatCursor(data.next_cursor)
    setChatHasMore(data.has_more)
  }

  async function deleteChat(chat: ChatV2Summary) {
    if (!window.confirm(`确定永久删除会话“${chat.title}”吗？所有分支和消息会立即删除，且不可恢复。`)) return
    await chatApi.remove(chat.id, crypto.randomUUID())
    setChats((current) => current.filter((item) => item.id !== chat.id))
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'account', label: '账户' },
    { id: 'favorites', label: '收藏' },
    { id: 'history', label: '历史' },
    { id: 'chats', label: '对话' },
    { id: 'prefs', label: '偏好' },
  ]

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-6">
      <h1 className="font-display text-3xl font-bold text-ink">用户中心</h1>
      <p className="mt-1 text-sm text-ink-soft/60">
        {user.email}{user.phone ? ` · ${user.phone}` : ''}
      </p>

      <div className="mt-6 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              setTab(t.id)
              setMsg('')
            }}
            className={`rounded-full px-4 py-2 text-sm font-medium ${
              tab === t.id ? 'bg-teal-deep text-white' : 'border border-line bg-white text-ink-soft'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {msg && <div className="mt-4 rounded-xl bg-mist px-3 py-2 text-xs text-teal-deep">{msg}</div>}

      <div className="mt-6 rounded-3xl border border-line bg-white p-6">
        {tab === 'account' && (
          <div className="space-y-8">
            <form onSubmit={saveNickname} className="max-w-md space-y-3">
              <h2 className="text-lg font-semibold">个人资料</h2>
              <label className="block text-xs text-ink-soft/60">
                昵称
                <input
                  value={nickname}
                  onChange={(e) => setNickname(e.target.value)}
                  className="mt-1 w-full rounded-xl border border-line px-3 py-2 text-sm"
                />
              </label>
              <button type="submit" className="rounded-xl bg-teal-deep px-4 py-2 text-sm font-semibold text-white">
                保存昵称
              </button>
            </form>
            <form onSubmit={changePassword} className="max-w-md space-y-3">
              <h2 className="text-lg font-semibold">修改密码</h2>
              <input
                type="password"
                placeholder="原密码"
                value={oldPw}
                onChange={(e) => setOldPw(e.target.value)}
                className="w-full rounded-xl border border-line px-3 py-2 text-sm"
                required
              />
              <input
                type="password"
                placeholder="新密码（至少10位）"
                minLength={10}
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                className="w-full rounded-xl border border-line px-3 py-2 text-sm"
                required
              />
              <button type="submit" className="rounded-xl border border-line px-4 py-2 text-sm font-medium">
                更新密码
              </button>
            </form>
            <button
              type="button"
              onClick={() => {
                void logout()
                navigate('/')
              }}
              className="text-sm font-medium text-rose-600"
            >
              退出登录
            </button>
          </div>
        )}

        {tab === 'favorites' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold">我的收藏</h2>
            {favorites.length === 0 ? (
              <p className="text-sm text-ink-soft/50">暂无收藏</p>
            ) : (
              <ul className="space-y-2">
                {favorites.map((f) => (
                  <li key={f.donor_code} className="flex items-center justify-between rounded-xl bg-sand px-4 py-3">
                    <Link to={`/donors/${encodeURIComponent(f.donor_code)}`} className="font-medium text-teal-deep">
                      代号 {f.donor_code}
                    </Link>
                    <span className="text-xs text-ink-soft/45">{f.created_at}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {tab === 'history' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold">浏览 / 匹配历史</h2>
            {history.length === 0 ? (
              <p className="text-sm text-ink-soft/50">暂无记录</p>
            ) : (
              <ul className="space-y-2">
                {history.map((h) => (
                  <li key={h.id} className="rounded-xl bg-sand px-4 py-3 text-sm">
                    <div className="flex justify-between gap-2">
                      <span className="font-medium">
                        {h.kind === 'browse' ? '浏览' : h.kind === 'search' ? '筛选搜索' : h.kind}
                        {h.donor_code ? ` · ${h.donor_code}` : ''}
                      </span>
                      <span className="text-xs text-ink-soft/45">{h.created_at}</span>
                    </div>
                    {h.donor_code && (
                      <Link className="mt-1 inline-block text-xs text-teal-deep" to={`/donors/${h.donor_code}`}>
                        查看详情
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {tab === 'chats' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold">对话记录</h2>
            {chats.length === 0 ? (
              <p className="text-sm text-ink-soft/50">暂无对话。在查找页开始智能对话后会自动保存。</p>
            ) : (
              <ul className="space-y-2">
                {chats.map((c) => (
                  <li key={c.id} className="rounded-xl bg-sand px-4 py-3">
                    <div className="font-medium text-ink">{c.title}</div>
                    <div className="mt-1 text-xs text-ink-soft/50">{c.branch_count} 条分支 · {c.message_count} 条消息</div>
                    <div className="mt-2 flex items-center justify-between text-xs text-ink-soft/50">
                      <span>{c.updated_at}</span>
                      <div className="flex items-center gap-3">
                      <button type="button" onClick={() => void deleteChat(c)} className="text-rose-600">永久删除</button>
                      <Link to={`/donors?chatId=${c.id}${c.active_branch_id ? `&branchId=${encodeURIComponent(c.active_branch_id)}` : ''}`} className="text-teal-deep">
                        继续对话
                      </Link>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {chatHasMore && (
              <button type="button" onClick={() => void loadMoreChats()} className="mt-4 text-sm font-medium text-teal-deep">
                加载更多对话
              </button>
            )}
          </div>
        )}

        {tab === 'prefs' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold">筛选偏好</h2>
            {(!prefs.priority.length && !Object.keys(prefs.filters || {}).length) ? (
              <p className="text-sm text-ink-soft/50">尚未保存偏好。可在查找页左侧点击「保存为偏好」。</p>
            ) : (
              <>
                <pre className="overflow-auto rounded-xl bg-sand p-4 text-xs text-ink-soft">
                  {JSON.stringify(prefs, null, 2)}
                </pre>
                <Link
                  to="/donors"
                  className="mt-4 inline-flex rounded-xl bg-teal-deep px-4 py-2 text-sm font-semibold text-white"
                >
                  应用到查找页
                </Link>
                <p className="mt-2 text-xs text-ink-soft/50">查找页会在登录后自动加载已保存的偏好。</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
