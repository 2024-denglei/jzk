import type { ReactNode } from 'react'
import { adminStickyTableCardClass } from './adminLayout'

export function StatusBadge({ status }: { status: string }) {
  const active = status === 'active'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium ${active ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-emerald-500' : 'bg-rose-500'}`} />
      {active ? '正常' : '已停用'}
    </span>
  )
}

/** Table card with pinned toolbar / footer and an independently scrolling body. */
export function StickyTableCard({
  toolbar,
  footer,
  children,
  className = '',
}: {
  toolbar: ReactNode
  footer?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={adminStickyTableCardClass(className)}>
      <div className="shrink-0">{toolbar}</div>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
      {footer ? <div className="shrink-0 bg-white">{footer}</div> : null}
    </div>
  )
}

export function AdminStatus({ active }: { active: boolean }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium ${active ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}><span className={`h-1.5 w-1.5 rounded-full ${active ? 'bg-emerald-500' : 'bg-rose-500'}`} />{active ? '正常' : '已停用'}</span>
}

export function PageHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-xl font-semibold tracking-tight text-[#132238]">{title}</h1>
      <p className="mt-1 text-xs text-[#708097]">{description}</p>
    </div>
  )
}

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="flex items-center justify-end gap-2 border-t border-[#e1e7ef] px-4 py-3 text-xs text-[#6d798c]">
      <span>共 {total} 条</span>
      <button disabled={page <= 1} onClick={() => onChange(page - 1)} className="h-8 rounded-md border border-[#d9e1ec] px-3 disabled:opacity-35">上一页</button>
      <span className="flex h-8 min-w-8 items-center justify-center rounded-md bg-[#1677ff] px-2 text-white">{page} / {pages}</span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)} className="h-8 rounded-md border border-[#d9e1ec] px-3 disabled:opacity-35">下一页</button>
    </div>
  )
}

export function EmptyState({ text = '暂无数据' }: { text?: string }) {
  return <div className="flex min-h-36 items-center justify-center text-sm text-[#9aa5b5]">{text}</div>
}

export function ErrorNotice({ message }: { message: string }) {
  return <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{message}</div>
}
