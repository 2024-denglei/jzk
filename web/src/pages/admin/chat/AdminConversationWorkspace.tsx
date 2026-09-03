import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatMessageNode,
  ChatV2Summary,
  FrozenMatchPage,
} from '../../../types'
import { CHAT_WELCOME_MESSAGE, CHAT_WELCOME_TITLE } from '../../../features/chat/chatState'
import { formatTime } from '../adminFormat'
import { adminChatApi, type AdminGenerationTrace } from './adminChatApi'
import {
  branchOriginLabel,
  latestSystemContextEvent,
  layoutHorizontalBranchTree,
  turnExecutionEvents,
  type AgentToolCall,
  type AgentTranscriptEvent,
} from './adminChatState'

type LoadState = { loading: boolean; error: string }
type AssistantArtifacts = {
  trace: AdminGenerationTrace | null
  match: FrozenMatchPage | null
  traceState: LoadState
  matchState: LoadState
}

const IDLE: LoadState = { loading: false, error: '' }

function emptyArtifacts(message: ChatMessageNode): AssistantArtifacts {
  return {
    trace: null,
    match: null,
    traceState: { loading: Boolean(message.generation_id), error: '' },
    matchState: { loading: Boolean(message.match_run), error: '' },
  }
}

function statusLabel(status: ChatMessageNode['status']) {
  return { generating: '生成中', completed: '已完成', stopped: '已停止', failed: '失败' }[status]
}

