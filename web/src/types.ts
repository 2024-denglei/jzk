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
  semen_test?: string
  blood_test?: string
  chromosome_test?: string
  microbio_test?: string
  specimen_count?: number
  availability?: string
  remark?: string
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
}

export interface User {
  id: number
  email: string
  nickname: string
  created_at: string
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
  /** 聊天侧预览用（通常最多 20 条），完整列表放 match_bag_id 对应缓存 */
  candidates?: Candidate[]
  /** 完整匹配结果在 ChatPanel 本地缓存中的 key */
  match_bag_id?: string
  /** 本轮匹配总数（可大于 candidates 预览长度） */
  candidates_total?: number
  prefer_hits?: PreferHit[]
  /** 用户消息：发送前条件；助手消息：本轮结束后条件 */
  snapshot?: ChatSnapshot
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
