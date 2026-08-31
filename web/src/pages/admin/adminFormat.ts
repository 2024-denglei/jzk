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
}

export function auditActionLabel(action?: string | null) {
  if (!action) return '—'
  return AUDIT_ACTION_LABELS[action] || action
}
