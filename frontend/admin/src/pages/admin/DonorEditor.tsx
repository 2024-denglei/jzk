import type { DonorField, DonorFormValues } from './donorForm'
import { DONOR_FORM_SECTIONS } from './donorForm'

type Props = {
  originalCode: string
  values: DonorFormValues
  busy: boolean
  onChange: (key: string, value: string) => void
  onClose: () => void
  onSave: () => void
  submitLabel?: string
}

export function DonorEditor({ originalCode, values, busy, onChange, onClose, onSave, submitLabel = '保存档案' }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[#0b1729]/45" role="dialog" aria-modal="true" aria-label={originalCode ? `编辑 ${originalCode}` : '新建捐精人档案'}>
      <div className="flex h-full w-full max-w-3xl flex-col bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-[#e2e8f0] px-5 py-4 sm:px-6">
          <div>
            <h2 className="text-base font-semibold text-[#17263b]">{originalCode ? `编辑 ${originalCode}` : '新建捐精人档案'}</h2>
            <p className="mt-1 text-xs text-[#7d899b]">按资料类别填写，留空的非必填项会保存为空。</p>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-xl text-[#7f8b9d] hover:bg-[#f1f5f9]" aria-label="关闭编辑表单">
            <i className="ri-close-line" />
          </button>
        </div>

        <form onSubmit={(event) => { event.preventDefault(); onSave() }} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto bg-[#f7f9fc] px-5 py-5 sm:px-6">
            <div className="space-y-4">
              {DONOR_FORM_SECTIONS.map((section) => (
                <section key={section.title} className="rounded-xl border border-[#dce4ee] bg-white p-4 sm:p-5">
                  <div className="mb-4 border-b border-[#edf1f5] pb-3">
                    <h3 className="text-sm font-semibold text-[#27364d]">{section.title}</h3>
                    <p className="mt-1 text-[11px] text-[#8793a4]">{section.description}</p>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {section.fields.map((field) => (
                      <FieldControl
                        key={field.key}
                        field={field}
                        value={values[field.key] || ''}
                        disabled={field.key === 'code' && Boolean(originalCode)}
                        onChange={(value) => onChange(field.key, value)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-[#e2e8f0] bg-white px-5 py-3 sm:px-6">
            <button type="button" disabled={busy} onClick={onClose} className="rounded-lg border border-[#d8e0eb] px-4 py-2 text-xs text-[#5d6b80] disabled:opacity-50">取消</button>
            <button type="submit" disabled={busy || !values.code.trim()} className="min-w-24 rounded-lg bg-[#1677ff] px-4 py-2 text-xs font-medium text-white disabled:opacity-50">
              {busy ? '正在处理…' : submitLabel}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function FieldControl({ field, value, disabled, onChange }: { field: DonorField; value: string; disabled: boolean; onChange: (value: string) => void }) {
  const className = 'mt-1.5 w-full rounded-lg border border-[#d7e0ea] bg-white px-3 text-xs text-[#27364d] outline-none transition focus:border-[#1677ff] focus:ring-2 focus:ring-[#1677ff]/10 disabled:bg-[#f1f5f9] disabled:text-[#8b97a8]'
  const label = field.key === 'status' ? '正常 / 已停用' : field.label
  const options = value && !field.options?.includes(value) ? [value, ...(field.options || [])] : field.options

  return (
    <label className={field.wide ? 'sm:col-span-2' : ''}>
      <span className="text-xs font-medium text-[#44536a]">{field.label}{field.required ? <span className="ml-1 text-rose-500">*</span> : null}</span>
      {field.kind === 'select' ? (
        <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className={`${className} h-10`}>
          <option value="">请选择</option>
          {options?.map((option) => <option key={option} value={option}>{field.key === 'status' ? (option === 'active' ? '正常' : '已停用') : option}</option>)}
        </select>
      ) : field.kind === 'textarea' ? (
        <textarea value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} placeholder={field.placeholder || `请输入${field.label}`} rows={3} className={`${className} resize-y py-2.5 leading-5`} />
      ) : (
        <input
          type={field.kind}
          value={value}
          disabled={disabled}
          required={field.required}
          step={field.step}
          min={field.kind === 'number' ? '0' : undefined}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.placeholder || `请输入${label}`}
          className={`${className} h-10`}
        />
      )}
    </label>
  )
}
