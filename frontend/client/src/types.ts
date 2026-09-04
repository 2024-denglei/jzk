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

/** 对话结果同步到中间栏时的可选行为。 */
export interface CandidateSyncOptions {
  /** 用户主动要在中间栏查看时，移动端可关闭聊天抽屉。 */
  focusMiddle?: boolean
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

export type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatForkReason,
  ChatListPage,
  ChatMatchRunSummary,
  ChatMessageNode,
  ChatMessagePathPage,
  ChatMessageStatus,
  ChatTurnAction,
  ChatTurnCommand,
  ChatTurnCreationResult,
  ChatV2Summary,
  GenerationRun,
  GenerationStatus,
  MessageFeedback,
  MessageFeedbackRating,
} from '@jzk/shared'

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
