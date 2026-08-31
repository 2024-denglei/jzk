import { useState } from 'react'
import { adminFetch } from './adminApi'
import { ErrorNotice, PageHeader } from './AdminUi'

export function ImportView() {
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function upload(file: File) { setBusy(true); setError(''); setMessage(''); const body = new FormData(); body.append('file', file); try { const data = await adminFetch<{ success_count: number; fail_count: number; mapped_rows: number; total_rows: number }>('/api/admin/donors/import', { method: 'POST', body }); setMessage(`导入完成：成功 ${data.success_count} 条，失败 ${data.fail_count} 条，映射 ${data.mapped_rows}/${data.total_rows} 行。`) } catch (err) { setError(err instanceof Error ? err.message : '导入失败') } finally { setBusy(false) } }
  return <div><PageHeader title="Excel 导入" description="批量导入捐精人档案，完成后自动刷新匹配缓存。" />{error ? <ErrorNotice message={error} /> : null}<div className="rounded-xl border border-[#dce4ee] bg-white p-6"><div className="rounded-xl border-2 border-dashed border-[#cdd8e6] bg-[#f8fafc] px-6 py-14 text-center"><div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#e8f2ff] text-[#1677ff]"><i className="ri-file-excel-2-line text-2xl" /></div><h2 className="mt-4 text-sm font-medium">上传捐精人信息表</h2><p className="mt-2 text-xs text-[#8793a4]">支持 .xls 和 .xlsx，请使用“文本信息”字段模板。</p><label className="mt-5 inline-flex cursor-pointer rounded-lg bg-[#1677ff] px-4 py-2.5 text-xs font-medium text-white"><input type="file" accept=".xls,.xlsx" disabled={busy} className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file) }} />{busy ? '正在导入…' : '选择 Excel 文件'}</label></div>{message ? <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}</div></div>
}
