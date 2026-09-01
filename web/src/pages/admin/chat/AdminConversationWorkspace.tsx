import { useEffect, useMemo, useState } from 'react'
import type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatMessageNode,
  ChatV2Summary,
  FrozenMatchPage,
} from '../../../types'
import { formatTime } from '../adminFormat'
import { adminChatApi, type AdminGenerationTrace } from './adminChatApi'
import {
  agentTranscriptEvents,
  branchOriginLabel,
  flattenBranchTree,
  type AgentTranscriptEvent,
} from './adminChatState'

type LoadState = { loading: boolean; error: string }
const IDLE: LoadState = { loading: false, error: '' }

function messageRole(role: ChatMessageNode['role']) {
  return role === 'user' ? '用户' : role === 'assistant' ? 'AI' : '系统'
}

function statusLabel(status: ChatMessageNode['status']) {
  return { generating: '生成中', completed: '已完成', stopped: '已停止', failed: '失败' }[status]
}

export function AdminConversationWorkspace({ userId }: { userId: number }) {
  const [chats, setChats] = useState<ChatV2Summary[]>([])
  const [chatCursor, setChatCursor] = useState<string | null>(null)
  const [chatHasMore, setChatHasMore] = useState(false)
  const [tree, setTree] = useState<ChatConversationTree | null>(null)
  const [branchId, setBranchId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessageNode[]>([])
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [hasOlder, setHasOlder] = useState(false)
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const [match, setMatch] = useState<FrozenMatchPage | null>(null)
  const [trace, setTrace] = useState<AdminGenerationTrace | null>(null)
  const [listState, setListState] = useState<LoadState>({ loading: true, error: '' })
  const [treeState, setTreeState] = useState<LoadState>(IDLE)
  const [pathState, setPathState] = useState<LoadState>(IDLE)
  const [matchState, setMatchState] = useState<LoadState>(IDLE)
  const [traceState, setTraceState] = useState<LoadState>(IDLE)

  const branchRows = useMemo(() => flattenBranchTree(tree?.branches || []), [tree])
  const selectedMessage = messages.find((message) => message.id === selectedMessageId) || null
  const selectedBranch = tree?.branches.find((branch) => branch.id === branchId) || null

  async function loadChats(reset = true) {
    setListState({ loading: true, error: '' })
    try {
      const page = await adminChatApi.list(userId, reset ? null : chatCursor)
      setChats((current) => reset ? page.items : [...current, ...page.items])
      setChatCursor(page.next_cursor)
      setChatHasMore(page.has_more)
      setListState(IDLE)
      if (reset && page.items[0]) await openChat(page.items[0].id)
    } catch (error) {
      setListState({ loading: false, error: error instanceof Error ? error.message : '会话列表加载失败' })
    }
  }

  useEffect(() => {
    void loadChats(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  async function openChat(chatId: number) {
    setTreeState({ loading: true, error: '' })
    setTree(null)
    setMessages([])
    setSelectedMessageId(null)
    setMatch(null)
    setTrace(null)
    try {
      const loaded = await adminChatApi.tree(userId, chatId)
      setTree(loaded)
      const selected = loaded.branches.find((branch) => branch.id === loaded.chat.active_branch_id)
        || loaded.branches[0]
      setTreeState(IDLE)
      if (selected) await openBranch(chatId, selected)
    } catch (error) {
      setTreeState({ loading: false, error: error instanceof Error ? error.message : '分支树加载失败' })
    }
  }

  async function openBranch(chatId: number, branch: ChatBranchSummary) {
    setBranchId(branch.id)
    setPathState({ loading: true, error: '' })
    setMessages([])
    setSelectedMessageId(null)
    setMatch(null)
    setTrace(null)
    try {
      const page = await adminChatApi.messages(userId, chatId, branch.id)
      setMessages(page.items)
      setNextBefore(page.next_before)
      setHasOlder(page.has_more)
      setPathState(IDLE)
      const latestAssistant = [...page.items].reverse().find((message) => message.role === 'assistant')
      const latest = latestAssistant || page.items[page.items.length - 1]
      if (latest) void inspectMessage(chatId, latest, page.items)
    } catch (error) {
      setPathState({ loading: false, error: error instanceof Error ? error.message : '消息路径加载失败' })
    }
  }

  async function loadOlder() {
    if (!tree || !branchId || !nextBefore || pathState.loading) return
    setPathState({ loading: true, error: '' })
    try {
      const page = await adminChatApi.messages(userId, tree.chat.id, branchId, nextBefore)
      setMessages((current) => {
        const byId = new Map([...page.items, ...current].map((message) => [message.id, message]))
        return [...byId.values()].sort((left, right) => left.depth - right.depth)
      })
      setNextBefore(page.next_before)
      setHasOlder(page.has_more)
      setPathState(IDLE)
    } catch (error) {
      setPathState({ loading: false, error: error instanceof Error ? error.message : '更早消息加载失败' })
    }
  }

  async function inspectMessage(chatId: number, message: ChatMessageNode, currentMessages = messages) {
    setSelectedMessageId(message.id)
    setMatch(null)
    setTrace(null)
    setMatchState(IDLE)
    setTraceState(IDLE)
    if (message.role !== 'assistant') return
    const tasks: Promise<void>[] = []
    if (message.match_run) {
      setMatchState({ loading: true, error: '' })
      tasks.push(adminChatApi.match(userId, chatId, message.id).then((page) => {
        setMatch(page)
        setMatchState(IDLE)
      }).catch((error) => setMatchState({ loading: false, error: error instanceof Error ? error.message : '排名快照加载失败' })))
    }
    if (message.generation_id) {
      setTraceState({ loading: true, error: '' })
      tasks.push(adminChatApi.trace(userId, chatId, message.generation_id).then((result) => {
        setTrace(result)
        setTraceState(IDLE)
      }).catch((error) => setTraceState({ loading: false, error: error instanceof Error ? error.message : '数据库 Trace 加载失败' })))
    }
    await Promise.all(tasks)
    if (!currentMessages.some((item) => item.id === message.id)) setSelectedMessageId(null)
  }

  async function loadMatchPage(page: number) {
    if (!tree || !selectedMessage?.match_run) return
    setMatchState({ loading: true, error: '' })
    try {
      setMatch(await adminChatApi.match(userId, tree.chat.id, selectedMessage.id, page))
      setMatchState(IDLE)
    } catch (error) {
      setMatchState({ loading: false, error: error instanceof Error ? error.message : '排名快照加载失败' })
    }
  }

  return (
    <div className="grid h-full min-h-0 min-w-[1120px] grid-cols-[245px_330px_minmax(500px,1fr)] overflow-hidden bg-[#f5f7fa]">
      <aside className="flex min-h-0 flex-col border-r border-[#e1e7ef] bg-white">
        <PaneTitle icon="ri-chat-history-line" title="会话记录" subtitle="按最近更新时间排序" count={chats.length} />
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

      <section className="flex min-h-0 flex-col border-r border-[#e1e7ef] bg-[#f7f9fc]">
        <PaneTitle icon="ri-git-branch-line" title="对话线路" subtitle={tree ? `完整保留 ${tree.chat.branch_count} 条分支路径` : '选择会话后加载'} count={tree?.chat.branch_count} />
        {treeState.error ? <InlineError text={treeState.error} /> : null}
        {tree && <div className="max-h-44 shrink-0 overflow-y-auto border-b border-[#e4eaf1] bg-white p-2">
          {branchRows.map(({ branch, depth }) => (
            <button key={branch.id} type="button" onClick={() => void openBranch(tree.chat.id, branch)} style={{ marginLeft: `${depth * 12}px`, width: `calc(100% - ${depth * 12}px)` }} className={`mb-1 rounded-lg border px-2.5 py-2 text-left transition ${branch.id === branchId ? 'border-[#9fc5f6] bg-[#edf5ff] text-[#135ca8]' : 'border-transparent hover:bg-[#f6f8fb]'}`}>
              <div className="flex items-center gap-1.5 text-[10px] font-semibold"><i className={branch.fork_reason === 'root' ? 'ri-chat-3-line' : 'ri-git-branch-line'} /><span className="truncate">{branch.name}</span>{branch.is_active && <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[8px] text-emerald-700">用户活跃</span>}</div>
              <div className="mt-1 truncate text-[9px] text-[#8793a5]">{branchOriginLabel(branch)} · {branch.message_count} 条消息</div>
            </button>
          ))}
        </div>}
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {hasOlder && <button type="button" onClick={() => void loadOlder()} disabled={pathState.loading} className="mb-2 w-full rounded-lg border border-[#dce4ee] bg-white py-2 text-[10px] text-[#1677ff] disabled:opacity-50">加载更早消息</button>}
          {messages.map((message) => (
            <button key={message.id} type="button" onClick={() => tree && void inspectMessage(tree.chat.id, message)} className={`relative mb-2 block w-full rounded-xl border bg-white p-3 pl-11 text-left transition ${selectedMessageId === message.id ? 'border-[#6aa2eb] shadow-[0_0_0_2px_rgba(22,119,255,0.08)]' : 'border-[#e2e8f0] hover:border-[#b7cce4]'}`}>
              <span className={`absolute left-3 top-3 flex h-6 w-6 items-center justify-center rounded-lg text-[8px] font-semibold ${message.role === 'user' ? 'bg-[#e8f2ff] text-[#1677ff]' : message.role === 'assistant' ? 'bg-violet-50 text-violet-700' : 'bg-amber-50 text-amber-700'}`}>{messageRole(message.role)}</span>
              <div className="flex items-center justify-between gap-2 text-[9px]"><span className="font-semibold text-[#526077]">{messageRole(message.role)}消息 · #{message.depth}</span><span className="text-[#99a4b3]">{statusLabel(message.status)}</span></div>
              <div className="mt-2 line-clamp-3 whitespace-pre-wrap text-[10.5px] leading-5 text-[#45546a]">{message.content || '（无正文）'}</div>
              {message.match_run && <div className="mt-2 flex items-center gap-1 text-[9px] font-medium text-emerald-700"><i className="ri-database-2-line" />候选人快照 · {message.match_run.total} 位</div>}
            </button>
          ))}
          <LoadNotice state={pathState} empty={!messages.length} emptyText="该分支暂无消息" />
        </div>
      </section>

      <section className="flex min-h-0 flex-col bg-[#f5f7fa]">
        <PaneTitle icon="ri-pulse-line" title="Agent 执行记录" subtitle="按真实模型上下文与工具调用顺序展示" />
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!selectedMessage ? <EmptyInspector text="选择一条 AI 消息查看本轮 Agent 执行记录" /> : selectedMessage.role !== 'assistant' ? <>
            <MessageSummary message={selectedMessage} />
            <EmptyInspector text="用户消息没有独立生成任务，请选择其后的 AI 消息" />
          </> : <>
            <div className="mb-3 flex items-start justify-between gap-3">
              <div><div className="text-[9px] text-[#8793a5]">Session #{tree?.chat.id} / {selectedBranch?.name || '线路'} / 消息 #{selectedMessage.depth}</div><h3 className="mt-1 text-sm font-semibold text-[#2e3d54]">Agent 本轮执行上下文</h3></div>
              <span className={`rounded-full px-2.5 py-1 text-[9px] font-semibold ${selectedMessage.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-[#eef2f7] text-[#667389]'}`}>{statusLabel(selectedMessage.status)}</span>
            </div>
            <LoadNotice state={traceState} empty={!trace} emptyText={selectedMessage.generation_id ? '暂无生成记录' : '该消息没有生成任务'} />
            {trace ? <AgentTranscript trace={trace} match={match} matchState={matchState} onMatchPage={(page) => void loadMatchPage(page)} /> : null}
          </>}
        </div>
      </section>
    </div>
  )
}

function PaneTitle({ icon, title, subtitle, count }: { icon: string; title: string; subtitle: string; count?: number }) {
  return <header className="shrink-0 border-b border-[#e1e7ef] bg-white px-4 py-3"><div className="flex items-center justify-between gap-2"><div className="flex items-center gap-2 text-xs font-semibold text-[#304159]"><i className={`${icon} text-[#1677ff]`} />{title}</div>{count !== undefined && <span className="rounded-full bg-[#edf4ff] px-2 py-0.5 text-[9px] font-semibold text-[#1677ff]">{count}</span>}</div><div className="mt-1 text-[9px] text-[#929dac]">{subtitle}</div></header>
}

function LoadNotice({ state, empty, emptyText }: { state: LoadState; empty: boolean; emptyText: string }) {
  if (state.loading) return <div className="py-5 text-center text-[10px] text-[#8c98a9]">加载中…</div>
  if (state.error) return <InlineError text={state.error} />
  return empty ? <div className="py-5 text-center text-[10px] text-[#a0aaba]">{emptyText}</div> : null
}

function InlineError({ text }: { text: string }) {
  return <div className="m-2 rounded-lg bg-rose-50 px-3 py-2 text-[10px] text-rose-700">{text}</div>
}

function EmptyInspector({ text }: { text: string }) {
  return <div className="py-20 text-center text-xs text-[#9aa5b5]">{text}</div>
}

function MessageSummary({ message }: { message: ChatMessageNode }) {
  return <section className="rounded-xl border border-[#dfe6ef] bg-white p-4"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#304159]">{messageRole(message.role)}消息</span><span className="text-[9px] text-[#8793a5]">#{message.depth}</span></div><div className="mt-3 whitespace-pre-wrap text-xs leading-6 text-[#45546a]">{message.content || '（无正文）'}</div></section>
}

function AgentTranscript({ trace, match, matchState, onMatchPage }: {
  trace: AdminGenerationTrace
  match: FrozenMatchPage | null
  matchState: LoadState
  onMatchPage: (page: number) => void
}) {
  const events = agentTranscriptEvents(trace.steps)
  return <>
    <section className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#dfe6ef] bg-white px-3 py-2.5 text-[9px] text-[#748196]">
      <span className="min-w-0 truncate font-mono">generation {trace.generation.id}</span>
      <span className="flex gap-3"><span>{trace.generation.model || '—'}</span><span>{trace.generation.prompt_version || '—'}</span><span>{events.length} 个消息事件</span><span>尝试 {trace.generation.attempt_count}</span></span>
    </section>
    {events.length ? <div className="relative ml-2 border-l border-[#d9e1ec] pl-5">
      {events.map((event) => <TranscriptEvent key={event.id} event={event} match={match} matchState={matchState} onMatchPage={onMatchPage} />)}
      <div className="pb-2 pt-1 text-center text-[9px] text-[#8d99aa]">Agent 本轮执行结束</div>
    </div> : <LegacyTrace trace={trace} match={match} matchState={matchState} onMatchPage={onMatchPage} />}
  </>
}

const ROLE_PRESENTATION = {
  system: { label: 'System Prompt', mark: 'S', dot: 'bg-violet-500', markStyle: 'bg-violet-50 text-violet-700' },
  user: { label: 'User', mark: 'U', dot: 'bg-blue-500', markStyle: 'bg-blue-50 text-blue-700' },
  assistant: { label: 'Assistant', mark: 'A', dot: 'bg-slate-500', markStyle: 'bg-slate-100 text-slate-700' },
  tool: { label: 'Tool Result', mark: 'TR', dot: 'bg-emerald-500', markStyle: 'bg-emerald-50 text-emerald-700' },
} as const

function TranscriptEvent({ event, match, matchState, onMatchPage }: {
  event: AgentTranscriptEvent
  match: FrozenMatchPage | null
  matchState: LoadState
  onMatchPage: (page: number) => void
}) {
  const role = ROLE_PRESENTATION[event.role]
  const isToolCall = event.role === 'assistant' && event.phase === 'tool_call'
  const label = isToolCall ? 'Assistant · Tool Call' : event.role === 'assistant' && event.phase === 'final' ? 'Assistant · Final' : role.label
  const showSnapshot = event.role === 'tool' && Boolean(event.resultSetId) && (!match || match.result_set_id === event.resultSetId)
  return <article className="relative mb-3 rounded-xl border border-[#dfe6ef] bg-white shadow-[0_2px_8px_rgba(38,55,78,0.03)]">
    <span className={`absolute -left-[26px] top-4 h-2.5 w-2.5 rounded-full border-2 border-[#f5f7fa] ${isToolCall ? 'bg-amber-500' : role.dot}`} />
    <header className="flex items-center justify-between gap-3 border-b border-[#e8edf3] px-3 py-2.5">
      <div className="flex items-center gap-2"><span className={`flex h-6 min-w-6 items-center justify-center rounded-lg px-1 text-[8px] font-semibold ${isToolCall ? 'bg-amber-50 text-amber-700' : role.markStyle}`}>{isToolCall ? 'TC' : role.mark}</span><span className="text-[10px] font-semibold text-[#405169]">{label}</span></div>
      <span className="text-[8.5px] text-[#98a3b4]">#{event.order} · {phaseLabel(event.phase)}{event.attemptCount ? ` · 尝试 ${event.attemptCount}` : ''}</span>
    </header>
    <div className="px-3 py-3 text-[10.5px] leading-5 text-[#45546a]">
      {event.role === 'system' ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#f6f8fb] p-3 font-mono text-[9px] leading-4 text-[#405169]">{event.text || '（空系统提示词）'}</pre>
        : event.text ? <div className={`whitespace-pre-wrap ${event.role === 'tool' ? 'rounded-lg bg-[#f6f8fb] p-2 font-mono text-[9px] leading-4' : ''}`}>{prettyText(event.text)}</div> : null}
      {event.toolCalls.map((call, index) => <div key={`${call.id}-${index}`} className="mt-2">
        <div className="mb-1.5 inline-flex items-center gap-1 rounded-md bg-amber-50 px-2 py-1 font-mono text-[9px] font-semibold text-amber-700"><i className="ri-tools-line" />{call.name || 'unknown_tool'}</div>
        <pre className="overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#fff9ef] p-2 font-mono text-[9px] leading-4 text-[#6b532d]">{prettyText(call.argumentsText) || '{}'}</pre>
      </div>)}
      {event.role === 'tool' && <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[8.5px]">
        {event.count !== null && <span className="rounded-md bg-emerald-50 px-2 py-1 font-semibold text-emerald-700">{event.count} 位候选人</span>}
        {event.resultSetId && <span className="max-w-full truncate rounded-md bg-[#edf4ff] px-2 py-1 font-mono text-[#1677ff]">snapshot {event.resultSetId}</span>}
      </div>}
      {showSnapshot && <div className="mt-3 border-t border-[#e8edf3] pt-3">
        <LoadNotice state={matchState} empty={!match} emptyText="排名快照加载中或暂无候选项" />
        {match ? <MatchSnapshot page={match} onPage={onMatchPage} /> : null}
      </div>}
    </div>
  </article>
}

function phaseLabel(phase: string) {
  return { input_context: '实际输入上下文', tool_call: '工具调用', tool_result: '工具返回', final: '最终回复' }[phase] || phase || '消息'
}

function prettyText(value: string) {
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}

function LegacyTrace({ trace, match, matchState, onMatchPage }: {
  trace: AdminGenerationTrace
  match: FrozenMatchPage | null
  matchState: LoadState
  onMatchPage: (page: number) => void
}) {
  return <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-3"><div className="text-[10px] font-semibold text-amber-800">该历史任务生成于完整 Agent 转录启用前</div><div className="mt-1 text-[9px] leading-4 text-amber-700">无法事后准确还原 System、消息上下文和工具返回顺序；下面仅展示当时保存的运行元数据。</div><div className="mt-3 space-y-2">{trace.steps.map((step) => <details key={step.id} className="rounded-lg border border-amber-100 bg-white px-3 py-2"><summary className="cursor-pointer text-[9px] font-medium text-[#59677d]">#{step.step_order} · {step.step_type}</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[8.5px] leading-4 text-[#68768a]">{JSON.stringify(step.payload_json, null, 2)}</pre></details>)}</div>{match || matchState.loading || matchState.error ? <div className="mt-3 border-t border-amber-200 pt-3"><LoadNotice state={matchState} empty={!match} emptyText="暂无排名快照" />{match ? <MatchSnapshot page={match} onPage={onMatchPage} /> : null}</div> : null}</div>
}

function MatchSnapshot({ page, onPage }: { page: FrozenMatchPage; onPage: (page: number) => void }) {
  return <div><div className="mb-2 flex flex-wrap items-center gap-2 text-[9px] text-[#778499]"><span className="font-semibold text-[#1677ff]">完整排名 {page.total} 位</span><span>模型 {page.model_version || '—'}</span><span>快照 v{page.snapshot_schema_version}</span><span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">已冻结</span></div><div className="overflow-x-auto rounded-lg border border-[#e5eaf1]"><table className="w-full text-left text-[9px]"><thead className="bg-[#f7f9fc] text-[#778499]"><tr><th className="px-2 py-2">排名</th><th className="px-2 py-2">候选人</th><th className="px-2 py-2">分数</th><th className="px-2 py-2">当前状态</th></tr></thead><tbody className="divide-y divide-[#edf1f5]">{page.items.map((item) => <tr key={`${item.rank}-${item.donor_info.code}`}><td className="px-2 py-2 font-mono font-semibold text-[#1677ff]">#{item.rank}</td><td className="px-2 py-2 font-medium text-[#304159]">{item.donor_info.code}</td><td className="px-2 py-2">{item.score.toFixed(3)}</td><td className="px-2 py-2">{item.current_status}</td></tr>)}</tbody></table></div><div className="mt-2 flex items-center justify-between text-[9px]"><button type="button" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)} className="text-[#1677ff] disabled:opacity-30">上一页</button><span>第 {page.page} 页</span><button type="button" disabled={!page.has_more} onClick={() => onPage(page.page + 1)} className="text-[#1677ff] disabled:opacity-30">下一页</button></div></div>
}
