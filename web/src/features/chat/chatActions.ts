import type { ChatTurnAction, ChatTurnCommand } from '../../types'

export type PendingChatAction = {
  action: Exclude<ChatTurnAction, 'append'>
  parentMessageId?: string | null
  derivedFromMessageId?: string | null
  label: string
}

export function pendingActionComposerBanner(pending?: PendingChatAction | null): string | null {
  return pending?.action === 'edit_resend' ? pending.label : null
}

export function buildTurnCommand(input: {
  selectedBranchId?: string | null
  branchHeadMessageId?: string | null
  pending?: PendingChatAction | null
  content: string
  requestId: string
}): ChatTurnCommand {
  const action: ChatTurnAction = input.pending?.action || 'append'
  return {
    branch_id: input.selectedBranchId || null,
    parent_message_id: input.pending?.parentMessageId ?? input.branchHeadMessageId ?? null,
    action,
    derived_from_message_id: input.pending?.derivedFromMessageId || null,
    content: input.content.trim(),
    client_request_id: input.requestId,
  }
}
