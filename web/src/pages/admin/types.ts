export type AdminInfo = {
  id: number
  username: string
  display_name: string
  role: string
}

export type PageData<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type UserSummary = {
  total: number
  active: number
  disabled: number
  today_new: number
}

export type UserArchive = {
  id: number
  email: string
  phone: string
  nickname: string
  status: 'active' | 'disabled'
  created_at: string
  updated_at?: string
  last_login_at?: string | null
  disabled_at?: string | null
  disabled_reason?: string | null
  favorite_count: number
  history_count: number
  chat_count: number
  preferences?: {
    filters: Record<string, unknown>
    priority: string[]
    updated_at?: string | null
  }
}

export type FavoriteRecord = {
  id: number
  donor_code: string
  created_at: string
  donor_status?: string | null
  education?: string | null
  ethnicity?: string | null
  height_cm?: number | null
  specimen_count?: number | null
}

export type HistoryRecord = {
  id: number
  kind: 'browse' | 'search' | 'match'
  donor_code?: string | null
  payload?: unknown
  created_at: string
}

export type ChatRecord = {
  id: number
  session_id: string
  title: string
  message_count: number
  created_at: string
  updated_at: string
}

export type ChatDetail = ChatRecord & {
  messages: Array<{ role?: string; content?: string; candidates?: unknown[] }>
  candidates: unknown[]
  state: Record<string, unknown>
}

export type UserAuditRecord = {
  id: number
  action: 'view_chat' | 'kick' | 'disable' | 'enable'
  reason?: string | null
  operator_id?: number | null
  operator_name?: string | null
  created_at: string
}

export type DonorRow = {
  code: string
  serial_no?: number
  status: string
  specimen_count: number
  education?: string
  ethnicity?: string
  height_cm?: number
  donor_info?: { code: string; education?: string; ethnicity?: string; height?: number }
  [key: string]: unknown
}

export type DonorAuditRow = {
  id: number
  donor_code: string
  action: string
  created_at: string
  operator_id: number | null
  operator_name?: string | null
}
