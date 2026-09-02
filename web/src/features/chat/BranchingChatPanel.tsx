import { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ChatMatchCards } from '../../components/ChatMatchCards'
import { useAuth } from '../../context/AuthContext'
import { createSpeechRecognizer, getSpeechSupport, speakText, stopSpeaking } from '../../lib/speech'
import { WORKBENCH_HEADER_HEIGHT_CLASS } from '../../lib/workbenchLayout'
import type { Candidate, ChatBranchSummary, ChatMessageNode, ChatV2Summary, MatchResultDescriptor, MessageFeedbackRating } from '../../types'
import { buildTurnCommand, type PendingChatAction } from './chatActions'
import { chatApi, frozenPageToMatchResult } from './chatApi'
import { canCreateBranchAfterMessage, candidateSyncAction, CHAT_WELCOME_MESSAGE, CHAT_WELCOME_TITLE, createChatClientState, mergeMessagePage, messagesForSelectedBranch, nextFeedbackRating, patchMessage, previewMessagesAtBranchPoint, selectConversation } from './chatState'
import { closeTabState, nextDraftBranchName, replaceDraftTab, type WorkspaceTab } from './chatTabs'
import { followGeneration, generationProgressFromEvent, type GenerationEvent, type GenerationProgress } from './generationStream'

const SUGGESTIONS = ['硕士，身高 175 以上', 'O 型血，体型一般', '本科以上，标本充足']
const FORK_LABEL: Record<ChatBranchSummary['fork_reason'], string> = {
  root: '主线', rewind_continue: '回溯后继续', edit_resend: '编辑重发',
  regenerate: '重新生成', concurrent_send: '并发分支',
}
const MESSAGE_ICON_ACTION = 'inline-flex h-7 w-7 items-center justify-center rounded-md text-[14px] text-ink-soft/45 transition hover:bg-mist hover:text-teal-deep focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-teal/40'

