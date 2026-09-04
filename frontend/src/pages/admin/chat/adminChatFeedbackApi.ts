import { adminFetch } from '../adminApi'

export type AdminFeedbackRating = 'like' | 'dislike'

export type AdminFeedbackItem = {
  message_id: string
  rating: AdminFeedbackRating
  user_id: number
  user_display: string
  chat_id: number
  branch_id: string
  branch_name: string
  message_preview: string
  created_at: string
  updated_at: string
}

export type AdminFeedbackPage = {
  items: AdminFeedbackItem[]
  next_cursor: string | null
  has_more: boolean
}

export type AdminFeedbackSummary = {
  likes: number
  dislikes: number
  recent_dislikes: number
}

export type AdminFeedbackFilters = {
  rating: AdminFeedbackRating | ''
  userId: string
  dateFrom: string
  dateTo: string
}

export const adminChatFeedbackApi = {
  summary() {
    return adminFetch<AdminFeedbackSummary>('/api/admin/chat-feedback/summary')
  },
  list(filters: AdminFeedbackFilters, cursor?: string | null, limit = 20) {
    const query = new URLSearchParams({ limit: String(limit) })
    query.set('rating', filters.rating || 'all')
    if (filters.userId) query.set('user_id', filters.userId)
    if (filters.dateFrom) query.set('date_from', `${filters.dateFrom}T00:00:00Z`)
    if (filters.dateTo) query.set('date_to', `${filters.dateTo}T23:59:59.999Z`)
    if (cursor) query.set('cursor', cursor)
    return adminFetch<AdminFeedbackPage>(`/api/admin/chat-feedback?${query}`)
  },
}
