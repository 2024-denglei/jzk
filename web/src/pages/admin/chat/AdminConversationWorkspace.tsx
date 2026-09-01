import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatMessageNode,
  ChatV2Summary,
  FrozenMatchPage,
} from '../../../types'
import { formatTime } from '../adminFormat'
import { adminChatApi, type AdminGenerationTrace } from './adminChatApi'
import { branchOriginLabel, flattenBranchTree } from './adminChatState'

type LoadState = { loading: boolean; error: string }
const IDLE: LoadState = { loading: false, error: '' }

function messageRole(role: ChatMessageNode['role']) {
  return role === 'user' ? '用户' : role === 'assistant' ? 'AI' : '系统'
}

function statusLabel(status: ChatMessageNode['status']) {
  return { generating: '生成中', completed: '完成', stopped: '已停止', failed: '失败' }[status]
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
      const latest = page.items[page.items.length - 1]
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
    <div className="grid h-full min-h-0 min-w-[1120px] grid-cols-[260px_430px_minmax(360px,1fr)] overflow-hidden">
      <aside className="flex min-h-0 flex-col border-r border-[#e1e7ef] bg-white">
        <PaneTitle icon="ri-chat-history-line" title="会话" subtitle="仅读取计数与摘要" />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {chats.map((chat) => (
            <button key={chat.id} type="button" onClick={() => void openChat(chat.id)} className={`w-full border-b border-[#edf1f5] px-3 py-3 text-left ${tree?.chat.id === chat.id ? 'bg-[#eef6ff]' : 'hover:bg-[#f8fbff]'}`}>
              <div className="truncate text-xs font-semibold text-[#304159]">{chat.title}</div>
              <div className="mt-1 line-clamp-2 text-[10px] leading-4 text-[#7a8799]">{chat.last_message_preview || '暂无消息摘要'}</div>
              <div className="mt-2 flex justify-between text-[9px] text-[#9aa5b5]"><span>{chat.branch_count} 分支 · {chat.message_count} 消息</span><span>{formatTime(chat.updated_at)}</span></div>
            </button>
          ))}
          <LoadNotice state={listState} empty={!chats.length} emptyText="暂无 V2 会话" />
          {chatHasMore && !listState.loading && <button type="button" onClick={() => void loadChats(false)} className="w-full py-3 text-xs text-[#1677ff]">加载更多会话</button>}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col border-r border-[#e1e7ef] bg-[#f8fafc]">
        <PaneTitle icon="ri-git-branch-line" title="分支与消息路径" subtitle={tree ? `${tree.chat.branch_count} 条分支，查看不会改变用户活跃分支` : '选择会话后加载'} />
        {treeState.error ? <InlineError text={treeState.error} /> : null}
        {tree && <div className="max-h-48 shrink-0 overflow-y-auto border-b border-[#e4eaf1] bg-white p-2">
          {branchRows.map(({ branch, depth }) => (
            <button key={branch.id} type="button" onClick={() => void openBranch(tree.chat.id, branch)} style={{ paddingLeft: `${10 + depth * 16}px` }} className={`mb-1 w-full rounded-lg py-2 pr-2 text-left ${branch.id === branchId ? 'bg-[#e8f2ff] text-[#135ca8]' : 'hover:bg-[#f6f8fb]'}`}>
              <div className="flex items-center gap-1 text-[10px] font-medium"><span className="text-[#9aa5b5]">└</span><span className="truncate">{branch.name}</span>{branch.is_active && <span className="rounded bg-emerald-50 px-1 text-[8px] text-emerald-700">用户活跃</span>}</div>
              <div className="ml-3 mt-0.5 text-[9px] text-[#8793a5]">{branchOriginLabel(branch)} · {branch.message_count} 条</div>
              {branch.forked_from_message_id && <div className="ml-3 mt-0.5 truncate font-mono text-[8px] text-[#a0aaba]">fork {branch.forked_from_message_id}</div>}
            </button>
          ))}
        </div>}
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {hasOlder && <button type="button" onClick={() => void loadOlder()} disabled={pathState.loading} className="mb-2 w-full rounded-lg border border-[#dce4ee] bg-white py-2 text-[10px] text-[#1677ff] disabled:opacity-50">加载更早消息</button>}
          {messages.map((message) => (
            <button key={message.id} type="button" onClick={() => tree && void inspectMessage(tree.chat.id, message)} className={`mb-2 block w-full rounded-xl border p-3 text-left ${selectedMessageId === message.id ? 'border-[#82b7f4] bg-white shadow-sm' : 'border-[#e2e8f0] bg-white/80 hover:border-[#b7cce4]'}`}>
              <div className="flex items-center justify-between gap-2"><span className={`rounded px-1.5 py-0.5 text-[9px] ${message.role === 'user' ? 'bg-[#e8f2ff] text-[#1677ff]' : 'bg-violet-50 text-violet-700'}`}>{messageRole(message.role)}</span><span className="text-[9px] text-[#99a4b3]">#{message.depth} · {statusLabel(message.status)}</span></div>
              <div className="mt-2 line-clamp-3 whitespace-pre-wrap text-[11px] leading-5 text-[#45546a]">{message.content || '（无正文）'}</div>
              {message.derived_from_message_id && <div className="mt-1 truncate font-mono text-[8px] text-amber-600">derived {message.derived_from_message_id}</div>}
            </button>
          ))}
          <LoadNotice state={pathState} empty={!messages.length} emptyText="该分支暂无消息" />
        </div>
      </section>

      <section className="flex min-h-0 flex-col bg-white">
        <PaneTitle icon="ri-file-search-line" title="消息 Inspector" subtitle="按 AI 消息懒加载完整排名与数据库 Trace" />
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {!selectedMessage ? <div className="py-20 text-center text-xs text-[#9aa5b5]">选择一条消息查看来源、快照和生成步骤</div> : <>
            <MessageMetadata message={selectedMessage} />
            {selectedMessage.role === 'assistant' ? <>
              <InspectorSection title="完整排名快照" icon="ri-list-ordered-2">
                <LoadNotice state={matchState} empty={!match} emptyText={selectedMessage.match_run ? '该快照暂无候选项' : '该消息没有匹配快照'} />
                {match ? <MatchSnapshot page={match} onPage={(page) => void loadMatchPage(page)} /> : null}
              </InspectorSection>
              <InspectorSection title="GenerationStep 数据库 Trace" icon="ri-pulse-line">
                <LoadNotice state={traceState} empty={!trace} emptyText={selectedMessage.generation_id ? '暂无生成步骤' : '该消息没有生成任务'} />
                {trace ? <GenerationTrace trace={trace} /> : null}
              </InspectorSection>
            </> : null}
          </>}
        </div>
      </section>
    </div>
  )
}

