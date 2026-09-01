import { api } from '../../lib/api.ts'
import type {
  Candidate,
  ChatConversationTree,
  ChatMessagePathPage,
  ChatTurnCommand,
  ChatTurnCreationResult,
  ChatV2Summary,
  FrozenMatchPage,
  GenerationRun,
  MatchResultDescriptor,
} from '../../types'

export interface ChatListPage {
  items: ChatV2Summary[]
  next_cursor: string | null
  has_more: boolean
}

export const chatApi = {
  list(cursor?: string | null, limit = 20) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (cursor) query.set('cursor', cursor)
    return api.get<ChatListPage>(`/api/chats?${query}`)
  },
  tree(chatId: number) {
    return api.get<ChatConversationTree>(`/api/chats/${chatId}`)
  },
  messages(chatId: number, branchId: string, before?: string | null, limit = 40) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (before) query.set('before', before)
    return api.get<ChatMessagePathPage>(
      `/api/chats/${chatId}/branches/${encodeURIComponent(branchId)}/messages?${query}`,
    )
  },
  turn(chatId: number | null, command: ChatTurnCommand) {
    const path = chatId === null ? '/api/chats/turns' : `/api/chats/${chatId}/turns`
    return api.post<ChatTurnCreationResult>(path, command)
  },
  generation(generationId: string) {
    return api.get<GenerationRun>(`/api/generations/${encodeURIComponent(generationId)}`)
  },
  stop(generationId: string) {
    return api.post<GenerationRun>(`/api/generations/${encodeURIComponent(generationId)}/stop`)
  },
  match(messageId: string, page = 1, limit = 20) {
    return api.get<FrozenMatchPage>(
      `/api/messages/${encodeURIComponent(messageId)}/match-results?page=${page}&limit=${limit}`,
    )
  },
  rename(chatId: number, title: string) {
    return api.patch<{ ok: boolean; title: string }>(`/api/chats/${chatId}`, { title })
  },
  updateBranch(chatId: number, branchId: string, body: { is_archived: boolean }) {
    return api.patch<{ ok: boolean }>(
      `/api/chats/${chatId}/branches/${encodeURIComponent(branchId)}`,
      body,
    )
  },
  remove(chatId: number, requestId: string) {
    return api.delete<{ ok: boolean }>(`/api/chats/${chatId}`, {
      confirm_irreversible: true,
      request_id: requestId,
    })
  },
}

export function frozenPageToMatchResult(
  page: FrozenMatchPage,
  sourceMessageId?: string,
): MatchResultDescriptor {
  const items: Candidate[] = page.items.map((item) => ({
    donor_info: item.donor_info,
    score: item.score,
    rank: item.rank,
    match_pct: item.match_explanation.match_pct ?? null,
    reason: item.match_explanation.reason || '',
    match_level: item.match_explanation.match_level || 'snapshot',
    field_match: item.match_explanation.field_match || {},
    field_scores: item.match_explanation.field_scores,
  }))
  return {
    result_set_id: page.result_set_id,
    total: page.total,
    items,
    next_cursor: page.has_more ? String(page.page + 1) : null,
    source_message_id: sourceMessageId,
  }
}
