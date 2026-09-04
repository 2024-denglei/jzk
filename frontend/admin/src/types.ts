export type {
  ChatBranchSummary,
  ChatConversationTree,
  ChatListPage,
  ChatMessageNode,
  ChatMessagePathPage,
  ChatV2Summary,
  GenerationRun,
} from '@jzk/shared'

export type FrozenMatchPage = {
  result_set_id: string
  total: number
  page: number
  page_size: number
  returned_count: number
  items: Array<{
    rank: number
    score: number
    donor_info: { code: string; status_snapshot?: string }
    match_explanation?: {
      reason?: string
      match_pct?: number | null
      match_level?: string
    }
    current_status: string
    currently_selectable: boolean
  }>
  has_more: boolean
  model_version: string
  dataset_version: string
  snapshot_schema_version: number
  snapshot_source: string
}
