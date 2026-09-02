import { useMemo, useState } from 'react'
import { WORKBENCH_HEADER_HEIGHT_CLASS } from '../lib/workbenchLayout'
import type { FilterState } from '../types'
import { DEFAULT_PRIORITY } from '../types'

type Props = {
  collapsed: boolean
  onToggle: () => void
  filters: FilterState
  setFilters: (f: FilterState) => void
  priority: string[]
  setPriority: (p: string[]) => void
  onSearch: () => void
  onClear: () => void
  searching?: boolean
  /** 移动端抽屉模式：始终展开内容，由外层控制显隐 */
  drawer?: boolean
  className?: string
}

type ChipGroup = {
  title: string
  key: keyof FilterState
  multi: boolean
  primary?: boolean
  options: { value: string; label: string }[]
}

const CHIP_GROUPS: ChipGroup[] = [
  {
    title: '学历',
    key: 'education',
    multi: true,
    primary: true,
    options: [
      { value: '大专', label: '大专' },
      { value: '本科', label: '本科' },
      { value: '硕士', label: '硕士' },
      { value: '博士', label: '博士' },
    ],
  },
  {
    title: '身高',
    key: 'height',
    multi: false,
    primary: true,
    options: [
      { value: '170cm以上', label: '170cm+' },
      { value: '175cm以上', label: '175cm+' },
      { value: '180cm以上', label: '180cm+' },
      { value: '170-180cm', label: '170-180cm' },
    ],
  },
  {
    title: '血型',
    key: 'blood_type',
    multi: true,
    primary: true,
    options: [
      { value: 'A', label: 'A' },
      { value: 'B', label: 'B' },
      { value: 'O', label: 'O' },
      { value: 'AB', label: 'AB' },
    ],
  },
  {
    title: '标本数量',
    key: 'specimen_min',
    multi: false,
    primary: true,
    options: [
      { value: '3', label: '≥3' },
      { value: '5', label: '≥5' },
      { value: '8', label: '≥8' },
      { value: '10', label: '≥10' },
    ],
  },
  {
    title: 'RH血型',
    key: 'rh_blood',
    multi: true,
    options: [
      { value: '阳性', label: '阳性' },
      { value: '阴性', label: '阴性' },
    ],
  },
  {
    title: '年龄',
    key: 'age',
    multi: false,
    options: [
      { value: '25岁以下', label: '25以下' },
      { value: '20-28岁', label: '20-28' },
      { value: '25-30岁', label: '25-30' },
      { value: '30岁以下', label: '30以下' },
    ],
  },
  {
    title: '籍贯',
    key: 'hometown',
    multi: true,
    options: ['四川', '重庆', '广东', '湖南', '湖北', '河南', '浙江', '江苏', '山东', '云南', '贵州', '陕西'].map(
      (v) => ({ value: v, label: v }),
    ),
  },
  {
    title: '民族',
    key: 'ethnicity',
    multi: true,
    options: [
      { value: '汉', label: '汉' },
      { value: '回', label: '回' },
      { value: '藏', label: '藏' },
      { value: '蒙', label: '蒙' },
      { value: '维', label: '维' },
      { value: '苗', label: '苗' },
      { value: '壮', label: '壮' },
    ],
  },
  {
    title: '体型',
    key: 'figure',
    multi: true,
    options: [
      { value: '一般', label: '一般' },
      { value: '瘦弱', label: '瘦弱' },
      { value: '强壮', label: '强壮' },
      { value: '肥胖', label: '肥胖' },
    ],
  },
  {
    title: '脸型',
    key: 'face_shape',
    multi: true,
    options: ['长方', '长', '椭圆', '瓜子'].map((v) => ({ value: v, label: v })),
  },
  {
    title: '眼皮',
    key: 'eyelid',
    multi: true,
    options: [
      { value: '单', label: '单' },
      { value: '双', label: '双' },
    ],
  },
  {
    title: '肤色',
    key: 'skin_color',
    multi: true,
    options: [
      { value: '偏白', label: '偏白' },
      { value: '一般', label: '一般' },
      { value: '偏黑', label: '偏黑' },
    ],
  },
  {
    title: '唇型',
    key: 'lip_shape',
    multi: true,
    options: [
      { value: '一般', label: '一般' },
      { value: '厚', label: '厚' },
      { value: '薄', label: '薄' },
    ],
  },
  {
    title: '性格',
    key: 'personality',
    multi: true,
    options: [
      { value: '内向', label: '内向' },
      { value: '外向', label: '外向' },
    ],
  },
  {
    title: '职业',
    key: 'occupation',
    multi: true,
    options: [
      { value: '医', label: '医疗' },
      { value: '工程', label: '工程' },
      { value: '教', label: '教育' },
      { value: '金融', label: '金融' },
      { value: '学生', label: '学生' },
      { value: '科研', label: '科研' },
    ],
  },
  {
    title: '星座',
    key: 'constellation',
    multi: true,
    options: [
      '白羊座',
      '金牛座',
      '双子座',
      '巨蟹座',
      '狮子座',
      '处女座',
      '天秤座',
      '天蝎座',
      '射手座',
      '摩羯座',
      '水瓶座',
      '双鱼座',
    ].map((v) => ({ value: v, label: v.replace('座', '') })),
  },
]

