import type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatMessageNode,
  ChatMessagePathPage,
  GenerationStatus,
  MessageFeedbackRating,
} from '../../types'

export const CHAT_WELCOME_TITLE = '您好'
export const CHAT_WELCOME_MESSAGE = '描述您的期望，我会帮您筛选合适的候选人。'

export interface BranchPathState {
  ids: string[]
  nextBefore: string | null
  hasMore: boolean
}

export interface ChatClientState {
  tree: ChatConversationTree | null
  selectedBranchId: string | null
  messagesById: Record<string, ChatMessageNode>
  pathsByBranch: Record<string, BranchPathState>
}

export function createChatClientState(): ChatClientState {
  return {
    tree: null,
    selectedBranchId: null,
    messagesById: {},
    pathsByBranch: {},
  }
}

export function selectConversation(
  state: ChatClientState,
  tree: ChatConversationTree,
  requestedBranchId?: string | null,
): ChatClientState {
  const requested = tree.branches.find((branch) => branch.id === requestedBranchId)
  const active = tree.branches.find((branch) => branch.id === tree.chat.active_branch_id)
  const selected = requested || active || tree.branches.find((branch) => !branch.is_archived) || tree.branches[0]
  return { ...state, tree, selectedBranchId: selected?.id || null }
}

export function mergeMessagePage(
  state: ChatClientState,
  page: ChatMessagePathPage,
  older = false,
): ChatClientState {
  const messagesById = { ...state.messagesById }
  for (const message of page.items) messagesById[message.id] = message

  const previous = state.pathsByBranch[page.branch_id]?.ids || []
  const combined = older ? [...page.items.map((item) => item.id), ...previous] : page.items.map((item) => item.id)
  const ids = [...new Set(combined)].sort((left, right) => {
    const a = messagesById[left]
    const b = messagesById[right]
    return (a?.depth ?? 0) - (b?.depth ?? 0) || left.localeCompare(right)
  })
  return {
    ...state,
    messagesById,
    pathsByBranch: {
      ...state.pathsByBranch,
      [page.branch_id]: {
        ids,
        nextBefore: page.next_before,
        hasMore: page.has_more,
      },
    },
  }
}

export function patchMessage(
  state: ChatClientState,
  messageId: string,
  patch: Partial<ChatMessageNode>,
): ChatClientState {
  const current = state.messagesById[messageId]
  if (!current) return state
  return {
    ...state,
    messagesById: {
      ...state.messagesById,
      [messageId]: { ...current, ...patch },
    },
  }
}

export function nextFeedbackRating(
  current: MessageFeedbackRating | null,
  clicked: MessageFeedbackRating,
): MessageFeedbackRating | null {
  return current === clicked ? null : clicked
}

export function messagesForSelectedBranch(state: ChatClientState): ChatMessageNode[] {
  if (!state.selectedBranchId) return []
  return (state.pathsByBranch[state.selectedBranchId]?.ids || [])
    .map((id) => state.messagesById[id])
    .filter((message): message is ChatMessageNode => Boolean(message))
}

export type BranchPreview = { items: ChatMessageNode[]; hiddenCount: number }

export function previewMessagesAtBranchPoint(
  messages: ChatMessageNode[],
  parentMessageId: string | null,
): BranchPreview {
  if (parentMessageId === null) return { items: [], hiddenCount: messages.length }
  const branchPointIndex = messages.findIndex((message) => message.id === parentMessageId)
  if (branchPointIndex < 0) return { items: messages, hiddenCount: 0 }
  const items = messages.slice(0, branchPointIndex + 1)
  return { items, hiddenCount: messages.length - items.length }
}

export function canCreateBranchAfterMessage(
  message: ChatMessageNode,
  index: number,
  messageCount: number,
): boolean {
  return message.role === 'assistant'
    && message.status === 'completed'
    && message.state_recoverable
    && index < messageCount - 1
}

export type CandidateSyncAction =
  | { kind: 'preserve' }
  | { kind: 'clear' }
  | { kind: 'load'; message: ChatMessageNode }

export function candidateSyncAction(messages: ChatMessageNode[]): CandidateSyncAction {
  // 新 Turn 刚创建时只有 generating 占位消息，完整快照尚未关联。
  // 此时保留中间候选区，避免先清空一次、生成完成后又刷新一次。
  if (messages.some((message) => message.status === 'generating')) return { kind: 'preserve' }
  const latestMatch = [...messages].reverse().find((message) => message.match_run)
  // clear：无可用对话快照。调用方应回到「全部捐献者」，不要展示空的对话结果。
  return latestMatch ? { kind: 'load', message: latestMatch } : { kind: 'clear' }
}

export function branchChildren(branches: ChatBranchSummary[]): Map<string | null, ChatBranchSummary[]> {
  const children = new Map<string | null, ChatBranchSummary[]>()
  for (const branch of branches) {
    const siblings = children.get(branch.parent_branch_id) || []
    siblings.push(branch)
    children.set(branch.parent_branch_id, siblings)
  }
  return children
}

export function isTerminalGeneration(status: GenerationStatus): boolean {
  return status === 'completed' || status === 'stopped' || status === 'failed'
}
