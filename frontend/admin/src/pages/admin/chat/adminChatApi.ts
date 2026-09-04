import type {
  ChatConversationTree,
  ChatListPage,
  ChatMessagePathPage,
  FrozenMatchPage,
  GenerationRun,
} from '../../../types'
import { adminFetch } from '../adminApi'

export type AdminChatListPage = ChatListPage

export type GenerationStep = {
  id: number
  step_order: number
  step_type: string
  payload_json: Record<string, unknown>
  created_at: string
  elapsed_ms: number | null
}

export type AdminGenerationTrace = {
  generation: GenerationRun
  steps: GenerationStep[]
}

function base(userId: number) {
  return `/api/admin/users/${userId}/conversations`
}

export const adminChatApi = {
  list(userId: number, cursor?: string | null, limit = 20) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (cursor) query.set('cursor', cursor)
    return adminFetch<AdminChatListPage>(`${base(userId)}?${query}`)
  },
  tree(userId: number, chatId: number) {
    return adminFetch<ChatConversationTree>(`${base(userId)}/${chatId}`)
  },
  messages(userId: number, chatId: number, branchId: string, before?: string | null, limit = 50) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (before) query.set('before', before)
    return adminFetch<ChatMessagePathPage>(
      `${base(userId)}/${chatId}/branches/${encodeURIComponent(branchId)}/messages?${query}`,
    )
  },
  messageContext(userId: number, chatId: number, branchId: string, messageId: string) {
    return adminFetch<ChatMessagePathPage>(
      `${base(userId)}/${chatId}/branches/${encodeURIComponent(branchId)}/messages/${encodeURIComponent(messageId)}/context`,
    )
  },
  match(userId: number, chatId: number, messageId: string, page = 1, limit = 20) {
    return adminFetch<FrozenMatchPage>(
      `${base(userId)}/${chatId}/messages/${encodeURIComponent(messageId)}/match-results?page=${page}&limit=${limit}`,
    )
  },
  trace(userId: number, chatId: number, generationId: string) {
    return adminFetch<AdminGenerationTrace>(
      `${base(userId)}/${chatId}/generations/${encodeURIComponent(generationId)}?limit=500`,
    )
  },
}
