import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { donorsPathWithSearch } from '../lib/donorsWorkbench'
import type { Candidate } from '../types'

/** 基于代号生成柔和背景色，用于头像占位 */
function avatarTone(code: string) {
  let hash = 0
  for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) >>> 0
  const hues = [168, 186, 195, 172, 158]
  return `hsl(${hues[hash % hues.length]} 32% 90%)`
}

export function DonorCard({ candidate, index = 0 }: { candidate: Candidate; index?: number }) {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const d = candidate.donor_info
  const pct =
    candidate.match_pct != null
      ? Math.round(candidate.match_pct)
      : candidate.score
        ? Math.round(candidate.score * 100)
        : null
  const showMatch = pct != null && pct > 0
  const letter = (d.code?.replace(/[^A-Za-z]/g, '')[0] || d.code?.[0] || 'D').toUpperCase()
  const detailPath = donorsPathWithSearch(`/donors/${encodeURIComponent(d.code)}`, searchParams)
  const href = user ? detailPath : `/login?next=${encodeURIComponent(detailPath)}`

  // 参考 Cryos：双列键值，信息稍多以便扫读
  const fields = [
    { label: '学历', value: d.education || '—' },
    { label: '身高', value: d.height ? `${d.height} cm` : '—' },
    { label: '血型', value: d.blood_type ? `${d.blood_type}型` : '—' },
    { label: '年龄', value: d.age ? `${d.age} 岁` : '—' },
    { label: '民族', value: d.ethnicity || '—' },
    { label: '籍贯', value: d.hometown || '—' },
    { label: '体型', value: d.figure || '—' },
    { label: '性格', value: d.personality || '—' },
    { label: '职业', value: d.occupation || '—' },
    { label: '标本', value: `${d.specimen_count ?? 0} 管` },
  ]

  return (
    <Link
      to={href}
      className="donor-card-lift stagger-item group flex flex-col overflow-hidden rounded-2xl border border-line/90 bg-white"
      style={{ animationDelay: `${Math.min(index, 11) * 35}ms` }}
    >
      {/* 头部：圆形头像占位 + 代号 */}
      <div className="flex items-start gap-3 border-b border-line/50 px-4 pb-3 pt-4">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full ring-2 ring-white"
          style={{ background: avatarTone(d.code || 'D') }}
          aria-label={`捐献者 ${d.code} 头像占位`}
        >
          {/* 卡通头像占位：后续可换成真实卡通图 */}
          <span className="font-display text-2xl font-bold text-teal-deep/70">{letter}</span>
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex items-start justify-between gap-2">
            <div className="font-display text-lg font-bold uppercase leading-tight tracking-wide text-ink">
              {d.code}
            </div>
            {showMatch && (
              <div className="shrink-0 rounded-full bg-mist px-2 py-0.5 text-[11px] font-semibold tabular-nums text-teal-deep">
                {pct}%
              </div>
            )}
          </div>
          <div className="mt-1 text-[12px] text-ink-soft/50">
            {d.age ? `${d.age} 岁` : '年龄未知'}
            <span className="mx-1 text-line">·</span>
            标本 {d.specimen_count ?? 0} 管
          </div>
          <div className="mt-1 text-[11px] text-ink-soft/40">
            {d.status === 'disabled' ? '已停用' : '可选择'}
          </div>
        </div>
      </div>

      {/* 双列属性区 */}
      <div className="grid flex-1 grid-cols-2 gap-x-4 gap-y-3 px-4 py-3.5">
        {fields.map((f) => (
          <div key={f.label} className="min-w-0">
            <div className="text-[11px] font-semibold text-ink">{f.label}</div>
            <div className="mt-0.5 truncate text-[12.5px] text-ink-soft/70">{f.value}</div>
          </div>
        ))}
      </div>

      <div className="border-t border-line/50 px-4 py-2.5 text-right text-[11px] font-medium text-teal-deep">
        <span className="opacity-0 transition group-hover:opacity-100">查看详情 →</span>
      </div>
    </Link>
  )
}

export function DonorCardSkeleton() {
  return (
    <div className="flex min-h-[280px] flex-col overflow-hidden rounded-2xl border border-line/80 bg-white">
      <div className="flex items-start gap-3 border-b border-line/50 px-4 pb-3 pt-4">
        <div className="skeleton h-16 w-16 rounded-full" />
        <div className="flex-1 space-y-2 pt-1">
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-3 w-32" />
          <div className="skeleton h-3 w-16" />
        </div>
      </div>
      <div className="grid flex-1 grid-cols-2 gap-x-4 gap-y-3 px-4 py-3.5">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <div className="skeleton h-3 w-10" />
            <div className="skeleton h-3 w-16" />
          </div>
        ))}
      </div>
    </div>
  )
}
