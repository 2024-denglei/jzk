import { useState } from 'react'

export type UserControlAction = 'kick' | 'disable' | 'enable'

const ACTIONS: Record<UserControlAction, { title: string; description: string; button: string }> = {
  kick: { title: '强制用户下线', description: '该用户当前持有的所有登录凭证会立即失效，但仍可重新登录。', button: '确认下线' },
  disable: { title: '停用用户账号', description: '用户会立即下线，并且无法再次登录，直到账号被恢复。', button: '确认停用' },
  enable: { title: '恢复用户账号', description: '恢复后用户可以重新登录，已有旧凭证不会自动恢复。', button: '确认恢复' },
}

export function UserControlDialog({ action, userName, busy, onClose, onConfirm }: {
  action: UserControlAction
  userName: string
  busy: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  const copy = ACTIONS[action]
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1729]/45 px-4 backdrop-blur-[2px]">
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
        <div className="flex items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${action === 'disable' ? 'bg-red-50 text-red-600' : 'bg-amber-50 text-amber-600'}`}>
            <i className="ri-error-warning-line text-xl" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-[#17263c]">{copy.title}</h2>
            <p className="mt-1 text-xs leading-5 text-[#6f7c90]">用户：{userName}。{copy.description}</p>
          </div>
        </div>
        <label className="mt-5 block text-xs font-medium text-[#34445b]">
          操作原因
          <textarea
            autoFocus
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="请填写操作原因（至少 2 个字）"
            className="mt-2 h-24 w-full resize-none rounded-lg border border-[#d8e0eb] px-3 py-2 text-sm outline-none transition focus:border-[#1677ff] focus:ring-2 focus:ring-[#1677ff]/10"
          />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <button disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs text-[#5d6b80]">取消</button>
          <button
            disabled={busy || reason.trim().length < 2}
            onClick={() => onConfirm(reason.trim())}
            className={`rounded-lg px-4 py-2 text-xs font-medium text-white disabled:opacity-45 ${action === 'disable' ? 'bg-red-600' : 'bg-[#1677ff]'}`}
          >
            {busy ? '处理中…' : copy.button}
          </button>
        </div>
      </div>
    </div>
  )
}
