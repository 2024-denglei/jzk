import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { adminFetch, postAdmin } from './adminApi'
import { DonorEditor } from './DonorEditor'
import { createDonorForm, donorFormToPayload, type DonorFormValues } from './donorForm'
import { ErrorNotice, PageHeader, Pagination, StatusBadge } from './AdminUi'
import type { DonorRow, PageData } from './types'

type EditorState = {
  originalCode: string
  values: DonorFormValues
}

export function DonorsView() {
  const [searchParams] = useSearchParams()
  const initial = searchParams.get('code') || ''
  const [draft, setDraft] = useState(initial)
  const [query, setQuery] = useState(initial)
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PageData<DonorRow>>({ items: [], total: 0, page: 1, page_size: 20 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [saving, setSaving] = useState(false)
  const [pendingCodes, setPendingCodes] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '20' })
      if (query) params.set('q', query)
      if (status) params.set('status', status)
      setData(await adminFetch(`/api/admin/donors?${params}`))
    } catch (err) {
      setError(err instanceof Error ? err.message : '档案加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, query, status])

  useEffect(() => { void load() }, [load])

  async function toggle(row: DonorRow) {
    if (pendingCodes.has(row.code)) return
    const nextStatus = row.status === 'active' ? 'disabled' : 'active'
    setError('')
    setPendingCodes((current) => new Set(current).add(row.code))
    setData((current) => ({
      ...current,
      items: current.items.map((item) => item.code === row.code ? { ...item, status: nextStatus } : item),
    }))
    try {
      await postAdmin(`/api/admin/donors/${encodeURIComponent(row.code)}/status`, { status: nextStatus })
    } catch (err) {
      setData((current) => ({
        ...current,
        items: current.items.map((item) => item.code === row.code ? { ...item, status: row.status } : item),
      }))
      setError(err instanceof Error ? err.message : '状态修改失败')
    } finally {
      setPendingCodes((current) => {
        const next = new Set(current)
        next.delete(row.code)
        return next
      })
    }
  }

  async function save() {
    if (!editor) return
    setSaving(true)
    setError('')
    try {
      const body = donorFormToPayload(editor.values)
      const code = editor.originalCode || String(body.code || '')
      if (!code) throw new Error('需要填写捐精人代号')
      body.code = code
      await adminFetch(editor.originalCode ? `/api/admin/donors/${encodeURIComponent(code)}` : '/api/admin/donors', {
        method: editor.originalCode ? 'PUT' : 'POST',
        body: JSON.stringify(body),
      })
      setEditor(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function openEditor(row?: DonorRow) {
    setEditor({ originalCode: row?.code || '', values: createDonorForm(row) })
  }

  return (
    <div>
      <PageHeader title="捐精人档案" description="维护捐精人基础资料、标本库存和启停状态。" />
      {error ? <ErrorNotice message={error} /> : null}
      <div className="rounded-xl border border-[#dce4ee] bg-white">
        <form onSubmit={(event) => { event.preventDefault(); setQuery(draft.trim()); setPage(1) }} className="flex flex-wrap gap-2 border-b border-[#e2e8f0] p-3">
          <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索代号、编号或民族" className="h-9 min-w-[240px] flex-1 rounded-lg border border-[#d9e1ec] px-3 text-xs outline-none focus:border-[#1677ff]" />
          <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs">
            <option value="">全部状态</option>
            <option value="active">正常</option>
            <option value="disabled">已停用</option>
          </select>
          <button className="h-9 rounded-lg bg-[#1677ff] px-4 text-xs text-white">查询</button>
          <button type="button" onClick={() => openEditor()} className="h-9 rounded-lg border border-[#9fc7ff] px-4 text-xs text-[#1677ff]">新建档案</button>
        </form>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-xs">
            <thead className="bg-[#f7f9fc] text-[#667389]">
              <tr><th className="px-4 py-3 font-medium">代号</th><th className="px-4 py-3 font-medium">编号</th><th className="px-4 py-3 font-medium">学历</th><th className="px-4 py-3 font-medium">民族</th><th className="px-4 py-3 font-medium">身高</th><th className="px-4 py-3 font-medium">标本库存</th><th className="px-4 py-3 font-medium">状态</th><th className="px-4 py-3 font-medium">操作</th></tr>
            </thead>
            <tbody className="divide-y divide-[#e5eaf1]">
              {data.items.map((row) => {
                const pending = pendingCodes.has(row.code)
                return (
                  <tr key={row.code} className="hover:bg-[#f8fbff]">
                    <td className="px-4 py-3 font-medium text-[#1d4f91]">{row.code}</td>
                    <td className="px-4 py-3">{row.serial_no || '—'}</td>
                    <td className="px-4 py-3">{row.donor_info?.education || row.education || '—'}</td>
                    <td className="px-4 py-3">{row.donor_info?.ethnicity || row.ethnicity || '—'}</td>
                    <td className="px-4 py-3">{row.donor_info?.height || row.height_cm || '—'}</td>
                    <td className="px-4 py-3">{row.specimen_count}</td>
                    <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => openEditor(row)} className="mr-3 text-[#1677ff]">编辑</button>
                      <button type="button" disabled={pending} onClick={() => void toggle(row)} className={`${row.status === 'active' ? 'text-rose-600' : 'text-emerald-600'} disabled:text-[#9aa5b5]`}>
                        {pending ? '处理中…' : row.status === 'active' ? '停用' : '启用'}
                      </button>
                    </td>
                  </tr>
                )
              })}
              {loading ? <tr><td colSpan={8} className="py-16 text-center text-sm text-[#8c98aa]">正在加载档案…</td></tr> : null}
              {!loading && !data.items.length ? <tr><td colSpan={8} className="py-16 text-center text-sm text-[#9aa5b5]">暂无档案</td></tr> : null}
            </tbody>
          </table>
        </div>
        <Pagination page={page} pageSize={data.page_size} total={data.total} onChange={setPage} />
      </div>
      {editor ? (
        <DonorEditor
          originalCode={editor.originalCode}
          values={editor.values}
          busy={saving}
          onChange={(key, value) => setEditor((current) => current ? { ...current, values: { ...current.values, [key]: value } } : null)}
          onClose={() => { if (!saving) setEditor(null) }}
          onSave={() => void save()}
        />
      ) : null}
    </div>
  )
}
