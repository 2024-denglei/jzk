import { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ChatMatchCards } from '../../components/ChatMatchCards'
import { useAuth } from '../../context/AuthContext'
import { createSpeechRecognizer, getSpeechSupport, speakText, stopSpeaking } from '../../lib/speech'
import type { Candidate, ChatBranchSummary, ChatMessageNode, ChatV2Summary, MatchResultDescriptor } from '../../types'
import { buildTurnCommand, type PendingChatAction } from './chatActions'
import { chatApi, frozenPageToMatchResult } from './chatApi'
import { candidateSyncAction, createChatClientState, mergeMessagePage, messagesForSelectedBranch, patchMessage, previewMessagesAtBranchPoint, selectConversation } from './chatState'
import { followGeneration, type GenerationEvent } from './generationStream'

const SUGGESTIONS = ['硕士，身高 175 以上', 'O 型血，体型一般', '本科以上，标本充足']
const WELCOME = '描述您的期望，我会帮您筛选合适的候选人。'
const FORK_LABEL: Record<ChatBranchSummary['fork_reason'], string> = {
  root: '主线', rewind_continue: '回溯后继续', edit_resend: '编辑重发',
  regenerate: '重新生成', concurrent_send: '并发分支',
}

type Props = {
  onCandidates: (items: Candidate[], result?: MatchResultDescriptor) => void
  seedMessage?: string | null
  onSeedConsumed?: () => void
  resumeChatId?: number | null
  resumeBranchId?: string | null
  onConversationChange?: (chatId: number | null, branchId: string | null) => void
  drawer?: boolean
  onClose?: () => void
  className?: string
}

function fmtMd(text: string) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br/>')
}

function branchDepth(branch: ChatBranchSummary, branches: ChatBranchSummary[]) {
  const byId = new Map(branches.map((item) => [item.id, item]))
  let depth = 0
  let parent = branch.parent_branch_id
  const seen = new Set<string>()
  while (parent && !seen.has(parent)) {
    seen.add(parent)
    depth += 1
    parent = byId.get(parent)?.parent_branch_id || null
  }
  return depth
}

function isAbortError(error: unknown) {
  return error instanceof Error && error.name === 'AbortError'
}

