export function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const AUDIT_ACTION_LABELS: Record<string, string> = {
  create: '新建档案',
  update: '编辑档案',
  disable: '停用档案',
  enable: '启用档案',
  import: '导入档案',
  upsert: '保存档案',
  view_chat: '查看 AI 会话',
  kick: '强制用户下线',
}

export function auditActionLabel(action?: string | null, source?: 'donor' | 'user') {
  if (!action) return '—'
  if (source === 'user' && action === 'disable') return '停用账号'
  if (source === 'user' && action === 'enable') return '恢复账号'
  return AUDIT_ACTION_LABELS[action] || action
}

export function adminRoleLabel(role: string) {
  return { super_admin: '超级管理员', donor_admin: '档案管理员' }[role] || role
}
