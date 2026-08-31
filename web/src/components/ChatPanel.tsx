import { startTransition, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api, expireUserSession, getToken } from '../lib/api'
import {
  createSpeechRecognizer,
  getSpeechSupport,
  speakText,
  stopSpeaking,
} from '../lib/speech'
import type { Candidate, ChatMessage, PreferHit } from '../types'
import { ChatMatchCards } from './ChatMatchCards'

const SUGGESTIONS = ['硕士，身高 175 以上', 'O 型血，体型一般', '本科以上，标本充足']
const GUEST_WELCOME = '描述您的期望，我会帮您筛选合适的候选人。'
/** 写入 React 消息状态的预览条数；完整列表放 matchBagsRef，避免卡顿 */
const CHAT_STATE_PREVIEW = 20

type ChatListItem = { id: number; session_id: string; title: string; updated_at: string }

type Props = {
  onCandidates: (items: Candidate[]) => void
  seedMessage?: string | null
  onSeedConsumed?: () => void
  resumeChatId?: number | null
  onResumeConsumed?: () => void
  onSessionPersist?: (payload: {
    session_id: string
    messages: ChatMessage[]
    candidates: Candidate[]
  }) => void
  drawer?: boolean
  onClose?: () => void
  className?: string
}

function fmtMd(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>')
}

function shortWelcome(raw: string) {
  const plain = raw.replace(/\*\*/g, '').replace(/\n+/g, ' ').trim()
  if (plain.length <= 72) return plain
  return plain.slice(0, 70) + '…'
}

