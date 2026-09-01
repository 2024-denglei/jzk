import type { ChatBranchSummary } from '../../../types'

export type BranchTreeRow = { branch: ChatBranchSummary; depth: number }

export function flattenBranchTree(branches: ChatBranchSummary[]): BranchTreeRow[] {
  const children = new Map<string | null, ChatBranchSummary[]>()
  for (const branch of branches) {
    const siblings = children.get(branch.parent_branch_id) || []
    siblings.push(branch)
    children.set(branch.parent_branch_id, siblings)
  }
  const rows: BranchTreeRow[] = []
  const visited = new Set<string>()
  function visit(parentId: string | null, depth: number) {
    for (const branch of children.get(parentId) || []) {
      if (visited.has(branch.id)) continue
      visited.add(branch.id)
      rows.push({ branch, depth })
      visit(branch.id, depth + 1)
    }
  }
  visit(null, 0)
  for (const branch of branches) {
    if (!visited.has(branch.id)) rows.push({ branch, depth: 0 })
  }
  return rows
}

export function branchOriginLabel(branch: ChatBranchSummary): string {
  const labels: Record<ChatBranchSummary['fork_reason'], string> = {
    root: '根分支',
    rewind_continue: '用户回溯后继续',
    edit_resend: '用户编辑消息后重发',
    regenerate: '用户重新生成 AI 回复',
    concurrent_send: '多窗口并发发送形成分支',
  }
  return labels[branch.fork_reason]
}
