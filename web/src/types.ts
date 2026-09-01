export interface DonorInfo {
  id: string
  code: string
  blood_type: string
  rh_blood: string
  ethnicity: string
  height: number
  age: number
  constellation: string
  hometown: string
  occupation: string
  education: string
  face_shape: string
  eyelid: string
  skin_color: string
  lip_shape: string
  nose_bridge: string
  hair_color: string
  hair_style: string
  beard: string
  figure: string
  weight: number
  bmi: number
  personality: string
  hobby: string
  hair_volume?: string
  mustache?: string
  hobby_sports?: string
  hobby_arts?: string
  hobby_leisure?: string
  hobby_travel?: string
  hobby_reading?: string
  hobby_food?: string
  drink_history?: string
  smoke_history?: string
  personal_disease?: string
  present_illness?: string
  past_illness?: string
  surgery_history?: string
  personal_life_hist?: string
  partners_6m?: string
  std_history?: string
  marital_fertility?: string
  marriage_age?: string
  children_info?: string
  genetic_history?: string
  chromosome_disease?: string
  monogenic_disease?: string
  polygenic_disease?: string
  consanguinity?: string
  specimen_count?: number
  status?: string
}

export interface FieldScore {
  field: string
  s: number
  weight?: number
  constraint?: string
  actual?: unknown
}

export interface PreferHit {
  field: string
  label: string
  hits: number
  of: number
}

export interface Candidate {
  donor_info: DonorInfo
  score: number
  match_pct: number | null
  reason: string
  match_level: string
  field_match: Record<string, { match: boolean; user?: string; actual?: string }>
  field_scores?: FieldScore[]
  rank?: number
}

export interface MatchResultDescriptor {
  result_set_id: string
  total: number
  items: Candidate[]
  next_cursor?: string | null
  /** V2 对话快照必须继续通过消息所有权接口分页。 */
  source_message_id?: string
}

export interface User {
  id: number
  email: string
  phone: string | null
  nickname: string
  status?: 'active' | 'disabled'
  created_at: string
  last_login_at?: string | null
}

export interface FilterState {
  education: string[]
  blood_type: string[]
  rh_blood: string[]
  height: string
  age: string
  figure: string[]
  skin_color: string[]
  face_shape: string[]
  eyelid: string[]
  lip_shape: string[]
  constellation: string[]
  hometown: string[]
  ethnicity: string[]
  occupation: string[]
  personality: string[]
  specimen_min: string
}

/** 回溯用：该消息完成时的筛选条件快照 */
export interface ChatSnapshot {
  parsed_features: Record<string, unknown>
  constraints: Record<string, string>
}

export interface ChatMessage {
  role: 'user' | 'bot' | 'system'
  content: string
  /** 聊天侧与中间栏的当前页预览（通常最多 20 条） */
  candidates?: Candidate[]
  /** 迁移前历史消息的本地缓存 key，仅用于兼容读取 */
  match_bag_id?: string
  /** 本轮匹配总数（可大于 candidates 预览长度） */
  candidates_total?: number
  match_result_id?: string
  match_next_cursor?: string | null
  prefer_hits?: PreferHit[]
  /** 用户消息：发送前条件；助手消息：本轮结束后条件 */
  snapshot?: ChatSnapshot
}

export type ChatTurnAction = 'append' | 'rewind_continue' | 'edit_resend' | 'regenerate'
export type ChatForkReason =
  | 'root'
  | 'rewind_continue'
  | 'edit_resend'
  | 'regenerate'
  | 'concurrent_send'
export type ChatMessageStatus = 'generating' | 'completed' | 'stopped' | 'failed'
export type GenerationStatus = 'queued' | 'running' | 'completed' | 'stopped' | 'failed'

export interface ChatV2Summary {
  id: number
  title: string
  active_branch_id: string | null
  active_branch_name: string | null
  branch_count: number
  message_count: number
  last_message_preview: string
  created_at: string
  updated_at: string
}

export interface ChatBranchSummary {
  id: string
  parent_branch_id: string | null
  forked_from_message_id: string | null
  derived_from_message_id: string | null
  name: string
  system_name: string
  fork_reason: ChatForkReason
  head_message_id: string | null
  message_count: number
  last_message_preview: string
  is_active: boolean
  is_archived: boolean
  created_at: string
  updated_at: string
}

export interface ChatMatchRunSummary {
  message_id: string
  total: number
  model_version: string
  dataset_version: string
  snapshot_schema_version: number
  snapshot_source: 'native' | 'legacy_backfill'
  created_at: string
}

export interface ChatMessageNode {
  id: string
  parent_message_id: string | null
  derived_from_message_id: string | null
  created_in_branch_id: string
  role: 'user' | 'assistant' | 'system'
  status: ChatMessageStatus
  content: string
  content_format: string
  depth: number
  state_recoverable: boolean
  generation_id: string | null
  match_run: ChatMatchRunSummary | null
  created_at: string
  completed_at: string | null
}

export interface ChatConversationTree {
  chat: ChatV2Summary
  branches: ChatBranchSummary[]
}

export interface ChatMessagePathPage {
  chat_id: number
  branch_id: string
  items: ChatMessageNode[]
  next_before: string | null
  has_more: boolean
}

export interface ChatTurnCommand {
  branch_id?: string | null
  parent_message_id?: string | null
  action: ChatTurnAction
  derived_from_message_id?: string | null
  content: string
  client_request_id: string
}

export interface ChatTurnCreationResult {
  chat_id: number
  branch_id: string
  user_message_id: string
  assistant_message_id: string
  generation_id: string
  branch_created: boolean
  fork_reason: ChatForkReason
  idempotent_replay: boolean
}

export interface GenerationRun {
  id: string
  chat_id: number
  branch_id: string
  user_message_id: string
  assistant_message_id: string
  status: GenerationStatus
  cancel_requested_at: string | null
  attempt_count: number
  error_type: string | null
  error_message_safe: string | null
}

export interface FrozenMatchPage {
  result_set_id: string
  total: number
  page: number
  page_size: number
  returned_count: number
  items: Array<{
    rank: number
    score: number
    donor_info: DonorInfo & { status_snapshot?: string }
    match_explanation: {
      reason?: string
      match_pct?: number | null
      match_level?: string
      field_match?: Candidate['field_match']
      field_scores?: FieldScore[]
    }
    current_status: string
    currently_selectable: boolean
  }>
  has_more: boolean
  model_version: string
  dataset_version: string
  snapshot_schema_version: number
  snapshot_source: 'native' | 'legacy_backfill'
}

export const DEFAULT_PRIORITY = [
  '学历',
  '身高',
  '血型',
  '体型',
  '肤色',
  '脸型',
  '眼皮',
]

export const EMPTY_FILTERS: FilterState = {
  education: [],
  blood_type: [],
  rh_blood: [],
  height: '',
  age: '',
  figure: [],
  skin_color: [],
  face_shape: [],
  eyelid: [],
  lip_shape: [],
  constellation: [],
  hometown: [],
  ethnicity: [],
  occupation: [],
  personality: [],
  specimen_min: '',
}