function PaneTitle({ icon, title, subtitle }: { icon: string; title: string; subtitle: string }) {
  return <header className="shrink-0 border-b border-[#e1e7ef] bg-white px-4 py-3"><div className="flex items-center gap-2 text-xs font-semibold text-[#304159]"><i className={`${icon} text-[#1677ff]`} />{title}</div><div className="mt-1 text-[9px] text-[#929dac]">{subtitle}</div></header>
}

function LoadNotice({ state, empty, emptyText }: { state: LoadState; empty: boolean; emptyText: string }) {
  if (state.loading) return <div className="py-5 text-center text-[10px] text-[#8c98a9]">加载中…</div>
  if (state.error) return <InlineError text={state.error} />
  return empty ? <div className="py-5 text-center text-[10px] text-[#a0aaba]">{emptyText}</div> : null
}

function InlineError({ text }: { text: string }) {
  return <div className="m-2 rounded-lg bg-rose-50 px-3 py-2 text-[10px] text-rose-700">{text}</div>
}

function MessageMetadata({ message }: { message: ChatMessageNode }) {
  return <section className="rounded-xl border border-[#dfe6ef] bg-[#f8fafc] p-4"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-[#304159]">{messageRole(message.role)}消息</span><span className="rounded bg-white px-2 py-1 text-[9px] text-[#667389]">{statusLabel(message.status)}</span></div><div className="mt-3 whitespace-pre-wrap text-xs leading-6 text-[#45546a]">{message.content || '（无正文）'}</div><dl className="mt-4 grid gap-2 border-t border-[#e5eaf1] pt-3 text-[9px] text-[#778499] sm:grid-cols-2"><Meta label="Message ID" value={message.id} /><Meta label="Parent" value={message.parent_message_id || '根节点'} /><Meta label="Created in branch" value={message.created_in_branch_id} /><Meta label="Derived from" value={message.derived_from_message_id || '—'} /><Meta label="State recoverable" value={message.state_recoverable ? '是' : '否'} /><Meta label="Created" value={formatTime(message.created_at)} /></dl></section>
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt>{label}</dt><dd className="mt-0.5 truncate font-mono text-[#45546a]" title={value}>{value}</dd></div>
}

function InspectorSection({ title, icon, children }: { title: string; icon: string; children: ReactNode }) {
  return <section className="mt-4 rounded-xl border border-[#dfe6ef]"><h3 className="border-b border-[#e8edf3] px-4 py-3 text-[11px] font-semibold text-[#405169]"><i className={`${icon} mr-1.5 text-[#1677ff]`} />{title}</h3><div className="p-3">{children}</div></section>
}

function MatchSnapshot({ page, onPage }: { page: FrozenMatchPage; onPage: (page: number) => void }) {
  return <div><div className="mb-2 flex flex-wrap gap-2 text-[9px] text-[#778499]"><span>共 {page.total} 位</span><span>模型 {page.model_version || '—'}</span><span>数据集 {page.dataset_version || '—'}</span><span>快照 v{page.snapshot_schema_version}</span></div><div className="overflow-x-auto"><table className="w-full text-left text-[10px]"><thead className="bg-[#f7f9fc] text-[#778499]"><tr><th className="px-2 py-2">排名</th><th className="px-2 py-2">代号</th><th className="px-2 py-2">分数</th><th className="px-2 py-2">当前状态</th></tr></thead><tbody className="divide-y divide-[#edf1f5]">{page.items.map((item) => <tr key={`${item.rank}-${item.donor_info.code}`}><td className="px-2 py-2 font-mono">#{item.rank}</td><td className="px-2 py-2 font-medium">{item.donor_info.code}</td><td className="px-2 py-2">{item.score.toFixed(3)}</td><td className="px-2 py-2">{item.current_status}</td></tr>)}</tbody></table></div><div className="mt-3 flex items-center justify-between text-[10px]"><button type="button" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)} className="text-[#1677ff] disabled:opacity-30">上一页</button><span>第 {page.page} 页</span><button type="button" disabled={!page.has_more} onClick={() => onPage(page.page + 1)} className="text-[#1677ff] disabled:opacity-30">下一页</button></div></div>
}

function GenerationTrace({ trace }: { trace: AdminGenerationTrace }) {
  return <div><div className="mb-3 grid gap-2 text-[9px] sm:grid-cols-3"><Meta label="Generation ID" value={trace.generation.id} /><Meta label="状态" value={trace.generation.status} /><Meta label="尝试次数" value={String(trace.generation.attempt_count)} /></div><div className="space-y-2">{trace.steps.map((step) => <details key={step.id} className="rounded-lg border border-[#e5eaf1] bg-[#fbfcfe] px-3 py-2"><summary className="cursor-pointer text-[10px] font-medium text-[#405169]">#{step.step_order} · {step.step_type}{step.elapsed_ms !== null ? ` · ${Math.round(step.elapsed_ms)}ms` : ''}</summary><pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all rounded bg-white p-2 text-[9px] leading-4 text-[#68768a]">{JSON.stringify(step.payload_json, null, 2)}</pre></details>)}</div></div>
}
