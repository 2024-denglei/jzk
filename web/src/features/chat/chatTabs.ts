import type { PendingChatAction } from './chatActions'

export type WorkspaceTab = {
  key: string
  branchId: string
  name: string
  closable: boolean
  pendingAction?: PendingChatAction
}

export function nextDraftBranchName(nonRootBranchCount: number, openDraftCount: number): string {
  return `分支${nonRootBranchCount + openDraftCount + 1}`
}

export function replaceDraftTab(
  tabs: WorkspaceTab[],
  draftKey: string,
  branchId: string,
  serverName: string,
): WorkspaceTab[] {
  return tabs.map((tab) => tab.key === draftKey
    ? { key: branchId, branchId, name: serverName, closable: true }
    : tab)
}

export function closeTabState(
  tabs: WorkspaceTab[],
  activeKey: string,
  closingKey: string,
): { tabs: WorkspaceTab[]; nextActiveKey: string } {
  const index = tabs.findIndex((tab) => tab.key === closingKey)
  const closing = tabs[index]
  if (!closing?.closable) return { tabs, nextActiveKey: activeKey }
  const remaining = tabs.filter((tab) => tab.key !== closingKey)
  if (closingKey !== activeKey) return { tabs: remaining, nextActiveKey: activeKey }
  const fallback = remaining[Math.max(0, index - 1)] || remaining[0]
  return { tabs: remaining, nextActiveKey: fallback?.key || 'new' }
}