export function ChatPanel({
  onCandidates,
  seedMessage,
  onSeedConsumed,
  resumeChatId,
  onResumeConsumed,
  onSessionPersist,
  drawer = false,
  onClose,
  className = '',
}: Props) {
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [welcome, setWelcome] = useState(GUEST_WELCOME)
  const [showWelcome, setShowWelcome] = useState(true)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyItems, setHistoryItems] = useState<ChatListItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [voiceHint, setVoiceHint] = useState('')
  const [ttsOn, setTtsOn] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const started = useRef(false)
  const recognitionRef = useRef<ReturnType<typeof createSpeechRecognizer>>(null)
  const abortRef = useRef<AbortController | null>(null)
  const featuresRef = useRef<Record<string, unknown>>({})
  const constraintsRef = useRef<Record<string, string>>({})
  const messagesRef = useRef<ChatMessage[]>([])
  const matchBagsRef = useRef<Record<string, Candidate[]>>({})
  const speechSupport = getSpeechSupport()

  messagesRef.current = messages

  function bagCandidates(full: Candidate[], preferHits?: PreferHit[]) {
    const bagId = `bag_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
    matchBagsRef.current[bagId] = full
    return {
      match_bag_id: bagId,
      candidates: full.slice(0, CHAT_STATE_PREVIEW),
      candidates_total: full.length,
      prefer_hits: preferHits?.length ? preferHits : undefined,
    }
  }

  function pushCandidatesToMiddle(items: Candidate[]) {
    startTransition(() => {
      onCandidates(items)
    })
  }

  useEffect(() => {
    return () => {
      try {
        recognitionRef.current?.abort()
      } catch {
        /* ignore */
      }
      abortRef.current?.abort()
      stopSpeaking()
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, welcome])

  useEffect(() => {
    if (authLoading) return
    if (!user) {
      started.current = false
      setWelcome(GUEST_WELCOME)
      setSessionId(null)
      return
    }
    if (resumeChatId) {
      started.current = true
      return
    }
    if (started.current) return
    started.current = true
    void (async () => {
      try {
        const data = await api.post<{ session_id: string; reply?: string }>('/api/chat', {
          session_id: null,
          message: '',
        })
        setSessionId(data.session_id)
        setWelcome(data.reply || GUEST_WELCOME)
      } catch {
        setMessages([{ role: 'system', content: '暂时无法连接顾问服务，请稍后重试。' }])
      }
    })()
  }, [authLoading, user, resumeChatId])

  useEffect(() => {
    if (!resumeChatId || !user) return
    void (async () => {
      try {
        const data = await api.post<{
          session_id: string
          messages: ChatMessage[]
          candidates: Candidate[]
        }>(`/api/user/chats/${resumeChatId}/resume`, {})
        setSessionId(data.session_id)
        const msgs = (data.messages || []).map((m) => {
          const roleRaw = String(m.role || 'bot')
          const role: ChatMessage['role'] =
            roleRaw === 'user' ? 'user' : roleRaw === 'system' ? 'system' : 'bot'
          return {
            role,
            content: m.content || '',
            candidates: m.candidates,
            prefer_hits: m.prefer_hits,
            candidates_total: m.candidates_total,
            match_bag_id: m.match_bag_id,
          }
        })
        const full =
          (Array.isArray(data.candidates) && data.candidates.length && data.candidates) ||
          [...msgs].reverse().find((m) => m.candidates && m.candidates.length)?.candidates ||
          []
        if (full.length) {
          const bag = bagCandidates(full)
          for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].role === 'bot' && msgs[i].candidates?.length) {
              msgs[i] = { ...msgs[i], ...bag }
              break
            }
          }
          setMessages(msgs)
          pushCandidatesToMiddle(full)
        } else {
          setMessages(msgs)
        }
        setShowWelcome(false)
        setWelcome('')
      } catch {
        /* ignore */
      } finally {
        onResumeConsumed?.()
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeChatId, user])

  useEffect(() => {
    if (!seedMessage || !sessionId || sending) return
    setShowWelcome(false)
    setInput(seedMessage)
    onSeedConsumed?.()
    const t = setTimeout(() => {
      void send(seedMessage)
    }, 50)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedMessage, sessionId])

  async function loadHistory() {
    if (!user) return
    setHistoryLoading(true)
    try {
      const data = await api.get<{ items: ChatListItem[] }>('/api/user/chats')
      setHistoryItems(data.items || [])
    } catch {
      setHistoryItems([])
    } finally {
      setHistoryLoading(false)
    }
  }

  async function startNewChat() {
    if (!user) {
      setHistoryOpen(false)
      setMessages([])
      setShowWelcome(true)
      setSending(false)
      setInput('')
      setWelcome(GUEST_WELCOME)
      setSessionId(null)
      return
    }
    setHistoryOpen(false)
    setMessages([])
    setShowWelcome(true)
    setSending(false)
    setInput('')
    try {
      const data = await api.post<{ session_id: string; reply?: string }>('/api/chat', {
        session_id: null,
        message: '',
      })
      setSessionId(data.session_id)
      setWelcome(data.reply || GUEST_WELCOME)
    } catch {
      setSessionId(null)
      setMessages([{ role: 'system', content: '无法创建新对话，请稍后重试。' }])
    }
  }

  async function openHistoryChat(id: number) {
    setHistoryOpen(false)
    try {
      const data = await api.post<{
        session_id: string
        messages: ChatMessage[]
        candidates: Candidate[]
      }>(`/api/user/chats/${id}/resume`, {})
      setSessionId(data.session_id)
      const msgs = (data.messages || []).map((m) => {
        const roleRaw = String(m.role || 'bot')
        const role: ChatMessage['role'] =
          roleRaw === 'user' ? 'user' : roleRaw === 'system' ? 'system' : 'bot'
        return {
          role,
          content: m.content || '',
          candidates: m.candidates,
          prefer_hits: m.prefer_hits,
          candidates_total: m.candidates_total,
          match_bag_id: m.match_bag_id,
        }
      })
      const full =
        (Array.isArray(data.candidates) && data.candidates.length && data.candidates) ||
        [...msgs].reverse().find((m) => m.candidates && m.candidates.length)?.candidates ||
        []
      if (full.length) {
        const bag = bagCandidates(full)
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'bot' && msgs[i].candidates?.length) {
            msgs[i] = { ...msgs[i], ...bag }
            break
          }
        }
        setMessages(msgs)
        pushCandidatesToMiddle(full)
      } else {
        setMessages(msgs)
      }
      setShowWelcome(false)
      setWelcome('')
    } catch {
      setMessages([{ role: 'system', content: '无法打开该历史对话。' }])
    }
  }

  async function abortSending() {
    const ac = abortRef.current
    abortRef.current = null
    ac?.abort()
    stopSpeaking()
    if (sessionId) {
      try {
        await api.post('/api/chat/abort', { session_id: sessionId })
      } catch {
        /* ignore */
      }
    }
  }

  async function rewindTo(index: number) {
    if (sending || index < 0 || index >= messages.length - 1) return
    const target = messages[index]
    if (!target || target.role === 'system') return
    if (!window.confirm('将回到该条消息，并删除之后的对话与推荐，是否继续？')) return

    const kept = messages.slice(0, index + 1)
    const snap = target.snapshot || { parsed_features: {}, constraints: {} }
    featuresRef.current = { ...(snap.parsed_features || {}) }
    constraintsRef.current = { ...(snap.constraints || {}) }

    let cands: Candidate[] = []
    for (let i = kept.length - 1; i >= 0; i--) {
      const m = kept[i]
      if (m.match_bag_id && matchBagsRef.current[m.match_bag_id]?.length) {
        cands = matchBagsRef.current[m.match_bag_id]
        break
      }
      if (m.candidates?.length) {
        cands = m.candidates
        break
      }
    }
    pushCandidatesToMiddle(cands)

    setMessages(kept)
    messagesRef.current = kept

    const history = kept
      .filter((m) => m.role === 'user' || m.role === 'bot')
      .map((m) => ({
        role: m.role === 'bot' ? 'assistant' : 'user',
        content: m.content,
      }))

    try {
      const data = await api.post<{ session_id: string }>('/api/chat/rewind', {
        session_id: sessionId,
        history,
        parsed_features: snap.parsed_features || {},
        constraints: snap.constraints || {},
        messages: kept,
        candidates: cands,
      })
      if (data.session_id) setSessionId(data.session_id)
      if (data.session_id || sessionId) {
        onSessionPersist?.({
          session_id: data.session_id || sessionId!,
          messages: kept,
          candidates: cands,
        })
      }
    } catch (e) {
      console.error(e)
    }
  }

  async function send(textOverride?: string) {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    if (sending) {
      await abortSending()
      return
    }
    const text = (textOverride ?? input).trim()
    if (!text) return
    setInput('')
    setShowWelcome(false)

    const beforeMessages = messagesRef.current
    const featuresBefore = { ...featuresRef.current }
    const constraintsBefore = { ...constraintsRef.current }
    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      snapshot: {
        parsed_features: featuresBefore,
        constraints: constraintsBefore,
      },
    }
    const nextMessages: ChatMessage[] = [...beforeMessages, userMsg]
    setMessages(nextMessages)
    setSending(true)

    let botText = ''
    let candidates: Candidate[] = []
    let preferHits: PreferHit[] = []
    let bagMeta: ReturnType<typeof bagCandidates> | null = null
    let currentSession = sessionId
    let aborted = false
    let featuresAfter = featuresBefore
    let constraintsAfter = constraintsBefore

    const ac = new AbortController()
    abortRef.current = ac

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const token = getToken()
      if (token) headers.Authorization = `Bearer ${token}`

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({ session_id: sessionId, message: text }),
        signal: ac.signal,
      })
      if (res.status === 401) {
        expireUserSession('登录已失效，请重新登录')
        navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
        throw new Error('未登录')
      }
      if (!res.body) throw new Error('无响应流')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let evt = ''

      const handleLine = (line: string) => {
        if (line.startsWith('event: ')) evt = line.slice(7).trim()
        else if (line.startsWith('data: ') && evt) {
          try {
            const data = JSON.parse(line.slice(6))
            if (evt === 'aborted') {
              aborted = true
            } else if (evt === 'token') {
              botText += data.text || ''
              // 流式阶段不挂候选列表，避免每 token 都拷贝大数组
              setMessages([...nextMessages, { role: 'bot', content: botText }])
            } else if (evt === 'reply') {
              botText = data.text || botText
              setMessages([...nextMessages, { role: 'bot', content: botText }])
            } else if (evt === 'candidates' && Array.isArray(data.items)) {
              candidates = data.items
              preferHits = Array.isArray(data.prefer_hits) ? data.prefer_hits : []
              bagMeta = bagCandidates(candidates, preferHits)
              setMessages([
                ...nextMessages,
                {
                  role: 'bot',
                  content: botText,
                  ...bagMeta,
                },
              ])
            } else if (evt === 'state' && data.session_id) {
              currentSession = data.session_id
              setSessionId(data.session_id)
              if (data.parsed_features && typeof data.parsed_features === 'object') {
                featuresAfter = data.parsed_features
                featuresRef.current = data.parsed_features
              }
              if (data.constraints && typeof data.constraints === 'object') {
                constraintsAfter = data.constraints
                constraintsRef.current = data.constraints
              }
            } else if (evt === 'error') {
              botText = data.message || '出错了'
              setMessages([
                ...nextMessages,
                { role: 'bot', content: `⚠️ ${botText}` },
              ])
            }
          } catch {
            /* ignore */
          }
          evt = ''
        }
      }

      setMessages([...nextMessages, { role: 'bot', content: '' }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) handleLine(line)
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        for (const line of buffer.split('\n')) handleLine(line)
      }

      if (aborted || ac.signal.aborted) {
        setMessages(beforeMessages)
        messagesRef.current = beforeMessages
        featuresRef.current = featuresBefore
        constraintsRef.current = constraintsBefore
        setInput(text)
        onCandidates([])
        return
      }

      const bag = bagMeta || (candidates.length ? bagCandidates(candidates, preferHits) : null)
      const botMsg: ChatMessage = {
        role: 'bot',
        content: botText || '已完成回复。',
        ...(bag || {}),
        snapshot: {
          parsed_features: featuresAfter,
          constraints: constraintsAfter,
        },
      }
      const finalMessages: ChatMessage[] = [...nextMessages, botMsg]
      setMessages(finalMessages)
      messagesRef.current = finalMessages
      if (ttsOn && botText) {
        speakText(botText)
      }
      if (currentSession) {
        onSessionPersist?.({
          session_id: currentSession,
          messages: finalMessages,
          candidates,
        })
      }
    } catch (err) {
      const isAbort =
        (err instanceof DOMException && err.name === 'AbortError') ||
        (err instanceof Error && err.name === 'AbortError') ||
        ac.signal.aborted
      if (isAbort || aborted) {
        setMessages(beforeMessages)
        messagesRef.current = beforeMessages
        featuresRef.current = featuresBefore
        constraintsRef.current = constraintsBefore
        setInput(text)
        onCandidates([])
        if (sessionId) {
          try {
            await api.post('/api/chat/abort', { session_id: sessionId })
          } catch {
            /* ignore */
          }
        }
      } else {
        setMessages([...nextMessages, { role: 'bot', content: '请求失败，请稍后重试。' }])
      }
    } finally {
      abortRef.current = null
      setSending(false)
    }
  }

  function stopRecording(commit = true) {
    setVoiceHint('')
    try {
      if (commit) recognitionRef.current?.stop()
      else recognitionRef.current?.abort()
    } catch {
      /* ignore */
    }
    setRecording(false)
  }

  function startRecording() {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    if (sending) return
    if (!speechSupport.recognition) {
      setVoiceHint('当前浏览器不支持语音识别，请使用 Chrome / Edge。')
      return
    }
    stopSpeaking()
    setVoiceHint('正在聆听…停顿约 2 秒后发送，也可再点麦克风结束')
    const recognition = createSpeechRecognizer(
      {
        onInterim: (text) => setInput(text),
        onFinal: (text) => {
          setInput(text)
          setRecording(false)
          setVoiceHint('')
          recognitionRef.current = null
          if (text) void send(text)
        },
        onError: (message) => {
          setVoiceHint(message)
          setRecording(false)
        },
        onEnd: () => {
          setRecording(false)
        },
      },
      { silenceMs: 2200 },
    )
    if (!recognition) {
      setVoiceHint('当前浏览器不支持语音识别，请使用 Chrome / Edge。')
      return
    }
    recognitionRef.current = recognition
    setRecording(true)
    try {
      recognition.start()
    } catch {
      setRecording(false)
      setVoiceHint('无法启动麦克风，请检查权限。')
    }
  }

  function toggleVoice() {
    if (recording) stopRecording()
    else startRecording()
  }

  const shellClass = drawer
    ? `flex h-full flex-col bg-white ${className}`
    : `hidden w-[420px] shrink-0 flex-col border-l border-line/80 bg-white/95 xl:flex xl:w-[420px] ${className}`

  return (
    <aside className={shellClass}>
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-line/60 px-3 py-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-ink">匹配顾问</div>
          <div className="mt-0.5 text-[11px] text-ink-soft/45">
            {user ? '对话已自动保存' : '登录后可保存历史对话'}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            title="新对话"
            onClick={() => void startNewChat()}
            className="rounded-md p-1.5 text-ink-soft/50 transition hover:bg-mist/60 hover:text-teal-deep"
          >
            <i className="ri-add-line text-base" />
          </button>
          {user ? (
            <button
              type="button"
              title="历史对话"
              onClick={() => {
                setHistoryOpen((v) => !v)
                if (!historyOpen) void loadHistory()
              }}
              className={`rounded-md p-1.5 transition hover:bg-mist/60 hover:text-teal-deep ${
                historyOpen ? 'bg-mist text-teal-deep' : 'text-ink-soft/50'
              }`}
            >
              <i className="ri-history-line text-base" />
            </button>
          ) : (
            <Link
              to="/login"
              title="登录以保存历史"
              className="rounded-md p-1.5 text-ink-soft/50 transition hover:bg-mist/60 hover:text-teal-deep"
            >
              <i className="ri-user-line text-base" />
            </Link>
          )}
          {drawer && onClose && (
            <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-soft/45">
              <i className="ri-close-line text-lg" />
            </button>
          )}
        </div>
      </div>

      {historyOpen && user && (
        <div className="max-h-40 shrink-0 overflow-y-auto border-b border-line/50 bg-sand/40 px-2 py-2">
          {historyLoading ? (
            <div className="px-2 py-1 text-[11px] text-ink-soft/45">加载中…</div>
          ) : historyItems.length === 0 ? (
            <div className="px-2 py-1 text-[11px] text-ink-soft/45">暂无历史对话</div>
          ) : (
            <ul className="space-y-1">
              {historyItems.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => void openHistoryChat(h.id)}
                    className="w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-white"
                  >
                    <div className="truncate text-[12px] font-medium text-ink">{h.title}</div>
                    <div className="text-[10px] text-ink-soft/40">{h.updated_at}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="scroll-y min-h-0 flex-1 space-y-3 overflow-y-auto bg-gradient-to-b from-sand/80 to-sand/30 px-3.5 py-3.5">
        {showWelcome && welcome && (
          <div className="animate-msg-in rounded-2xl border border-line/70 bg-white p-4">
            <div className="mb-2 flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-mist text-teal-deep">
                <i className="ri-chat-smile-3-line" />
              </div>
              <div className="text-[13px] font-semibold text-ink">您好</div>
            </div>
            <p className="mb-3 text-[12px] leading-relaxed text-ink-soft/65">{shortWelcome(welcome)}</p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="rounded-lg border border-line/80 bg-sand/40 px-3 py-2 text-left text-[12px] text-ink-soft/75 transition hover:border-teal/30 hover:bg-mist/50 hover:text-teal-deep"
                  onClick={() => void send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className="animate-msg-in group/msg relative">
            <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.role === 'user' ? (
                <div className="relative max-w-[88%] rounded-2xl rounded-br-md bg-teal-deep px-3.5 py-2.5 text-[12.5px] leading-relaxed text-white">
                  {m.content}
                  {!sending && i < messages.length - 1 && (
                    <button
                      type="button"
                      title="回到此处，删除之后的对话"
                      onClick={() => void rewindTo(i)}
                      className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border border-white/30 bg-teal-deep/95 text-white/80 opacity-0 shadow-sm transition hover:bg-ink hover:text-white group-hover/msg:opacity-100"
                      aria-label="回溯到此消息"
                    >
                      <i className="ri-arrow-go-back-line text-[12px]" />
                    </button>
                  )}
                </div>
              ) : m.role === 'system' ? (
                <div className="rounded-xl border border-amber-200/80 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900/80">
                  {m.content}
                </div>
              ) : (
                <div className="relative max-w-[92%] rounded-2xl rounded-bl-md border border-line/70 bg-white px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink/90">
                  <div
                    dangerouslySetInnerHTML={{
                      __html: fmtMd(m.content || (sending && i === messages.length - 1 ? '…' : '')),
                    }}
                  />
                  {!sending && i < messages.length - 1 && (
                    <button
                      type="button"
                      title="回到此处，删除之后的对话"
                      onClick={() => void rewindTo(i)}
                      className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-white text-ink-soft/55 opacity-0 shadow-sm transition hover:border-teal/40 hover:text-teal-deep group-hover/msg:opacity-100"
                      aria-label="回溯到此消息"
                    >
                      <i className="ri-arrow-go-back-line text-[12px]" />
                    </button>
                  )}
                </div>
              )}
            </div>
            {m.role === 'bot' && m.candidates && m.candidates.length > 0 && (
              <ChatMatchCards
                candidates={m.candidates}
                preferHits={m.prefer_hits}
                totalOverride={m.candidates_total}
                onViewInMiddle={() => {
                  const full =
                    (m.match_bag_id && matchBagsRef.current[m.match_bag_id]) || m.candidates || []
                  pushCandidatesToMiddle(full)
                }}
              />
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="shrink-0 border-t border-line/70 bg-white p-3">
        {(voiceHint || recording) && (
          <div className="mb-2 flex items-center gap-2 text-[11px] text-ink-soft/60">
            {recording ? (
              <span className="inline-flex items-center gap-1.5 text-red-500">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" />
                正在聆听…可稍作停顿，约 2 秒静默后发送
              </span>
            ) : (
              <span>{voiceHint}</span>
            )}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-line/80 bg-sand/50 px-2 py-1.5 transition focus-within:border-teal/40 focus-within:bg-white">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            rows={2}
            placeholder="例如：硕士、身高 175+… 或点击麦克风说话"
            className="min-h-[40px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[12.5px] outline-none"
          />
          <button
            type="button"
            title={ttsOn ? '关闭语音播报' : '开启语音播报'}
            onClick={() => {
              if (ttsOn) stopSpeaking()
              setTtsOn((v) => !v)
            }}
            className={`mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition ${
              ttsOn
                ? 'bg-mist text-teal-deep hover:bg-teal/15'
                : 'bg-sand text-ink-soft/45 hover:bg-mist/60'
            }`}
            aria-label="语音播报开关"
          >
            <i className={ttsOn ? 'ri-volume-up-line text-lg' : 'ri-volume-mute-line text-lg'} />
          </button>
          <button
            type="button"
            title="语音输入"
            disabled={sending}
            onClick={toggleVoice}
            className={`mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition disabled:opacity-40 ${
              recording
                ? 'animate-pulse bg-red-100 text-red-500'
                : 'bg-mist/80 text-ink-soft/70 hover:bg-indigo-50 hover:text-indigo-600'
            }`}
            aria-label="语音输入"
          >
            <i className={recording ? 'ri-mic-fill text-lg' : 'ri-mic-line text-lg'} />
          </button>
          <button
            type="button"
            disabled={!sending && !input.trim()}
            onClick={() => void send()}
            title={sending ? '停止生成' : '发送'}
            className={`mb-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-white transition disabled:opacity-40 ${
              sending ? 'bg-red-500 hover:bg-red-600' : 'bg-teal-deep hover:bg-ink'
            }`}
            aria-label={sending ? '停止生成' : '发送'}
          >
            {sending ? (
              <i className="ri-stop-fill text-lg" />
            ) : (
              <i className="ri-arrow-up-line text-lg" />
            )}
          </button>
        </div>
      </div>
    </aside>
  )
}