export function BranchingChatPanel({
  onCandidates, seedMessage, onSeedConsumed, resumeChatId, resumeBranchId,
  onConversationChange, drawer = false, onClose, className = '',
}: Props) {
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [chatState, setChatState] = useState(createChatClientState)
  const [input, setInput] = useState('')
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [branchesOpen, setBranchesOpen] = useState(false)
  const [historyItems, setHistoryItems] = useState<ChatV2Summary[]>([])
  const [historyCursor, setHistoryCursor] = useState<string | null>(null)
  const [historyHasMore, setHistoryHasMore] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingChatAction | null>(null)
  const [matchesByMessage, setMatchesByMessage] = useState<Record<string, MatchResultDescriptor>>({})
  const [matchLoadingId, setMatchLoadingId] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [ttsOn, setTtsOn] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<ReturnType<typeof createSpeechRecognizer>>(null)
  const generationAbortRef = useRef<AbortController | null>(null)
  const loadedLocationRef = useRef('')
  const ttsOnRef = useRef(ttsOn)
  const changeLocationRef = useRef(onConversationChange)
  const loadRef = useRef<((chatId: number, branchId?: string | null, notify?: boolean) => Promise<void>) | null>(null)

  changeLocationRef.current = onConversationChange
  ttsOnRef.current = ttsOn
  const tree = chatState.tree
  const currentChatId = tree?.chat.id || null
  const selectedBranch = tree?.branches.find((branch) => branch.id === chatState.selectedBranchId) || null
  const messages = useMemo(() => messagesForSelectedBranch(chatState), [chatState])
  const messagePreview = useMemo(
    () => pendingAction
      ? previewMessagesAtBranchPoint(messages, pendingAction.parentMessageId ?? null)
      : { items: messages, hiddenCount: 0 },
    [messages, pendingAction],
  )
  const visibleMessages = messagePreview.items
  const selectedPath = chatState.selectedBranchId ? chatState.pathsByBranch[chatState.selectedBranchId] : undefined
  const generatingMessage = [...messages].reverse().find((message) => message.status === 'generating' && message.generation_id)

  function publishCandidates(result?: MatchResultDescriptor) {
    startTransition(() => onCandidates(result?.items || [], result))
  }

  async function loadMatch(message: ChatMessageNode, show = true) {
    if (!message.match_run) {
      if (show) publishCandidates()
      return
    }
    const cached = matchesByMessage[message.id]
    if (cached) {
      if (show) publishCandidates(cached)
      return
    }
    setMatchLoadingId(message.id)
    try {
      const result = frozenPageToMatchResult(await chatApi.match(message.id), message.id)
      setMatchesByMessage((current) => ({ ...current, [message.id]: result }))
      if (show) publishCandidates(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法加载该消息的完整排名快照')
    } finally {
      setMatchLoadingId((current) => current === message.id ? null : current)
    }
  }

  async function loadConversation(chatId: number, requestedBranchId?: string | null, notify = true) {
    setLoadingConversation(true)
    setError('')
    setPendingAction(null)
    setNotice('')
    try {
      const nextTree = await chatApi.tree(chatId)
      const selected = nextTree.branches.find((branch) => branch.id === requestedBranchId)
        || nextTree.branches.find((branch) => branch.id === nextTree.chat.active_branch_id)
        || nextTree.branches.find((branch) => !branch.is_archived) || nextTree.branches[0]
      if (!selected) throw new Error('该会话没有可加载的分支')
      const page = await chatApi.messages(chatId, selected.id)
      setChatState((current) => {
        const base = current.tree?.chat.id === chatId ? current : createChatClientState()
        return mergeMessagePage(selectConversation(base, nextTree, selected.id), page)
      })
      loadedLocationRef.current = `${chatId}:${selected.id}`
      if (notify) changeLocationRef.current?.(chatId, selected.id)
      const candidateAction = candidateSyncAction(page.items)
      if (candidateAction.kind === 'load') await loadMatch(candidateAction.message)
      else if (candidateAction.kind === 'clear') publishCandidates()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法加载历史对话')
    } finally {
      setLoadingConversation(false)
    }
  }
  loadRef.current = loadConversation

  useEffect(() => () => {
    generationAbortRef.current?.abort()
    try { recognitionRef.current?.abort() } catch { /* ignore */ }
    stopSpeaking()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [visibleMessages.length, generatingMessage?.content, pendingAction?.action])

  useEffect(() => {
    if (authLoading || !user || !resumeChatId) return
    const exact = `${resumeChatId}:${resumeBranchId || ''}`
    if (loadedLocationRef.current === exact) return
    void loadRef.current?.(resumeChatId, resumeBranchId, false)
  }, [authLoading, user, resumeChatId, resumeBranchId])

  useEffect(() => {
    if (!seedMessage || !user || sending) return
    setInput(seedMessage)
    onSeedConsumed?.()
    const timer = window.setTimeout(() => void send(seedMessage), 50)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedMessage, user])

  useEffect(() => {
    const generationId = generatingMessage?.generation_id
    const assistantId = generatingMessage?.id
    const branchId = selectedBranch?.id
    if (!generationId || !assistantId || !currentChatId || !branchId) {
      setSending(false)
      return
    }
    const messageId = assistantId
    generationAbortRef.current?.abort()
    const controller = new AbortController()
    generationAbortRef.current = controller
    let streamedText = ''
    setSending(true)
    setNotice('正在连接生成任务…')

    function onEvent(event: GenerationEvent) {
      if (event.event === 'token') {
        streamedText += String(event.data.text || '')
        setChatState((state) => patchMessage(state, messageId, { content: streamedText, status: 'generating' }))
        setNotice('')
      } else if (event.event === 'generation_status') {
        setNotice(String(event.data.status) === 'queued' ? '任务排队中…' : '正在生成…')
      } else if (event.event === 'match_ready') {
        setNotice('完整排名快照已冻结，正在生成说明…')
      }
    }
    void followGeneration(generationId, {
      signal: controller.signal,
      onEvent,
      onReconnect: (attempt) => setNotice(`连接中断，正在第 ${attempt} 次重连…`),
    }).then(async (status) => {
      if (controller.signal.aborted) return
      setNotice(status === 'stopped' ? '生成已停止' : status === 'failed' ? '生成失败，可重试' : '')
      if (status === 'completed' && ttsOnRef.current && streamedText) speakText(streamedText)
      await loadRef.current?.(currentChatId, branchId, false)
    }).catch((cause) => {
      if (!isAbortError(cause)) setError(cause instanceof Error ? cause.message : '生成事件连接失败')
    }).finally(() => {
      if (generationAbortRef.current === controller) {
        generationAbortRef.current = null
        setSending(false)
      }
    })
    return () => controller.abort()
  }, [generatingMessage?.generation_id, generatingMessage?.id, currentChatId, selectedBranch?.id])

  async function loadHistory(reset = true) {
    if (!user || historyLoading) return
    setHistoryLoading(true)
    try {
      const page = await chatApi.list(reset ? null : historyCursor)
      setHistoryItems((current) => reset ? page.items : [...current, ...page.items])
      setHistoryCursor(page.next_cursor)
      setHistoryHasMore(page.has_more)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法加载会话列表')
    } finally { setHistoryLoading(false) }
  }

  function startNewChat() {
    generationAbortRef.current?.abort()
    setChatState(createChatClientState())
    setMatchesByMessage({})
    setPendingAction(null)
    setInput('')
    setError('')
    setNotice('')
    setHistoryOpen(false)
    loadedLocationRef.current = ''
    publishCandidates()
    changeLocationRef.current?.(null, null)
  }

  async function loadOlderMessages() {
    if (!currentChatId || !selectedBranch || !selectedPath?.hasMore || !selectedPath.nextBefore) return
    setLoadingConversation(true)
    try {
      const page = await chatApi.messages(currentChatId, selectedBranch.id, selectedPath.nextBefore)
      setChatState((state) => mergeMessagePage(state, page, true))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法加载更早消息')
    } finally { setLoadingConversation(false) }
  }

  async function stopGeneration(generationId: string) {
    try {
      await chatApi.stop(generationId)
      setNotice('正在停止生成…')
    } catch (cause) { setError(cause instanceof Error ? cause.message : '停止生成失败') }
  }

  async function send(textOverride?: string, regenerate?: ChatMessageNode) {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    if (sending) {
      if (generatingMessage?.generation_id) await stopGeneration(generatingMessage.generation_id)
      return
    }
    const text = regenerate ? '' : (textOverride ?? input).trim()
    if (!regenerate && !text) return
    setSending(true)
    setError('')
    setInput('')
    let created = false
    try {
      const result = await chatApi.turn(currentChatId, buildTurnCommand({
        selectedBranchId: selectedBranch?.id,
        branchHeadMessageId: selectedBranch?.head_message_id,
        pending: pendingAction,
        regenerate,
        content: text,
        requestId: crypto.randomUUID(),
      }))
      created = true
      setPendingAction(null)
      await loadConversation(result.chat_id, result.branch_id)
    } catch (cause) {
      setInput(text)
      setError(cause instanceof Error ? cause.message : '发送失败，请稍后重试')
    } finally { if (!created) setSending(false) }
  }

  function prepareRewind(message: ChatMessageNode) {
    setPendingAction({ action: 'rewind_continue', parentMessageId: message.id,
      label: `待创建：从“${message.content.slice(0, 24) || '此消息'}”继续，发送新消息后创建分支` })
    setInput('')
    setBranchesOpen(true)
    setNotice('已选择回溯点。请输入新消息并发送，原分支会完整保留。')
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function prepareEdit(message: ChatMessageNode) {
    setPendingAction({ action: 'edit_resend', parentMessageId: message.parent_message_id,
      derivedFromMessageId: message.id, label: '待创建：发送编辑后的消息后创建新分支，原路径完整保留' })
    setInput(message.content)
    setBranchesOpen(true)
    setNotice('请修改消息并发送，发送成功后新分支会显示在树中。')
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function cancelPendingAction() {
    setPendingAction(null)
    setNotice('')
  }

  async function renameBranch(branch: ChatBranchSummary) {
    if (!currentChatId) return
    const name = window.prompt('分支名称', branch.name)?.trim()
    if (!name || name === branch.name) return
    try {
      await chatApi.updateBranch(currentChatId, branch.id, { name })
      await loadConversation(currentChatId, selectedBranch?.id, false)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '修改分支名称失败') }
  }

  async function toggleBranchArchive(branch: ChatBranchSummary) {
    if (!currentChatId || branch.is_active) return
    try {
      await chatApi.updateBranch(currentChatId, branch.id, { is_archived: !branch.is_archived })
      await loadConversation(currentChatId, selectedBranch?.id, false)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '修改分支归档状态失败') }
  }

  async function deleteConversation() {
    if (!currentChatId || !tree) return
    if (!window.confirm(`确定永久删除会话“${tree.chat.title}”吗？\n\n所有分支、消息、完整排名快照和生成记录将立即删除，且不可恢复。`)) return
    try {
      await chatApi.remove(currentChatId, crypto.randomUUID())
      startNewChat()
      await loadHistory(true)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '删除会话失败') }
  }

  function toggleVoice() {
    if (recording) {
      try { recognitionRef.current?.stop() } catch { /* ignore */ }
      setRecording(false)
      return
    }
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    if (sending || !getSpeechSupport().recognition) return
    const recognition = createSpeechRecognizer({
      onInterim: setInput,
      onFinal: (text) => { setInput(text); setRecording(false); if (text) void send(text) },
      onError: (message) => { setNotice(message); setRecording(false) },
      onEnd: () => setRecording(false),
    }, { silenceMs: 2200 })
    if (!recognition) return
    recognitionRef.current = recognition
    setRecording(true)
    setNotice('正在聆听…')
    recognition.start()
  }

  const shellClass = drawer ? `flex h-full flex-col bg-white ${className}`
    : `hidden w-[420px] shrink-0 flex-col border-l border-line/80 bg-white/95 xl:flex xl:w-[420px] ${className}`

  return <aside className={shellClass}>
    <header className="shrink-0 border-b border-line/60 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-ink">{tree?.chat.title || '匹配顾问'}</div>
          <div className="mt-0.5 truncate text-[11px] text-ink-soft/45">{selectedBranch ? `${selectedBranch.name} · ${tree?.chat.branch_count || 1} 条分支` : '对话会保存为可回溯分支'}</div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button type="button" title="新对话" onClick={startNewChat} className="rounded-md p-1.5 text-ink-soft/50 hover:bg-mist/60"><i className="ri-add-line" /></button>
          {tree && <button type="button" title="分支树" onClick={() => setBranchesOpen((value) => !value)} className={`rounded-md p-1.5 ${branchesOpen ? 'bg-mist text-teal-deep' : 'text-ink-soft/50'}`}><i className="ri-git-branch-line" /></button>}
          {user ? <button type="button" title="历史对话" onClick={() => { setHistoryOpen((value) => !value); if (!historyOpen) void loadHistory(true) }} className={`rounded-md p-1.5 ${historyOpen ? 'bg-mist text-teal-deep' : 'text-ink-soft/50'}`}><i className="ri-history-line" /></button>
            : <Link to="/login" className="rounded-md p-1.5 text-ink-soft/50"><i className="ri-user-line" /></Link>}
          {tree && <button type="button" title="永久删除会话" onClick={() => void deleteConversation()} className="rounded-md p-1.5 text-ink-soft/40 hover:bg-rose-50 hover:text-rose-600"><i className="ri-delete-bin-line" /></button>}
          {drawer && onClose && <button type="button" onClick={onClose} className="rounded-md p-1 text-ink-soft/45"><i className="ri-close-line text-lg" /></button>}
        </div>
      </div>
      {tree && tree.branches.length > 1 && <div className="mt-2 flex gap-1.5 overflow-x-auto pb-0.5">
        {tree.branches.filter((branch) => !branch.is_archived).map((branch) => <button key={branch.id} type="button" onClick={() => void loadConversation(tree.chat.id, branch.id)} className={`max-w-40 shrink-0 truncate rounded-full px-2.5 py-1 text-[10px] ${branch.id === selectedBranch?.id ? 'bg-teal-deep text-white' : 'bg-sand text-ink-soft/60'}`}>{branch.name}</button>)}
      </div>}
    </header>

    {historyOpen && user && <section className="max-h-52 shrink-0 overflow-y-auto border-b border-line/50 bg-sand/50 px-2 py-2">
      {historyItems.map((chat) => <button key={chat.id} type="button" onClick={() => { setHistoryOpen(false); void loadConversation(chat.id, chat.active_branch_id) }} className="mb-1 w-full rounded-lg px-2 py-1.5 text-left hover:bg-white">
        <div className="flex items-center justify-between gap-2"><span className="truncate text-[12px] font-medium">{chat.title}</span><span className="text-[9px] text-ink-soft/40">{chat.branch_count} 分支</span></div>
        <div className="truncate text-[10px] text-ink-soft/45">{chat.last_message_preview || chat.updated_at}</div>
      </button>)}
      {historyLoading && <div className="px-2 py-1 text-[11px] text-ink-soft/45">加载中…</div>}
      {!historyLoading && historyItems.length === 0 && <div className="px-2 py-1 text-[11px] text-ink-soft/45">暂无新版对话</div>}
      {historyHasMore && <button type="button" onClick={() => void loadHistory(false)} className="w-full py-1 text-[11px] text-teal-deep">加载更多</button>}
    </section>}

    {branchesOpen && tree && <section className="max-h-64 shrink-0 overflow-y-auto border-b border-line/50 bg-white px-2 py-2">
      <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-ink-soft/40">完整分支树</div>
      {tree.branches.map((branch) => <div key={branch.id} style={{ paddingLeft: `${branchDepth(branch, tree.branches) * 14}px` }} className="group/branch flex items-center gap-1">
        <span className="text-ink-soft/30">└</span>
        <button type="button" onClick={() => void loadConversation(tree.chat.id, branch.id)} className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left ${branch.id === selectedBranch?.id ? 'bg-mist text-teal-deep' : 'hover:bg-sand'}`}>
          <div className="flex items-center gap-1"><span className="truncate text-[11px] font-medium">{branch.name}</span>{branch.is_active && <span className="text-[8px]">活跃</span>}{branch.is_archived && <span className="text-[8px]">已归档</span>}</div>
          <div className="text-[9px] text-ink-soft/40">{FORK_LABEL[branch.fork_reason]} · {branch.message_count} 条消息</div>
        </button>
        <button type="button" title="重命名分支" onClick={() => void renameBranch(branch)} className="p-1 text-ink-soft/30 opacity-0 group-hover/branch:opacity-100"><i className="ri-edit-line text-xs" /></button>
        {!branch.is_active && <button type="button" title={branch.is_archived ? '恢复分支' : '归档分支'} onClick={() => void toggleBranchArchive(branch)} className="p-1 text-ink-soft/30 opacity-0 group-hover/branch:opacity-100"><i className={`${branch.is_archived ? 'ri-inbox-unarchive-line' : 'ri-archive-line'} text-xs`} /></button>}
      </div>)}
      {pendingAction && <div className="mt-1 flex items-center gap-1 rounded-lg border border-dashed border-teal/30 bg-mist/40 px-2 py-1.5 text-teal-deep">
        <span className="text-ink-soft/30">└</span>
        <div className="min-w-0"><div className="truncate text-[11px] font-medium">待创建分支</div><div className="text-[9px] opacity-65">发送下方消息后写入分支树</div></div>
      </div>}
    </section>}

    <main className="scroll-y min-h-0 flex-1 space-y-3 overflow-y-auto bg-gradient-to-b from-sand/80 to-sand/30 px-3.5 py-3.5">
      {selectedPath?.hasMore && <button type="button" disabled={loadingConversation} onClick={() => void loadOlderMessages()} className="w-full py-1 text-[11px] text-teal-deep disabled:opacity-40">{loadingConversation ? '加载中…' : '加载更早消息'}</button>}
      {!tree && !loadingConversation && <div className="rounded-2xl border border-line/70 bg-white p-4"><div className="text-[13px] font-semibold">您好</div><p className="mt-1 text-[12px] text-ink-soft/65">{WELCOME}</p><div className="mt-3 flex flex-col gap-1.5">{SUGGESTIONS.map((item) => <button key={item} type="button" onClick={() => void send(item)} className="rounded-lg border border-line/80 bg-sand/40 px-3 py-2 text-left text-[12px] text-ink-soft/75">{item}</button>)}</div></div>}
      {loadingConversation && messages.length === 0 && <div className="py-8 text-center text-[12px] text-ink-soft/45">正在加载对话…</div>}
      {visibleMessages.map((message, index) => {
        const match = matchesByMessage[message.id]
        return <article key={message.id} className="animate-msg-in group/msg">
          <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}><div className={`relative max-w-[92%] rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${message.role === 'user' ? 'rounded-br-md bg-teal-deep text-white' : message.role === 'system' ? 'border border-amber-200 bg-amber-50 text-amber-900/80' : 'rounded-bl-md border border-line/70 bg-white text-ink/90'}`}>
            {message.role === 'assistant' ? <div dangerouslySetInnerHTML={{ __html: fmtMd(message.content || (message.status === 'generating' ? '…' : '')) }} /> : message.content}
            {message.status !== 'completed' && <div className="mt-1 text-[9px] opacity-55">{message.status === 'generating' ? '生成中' : message.status === 'stopped' ? '已停止' : '生成失败'}</div>}
          </div></div>
          {!sending && message.role !== 'system' && <div className={`mt-1 flex gap-2 text-[9px] text-ink-soft/45 ${message.role === 'user' ? 'justify-end' : ''}`}>
            {message.state_recoverable && index < visibleMessages.length - 1 && <button type="button" onClick={() => prepareRewind(message)} className="hover:text-teal-deep">从此处分支</button>}
            {message.role === 'user' && <button type="button" onClick={() => prepareEdit(message)} className="hover:text-teal-deep">编辑重发</button>}
            {message.role === 'assistant' && message.status !== 'generating' && <button type="button" onClick={() => void send(undefined, message)} className="hover:text-teal-deep">{message.status === 'failed' ? '重试' : '重新生成'}</button>}
            {message.match_run && <button type="button" onClick={() => void loadMatch(message)} className="hover:text-teal-deep">{matchLoadingId === message.id ? '加载排名…' : `完整排名（${message.match_run.total}）`}</button>}
          </div>}
          {match?.items.length ? <ChatMatchCards candidates={match.items} totalOverride={match.total} onViewInMiddle={() => publishCandidates(match)} /> : null}
        </article>
      })}
      {pendingAction && <div className="rounded-xl border border-dashed border-teal/25 bg-white/75 px-3 py-2 text-center text-[10px] text-ink-soft/55">
        <i className="ri-git-branch-line mr-1 text-teal-deep" />
        已定位到分支点，原路径后续 {messagePreview.hiddenCount} 条消息已收起但仍完整保留
      </div>}
      <div ref={bottomRef} />
    </main>

    <footer className="shrink-0 border-t border-line/70 bg-white p-3">
      {(error || notice) && <div className={`mb-2 rounded-lg px-2 py-1.5 text-[10px] ${error ? 'bg-rose-50 text-rose-700' : 'bg-mist text-teal-deep'}`}>{error || notice}</div>}
      {pendingAction && <div className="mb-2 flex items-start justify-between gap-2 rounded-lg border border-teal/20 bg-mist/50 px-2.5 py-2 text-[10px] text-teal-deep"><span>{pendingAction.label}</span><button type="button" onClick={cancelPendingAction}>取消</button></div>}
      <div className="flex items-end gap-2 rounded-xl border border-line/80 bg-sand/50 px-2 py-1.5 focus-within:border-teal/40">
        <textarea ref={inputRef} value={input} disabled={selectedBranch?.is_archived} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} rows={2} placeholder={selectedBranch?.is_archived ? '该分支已归档，请先恢复后继续' : pendingAction ? '输入消息，发送后创建新分支…' : '描述您的条件或继续对话…'} className="min-h-[40px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[12.5px] outline-none disabled:opacity-50" />
        <button type="button" title={ttsOn ? '关闭语音播报' : '开启语音播报'} onClick={() => { if (ttsOn) stopSpeaking(); setTtsOn((value) => !value) }} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg ${ttsOn ? 'bg-mist text-teal-deep' : 'text-ink-soft/45'}`}><i className={ttsOn ? 'ri-volume-up-line' : 'ri-volume-mute-line'} /></button>
        <button type="button" title="语音输入" disabled={sending} onClick={toggleVoice} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg disabled:opacity-40 ${recording ? 'bg-red-100 text-red-500' : 'bg-mist text-ink-soft/70'}`}><i className={recording ? 'ri-mic-fill' : 'ri-mic-line'} /></button>
        <button type="button" disabled={!sending && !input.trim()} onClick={() => void send()} title={sending ? '停止生成' : pendingAction ? '发送并创建分支' : '发送'} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg text-white disabled:opacity-40 ${sending ? 'bg-red-500' : 'bg-teal-deep'}`}><i className={sending ? 'ri-stop-fill' : 'ri-arrow-up-line'} /></button>
      </div>
    </footer>
  </aside>
}
