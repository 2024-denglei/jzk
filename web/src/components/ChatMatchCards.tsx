import { Link } from 'react-router-dom'
import type { Candidate, PreferHit } from '../types'

const PREFER_HIT_SCORE = 0.8

const FIELD_LABELS: Record<string, string> = {
  height_cm: '身高',
  weight_kg: '体重',
  bmi: 'BMI',
  age: '年龄',
  specimen_count: '标本',
  education: '学历',
  abo_blood: '血型',
  rh_blood: 'Rh',
  figure: '体型',
  skin_color: '肤色',
  face_shape: '脸型',
  eyelid: '眼皮',
  lip_shape: '唇型',
  constellation: '星座',
  ethnicity: '民族',
  hometown: '籍贯',
  occupation: '职业',
  personality: '性格',
  smoke_history: '吸烟',
}

function avatarTone(code: string) {
  let hash = 0
  for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) >>> 0
  const hues = [168, 186, 195, 172, 158]
  return `hsl(${hues[hash % hues.length]} 32% 90%)`
}

function preferFieldHit(c: Candidate, field: string): boolean {
  if (c.field_match?.[field]?.match) return true
  const row = c.field_scores?.find((x) => x.field === field)
  return row != null && Number(row.s) >= PREFER_HIT_SCORE
}

function derivePreferHits(candidates: Candidate[]): PreferHit[] {
  if (!candidates.length) return []
  const seen = new Set<string>()
  const out: PreferHit[] = []
  for (const row of candidates[0].field_scores || []) {
    if (row.constraint !== 'prefer' || seen.has(row.field)) continue
    seen.add(row.field)
    out.push({
      field: row.field,
      label: FIELD_LABELS[row.field] || row.field,
      hits: candidates.filter((c) => preferFieldHit(c, row.field)).length,
      of: candidates.length,
    })
  }
  return out
}

/** 聊天侧预览条数；中间栏由页面分页，避免一次挂载数千张卡片 */
const CHAT_PREVIEW = 20

type Props = {
  candidates: Candidate[]
  preferHits?: PreferHit[]
  /** 匹配总数；大于 candidates.length 时表示侧栏仅为预览 */
  totalOverride?: number
  onViewInMiddle: () => void
}

export function ChatMatchCards({ candidates, preferHits, totalOverride, onViewInMiddle }: Props) {
  if (!candidates.length) return null
  const hits = preferHits?.length ? preferHits : derivePreferHits(candidates)
  const total = totalOverride ?? hits[0]?.of ?? candidates.length
  const hitSummary = hits.map((h) => `${h.label} ${h.hits}/${h.of}`).join(' · ')
  const preview = candidates.slice(0, CHAT_PREVIEW)
  const truncated = total > preview.length || candidates.length > CHAT_PREVIEW

  return (
    <div className="mt-2 flex w-full max-w-[92%] flex-col overflow-hidden rounded-2xl border border-line/70 bg-white">
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-line/50 px-3 py-2">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-ink">
            本轮匹配{' '}
            <span className="tabular-nums text-teal-deep">{total}</span> 位
            {hits.length > 0 ? ' · 已按偏好重排' : ''}
          </div>
          {hitSummary ? (
            <div className="mt-0.5 truncate text-[11px] font-normal text-ink-soft/55">{hitSummary}</div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => onViewInMiddle()}
          className="shrink-0 rounded-md bg-teal-deep px-2.5 py-1 text-[11px] font-semibold text-white transition hover:bg-ink"
        >
          在中间查看
        </button>
      </div>

      <ul className="scroll-y max-h-[280px] divide-y divide-line/40 overflow-y-auto overscroll-contain">
        {preview.map((c) => {
          const d = c.donor_info
          const letter = (d.code?.replace(/[^A-Za-z]/g, '')[0] || d.code?.[0] || 'D').toUpperCase()
          const pct =
            c.match_pct != null
              ? Math.round(c.match_pct)
              : c.score
                ? Math.round(c.score * 100)
                : null
          const meta = [
            d.education || null,
            d.height ? `${d.height}cm` : null,
            d.age ? `${d.age}岁` : null,
          ]
            .filter(Boolean)
            .join(' · ')
          const marks = hits.filter((h) => preferFieldHit(c, h.field)).map((h) => h.label)

          return (
            <li key={d.code}>
              <Link
                to={`/donors/${encodeURIComponent(d.code)}`}
                className="flex items-center gap-2.5 px-3 py-2 transition hover:bg-mist/40"
              >
                <div
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                  style={{ background: avatarTone(d.code || 'D') }}
                >
                  <span className="font-display text-[13px] font-bold text-teal-deep/70">{letter}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[12.5px] font-semibold text-ink">{d.code}</span>
                    {pct != null && pct > 0 && (
                      <span className="shrink-0 rounded bg-mist px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-teal-deep">
                        {pct}%
                      </span>
                    )}
                    {marks.map((label) => (
                      <span
                        key={label}
                        className="shrink-0 rounded bg-teal-deep/10 px-1.5 py-0.5 text-[10px] font-medium text-teal-deep"
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                  <div className="truncate text-[11px] text-ink-soft/50">{meta || '点击查看详情'}</div>
                </div>
                <i className="ri-arrow-right-s-line shrink-0 text-ink-soft/30" />
              </Link>
            </li>
          )
        })}
      </ul>
      {truncated ? (
        <div className="border-t border-line/50 px-3 py-2 text-[11px] text-ink-soft/50">
          侧栏预览当前前 {Math.min(CHAT_PREVIEW, candidates.length)} 位，点「在中间查看」分页浏览
          {total > candidates.length ? `（共 ${total} 位符合条件）` : ''}
        </div>
      ) : null}
    </div>
  )
}
