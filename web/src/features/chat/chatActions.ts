import type { ChatMessageNode, ChatTurnAction, ChatTurnCommand } from '../../types'

export type PendingChatAction = {
  action: Exclude<ChatTurnAction, 'append' | 'regenerate'>
  parentMessageId?: string | null
  derivedFromMessageId?: string | null
  label: string
}

export function buildTurnCommand(input: {
  selectedBranchId?: string | null
  branchHeadMessageId?: string | null
  pending?: PendingChatAction | null
  regenerate?: ChatMessageNode
  content: string
  requestId: string
}): ChatTurnCommand {
  const action: ChatTurnAction = input.regenerate ? 'regenerate' : input.pending?.action || 'append'
  return {
    branch_id: input.selectedBranchId || null,
    parent_message_id: input.pending?.parentMessageId ?? input.branchHeadMessageId ?? null,
    action,
    derived_from_message_id: input.regenerate?.id || input.pending?.derivedFromMessageId || null,
    content: action === 'regenerate' ? '' : input.content.trim(),
    client_request_id: input.requestId,
  }
}
