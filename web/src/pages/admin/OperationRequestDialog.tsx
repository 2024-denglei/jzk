import { useState } from 'react'

export function OperationRequestDialog({ title, description, busy, onClose, onConfirm }: {
  title: string
  description: string
  busy: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0b1729]/45 px-4 backdrop-blur-[2px]" role="dialog" aria-modal="true" aria-label={title}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[#1677ff]"><i className="ri-file-list-3-line text-xl" /></div>
          <div><h2 className="text-base font-semibold text-[#17263c]">{title}</h2><p className="mt-1 text-xs leading-5 text-[#6f7c90]">{description} 超级管理员批准后，系统将自动执行。</p></div>
        </div>
        <label className="mt-5 block text-xs font-medium text-[#34445b]">
          申请理由
          <textarea autoFocus value={reason} onChange={(event) => setReason(event.target.value)} placeholder="请说明申请原因（至少 2 个字）" className="mt-2 h-24 w-full resize-none rounded-lg border border-[#d8e0eb] px-3 py-2 text-sm outline-none focus:border-[#1677ff] focus:ring-2 focus:ring-[#1677ff]/10" />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <button disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs text-[#5d6b80]">取消</button>
          <button disabled={busy || reason.trim().length < 2} onClick={() => onConfirm(reason.trim())} className="rounded-lg bg-[#1677ff] px-4 py-2 text-xs font-medium text-white disabled:opacity-45">{busy ? '正在提交…' : '提交申请'}</button>
        </div>
      </div>
    </div>
  )
}

