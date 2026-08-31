import { useState, type ReactNode } from 'react'
import type { AdminRecord } from './types'
import { adminCreateValidationErrors } from './adminAccountForm'

export type AdminCreateValues = {
  username: string
  password: string
  display_name: string
  role: 'super_admin' | 'donor_admin'
}

export function AdminCreateDialog({ busy, onClose, onConfirm }: {
  busy: boolean
  onClose: () => void
  onConfirm: (values: AdminCreateValues) => void
}) {
  const [values, setValues] = useState<AdminCreateValues>({ username: '', password: '', display_name: '', role: 'donor_admin' })
  const [confirmPassword, setConfirmPassword] = useState('')
  const errors = adminCreateValidationErrors({ username: values.username, password: values.password, confirmPassword, displayName: values.display_name })
  const valid = errors.length === 0
  const passwordHint = values.password.length < 12
    ? `至少需要 12 位，当前 ${values.password.length} 位，还需 ${12 - values.password.length} 位`
    : '密码长度符合要求'
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1729]/45 px-4" role="dialog" aria-modal="true" aria-label="新增管理员"><form onSubmit={(event) => { event.preventDefault(); if (valid) onConfirm({ ...values, username: values.username.trim(), display_name: values.display_name.trim() }) }} className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl"><div className="flex items-start justify-between"><div><h2 className="text-base font-semibold text-[#17263c]">新增管理员</h2><p className="mt-1 text-xs text-[#6f7c90]">创建独立登录账号并指定管理员角色。</p></div><button type="button" onClick={onClose} className="text-xl text-[#8290a2]"><i className="ri-close-line" /></button></div><div className="mt-5 space-y-4"><Field label="显示名称"><input autoFocus value={values.display_name} onChange={(event) => setValues({ ...values, display_name: event.target.value })} className={inputClass} placeholder="例如：张管理员" /></Field><Field label="登录账号"><input value={values.username} onChange={(event) => setValues({ ...values, username: event.target.value })} className={inputClass} placeholder="3-50 位字母、数字、点、横线或下划线" /></Field><Field label="初始密码"><input type="password" value={values.password} onChange={(event) => setValues({ ...values, password: event.target.value })} className={inputClass} placeholder="至少 12 位" /><span className={`mt-1 block text-[11px] ${values.password.length >= 12 ? 'text-emerald-600' : 'text-amber-600'}`}>{passwordHint}</span></Field><Field label="确认密码"><input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className={inputClass} placeholder="再次输入初始密码" />{confirmPassword && confirmPassword !== values.password ? <span className="mt-1 block text-[11px] text-rose-600">两次输入的密码不一致</span> : null}</Field><Field label="角色"><select value={values.role} onChange={(event) => setValues({ ...values, role: event.target.value as AdminCreateValues['role'] })} className={inputClass}><option value="donor_admin">普通管理员</option><option value="super_admin">超级管理员</option></select></Field></div>{errors.length ? <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700"><i className="ri-information-line mr-1" />暂时无法创建：{errors[0]}</div> : null}<div className="mt-6 flex justify-end gap-2"><button type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs">取消</button><button disabled={busy || !valid} title={valid ? undefined : errors[0]} className="rounded-lg bg-[#1677ff] px-4 py-2 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-45">{busy ? '正在创建…' : '创建管理员'}</button></div></form></div>
}

export function AdminStateDialog({ admin, action, busy, onClose, onConfirm }: {
  admin: AdminRecord
  action: 'delete' | 'restore'
  busy: boolean
  onClose: () => void
  onConfirm: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  const deleting = action === 'delete'
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1729]/45 px-4" role="dialog" aria-modal="true"><div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl"><h2 className="text-base font-semibold text-[#17263c]">{deleting ? '删除管理员' : '恢复管理员'}</h2><p className="mt-2 text-xs leading-5 text-[#6f7c90]">账号：{admin.display_name || admin.username}（{admin.username}）。{deleting ? '删除采用停用方式，账号会立即失去管理端访问权限，但历史操作和审计记录会保留。' : '恢复后该账号可以重新登录管理端。'}</p><label className="mt-4 block text-xs font-medium text-[#34445b]">操作原因<textarea autoFocus value={reason} onChange={(event) => setReason(event.target.value)} className="mt-2 h-24 w-full resize-none rounded-lg border border-[#d8e0eb] px-3 py-2 text-sm outline-none focus:border-[#1677ff]" placeholder="请填写原因（至少 2 个字）" /></label><div className="mt-5 flex justify-end gap-2"><button disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs">取消</button><button disabled={busy || reason.trim().length < 2} onClick={() => onConfirm(reason.trim())} className={`rounded-lg px-4 py-2 text-xs font-medium text-white disabled:opacity-45 ${deleting ? 'bg-rose-600' : 'bg-emerald-600'}`}>{busy ? '处理中…' : deleting ? '确认删除' : '确认恢复'}</button></div></div></div>
}

const inputClass = 'mt-2 h-10 w-full rounded-lg border border-[#d7e0ea] bg-white px-3 text-sm outline-none focus:border-[#1677ff]'
function Field({ label, children }: { label: string; children: ReactNode }) { return <label className="block text-xs font-medium text-[#44536a]">{label}{children}</label> }
