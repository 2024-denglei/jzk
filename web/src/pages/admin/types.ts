export type AdminInfo = {
  id: number
  username: string
  display_name: string
  role: string
  permissions: string[]
}

export type OperationRequestAction = 'donor_create' | 'donor_update' | 'donor_status' | 'user_kick' | 'user_disable' | 'user_enable'

export type OperationRequestRecord = {
  id: number
  requester_id: number
  requester_name?: string
  reviewer_id?: number | null
  reviewer_name?: string | null
  action: OperationRequestAction
  target_type: 'donor' | 'user'
  target_id: string
  payload: Record<string, unknown>
  before_snapshot?: Record<string, unknown> | null
  reason: string
  status: 'pending' | 'processing' | 'approved' | 'rejected' | 'cancelled' | 'failed'
  review_comment?: string | null
  execution_error?: string | null
  created_at: string
  reviewed_at?: string | null
}

export type AdminActionCount = {
  source: 'donor' | 'user' | 'admin'
  action: string
  count: number
}

export type AdminRecord = AdminInfo & {
  is_active: boolean
  created_at: string
  updated_at?: string
  donor_operation_count: number
  user_operation_count: number
  admin_operation_count: number
  operation_count: number
  last_operation_at?: string | null
  action_counts?: AdminActionCount[]
}

export type AdminAuditRecord = {
  source: 'donor' | 'user' | 'admin'
  record_id: number
  action: string
  target_id?: string | null
  target_name?: string | null
  reason?: string | null
  before_data?: unknown
  after_data?: unknown
  created_at: string
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

export type UserAuditRecord = {
  id: number
  action: 'view_chat' | 'view_chat_list' | 'view_chat_tree' | 'view_chat_path' | 'view_chat_match' | 'view_chat_trace' | 'kick' | 'disable' | 'enable'
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
