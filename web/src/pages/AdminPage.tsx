import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'

const TOKEN_KEY = 'jzk_admin_token'

type AdminInfo = {
  id: number
  username: string
  display_name: string
  role: string
}

type DonorRow = {
  code: string
  status: string
  specimen_count: number
  education?: string
  ethnicity?: string
  height_cm?: number
  donor_info?: { code: string; education?: string; ethnicity?: string; height?: number }
}

type AuditRow = {
  id: number
  donor_code: string
  action: string
  created_at: string
  operator_id: number | null
}

async function adminFetch(path: string, init: RequestInit = {}) {
  const token = localStorage.getItem(TOKEN_KEY)
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (!(init.body instanceof FormData) && !headers.has('Content-Type') && init.body) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(path, { ...init, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export function AdminPage() {
  const [admin, setAdmin] = useState<AdminInfo | null>(null)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [donors, setDonors] = useState<DonorRow[]>([])
  const [total, setTotal] = useState(0)
  const [audits, setAudits] = useState<AuditRow[]>([])
  const [tab, setTab] = useState<'donors' | 'audit' | 'import'>('donors')
  const [importMsg, setImportMsg] = useState('')
  const [editCode, setEditCode] = useState('')
  const [editJson, setEditJson] = useState('{\n  "code": "",\n  "abo_blood": "A",\n  "education": "本科",\n  "height_cm": 175,\n  "specimen_count": 10,\n  "status": "active"\n}')

  const loadMe = useCallback(async () => {
    try {
      const me = await adminFetch('/api/admin/me')
      setAdmin(me)
    } catch {
      setAdmin(null)
      localStorage.removeItem(TOKEN_KEY)
    }
  }, [])

  const loadDonors = useCallback(async () => {
    const data = await adminFetch(`/api/admin/donors?page=1&page_size=50&q=${encodeURIComponent(q)}`)
    setDonors(data.items || [])
    setTotal(data.total || 0)
  }, [q])

  const loadAudit = useCallback(async () => {
    const data = await adminFetch('/api/admin/audit?page=1&page_size=50')
    setAudits(data.items || [])
  }, [])

  useEffect(() => {
    if (localStorage.getItem(TOKEN_KEY)) loadMe()
  }, [loadMe])

  useEffect(() => {
    if (!admin) return
    if (tab === 'donors') loadDonors().catch((e) => setError(String(e.message || e)))
    if (tab === 'audit') loadAudit().catch((e) => setError(String(e.message || e)))
  }, [admin, tab, loadDonors, loadAudit])

  async function onLogin(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const data = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      }).then(async (r) => {
        const j = await r.json()
        if (!r.ok) throw new Error(j.detail || '登录失败')
        return j
      })
      localStorage.setItem(TOKEN_KEY, data.access_token)
      setAdmin(data.admin)
      setPassword('')
    } catch (err: any) {
      setError(err.message || '登录失败')
    }
  }

  async function toggleStatus(code: string, status: string) {
    const next = status === 'active' ? 'disabled' : 'active'
    await adminFetch(`/api/admin/donors/${encodeURIComponent(code)}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: next }),
    })
    await loadDonors()
  }

  async function onImport(file: File) {
    setImportMsg('导入中…')
    const fd = new FormData()
    fd.append('file', file)
    try {
      const data = await adminFetch('/api/admin/donors/import', { method: 'POST', body: fd })
      setImportMsg(
        `完成：成功 ${data.success_count}，失败 ${data.fail_count}，映射行 ${data.mapped_rows}/${data.total_rows}`,
      )
      await loadDonors()
    } catch (err: any) {
      setImportMsg(err.message || '导入失败')
    }
  }

  async function onSaveDonor() {
    setError('')
    try {
      const body = JSON.parse(editJson)
      const code = editCode || body.code
      if (!code) throw new Error('需要代号')
      body.code = code
      const exists = donors.some((d) => d.code === code)
      if (exists || editCode) {
        await adminFetch(`/api/admin/donors/${encodeURIComponent(code)}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        })
      } else {
        await adminFetch('/api/admin/donors', { method: 'POST', body: JSON.stringify(body) })
      }
      setEditCode('')
      await loadDonors()
    } catch (err: any) {
      setError(err.message || '保存失败')
    }
  }

  if (!admin) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <h1 className="font-display text-2xl text-ink">管理端登录</h1>
        <p className="mt-2 text-sm text-mute">捐精人主数据维护（与前台用户账号分离）</p>
        <form onSubmit={onLogin} className="mt-8 space-y-4">
          <label className="block text-sm">
            用户名
            <input
              className="mt-1 w-full rounded-lg border border-line px-3 py-2"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label className="block text-sm">
            密码
            <input
              type="password"
              className="mt-1 w-full rounded-lg border border-line px-3 py-2"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <button type="submit" className="w-full rounded-lg bg-teal-deep py-2.5 text-white">
            登录
          </button>
        </form>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl text-ink">捐精人数据管理</h1>
          <p className="mt-1 text-sm text-mute">
            {admin.display_name || admin.username}（{admin.role}）· 共 {total} 条
          </p>
        </div>
        <button
          className="text-sm text-mute underline"
          onClick={() => {
            localStorage.removeItem(TOKEN_KEY)
            setAdmin(null)
          }}
        >
          退出
        </button>
      </div>

      <div className="mt-6 flex gap-2 border-b border-line pb-2 text-sm">
        {(
          [
            ['donors', '档案列表'],
            ['import', 'Excel 导入'],
            ['audit', '操作审计'],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`rounded-lg px-3 py-1.5 ${tab === k ? 'bg-teal-deep text-white' : 'bg-sand text-ink'}`}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}

      {tab === 'donors' ? (
        <div className="mt-6 space-y-6">
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-lg border border-line px-3 py-2 text-sm"
              placeholder="搜索代号 / 编号 / 民族"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button className="rounded-lg bg-ink px-4 py-2 text-sm text-white" onClick={() => loadDonors()}>
              查询
            </button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-sand/80">
                <tr>
                  <th className="px-3 py-2">代号</th>
                  <th className="px-3 py-2">学历</th>
                  <th className="px-3 py-2">民族</th>
                  <th className="px-3 py-2">身高</th>
                  <th className="px-3 py-2">标本</th>
                  <th className="px-3 py-2">状态</th>
                  <th className="px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {donors.map((d) => (
                  <tr key={d.code} className="border-t border-line/70">
                    <td className="px-3 py-2 font-medium">{d.code}</td>
                    <td className="px-3 py-2">{d.donor_info?.education || d.education || '—'}</td>
                    <td className="px-3 py-2">{d.donor_info?.ethnicity || d.ethnicity || '—'}</td>
                    <td className="px-3 py-2">{d.donor_info?.height || d.height_cm || '—'}</td>
                    <td className="px-3 py-2">{d.specimen_count}</td>
                    <td className="px-3 py-2">{d.status}</td>
                    <td className="px-3 py-2 space-x-2">
                      <button
                        className="text-teal-deep underline"
                        onClick={() => {
                          setEditCode(d.code)
                          const { donor_info, ...rest } = d as any
                          setEditJson(JSON.stringify(rest, null, 2))
                          setTab('import')
                        }}
                      >
                        编辑
                      </button>
                      <button className="text-mute underline" onClick={() => toggleStatus(d.code, d.status)}>
                        {d.status === 'active' ? '停用' : '启用'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <h2 className="text-sm font-semibold text-ink">新建 / 编辑（JSON）</h2>
            <textarea
              className="mt-2 h-56 w-full rounded-lg border border-line p-3 font-mono text-xs"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <button className="mt-2 rounded-lg bg-teal-deep px-4 py-2 text-sm text-white" onClick={onSaveDonor}>
              保存到数据库
            </button>
          </div>
        </div>
      ) : null}

      {tab === 'import' ? (
        <div className="mt-6 space-y-4">
          <p className="text-sm text-mute">请使用《文本信息》字段模板（.xls / .xlsx）。导入后自动刷新匹配缓存。</p>
          <input
            type="file"
            accept=".xls,.xlsx"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) onImport(f)
            }}
          />
          {importMsg ? <p className="text-sm text-ink">{importMsg}</p> : null}
          <div>
            <h2 className="text-sm font-semibold">单条 JSON 保存</h2>
            <textarea
              className="mt-2 h-56 w-full rounded-lg border border-line p-3 font-mono text-xs"
              value={editJson}
              onChange={(e) => setEditJson(e.target.value)}
            />
            <button className="mt-2 rounded-lg bg-teal-deep px-4 py-2 text-sm text-white" onClick={onSaveDonor}>
              保存
            </button>
          </div>
        </div>
      ) : null}

      {tab === 'audit' ? (
        <div className="mt-6 overflow-x-auto rounded-xl border border-line">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-sand/80">
              <tr>
                <th className="px-3 py-2">时间</th>
                <th className="px-3 py-2">代号</th>
                <th className="px-3 py-2">动作</th>
                <th className="px-3 py-2">操作人</th>
              </tr>
            </thead>
            <tbody>
              {audits.map((a) => (
                <tr key={a.id} className="border-t border-line/70">
                  <td className="px-3 py-2">{a.created_at}</td>
                  <td className="px-3 py-2">{a.donor_code}</td>
                  <td className="px-3 py-2">{a.action}</td>
                  <td className="px-3 py-2">{a.operator_id ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