export function AdminConversationWorkspace({
  userId,
  initialChatId,
  initialBranchId,
  initialMessageId,
}: {
  userId: number
  initialChatId?: number
  initialBranchId?: string
  initialMessageId?: string
}) {
  const [chats, setChats] = useState<ChatV2Summary[]>([])
  const [chatCursor, setChatCursor] = useState<string | null>(null)
  const [chatHasMore, setChatHasMore] = useState(false)
  const [tree, setTree] = useState<ChatConversationTree | null>(null)
  const [branchId, setBranchId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessageNode[]>([])
  const [artifacts, setArtifacts] = useState<Record<string, AssistantArtifacts>>({})
  const [listState, setListState] = useState<LoadState>({ loading: true, error: '' })
  const [treeState, setTreeState] = useState<LoadState>(IDLE)
  const [pathState, setPathState] = useState<LoadState>(IDLE)
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(initialMessageId || null)
  const branchRequestRef = useRef(0)

  const branchLayout = useMemo(() => layoutHorizontalBranchTree(tree?.branches || []), [tree])
  const selectedBranch = tree?.branches.find((branch) => branch.id === branchId) || null
  const assistantMessages = useMemo(() => messages.filter((message) => message.role === 'assistant'), [messages])
  const systemEvent = useMemo(() => latestSystemContextEvent(
    assistantMessages.flatMap((message) => {
      const trace = artifacts[message.id]?.trace
      return trace ? [trace.steps] : []
    }),
  ), [artifacts, assistantMessages])

  async function loadChats(reset = true) {
    setListState({ loading: true, error: '' })
    try {
      const page = await adminChatApi.list(userId, reset ? null : chatCursor)
      setChats((current) => reset ? page.items : [...current, ...page.items])
      setChatCursor(page.next_cursor)
      setChatHasMore(page.has_more)
      setListState(IDLE)
      if (reset && initialChatId) await openChat(initialChatId, initialBranchId, initialMessageId)
      else if (reset && page.items[0]) await openChat(page.items[0].id)
    } catch (error) {
      setListState({ loading: false, error: error instanceof Error ? error.message : '会话列表加载失败' })
    }
  }

  useEffect(() => {
    void loadChats(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, initialChatId, initialBranchId, initialMessageId])

  useEffect(() => {
    if (!focusedMessageId || !messages.some((message) => message.id === focusedMessageId)) return
    requestAnimationFrame(() => {
      document.querySelector(`[data-message-id="${focusedMessageId}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
  }, [focusedMessageId, messages])

  async function openChat(chatId: number, requestedBranchId?: string, requestedMessageId?: string) {
    const request = ++branchRequestRef.current
    setTreeState({ loading: true, error: '' })
    setTree(null)
    setMessages([])
    setArtifacts({})
    try {
      const loaded = await adminChatApi.tree(userId, chatId)
      if (request !== branchRequestRef.current) return
      setTree(loaded)
      setChats((current) => current.some((chat) => chat.id === loaded.chat.id) ? current : [loaded.chat, ...current])
      setTreeState(IDLE)
      const selected = loaded.branches.find((branch) => branch.id === requestedBranchId)
        || loaded.branches.find((branch) => branch.id === loaded.chat.active_branch_id)
        || loaded.branches[0]
      if (selected) await openBranch(chatId, selected, requestedMessageId)
    } catch (error) {
      if (request !== branchRequestRef.current) return
      setTreeState({ loading: false, error: error instanceof Error ? error.message : '分支树加载失败' })
    }
  }

  async function openBranch(chatId: number, branch: ChatBranchSummary, targetMessageId?: string) {
    const request = ++branchRequestRef.current
    setBranchId(branch.id)
    setPathState({ loading: true, error: '' })
    setMessages([])
    setArtifacts({})
    setFocusedMessageId(targetMessageId || null)
    try {
      const page = targetMessageId
        ? await adminChatApi.messageContext(userId, chatId, branch.id, targetMessageId)
        : await adminChatApi.messages(userId, chatId, branch.id)
      if (request !== branchRequestRef.current) return
      setMessages(page.items)
      setPathState(IDLE)
      void loadAssistantArtifacts(chatId, page.items, request)
    } catch (error) {
      if (request !== branchRequestRef.current) return
      setPathState({ loading: false, error: error instanceof Error ? error.message : '消息路径加载失败' })
    }
  }

  async function loadAssistantArtifacts(chatId: number, path: ChatMessageNode[], request: number) {
    const assistants = path.filter((message) => message.role === 'assistant')
    setArtifacts(Object.fromEntries(assistants.map((message) => [message.id, emptyArtifacts(message)])))
    await Promise.all(assistants.flatMap((message) => {
      const tasks: Promise<void>[] = []
      if (message.generation_id) {
        tasks.push(adminChatApi.trace(userId, chatId, message.generation_id).then((trace) => {
          if (request !== branchRequestRef.current) return
          setArtifacts((current) => ({
            ...current,
            [message.id]: { ...(current[message.id] || emptyArtifacts(message)), trace, traceState: IDLE },
          }))
        }).catch((error) => {
          if (request !== branchRequestRef.current) return
          setArtifacts((current) => ({
            ...current,
            [message.id]: {
              ...(current[message.id] || emptyArtifacts(message)),
              traceState: { loading: false, error: error instanceof Error ? error.message : 'Agent Trace 加载失败' },
            },
          }))
        }))
      }
      if (message.match_run) {
        tasks.push(adminChatApi.match(userId, chatId, message.id).then((match) => {
          if (request !== branchRequestRef.current) return
          setArtifacts((current) => ({
            ...current,
            [message.id]: { ...(current[message.id] || emptyArtifacts(message)), match, matchState: IDLE },
          }))
        }).catch((error) => {
          if (request !== branchRequestRef.current) return
          setArtifacts((current) => ({
            ...current,
            [message.id]: {
              ...(current[message.id] || emptyArtifacts(message)),
              matchState: { loading: false, error: error instanceof Error ? error.message : '排名快照加载失败' },
            },
          }))
        }))
      }
      return tasks
    }))
  }

  async function loadMatchPage(message: ChatMessageNode, page: number) {
    if (!tree || !message.match_run) return
    const request = branchRequestRef.current
    setArtifacts((current) => ({
      ...current,
      [message.id]: { ...(current[message.id] || emptyArtifacts(message)), matchState: { loading: true, error: '' } },
    }))
    try {
      const match = await adminChatApi.match(userId, tree.chat.id, message.id, page)
      if (request !== branchRequestRef.current) return
      setArtifacts((current) => ({
        ...current,
        [message.id]: { ...(current[message.id] || emptyArtifacts(message)), match, matchState: IDLE },
      }))
    } catch (error) {
      if (request !== branchRequestRef.current) return
      setArtifacts((current) => ({
        ...current,
        [message.id]: {
          ...(current[message.id] || emptyArtifacts(message)),
          matchState: { loading: false, error: error instanceof Error ? error.message : '排名快照加载失败' },
        },
      }))
    }
  }

  return (
    <div className="grid h-full min-h-0 min-w-[1040px] grid-cols-[250px_minmax(0,1fr)] overflow-hidden bg-[#f5f7fa]">
      <aside className="flex min-h-0 flex-col border-r border-[#e1e7ef] bg-white">
        <PaneTitle icon="ri-chat-history-line" title="会话记录" subtitle="每个 Session 对应一棵完整分支树" count={chats.length} />
        <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto bg-[#f7f9fc] p-2">
          {chats.map((chat) => (
            <button key={chat.id} type="button" onClick={() => void openChat(chat.id)} className={`w-full rounded-xl border px-3 py-3 text-left transition ${tree?.chat.id === chat.id ? 'border-[#b9d3fb] bg-[#eaf2ff] shadow-sm' : 'border-transparent hover:bg-white'}`}>
              <div className="truncate text-[12px] font-semibold tracking-wide text-[#304159]">Session #{chat.id}</div>
              <div className="mt-1.5 line-clamp-2 text-[10px] leading-4 text-[#748196]">{chat.last_message_preview || '暂无消息摘要'}</div>
              <div className="mt-2 flex justify-between gap-2 text-[9px] text-[#98a3b4]"><span>{chat.branch_count} 条线路 · {chat.message_count} 条消息</span><span className="shrink-0">{formatTime(chat.updated_at)}</span></div>
            </button>
          ))}
          <LoadNotice state={listState} empty={!chats.length} emptyText="暂无会话" />
          {chatHasMore && !listState.loading && <button type="button" onClick={() => void loadChats(false)} className="w-full py-3 text-xs text-[#1677ff]">加载更多会话</button>}
        </div>
      </aside>

      <main className="flex min-h-0 min-w-0 flex-col bg-[#f5f7fa]">
        <section className="shrink-0 border-b border-[#e1e7ef] bg-white">
          <PaneTitle icon="ri-git-branch-line" title={tree ? `Session #${tree.chat.id} 的对话分支` : '对话分支'} subtitle="横向展示完整分支关系，点击节点切换下方对话" count={tree?.chat.branch_count} />
          {treeState.error ? <InlineError text={treeState.error} /> : null}
          {tree && <HorizontalBranchTree layout={branchLayout} selectedBranchId={branchId} onSelect={(branch) => void openBranch(tree.chat.id, branch)} />}
        </section>

        <section className="min-h-0 flex-1 overflow-y-auto p-4">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div><div className="text-[9px] text-[#8793a5]">{tree ? `Session #${tree.chat.id}` : 'Session'} / {selectedBranch?.name || '请选择线路'}</div><h3 className="mt-1 text-sm font-semibold text-[#2e3d54]">{selectedBranch ? `${selectedBranch.name} · 完整执行时间线` : '选择分支查看完整执行时间线'}</h3></div>
            {selectedBranch && <span className="rounded-full bg-[#edf4ff] px-2.5 py-1 text-[9px] font-semibold text-[#1677ff]">{assistantMessages.length} 轮 Agent 执行</span>}
          </div>
          <LoadNotice state={pathState} empty={!messages.length} emptyText="该分支暂无消息" />
          {messages.length > 0 && <BranchExecutionTimeline
            messages={messages}
            artifacts={artifacts}
            systemEvent={systemEvent}
            focusedMessageId={focusedMessageId}
            onMatchPage={(message, page) => void loadMatchPage(message, page)}
          />}
        </section>
      </main>
    </div>
  )
}

function PaneTitle({ icon, title, subtitle, count }: { icon: string; title: string; subtitle: string; count?: number }) {
  return <header className="shrink-0 border-b border-[#e1e7ef] bg-white px-4 py-3"><div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2 text-xs font-semibold text-[#304159]"><i className={`${icon} text-[#1677ff]`} />{title}</div>{count !== undefined && <span className="rounded-full bg-[#edf4ff] px-2 py-0.5 text-[9px] font-semibold text-[#1677ff]">{count}</span>}</div><div className="mt-1 text-[9px] text-[#929dac]">{subtitle}</div></header>
}

function HorizontalBranchTree({ layout, selectedBranchId, onSelect }: {
  layout: ReturnType<typeof layoutHorizontalBranchTree>
  selectedBranchId: string | null
  onSelect: (branch: ChatBranchSummary) => void
}) {
  const onlyRoot = layout.nodes.length <= 1
  return <div className="max-h-[250px] overflow-auto bg-[#f8fafc] px-4 py-3">
    {onlyRoot && (
      <div className="mb-2 text-[9px] text-[#929dac]">暂无子分支（仅主线）。编辑消息会改写当前线路，不会产生新分支；只有「回溯后继续」才会分叉。</div>
    )}
    <div className="relative" style={{ width: `${layout.width}px`, height: `${layout.height}px` }}>
      <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
        {layout.edges.map((edge) => {
          const middle = (edge.fromX + edge.toX) / 2
          return <path key={`${edge.parentId}-${edge.childId}`} d={`M ${edge.fromX} ${edge.fromY} C ${middle} ${edge.fromY}, ${middle} ${edge.toY}, ${edge.toX} ${edge.toY}`} fill="none" stroke="#b8c6d8" strokeWidth="1.5" />
        })}
      </svg>
      {layout.nodes.map((node) => <button key={node.branch.id} type="button" onClick={() => onSelect(node.branch)} style={{ left: `${node.x}px`, top: `${node.y}px` }} className={`absolute h-[52px] w-[170px] rounded-xl border bg-white px-3 py-2 text-left shadow-[0_3px_9px_rgba(38,55,78,0.05)] transition ${node.branch.id === selectedBranchId ? 'border-[#5b97ea] bg-[#eaf2ff] ring-2 ring-[#1677ff]/10' : 'border-[#d8e0eb] hover:border-[#9fc2f4]'}`}>
        <div className="flex items-center gap-1.5 text-[10px] font-semibold text-[#33445c]"><i className={node.branch.fork_reason === 'root' ? 'ri-chat-3-line text-[#1677ff]' : 'ri-git-branch-line text-[#1677ff]'} /><span className="truncate">{node.branch.name}</span>{node.branch.is_active && <span className="ml-auto rounded bg-emerald-50 px-1 py-0.5 text-[7px] text-emerald-700">用户活跃</span>}</div>
        <div className="mt-1 truncate text-[8.5px] text-[#8995a7]">{branchOriginLabel(node.branch)} · {node.branch.message_count} 条消息</div>
      </button>)}
    </div>
  </div>
}

function BranchExecutionTimeline({ messages, artifacts, systemEvent, focusedMessageId, onMatchPage }: {
  messages: ChatMessageNode[]
  artifacts: Record<string, AssistantArtifacts>
  systemEvent: AgentTranscriptEvent | null
  focusedMessageId: string | null
  onMatchPage: (message: ChatMessageNode, page: number) => void
}) {
  const assistants = messages.filter((message) => message.role === 'assistant')
  const latestTrace = [...assistants].reverse().flatMap((message) => artifacts[message.id]?.trace ? [artifacts[message.id].trace] : [])[0]
  const moduleCount = 1 + (systemEvent ? 1 : 0) + messages.reduce((count, message) => {
    if (message.role !== 'assistant') return count + 1
    const trace = artifacts[message.id]?.trace
    if (!trace) return count + 1
    return count + Math.max(1, turnExecutionEvents(trace.steps).reduce(
      (total, event) => total + 1 + (event.phase === 'tool_call' ? event.toolCalls.length : 0),
      0,
    ))
  }, 0)
  return <section className="overflow-hidden rounded-2xl border border-[#dce4ee] bg-white shadow-[0_3px_12px_rgba(38,55,78,0.04)]">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e7ecf3] bg-[#fbfcfe] px-4 py-3">
      <div><div className="text-[11px] font-semibold text-[#304159]">该线路从打开到当前的完整 Agent 执行时间线</div><div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[8.5px] text-[#8a96a8]">{latestTrace?.generation.model && <span>{latestTrace.generation.model}</span>}{latestTrace?.generation.prompt_version && <span>{latestTrace.generation.prompt_version}</span>}<span>{assistants.length} generations</span></div></div>
      <span className="rounded-full bg-[#edf4ff] px-2 py-1 text-[8.5px] font-semibold text-[#1677ff]">{moduleCount} 个时间线模块</span>
    </header>
    <div className="p-3">
      <div className="relative ml-3 space-y-3 border-l border-[#d8e1ec] pl-6">
        {systemEvent && <TimelineModule tone="violet"><MessagePart event={systemEvent} /></TimelineModule>}
        <TimelineModule tone="slate"><LegacyPart title={`AI 初始问候 · ${CHAT_WELCOME_TITLE}`} subtitle="客户端打开会话时展示 · 不属于模型输入" icon="ri-message-2-line" iconStyle="bg-cyan-50 text-cyan-700"><div className="whitespace-pre-wrap">{CHAT_WELCOME_MESSAGE}</div></LegacyPart></TimelineModule>
        {messages.map((message) => <div key={message.id} data-message-id={message.id} className={`rounded-xl transition ${message.id === focusedMessageId ? 'ring-2 ring-amber-300 ring-offset-4 ring-offset-[#f5f7fa]' : ''}`}>
          {message.role === 'assistant'
            ? <AssistantExecutionModules message={message} artifacts={artifacts[message.id] || emptyArtifacts(message)} onMatchPage={(page) => onMatchPage(message, page)} />
            : <TimelineModule tone={message.role === 'user' ? 'blue' : 'violet'}><StoredMessagePart message={message} /></TimelineModule>}
          {message.id === focusedMessageId && <div className="mt-1 rounded-lg bg-amber-50 px-3 py-1.5 text-[9px] font-medium text-amber-700"><i className="ri-map-pin-line mr-1" />当前反馈对应的 AI 回复</div>}
        </div>)}
      </div>
    </div>
  </section>
}

function AssistantExecutionModules({ message, artifacts, onMatchPage }: {
  message: ChatMessageNode
  artifacts: AssistantArtifacts
  onMatchPage: (page: number) => void
}) {
  const events = artifacts.trace ? turnExecutionEvents(artifacts.trace.steps) : []
  if (artifacts.traceState.loading) return <TimelineModule tone="slate"><TimelineNotice text="正在加载本轮 Agent 执行…" /></TimelineModule>
  if (artifacts.traceState.error) return <TimelineModule tone="slate"><InlineError text={artifacts.traceState.error} /></TimelineModule>
  if (!artifacts.trace) return <TimelineModule tone="slate"><StoredMessagePart message={message} /></TimelineModule>
  if (!events.length) return <TimelineModule tone="slate"><LegacyAgentTurn trace={artifacts.trace} assistant={message} match={artifacts.match} matchState={artifacts.matchState} onMatchPage={onMatchPage} /></TimelineModule>
  return <>{events.flatMap((event) => event.phase === 'tool_call'
    ? [
      <TimelineModule key={`${message.id}-${event.id}-model`} tone="slate"><MessagePart event={event} /></TimelineModule>,
      ...event.toolCalls.map((call, callIndex) => <TimelineModule key={`${message.id}-${event.id}-call-${call.id}-${callIndex}`} tone="amber"><ToolCallPart call={call} order={event.order} /></TimelineModule>),
    ]
    : [<TimelineModule key={`${message.id}-${event.id}`} tone={timelineTone(event)}><MessagePart event={event} match={artifacts.match} matchState={artifacts.matchState} onMatchPage={onMatchPage} /></TimelineModule>])}</>
}

function StoredMessagePart({ message }: { message: ChatMessageNode }) {
  const isUser = message.role === 'user'
  return <LegacyPart title={isUser ? '用户消息' : message.role === 'system' ? '会话系统消息' : '模型回复'} subtitle={`${isUser ? 'User' : message.role === 'system' ? 'System' : 'Assistant'} · 数据库消息 #${message.depth}`} icon={isUser ? 'ri-user-line' : message.role === 'system' ? 'ri-shield-line' : 'ri-robot-2-line'} iconStyle={isUser ? 'bg-blue-50 text-blue-700' : message.role === 'system' ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-700'}><div className="whitespace-pre-wrap">{message.content || `（${statusLabel(message.status)}，无正文）`}</div></LegacyPart>
}

function TimelineNotice({ text }: { text: string }) {
  return <div className="rounded-xl border border-[#e0e6ee] bg-white px-3 py-4 text-[10px] text-[#8c98a9]"><i className="ri-loader-4-line mr-2 animate-spin" />{text}</div>
}

function TimelineModule({ tone, children }: { tone: 'violet' | 'blue' | 'slate' | 'amber' | 'emerald'; children: ReactNode }) {
  const dot = { violet: 'bg-violet-500', blue: 'bg-blue-500', slate: 'bg-slate-500', amber: 'bg-amber-500', emerald: 'bg-emerald-500' }[tone]
  return <div className="relative"><span className={`absolute -left-[30px] top-4 h-2.5 w-2.5 rounded-full border-2 border-[#f5f7fa] ${dot}`} />{children}</div>
}

function timelineTone(event: AgentTranscriptEvent): 'violet' | 'blue' | 'slate' | 'emerald' {
  if (event.role === 'system') return 'violet'
  if (event.role === 'user') return 'blue'
  if (event.role === 'tool') return 'emerald'
  return 'slate'
}

function MessagePart({ event, match, matchState = IDLE, onMatchPage = () => undefined }: {
  event: AgentTranscriptEvent
  match?: FrozenMatchPage | null
  matchState?: LoadState
  onMatchPage?: (page: number) => void
}) {
  const presentation = partPresentation(event)
  const showSnapshot = event.role === 'tool' && Boolean(event.resultSetId) && (!match || match.result_set_id === event.resultSetId)
  return <details open className="group overflow-hidden rounded-xl border border-[#e0e6ee] bg-white shadow-[0_2px_8px_rgba(38,55,78,0.03)]">
    <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-3 py-2.5 [&::-webkit-details-marker]:hidden">
      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${presentation.iconStyle}`}><i className={presentation.icon} /></span>
      <span className="min-w-0 flex-1"><span className="block text-[10px] font-semibold text-[#405169]">{presentation.title}</span><span className="block truncate text-[8.5px] text-[#8c98a9]">{presentation.subtitle} · #{event.order}</span></span>
      <i className="ri-arrow-down-s-line text-[#8e99aa] transition group-open:rotate-180" />
    </summary>
    <div className="border-t border-[#edf1f5] px-3 py-3 pl-12 text-[10.5px] leading-5 text-[#45546a]">
      {event.role === 'system' || event.role === 'tool' ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#f6f8fb] p-3 font-mono text-[9px] leading-4 text-[#405169]">{prettyText(event.text) || '（空内容）'}</pre> : <div className="whitespace-pre-wrap">{event.text || (event.phase === 'tool_call' ? '模型返回工具调用请求。' : '（空内容）')}</div>}
      {event.role === 'tool' && <div className="mt-2 flex flex-wrap gap-1.5 text-[8.5px]">{event.count !== null && <span className="rounded bg-emerald-50 px-2 py-1 font-semibold text-emerald-700">{event.count} 位候选人</span>}{event.resultSetId && <span className="max-w-full truncate rounded bg-[#edf4ff] px-2 py-1 font-mono text-[#1677ff]">snapshot {event.resultSetId}</span>}</div>}
      {showSnapshot && <div className="mt-3 border-t border-[#e8edf3] pt-3"><LoadNotice state={matchState} empty={!match} emptyText="暂无排名快照" />{match ? <MatchSnapshot page={match} onPage={onMatchPage} /> : null}</div>}
    </div>
  </details>
}

function ToolCallPart({ call, order }: { call: AgentToolCall; order: number }) {
  return <details open className="group overflow-hidden rounded-xl border border-amber-200 bg-white shadow-[0_2px_8px_rgba(38,55,78,0.03)]">
    <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-3 py-2.5 [&::-webkit-details-marker]:hidden">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700"><i className="ri-tools-line" /></span>
      <span className="min-w-0 flex-1"><span className="block text-[10px] font-semibold text-[#405169]">工具调用</span><span className="block truncate font-mono text-[8.5px] text-[#a47631]">{call.name || 'unknown_tool'} · #{order}</span></span>
      <i className="ri-arrow-down-s-line text-[#8e99aa] transition group-open:rotate-180" />
    </summary>
    <div className="border-t border-amber-100 px-3 py-3 pl-12"><pre className="overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#fff9ef] p-3 font-mono text-[9px] leading-4 text-[#6b532d]">{prettyText(call.argumentsText) || '{}'}</pre></div>
  </details>
}

function partPresentation(event: AgentTranscriptEvent) {
  if (event.role === 'system') {
    if (event.kind === 'preference_snapshot' || event.text.startsWith('【当前完整偏好画像】')) {
      return { title: '当前画像快照', subtitle: 'Preference Snapshot · 本轮权威状态', icon: 'ri-user-heart-line', iconStyle: 'bg-fuchsia-50 text-fuchsia-700' }
    }
    return { title: '系统提示词', subtitle: 'System Prompt · 最终组装上下文', icon: 'ri-shield-check-line', iconStyle: 'bg-violet-50 text-violet-700' }
  }
  if (event.role === 'user') return { title: '用户消息', subtitle: event.phase === 'input_context' ? 'User · 实际输入上下文' : 'User', icon: 'ri-user-line', iconStyle: 'bg-blue-50 text-blue-700' }
  if (event.role === 'tool') return { title: '工具结果', subtitle: `${event.toolName || 'Tool'} · 实际返回`, icon: 'ri-database-2-line', iconStyle: 'bg-emerald-50 text-emerald-700' }
  if (event.phase === 'final') return { title: '模型最终回复', subtitle: 'Assistant Final · 工具结果之后', icon: 'ri-sparkling-2-line', iconStyle: 'bg-slate-100 text-slate-700' }
  if (event.phase === 'tool_call') return { title: '模型回复', subtitle: 'Assistant · 模型决定调用工具', icon: 'ri-robot-2-line', iconStyle: 'bg-slate-100 text-slate-700' }
  return { title: '模型回复', subtitle: 'Assistant · 历史上下文', icon: 'ri-robot-2-line', iconStyle: 'bg-slate-100 text-slate-700' }
}

function LegacyAgentTurn({ trace, assistant, match, matchState, onMatchPage }: {
  trace: AdminGenerationTrace
  assistant: ChatMessageNode
  match: FrozenMatchPage | null
  matchState: LoadState
  onMatchPage: (page: number) => void
}) {
  return <div className="space-y-2">
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[9px] leading-4 text-amber-800">该轮生成早于完整 Agent 转录功能，System 和工具结果无法事后准确还原；以下仅展示当时真实保留的内容。</div>
    <LegacyPart title="旧版运行元数据" subtitle="Generation Steps" icon="ri-pulse-line" iconStyle="bg-amber-50 text-amber-700"><div className="space-y-2">{trace.steps.map((step) => <details key={step.id} className="rounded-lg border border-[#e5eaf1] bg-[#fbfcfe] px-3 py-2"><summary className="cursor-pointer text-[9px] font-medium text-[#59677d]">#{step.step_order} · {step.step_type}</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[8.5px] leading-4 text-[#68768a]">{JSON.stringify(step.payload_json, null, 2)}</pre></details>)}</div></LegacyPart>
    {match || matchState.loading || matchState.error ? <LegacyPart title="工具结果" subtitle="冻结排名快照" icon="ri-database-2-line" iconStyle="bg-emerald-50 text-emerald-700"><LoadNotice state={matchState} empty={!match} emptyText="暂无排名快照" />{match ? <MatchSnapshot page={match} onPage={onMatchPage} /> : null}</LegacyPart> : null}
    <LegacyPart title="模型最终回复" subtitle="Assistant Final" icon="ri-sparkling-2-line" iconStyle="bg-slate-100 text-slate-700"><div className="whitespace-pre-wrap">{assistant.content || '（无正文）'}</div></LegacyPart>
  </div>
}

function LegacyPart({ title, subtitle, icon, iconStyle, children }: { title: string; subtitle: string; icon: string; iconStyle: string; children: ReactNode }) {
  return <details open className="group overflow-hidden rounded-xl border border-[#e0e6ee] bg-white"><summary className="flex min-h-11 cursor-pointer list-none items-center gap-2.5 px-3 py-2.5 [&::-webkit-details-marker]:hidden"><span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${iconStyle}`}><i className={icon} /></span><span className="min-w-0 flex-1"><span className="block text-[10px] font-semibold text-[#405169]">{title}</span><span className="block truncate text-[8.5px] text-[#8c98a9]">{subtitle}</span></span><i className="ri-arrow-down-s-line text-[#8e99aa] transition group-open:rotate-180" /></summary><div className="border-t border-[#edf1f5] px-3 py-3 pl-12 text-[10px] leading-5 text-[#45546a]">{children}</div></details>
}

function LoadNotice({ state, empty, emptyText }: { state: LoadState; empty: boolean; emptyText: string }) {
  if (state.loading) return <div className="py-5 text-center text-[10px] text-[#8c98a9]">加载中…</div>
  if (state.error) return <InlineError text={state.error} />
  return empty ? <div className="py-5 text-center text-[10px] text-[#a0aaba]">{emptyText}</div> : null
}

function InlineError({ text }: { text: string }) {
  return <div className="rounded-lg bg-rose-50 px-3 py-2 text-[10px] text-rose-700">{text}</div>
}

function prettyText(value: string) {
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}

function MatchSnapshot({ page, onPage }: { page: FrozenMatchPage; onPage: (page: number) => void }) {
  return <div><div className="mb-2 flex flex-wrap items-center gap-2 text-[9px] text-[#778499]"><span className="font-semibold text-[#1677ff]">完整排名 {page.total} 位</span><span>模型 {page.model_version || '—'}</span><span>快照 v{page.snapshot_schema_version}</span><span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">已冻结</span></div><div className="overflow-x-auto rounded-lg border border-[#e5eaf1]"><table className="w-full text-left text-[9px]"><thead className="bg-[#f7f9fc] text-[#778499]"><tr><th className="px-2 py-2">排名</th><th className="px-2 py-2">候选人</th><th className="px-2 py-2">分数</th><th className="px-2 py-2">当前状态</th></tr></thead><tbody className="divide-y divide-[#edf1f5]">{page.items.map((item) => <tr key={`${item.rank}-${item.donor_info.code}`}><td className="px-2 py-2 font-mono font-semibold text-[#1677ff]">#{item.rank}</td><td className="px-2 py-2 font-medium text-[#304159]">{item.donor_info.code}</td><td className="px-2 py-2">{item.score.toFixed(3)}</td><td className="px-2 py-2">{item.current_status}</td></tr>)}</tbody></table></div><div className="mt-2 flex items-center justify-between text-[9px]"><button type="button" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)} className="text-[#1677ff] disabled:opacity-30">上一页</button><span>第 {page.page} 页</span><button type="button" disabled={!page.has_more} onClick={() => onPage(page.page + 1)} className="text-[#1677ff] disabled:opacity-30">下一页</button></div></div>
}