type Props = {
  onCandidates: (items: Candidate[], result?: MatchResultDescriptor) => void
  /** 无对话快照可展示时回退中间栏（通常为全部捐献者），勿传空数组进 onCandidates */
  onClearCandidates?: () => void
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

const GENERATION_PROGRESS_LABELS: Record<GenerationProgress['stage'], string> = {
  connecting: '正在连接 Agent',
  queued: '任务排队中',
  thinking: '正在理解您的需求',
  tool_call: '正在调用匹配工具',
  tool_result: '匹配完成，正在整理结果',
  summarizing: '正在组织回复',
  responding: '正在生成回复',
  reconnecting: '连接中断，正在恢复',
  stopping: '正在停止生成',
  stopped: '生成已停止',
  failed: '生成失败，请编辑上一条消息后重试',
}

function GenerationStatusLine({ progress, content }: { progress: GenerationProgress | null; content: string }) {
  const current = progress || { stage: 'connecting' as const }
  const isActive = current.stage !== 'stopped' && current.stage !== 'failed'
  const count = current.stage === 'tool_result' && current.count !== undefined
    ? `，已找到 ${current.count.toLocaleString()} 位候选人`
    : ''
  const reconnect = current.stage === 'reconnecting' && current.detail ? ` · ${current.detail}` : ''
  return <div className="w-full max-w-[92%] py-1 pl-1">
    <div role="status" aria-live="polite" className={`text-[11.5px] font-medium ${isActive ? 'generation-status-sweep' : current.stage === 'failed' ? 'text-rose-600' : 'text-ink-soft/55'}`}>
      {GENERATION_PROGRESS_LABELS[current.stage]}{count}{reconnect}
    </div>
    {content && <div className="mt-2 rounded-2xl rounded-bl-md border border-line/70 bg-white px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink/90" dangerouslySetInnerHTML={{ __html: fmtMd(content) }} />}
  </div>
}

export function BranchingChatPanel({
  onCandidates, onClearCandidates, seedMessage, onSeedConsumed, resumeChatId, resumeBranchId,
  onConversationChange, drawer = false, onClose, className = '',
}: Props) {
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [chatState, setChatState] = useState(createChatClientState)
  const [workspaceTabs, setWorkspaceTabs] = useState<WorkspaceTab[]>([])
  const [activeTabKey, setActiveTabKey] = useState('new')
  const [inputsByTab, setInputsByTab] = useState<Record<string, string>>({ new: '' })
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [sending, setSending] = useState(false)
  const [generationProgress, setGenerationProgress] = useState<GenerationProgress | null>(null)
  const [feedbackBusy, setFeedbackBusy] = useState<Record<string, boolean>>({})
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const [branchesOpen, setBranchesOpen] = useState(false)
  const [historyItems, setHistoryItems] = useState<ChatV2Summary[]>([])
  const [historyCursor, setHistoryCursor] = useState<string | null>(null)
  const [historyHasMore, setHistoryHasMore] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [matchesByMessage, setMatchesByMessage] = useState<Record<string, MatchResultDescriptor>>({})
  const [matchLoadingId, setMatchLoadingId] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const [ttsOn, setTtsOn] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<ReturnType<typeof createSpeechRecognizer>>(null)
  const generationAbortRef = useRef<AbortController | null>(null)
  /** 用户主动停止的 generation，避免 reload 仍为 generating 时再次拉起 SSE */
  const userStoppedGenerationsRef = useRef(new Set<string>())
  const loadedLocationRef = useRef('')
  const workspaceChatIdRef = useRef<number | null>(null)
  const ttsOnRef = useRef(ttsOn)
  const changeLocationRef = useRef(onConversationChange)
  const loadRef = useRef<((chatId: number, branchId?: string | null, notify?: boolean, tabKey?: string) => Promise<void>) | null>(null)
  const loadOlderRef = useRef<(() => Promise<void>) | null>(null)

  changeLocationRef.current = onConversationChange
  ttsOnRef.current = ttsOn
  const tree = chatState.tree
  const currentChatId = tree?.chat.id || null
  const selectedBranch = tree?.branches.find((branch) => branch.id === chatState.selectedBranchId) || null
  const activeTab = workspaceTabs.find((tab) => tab.key === activeTabKey) || null
  const pendingAction = activeTab?.pendingAction || null
  const input = inputsByTab[activeTabKey] || ''
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

  function setInput(value: string) {
    setInputsByTab((current) => ({ ...current, [activeTabKey]: value }))
  }

  function setPendingAction(value: PendingChatAction | null) {
    setWorkspaceTabs((current) => current.map((tab) => tab.key === activeTabKey
      ? { ...tab, pendingAction: value || undefined }
      : tab))
  }

  function publishCandidates(result?: MatchResultDescriptor) {
    startTransition(() => onCandidates(result?.items || [], result))
  }

  function clearCandidates() {
    if (onClearCandidates) {
      startTransition(() => onClearCandidates())
      return
    }
    // 兼容未传入回调的调用方：至少不要把中间栏锁进空的对话结果
    startTransition(() => onCandidates([]))
  }

  async function loadMatch(message: ChatMessageNode, show = true) {
    if (!message.match_run) {
      if (show) clearCandidates()
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

  async function loadConversation(chatId: number, requestedBranchId?: string | null, notify = true, tabKey?: string) {
    setLoadingConversation(true)
    setError('')
    setNotice('')
    try {
      const nextTree = await chatApi.tree(chatId)
      const selected = nextTree.branches.find((branch) => branch.id === requestedBranchId)
        || nextTree.branches.find((branch) => branch.id === nextTree.chat.active_branch_id)
        || nextTree.branches.find((branch) => !branch.is_archived) || nextTree.branches[0]
      if (!selected) throw new Error('该会话没有可加载的分支')
      const page = await chatApi.messages(chatId, selected.id)
      const targetTabKey = tabKey || selected.id
      if (workspaceChatIdRef.current !== chatId) {
        const rootBranch = nextTree.branches.find((branch) => branch.fork_reason === 'root') || selected
        const initialTabs = [rootBranch, ...(selected.id === rootBranch.id ? [] : [selected])]
        workspaceChatIdRef.current = chatId
        setWorkspaceTabs(initialTabs.map((branch) => ({
          key: branch.id,
          branchId: branch.id,
          name: branch.name,
          closable: branch.fork_reason !== 'root',
        })))
        setInputsByTab(Object.fromEntries(initialTabs.map((branch) => [branch.id, ''])))
        setActiveTabKey(selected.id)
      } else {
        setWorkspaceTabs((current) => {
          if (current.some((tab) => tab.key === targetTabKey)) {
            return current.map((tab) => tab.key === targetTabKey && targetTabKey === selected.id
              ? { ...tab, name: selected.name }
              : tab)
          }
          return [...current, { key: selected.id, branchId: selected.id, name: selected.name, closable: selected.fork_reason !== 'root' }]
        })
        setActiveTabKey(targetTabKey)
      }
      setChatState((current) => {
        const base = current.tree?.chat.id === chatId ? current : createChatClientState()
        return mergeMessagePage(selectConversation(base, nextTree, selected.id), page)
      })
      loadedLocationRef.current = `${chatId}:${selected.id}`
      if (notify) changeLocationRef.current?.(chatId, selected.id)
      const candidateAction = candidateSyncAction(page.items)
      if (candidateAction.kind === 'load') await loadMatch(candidateAction.message)
      else if (candidateAction.kind === 'clear') clearCandidates()
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
      setGenerationProgress(null)
      return
    }
    // 用户已点终止：即使服务端短暂仍为 generating，也不再拉起 SSE
    if (userStoppedGenerationsRef.current.has(generationId)) {
      setSending(false)
      return
    }
    const messageId = assistantId
    generationAbortRef.current?.abort()
    const controller = new AbortController()
    generationAbortRef.current = controller
    let streamedText = ''
    setSending(true)
    setGenerationProgress({ stage: 'connecting' })

    function onEvent(event: GenerationEvent) {
      if (userStoppedGenerationsRef.current.has(generationId)) return
      const progress = generationProgressFromEvent(event)
      if (progress) setGenerationProgress(progress)
      if (event.event === 'token') {
        streamedText += String(event.data.text || '')
        setChatState((state) => patchMessage(state, messageId, { content: streamedText, status: 'generating' }))
      }
    }
    void followGeneration(generationId, {
      signal: controller.signal,
      onEvent,
      onReconnect: (attempt) => setGenerationProgress({ stage: 'reconnecting', detail: `第 ${attempt} 次重连` }),
    }).then(async (status) => {
      if (controller.signal.aborted || userStoppedGenerationsRef.current.has(generationId)) return
      if (status === 'stopped' || status === 'failed') setGenerationProgress({ stage: status })
      if (status === 'completed' && ttsOnRef.current && streamedText) speakText(streamedText)
      userStoppedGenerationsRef.current.delete(generationId)
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
    userStoppedGenerationsRef.current.clear()
    setSending(false)
    setGenerationProgress(null)
    setChatState(createChatClientState())
    setMatchesByMessage({})
    setWorkspaceTabs([])
    setActiveTabKey('new')
    setInputsByTab({ new: '' })
    workspaceChatIdRef.current = null
    setError('')
    setNotice('')
    setHistoryOpen(false)
    loadedLocationRef.current = ''
    clearCandidates()
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
  loadOlderRef.current = loadOlderMessages

  async function stopGeneration(generationId: string) {
    const assistantId = generatingMessage?.id
    const chatId = currentChatId
    const branchId = selectedBranch?.id
    // 立刻断开本地流并乐观更新 UI，不等服务端 worker 收尾
    userStoppedGenerationsRef.current.add(generationId)
    generationAbortRef.current?.abort()
    generationAbortRef.current = null
    setSending(false)
    setGenerationProgress({ stage: 'stopping' })
    if (assistantId) {
      setChatState((state) => patchMessage(state, assistantId, { status: 'stopped' }))
    }
    try {
      await chatApi.stop(generationId)
      setGenerationProgress({ stage: 'stopped' })
      if (chatId && branchId) {
        await loadRef.current?.(chatId, branchId, false)
        // reload 后若服务端仍短暂为 generating，保持本地 stopped；
        // generationId 留在 userStoppedGenerationsRef，直到新对话才清理。
        if (assistantId) {
          setChatState((state) => {
            const node = state.messagesById[assistantId]
            if (node?.generation_id === generationId && node.status === 'generating') {
              return patchMessage(state, assistantId, { status: 'stopped' })
            }
            return state
          })
        }
      }
    } catch (cause) {
      userStoppedGenerationsRef.current.delete(generationId)
      setGenerationProgress(null)
      setError(cause instanceof Error ? cause.message : '停止生成失败')
    }
  }

  async function toggleFeedback(message: ChatMessageNode, rating: MessageFeedbackRating) {
    if (!selectedBranch || feedbackBusy[message.id]) return
    const previous = message.feedback
    const next = nextFeedbackRating(previous?.rating || null, rating)
    setFeedbackBusy((current) => ({ ...current, [message.id]: true }))
    setError('')
    setChatState((state) => patchMessage(state, message.id, {
      feedback: next ? { message_id: message.id, rating: next, updated_at: new Date().toISOString() } : null,
    }))
    try {
      if (next) {
        const saved = await chatApi.setFeedback(message.id, selectedBranch.id, next)
        setChatState((state) => patchMessage(state, message.id, { feedback: saved }))
      } else {
        await chatApi.deleteFeedback(message.id)
      }
    } catch (cause) {
      setChatState((state) => patchMessage(state, message.id, { feedback: previous }))
      setError(cause instanceof Error ? cause.message : '反馈保存失败，请稍后重试')
    } finally {
      setFeedbackBusy((current) => {
        const nextBusy = { ...current }
        delete nextBusy[message.id]
        return nextBusy
      })
    }
  }

  async function send(textOverride?: string) {
    if (!user) {
      navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      return
    }
    if (sending) {
      if (generatingMessage?.generation_id) await stopGeneration(generatingMessage.generation_id)
      return
    }
    const text = (textOverride ?? input).trim()
    if (!text) return
    setSending(true)
    setGenerationProgress({ stage: 'queued' })
    setError('')
    setInput('')
    let created = false
    try {
      const result = await chatApi.turn(currentChatId, buildTurnCommand({
        selectedBranchId: selectedBranch?.id,
        branchHeadMessageId: selectedBranch?.head_message_id,
        pending: pendingAction,
        content: text,
        requestId: crypto.randomUUID(),
      }))
      created = true
      const submittedTabKey = activeTabKey
      if (pendingAction?.action === 'rewind_continue') {
        setWorkspaceTabs((current) => replaceDraftTab(
          current,
          submittedTabKey,
          result.branch_id,
          activeTab?.name || '分支',
        ))
        setInputsByTab((current) => {
          const next = { ...current, [result.branch_id]: '' }
          delete next[submittedTabKey]
          return next
        })
        setActiveTabKey(result.branch_id)
      } else {
        setPendingAction(null)
      }
      await loadConversation(result.chat_id, result.branch_id, true, result.branch_id)
    } catch (cause) {
      setInput(text)
      setGenerationProgress(null)
      setError(cause instanceof Error ? cause.message : '发送失败，请稍后重试')
    } finally { if (!created) setSending(false) }
  }

  function openBranchTab(branch: ChatBranchSummary) {
    if (!currentChatId) return
    setWorkspaceTabs((current) => current.some((tab) => tab.key === branch.id)
      ? current
      : [...current, { key: branch.id, branchId: branch.id, name: branch.name, closable: branch.fork_reason !== 'root' }])
    void loadConversation(currentChatId, branch.id, true, branch.id)
    setBranchesOpen(false)
  }

  function switchWorkspaceTab(tab: WorkspaceTab) {
    if (!currentChatId || tab.key === activeTabKey) return
    void loadConversation(currentChatId, tab.branchId, true, tab.key)
  }

  function closeWorkspaceTab(tabKey: string) {
    const nextState = closeTabState(workspaceTabs, activeTabKey, tabKey)
    if (nextState.tabs === workspaceTabs) return
    setWorkspaceTabs(nextState.tabs)
    setInputsByTab((current) => {
      const next = { ...current }
      delete next[tabKey]
      return next
    })
    if (tabKey !== activeTabKey) return
    const fallback = nextState.tabs.find((tab) => tab.key === nextState.nextActiveKey)
    if (fallback && currentChatId) {
      void loadConversation(currentChatId, fallback.branchId, true, fallback.key)
    }
  }

  function prepareRewind(message: ChatMessageNode) {
    if (!selectedBranch || !tree) return
    const draftName = nextDraftBranchName(
      tree.branches.filter((branch) => branch.fork_reason !== 'root').length,
      workspaceTabs.filter((tab) => tab.key.startsWith('draft:')).length,
    )
    const key = `draft:${crypto.randomUUID()}`
    const pending: PendingChatAction = {
      action: 'rewind_continue',
      parentMessageId: message.id,
      label: `新分支将从“${message.content.slice(0, 24) || '此消息'}”继续`,
    }
    setWorkspaceTabs((current) => [...current, {
      key,
      branchId: selectedBranch.id,
      name: draftName,
      closable: true,
      pendingAction: pending,
    }])
    setInputsByTab((current) => ({ ...current, [key]: '' }))
    setActiveTabKey(key)
    setNotice('')
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function prepareEdit(message: ChatMessageNode) {
    setPendingAction({ action: 'edit_resend', parentMessageId: message.parent_message_id,
      derivedFromMessageId: message.id, label: '正在编辑当前线路' })
    setInput(message.content)
    setNotice('')
    setError('')
    window.requestAnimationFrame(() => inputRef.current?.focus())
  }

  function cancelPendingAction() {
    setNotice('')
    if (pendingAction?.action === 'rewind_continue') closeWorkspaceTab(activeTabKey)
    else setPendingAction(null)
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
    <header className={`flex shrink-0 items-center border-b border-line/60 bg-white px-3 ${WORKBENCH_HEADER_HEIGHT_CLASS}`}>
      <div className="flex w-full items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-ink">AI 匹配顾问</div>
          <div className="mt-0.5 truncate text-[11px] text-ink-soft/45">{tree ? `对话已保存 · ${tree.chat.branch_count || 1} 条分支` : '描述条件，获取智能匹配建议'}</div>
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
    </header>

    {tree && workspaceTabs.length > 0 && <nav aria-label="当前打开的对话线路" className="flex shrink-0 items-end gap-1 overflow-x-auto border-b border-line/60 bg-mist/45 px-2 pt-1.5">
      {workspaceTabs.map((tab) => <div key={tab.key} className={`flex min-w-[92px] max-w-[140px] flex-1 items-center gap-1 rounded-t-lg border border-b-0 px-2 py-1.5 ${tab.key === activeTabKey ? 'border-line/70 bg-white text-teal-deep' : 'border-transparent text-ink-soft/55 hover:bg-white/60'}`}>
        <button type="button" onClick={() => switchWorkspaceTab(tab)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left" aria-current={tab.key === activeTabKey ? 'page' : undefined}>
          <i className={`${tab.name === '主线' ? 'ri-chat-3-line' : 'ri-git-branch-line'} shrink-0 text-[11px]`} />
          <span className="truncate text-[11px] font-medium">{tab.name}</span>
        </button>
        {tab.closable && <button type="button" title={`关闭${tab.name}`} aria-label={`关闭${tab.name}`} onClick={() => closeWorkspaceTab(tab.key)} className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-soft/35 hover:bg-rose-50 hover:text-rose-600"><i className="ri-close-line text-xs" /></button>}
      </div>)}
      <button type="button" title="打开其他分支" aria-label="打开其他分支" onClick={() => setBranchesOpen(true)} className="mb-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-soft/45 hover:bg-white hover:text-teal-deep"><i className="ri-add-line" /></button>
    </nav>}

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
        <button type="button" title="在助手内打开分支" onClick={() => openBranchTab(branch)} className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left ${branch.id === selectedBranch?.id ? 'bg-mist text-teal-deep' : 'hover:bg-sand'}`}>
          <div className="flex items-center gap-1"><span className="truncate text-[11px] font-medium">{branch.name}</span>{branch.is_active && <span className="text-[8px]">活跃</span>}{branch.is_archived && <span className="text-[8px]">已归档</span>}</div>
          <div className="text-[9px] text-ink-soft/40">{FORK_LABEL[branch.fork_reason]} · {branch.message_count} 条消息</div>
        </button>
        {!branch.is_active && <button type="button" title={branch.is_archived ? '恢复分支' : '归档分支'} onClick={() => void toggleBranchArchive(branch)} className="p-1 text-ink-soft/30 opacity-0 group-hover/branch:opacity-100"><i className={`${branch.is_archived ? 'ri-inbox-unarchive-line' : 'ri-archive-line'} text-xs`} /></button>}
      </div>)}
      {pendingAction?.action === 'rewind_continue' && <div className="mt-1 flex items-center gap-1 rounded-lg border border-dashed border-teal/30 bg-mist/40 px-2 py-1.5 text-teal-deep">
        <span className="text-ink-soft/30">└</span>
        <div className="min-w-0"><div className="truncate text-[11px] font-medium">待创建分支</div><div className="text-[9px] opacity-65">发送下方消息后写入分支树</div></div>
      </div>}
    </section>}

    <main className="scroll-y min-h-0 flex-1 space-y-3 overflow-y-auto bg-gradient-to-b from-sand/80 to-sand/30 px-3.5 py-3.5">
      {selectedPath?.hasMore && <button type="button" disabled={loadingConversation} onClick={() => void loadOlderMessages()} className="w-full py-1 text-[11px] text-teal-deep disabled:opacity-40">{loadingConversation ? '加载中…' : '加载更早消息'}</button>}
      {!tree && !loadingConversation && <div className="rounded-2xl border border-line/70 bg-white p-4"><div className="text-[13px] font-semibold">{CHAT_WELCOME_TITLE}</div><p className="mt-1 text-[12px] text-ink-soft/65">{CHAT_WELCOME_MESSAGE}</p><div className="mt-3 flex flex-col gap-1.5">{SUGGESTIONS.map((item) => <button key={item} type="button" onClick={() => void send(item)} className="rounded-lg border border-line/80 bg-sand/40 px-3 py-2 text-left text-[12px] text-ink-soft/75">{item}</button>)}</div></div>}
      {loadingConversation && messages.length === 0 && <div className="py-8 text-center text-[12px] text-ink-soft/45">正在加载对话…</div>}
      {visibleMessages.map((message, index) => {
        const match = matchesByMessage[message.id]
        const canBranch = canCreateBranchAfterMessage(message, index, visibleMessages.length)
        const canFeedback = message.role === 'assistant' && message.status === 'completed'
        return <article key={message.id} className="animate-msg-in group/msg">
          <div className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>{message.role === 'assistant' && message.status === 'generating'
            ? <GenerationStatusLine progress={generationProgress} content={message.content} />
            : <div className={`relative max-w-[92%] rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${message.role === 'user' ? 'rounded-br-md bg-teal-deep text-white' : message.role === 'system' ? 'border border-amber-200 bg-amber-50 text-amber-900/80' : 'rounded-bl-md border border-line/70 bg-white text-ink/90'}`}>
              {message.role === 'assistant' ? <div dangerouslySetInnerHTML={{ __html: fmtMd(message.content) }} /> : message.content}
              {message.status !== 'completed' && <div className="mt-1 text-[9px] opacity-55">{message.status === 'stopped' ? '已停止' : '生成失败'}</div>}
            </div>}</div>
          {message.match_run && !match?.items.length && <button type="button" onClick={() => void loadMatch(message)} className="mt-2 flex w-full max-w-[92%] items-center gap-2 rounded-xl border border-line/70 bg-white px-3 py-2 text-left text-[11px] text-ink-soft/65 hover:border-teal/30 hover:bg-mist/30">
            <i className={matchLoadingId === message.id ? 'ri-loader-4-line animate-spin text-teal-deep' : 'ri-group-line text-teal-deep'} />
            <span className="font-medium">候选人结果</span>
            <span className="tabular-nums">{message.match_run.total} 位</span>
            <i className="ri-arrow-right-s-line ml-auto text-ink-soft/35" />
          </button>}
          {match?.items.length ? <ChatMatchCards candidates={match.items} totalOverride={match.total} onViewInMiddle={() => publishCandidates(match)} /> : null}
          {((!sending && message.role !== 'system' && (canBranch || message.role === 'user' || message.match_run)) || canFeedback) && <div className={`mt-1 flex items-center gap-1 text-[9px] text-ink-soft/45 ${message.role === 'user' ? 'justify-end' : ''}`}>
            {!sending && canBranch && <button type="button" title="在完整回复后创建分支" aria-label="在完整回复后创建分支" onClick={() => prepareRewind(message)} className={MESSAGE_ICON_ACTION}><i className="ri-git-branch-line" /></button>}
            {!sending && message.role === 'user' && <button type="button" title="编辑当前消息" aria-label="编辑当前消息" onClick={() => prepareEdit(message)} className={MESSAGE_ICON_ACTION}><i className="ri-edit-line" /></button>}
            {!sending && message.match_run && <button type="button" title={`完整排名（${message.match_run.total}）`} aria-label={`完整排名，共 ${message.match_run.total} 位`} onClick={() => void loadMatch(message)} className={MESSAGE_ICON_ACTION}><i className={matchLoadingId === message.id ? 'ri-loader-4-line animate-spin' : 'ri-list-ordered-2'} /></button>}
            {canFeedback && <span className="ml-1 flex items-center gap-0.5 border-l border-line/60 pl-1">
              <button type="button" title="喜欢这条回复" aria-label="喜欢这条回复" aria-pressed={message.feedback?.rating === 'like'} disabled={feedbackBusy[message.id]} onClick={() => void toggleFeedback(message, 'like')} className={`${MESSAGE_ICON_ACTION} ${message.feedback?.rating === 'like' ? 'bg-emerald-50 text-emerald-600' : ''} disabled:opacity-40`}><i className={message.feedback?.rating === 'like' ? 'ri-thumb-up-fill' : 'ri-thumb-up-line'} /></button>
              <button type="button" title="不喜欢这条回复" aria-label="不喜欢这条回复" aria-pressed={message.feedback?.rating === 'dislike'} disabled={feedbackBusy[message.id]} onClick={() => void toggleFeedback(message, 'dislike')} className={`${MESSAGE_ICON_ACTION} ${message.feedback?.rating === 'dislike' ? 'bg-rose-50 text-rose-500' : ''} disabled:opacity-40`}><i className={message.feedback?.rating === 'dislike' ? 'ri-thumb-down-fill' : 'ri-thumb-down-line'} /></button>
            </span>}
          </div>}
        </article>
      })}
      {pendingAction?.action === 'rewind_continue' && <div className="rounded-xl border border-dashed border-teal/25 bg-white/75 px-3 py-2 text-center text-[10px] text-ink-soft/55">
        <i className="ri-git-branch-line mr-1 text-teal-deep" />
        已定位到分支点，原路径后续 {messagePreview.hiddenCount} 条消息会完整保留
      </div>}
      <div ref={bottomRef} />
    </main>

    <footer className="shrink-0 border-t border-line/70 bg-white p-3">
      {(error || notice) && <div className={`mb-2 rounded-lg px-2 py-1.5 text-[10px] ${error ? 'bg-rose-50 text-rose-700' : 'bg-mist text-teal-deep'}`}>{error || notice}</div>}
      {pendingAction?.action === 'edit_resend' && (
        <div className="mb-2 flex items-center justify-end">
          <button type="button" onClick={cancelPendingAction} className="text-[11px] text-ink-soft/50 transition hover:text-teal-deep">取消编辑</button>
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-line/80 bg-sand/50 px-2 py-1.5 focus-within:border-teal/40">
        <textarea ref={inputRef} value={input} disabled={selectedBranch?.is_archived} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} rows={2} placeholder={selectedBranch?.is_archived ? '该分支已归档，请先恢复后继续' : pendingAction?.action === 'rewind_continue' ? '输入新分支的第一条消息…' : pendingAction?.action === 'edit_resend' ? '修改这条消息…' : '描述您的条件或继续对话…'} className="min-h-[40px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[12.5px] outline-none disabled:opacity-50" />
        <button type="button" title={ttsOn ? '关闭语音播报' : '开启语音播报'} onClick={() => { if (ttsOn) stopSpeaking(); setTtsOn((value) => !value) }} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg ${ttsOn ? 'bg-mist text-teal-deep' : 'text-ink-soft/45'}`}><i className={ttsOn ? 'ri-volume-up-line' : 'ri-volume-mute-line'} /></button>
        <button type="button" title="语音输入" disabled={sending} onClick={toggleVoice} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg disabled:opacity-40 ${recording ? 'bg-red-100 text-red-500' : 'bg-mist text-ink-soft/70'}`}><i className={recording ? 'ri-mic-fill' : 'ri-mic-line'} /></button>
        <button type="button" disabled={!sending && !input.trim()} onClick={() => void send()} title={sending ? '停止生成' : pendingAction?.action === 'rewind_continue' ? '发送并创建分支' : pendingAction?.action === 'edit_resend' ? '保存编辑并发送' : '发送'} className={`mb-0.5 flex h-9 w-9 items-center justify-center rounded-lg text-white disabled:opacity-40 ${sending ? 'bg-red-500' : 'bg-teal-deep'}`}><i className={sending ? 'ri-stop-fill' : 'ri-arrow-up-line'} /></button>
      </div>
    </footer>
  </aside>
}
