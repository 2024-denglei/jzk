import type { ChatTurnAction, ChatTurnCommand } from '../../types'

export type PendingChatAction = {
  action: Exclude<ChatTurnAction, 'append'>
  parentMessageId?: string | null
  derivedFromMessageId?: string | null
  label: string
}

export function buildTurnCommand(input: {
  selectedBranchId?: string | null
  branchHeadMessageId?: string | null
  pending?: PendingChatAction | null
  content: string
  requestId: string
}): ChatTurnCommand {
  const action: ChatTurnAction = input.pending?.action || 'append'
  // edit_resend 必须保留被编辑消息的真实父节点（首条用户消息为 null），
  // 不能用 ?? 回落到 branchHead，否则后端会报「编辑消息的父节点不一致」。
  const parent_message_id = action === 'edit_resend'
    ? input.pending?.parentMessageId ?? null
    : input.pending?.parentMessageId ?? input.branchHeadMessageId ?? null
  return {
    branch_id: input.selectedBranchId || null,
    parent_message_id,
    action,
    derived_from_message_id: input.pending?.derivedFromMessageId || null,
    content: input.content.trim(),
    client_request_id: input.requestId,
  }
}
