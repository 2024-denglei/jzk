import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { adminFetch, postAdmin } from './adminApi'
import { DonorEditor } from './DonorEditor'
import { createDonorForm, donorFormToPayload, type DonorFormValues } from './donorForm'
import { adminPageShellClass } from './adminLayout'
import { ErrorNotice, PageHeader, Pagination, StatusBadge, StickyTableCard } from './AdminUi'
import type { DonorRow, PageData } from './types'
import type { OperationRequestAction } from './types'
import { ADMIN_PERMISSIONS, hasAdminPermission } from './adminPermissions'
import { OperationRequestDialog } from './OperationRequestDialog'

type EditorState = {
  originalCode: string
  values: DonorFormValues
}

type PendingRequest = { action: OperationRequestAction; targetId: string; payload: Record<string, unknown>; title: string; description: string; closeEditor?: boolean }

export function DonorsView({ permissions }: { permissions: string[] }) {
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
  const [pendingRequest, setPendingRequest] = useState<PendingRequest | null>(null)
  const [requestBusy, setRequestBusy] = useState(false)
  const [message, setMessage] = useState('')
  const canWrite = hasAdminPermission(permissions, ADMIN_PERMISSIONS.donorsWrite)
  const canRequest = hasAdminPermission(permissions, ADMIN_PERMISSIONS.donorsWriteRequest)

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
    if (!canWrite) {
      if (canRequest) setPendingRequest({ action: 'donor_status', targetId: row.code, payload: { status: nextStatus }, title: `申请${nextStatus === 'disabled' ? '停用' : '启用'}档案`, description: `目标档案：${row.code}。` })
      return
    }
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
    setError('')
    const body = donorFormToPayload(editor.values)
    const code = editor.originalCode || String(body.code || '')
    if (!code) { setError('需要填写捐精人代号'); return }
    body.code = code
    if (!canWrite) {
      if (canRequest) setPendingRequest({ action: editor.originalCode ? 'donor_update' : 'donor_create', targetId: code, payload: body, title: editor.originalCode ? `申请修改 ${code}` : `申请新增 ${code}`, description: '本次填写的档案内容将作为审批执行数据。', closeEditor: true })
      return
    }
    setSaving(true)
    try {
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

  async function submitRequest(reason: string) {
    if (!pendingRequest) return
    setRequestBusy(true); setError(''); setMessage('')
    try {
      await postAdmin('/api/admin/requests', { action: pendingRequest.action, target_id: pendingRequest.targetId, payload: pendingRequest.payload, reason })
      setMessage('操作申请已提交，超级管理员批准后系统会自动执行。')
      if (pendingRequest.closeEditor) setEditor(null)
      setPendingRequest(null)
    } catch (err) { setError(err instanceof Error ? err.message : '申请提交失败') }
    finally { setRequestBusy(false) }
  }

  return (
    <div className={adminPageShellClass()}>
      <div className="shrink-0">
        <PageHeader title="捐精人档案" description="维护捐精人基础资料、标本库存和启停状态。" />
        {error ? <ErrorNotice message={error} /> : null}
        {message ? <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div> : null}
      </div>
      <StickyTableCard
        toolbar={(
          <form onSubmit={(event) => { event.preventDefault(); setQuery(draft.trim()); setPage(1) }} className="flex flex-wrap gap-2 border-b border-[#e2e8f0] p-3">
            <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="搜索代号、编号或民族" className="h-9 min-w-[240px] flex-1 rounded-lg border border-[#d9e1ec] px-3 text-xs outline-none focus:border-[#1677ff]" />
            <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} className="h-9 rounded-lg border border-[#d9e1ec] bg-white px-3 text-xs">
              <option value="">全部状态</option>
              <option value="active">正常</option>
              <option value="disabled">已停用</option>
            </select>
            <button className="h-9 rounded-lg bg-[#1677ff] px-4 text-xs text-white">查询</button>
            {(canWrite || canRequest) ? <button type="button" onClick={() => openEditor()} className="h-9 rounded-lg border border-[#9fc7ff] px-4 text-xs text-[#1677ff]">{canWrite ? '新建档案' : '申请新增'}</button> : null}
          </form>
        )}
        footer={<Pagination page={page} pageSize={data.page_size} total={data.total} onChange={setPage} />}
      >
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-[#f7f9fc] text-[#667389]">
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
                    {(canWrite || canRequest) ? <button type="button" onClick={() => openEditor(row)} className="mr-3 text-[#1677ff]">{canWrite ? '编辑' : '申请修改'}</button> : null}
                    <button type="button" disabled={pending} onClick={() => void toggle(row)} className={`${row.status === 'active' ? 'text-rose-600' : 'text-emerald-600'} disabled:text-[#9aa5b5]`}>
                      {pending ? '处理中…' : `${canWrite ? '' : '申请'}${row.status === 'active' ? '停用' : '启用'}`}
                    </button>
                  </td>
                </tr>
              )
            })}
            {loading ? <tr><td colSpan={8} className="py-16 text-center text-sm text-[#8c98aa]">正在加载档案…</td></tr> : null}
            {!loading && !data.items.length ? <tr><td colSpan={8} className="py-16 text-center text-sm text-[#9aa5b5]">暂无档案</td></tr> : null}
          </tbody>
        </table>
      </StickyTableCard>
      {editor ? (
        <DonorEditor
          originalCode={editor.originalCode}
          values={editor.values}
          busy={saving}
          onChange={(key, value) => setEditor((current) => current ? { ...current, values: { ...current.values, [key]: value } } : null)}
          onClose={() => { if (!saving) setEditor(null) }}
          onSave={() => void save()}
          submitLabel={canWrite ? '保存档案' : '提交修改申请'}
        />
      ) : null}
      {pendingRequest ? <OperationRequestDialog title={pendingRequest.title} description={pendingRequest.description} busy={requestBusy} onClose={() => setPendingRequest(null)} onConfirm={(reason) => void submitRequest(reason)} /> : null}
    </div>
  )
}