function toggleMulti(list: string[], value: string) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

function countSelected(filters: FilterState): number {
  let n = 0
  for (const [k, v] of Object.entries(filters)) {
    if (Array.isArray(v)) n += v.length
    else if (v) n += 1
    void k
  }
  return n
}

function selectedChips(filters: FilterState): { key: keyof FilterState; label: string; value: string }[] {
  const out: { key: keyof FilterState; label: string; value: string }[] = []
  for (const g of CHIP_GROUPS) {
    const cur = filters[g.key]
    if (g.multi) {
      for (const v of cur as string[]) {
        const opt = g.options.find((o) => o.value === v)
        out.push({ key: g.key, label: `${g.title} ${opt?.label || v}`, value: v })
      }
    } else if (cur) {
      const opt = g.options.find((o) => o.value === cur)
      out.push({ key: g.key, label: `${g.title} ${opt?.label || cur}`, value: String(cur) })
    }
  }
  return out
}

function removeChip(filters: FilterState, key: keyof FilterState, value: string): FilterState {
  const cur = filters[key]
  if (Array.isArray(cur)) {
    return { ...filters, [key]: cur.filter((v) => v !== value) }
  }
  return { ...filters, [key]: '' }
}

export function FilterPanel({
  collapsed,
  onToggle,
  filters,
  setFilters,
  priority,
  setPriority,
  onSearch,
  onClear,
  searching,
  drawer = false,
  className = '',
}: Props) {
  const [tab, setTab] = useState<'cond' | 'prio'>('cond')
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  const selectedCount = useMemo(() => countSelected(filters), [filters])
  const chips = useMemo(() => selectedChips(filters), [filters])
  const list = priority.length ? priority : DEFAULT_PRIORITY

  function renderGroup(group: ChipGroup) {
    const current = filters[group.key]
    return (
      <div key={group.key} className="mb-4">
        <div className="mb-2 text-[11px] font-semibold tracking-wide text-ink-soft/45">{group.title}</div>
        <div className="flex flex-wrap gap-2">
          {group.options.map((opt) => {
            const active = group.multi
              ? (current as string[]).includes(opt.value)
              : current === opt.value
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  if (group.multi) {
                    setFilters({
                      ...filters,
                      [group.key]: toggleMulti(current as string[], opt.value),
                    })
                  } else {
                    setFilters({
                      ...filters,
                      [group.key]: current === opt.value ? '' : opt.value,
                    })
                  }
                }}
                className={`min-h-[32px] rounded-lg border px-3 py-1.5 text-[12px] font-medium transition ${
                  active
                    ? 'border-teal/45 bg-mist/90 text-teal-deep'
                    : 'border-line/80 bg-white text-ink-soft/65 hover:border-teal/25 hover:text-ink'
                }`}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      </div>
    )
  }

  const body = (
    <>
      <div className={`flex shrink-0 items-center justify-between border-b border-line/60 bg-white/70 px-4 backdrop-blur-sm ${WORKBENCH_HEADER_HEIGHT_CLASS}`}>
        <div className="flex gap-4">
          <button
            type="button"
            className={`relative pb-0.5 text-[13px] font-semibold transition ${
              tab === 'cond' ? 'text-teal-deep' : 'text-ink-soft/40 hover:text-ink-soft/70'
            }`}
            onClick={() => setTab('cond')}
          >
            条件
            {tab === 'cond' && <span className="absolute inset-x-0 -bottom-2.5 h-0.5 rounded bg-teal" />}
          </button>
          <button
            type="button"
            className={`relative pb-0.5 text-[13px] font-semibold transition ${
              tab === 'prio' ? 'text-teal-deep' : 'text-ink-soft/40 hover:text-ink-soft/70'
            }`}
            onClick={() => setTab('prio')}
          >
            优先级
            {tab === 'prio' && <span className="absolute inset-x-0 -bottom-2.5 h-0.5 rounded bg-teal" />}
          </button>
        </div>
        {!drawer && (
          <button
            type="button"
            onClick={onToggle}
            className="rounded-md p-1.5 text-ink-soft/45 transition hover:bg-sand hover:text-ink-soft"
            title="收起筛选"
          >
            <i className="ri-side-bar-line text-base" />
          </button>
        )}
        {drawer && (
          <button type="button" onClick={onToggle} className="rounded-md p-1.5 text-ink-soft/50">
            <i className="ri-close-line text-lg" />
          </button>
        )}
      </div>

      {tab === 'cond' && selectedCount > 0 && (
        <div className="shrink-0 border-b border-line/50 bg-sand/50 px-4 py-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] font-medium text-ink-soft/55">已选 {selectedCount} 项</span>
            <button type="button" onClick={onClear} className="text-[11px] text-teal-deep hover:underline">
              全部清空
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {chips.slice(0, 8).map((c) => (
              <button
                key={`${c.key}-${c.value}`}
                type="button"
                onClick={() => setFilters(removeChip(filters, c.key, c.value))}
                className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-1 text-[11px] text-ink-soft/75 ring-1 ring-line/80"
                title="移除"
              >
                {c.label}
                <i className="ri-close-line text-[12px] text-ink-soft/40" />
              </button>
            ))}
            {chips.length > 8 && (
              <span className="px-1 text-[11px] text-ink-soft/40">+{chips.length - 8}</span>
            )}
          </div>
        </div>
      )}

      <div className="scroll-y min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {tab === 'cond' ? (
          <div>{CHIP_GROUPS.map(renderGroup)}</div>
        ) : (
          <div>
            <p className="mb-3 text-[12px] leading-relaxed text-ink-soft/50">
              拖拽调整重要程度。越靠上，匹配时越优先被满足。
            </p>
            <div className="relative space-y-1.5 before:absolute before:top-3 before:bottom-3 before:left-[15px] before:w-px before:bg-mist">
              {list.map((item, index) => (
                <div
                  key={item}
                  draggable
                  onDragStart={() => setDragIndex(index)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => {
                    if (dragIndex === null || dragIndex === index) return
                    const next = [...list]
                    const [moved] = next.splice(dragIndex, 1)
                    next.splice(index, 0, moved)
                    setPriority(next)
                    setDragIndex(null)
                  }}
                  className="relative flex cursor-grab items-center gap-3 rounded-xl bg-white px-2.5 py-2.5 ring-1 ring-line/70 active:cursor-grabbing"
                >
                  <span
                    className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                      index < 3 ? 'bg-teal-deep text-white' : 'bg-mist text-teal-deep'
                    }`}
                  >
                    {index + 1}
                  </span>
                  <span className="flex-1 text-[13px] font-medium text-ink-soft/80">{item}</span>
                  <i className="ri-draggable text-ink-soft/30" />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="sticky bottom-0 shrink-0 border-t border-line/70 bg-white/95 px-4 py-3 backdrop-blur">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClear}
            className="h-10 flex-1 rounded-lg border border-line text-[12px] font-medium text-ink-soft/70 transition hover:bg-sand"
          >
            清空
          </button>
          <button
            type="button"
            disabled={searching}
            onClick={onSearch}
            className="h-10 flex-[1.4] rounded-lg bg-teal-deep text-[12px] font-semibold text-white transition hover:bg-ink disabled:opacity-55"
          >
            {searching ? '匹配中…' : '搜索匹配'}
          </button>
        </div>
      </div>
    </>
  )

  if (!drawer && collapsed) {
    return (
      <aside
        className={`panel-rail hidden w-12 shrink-0 flex-col items-center border-r border-line/80 bg-white/95 py-3 lg:flex ${className}`}
      >
        <button
          type="button"
          onClick={onToggle}
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-mist text-teal-deep transition hover:bg-teal-deep hover:text-white"
          title="展开筛选"
        >
          <i className="ri-filter-3-line" />
        </button>
        {selectedCount > 0 && (
          <span className="mt-2 flex h-5 min-w-5 items-center justify-center rounded-full bg-teal-deep px-1 text-[10px] font-bold text-white">
            {selectedCount}
          </span>
        )}
        <div className="mt-5 text-[10px] tracking-[0.2em] text-ink-soft/35 [writing-mode:vertical-rl]">
          筛选
        </div>
      </aside>
    )
  }

  if (drawer) {
    return <div className={`flex h-full flex-col bg-white ${className}`}>{body}</div>
  }

  return (
    <aside
      className={`panel-rail hidden w-[288px] shrink-0 flex-col border-r border-line/80 bg-white/95 lg:flex ${className}`}
    >
      {body}
    </aside>
  )
}
