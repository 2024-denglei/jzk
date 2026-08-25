import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import type { DonorInfo } from '../types'

function Row({ label, value }: { label: string; value: string | number | undefined | null }) {
  const v = value === undefined || value === null || value === '' ? '—' : String(value)
  return (
    <div className="flex items-center justify-between border-b border-line/50 py-2.5 text-[13px]">
      <span className="text-ink-soft/45">{label}</span>
      <span className="font-medium text-ink">{v}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line/80 bg-white p-4 md:p-5">
      <h2 className="mb-2 font-display text-base font-bold text-ink md:text-lg">{title}</h2>
      {children}
    </section>
  )
}

function avatarTone(code: string) {
  let hash = 0
  for (let i = 0; i < code.length; i++) hash = (hash * 31 + code.charCodeAt(i)) >>> 0
  const hues = [168, 186, 195, 172, 158]
  return `hsl(${hues[hash % hues.length]} 32% 90%)`
}

type Props = {
  code: string
  onBack: () => void
  onAskAbout: (code: string) => void
}

export function DonorDetailPanel({ code, onBack, onAskAbout }: Props) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [donor, setDonor] = useState<DonorInfo | null>(null)
  const [error, setError] = useState('')
  const [favorited, setFavorited] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!user) {
      setLoading(true)
      setDonor(null)
      setError('')
      setFavorited(false)
      return
    }
    let cancelled = false
    void (async () => {
      setLoading(true)
      setError('')
      setDonor(null)
      try {
        const data = await api.get<{ donor_info: DonorInfo }>(
          `/api/donors/${encodeURIComponent(code)}`,
        )
        if (cancelled) return
        setDonor(data.donor_info)
        if (user) {
          void api.post('/api/user/history', { kind: 'browse', donor_code: data.donor_info.code })
          try {
            const fav = await api.get<{ favorited: boolean }>(
              `/api/user/favorites/${encodeURIComponent(data.donor_info.code)}`,
            )
            if (!cancelled) setFavorited(fav.favorited)
          } catch {
            if (!cancelled) setFavorited(false)
          }
        } else {
          setFavorited(false)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code, user])

  async function toggleFavorite() {
    if (!user) {
      navigate('/login?next=' + encodeURIComponent(`/donors/${code}`))
      return
    }
    if (!donor) return
    if (favorited) {
      await api.delete(`/api/user/favorites/${encodeURIComponent(donor.code)}`)
      setFavorited(false)
    } else {
      await api.post('/api/user/favorites', { donor_code: donor.code })
      setFavorited(true)
    }
  }

  if (loading) {
    return (
      <div className="animate-fade-up space-y-4 p-4 md:p-5">
        <div className="skeleton h-4 w-24" />
        <div className="skeleton h-8 w-40" />
        <div className="skeleton h-40 w-full rounded-2xl" />
        <div className="skeleton h-40 w-full rounded-2xl" />
      </div>
    )
  }

  if (error || !donor) {
    return (
      <div className="flex min-h-[240px] flex-col items-center justify-center p-8 text-center">
        <div className="text-sm text-amber-700">{error || '未找到该捐献者'}</div>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 text-sm font-medium text-teal-deep hover:underline"
        >
          ← 返回列表
        </button>
      </div>
    )
  }

  const letter = (donor.code?.replace(/[^A-Za-z]/g, '')[0] || donor.code?.[0] || 'D').toUpperCase()

  return (
    <div className="animate-fade-up scroll-y h-full overflow-y-auto px-4 py-4 md:px-5 md:py-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full ring-2 ring-white"
            style={{ background: avatarTone(donor.code) }}
          >
            <span className="font-display text-2xl font-bold text-teal-deep/70">{letter}</span>
          </div>
          <div className="min-w-0">
            <h1 className="font-display text-2xl font-bold tracking-wide text-ink md:text-3xl">
              {donor.code}
            </h1>
            <p className="mt-1 text-[13px] text-ink-soft/55">
              {donor.ethnicity || '民族未知'}
              {donor.occupation ? ` · ${donor.occupation}` : ''}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void toggleFavorite()}
            className={`rounded-lg px-3.5 py-2 text-[13px] font-semibold transition ${
              favorited
                ? 'bg-mist text-teal-deep'
                : 'border border-line bg-white text-ink-soft/70 hover:border-teal/30'
            }`}
          >
            <i className={`ri-heart-${favorited ? 'fill' : 'line'} mr-1`} />
            {favorited ? '已收藏' : '收藏'}
          </button>
          <button
            type="button"
            onClick={() => onAskAbout(donor.code)}
            className="rounded-lg bg-teal-deep px-3.5 py-2 text-[13px] font-semibold text-white transition hover:bg-ink"
          >
            在对话中询问
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-2xl space-y-3.5">
        <Section title="基本信息">
          <Row label="学历" value={donor.education} />
          <Row label="职业" value={donor.occupation} />
          <Row label="年龄" value={donor.age ? `${donor.age}岁` : '—'} />
          <Row label="血型" value={donor.blood_type ? `${donor.blood_type}型` : '—'} />
          <Row label="Rh血型" value={donor.rh_blood} />
          <Row label="民族" value={donor.ethnicity} />
          <Row label="籍贯" value={donor.hometown} />
          <Row label="星座" value={donor.constellation} />
        </Section>

        <Section title="外貌特征">
          <Row label="身高" value={donor.height ? `${donor.height}cm` : '—'} />
          <Row label="体重" value={donor.weight ? `${donor.weight}kg` : '—'} />
          <Row label="BMI" value={donor.bmi || '—'} />
          <Row label="体型" value={donor.figure} />
          <Row label="脸型" value={donor.face_shape} />
          <Row label="眼皮" value={donor.eyelid} />
          <Row label="肤色" value={donor.skin_color} />
          <Row label="发色" value={donor.hair_color} />
          <Row label="发型" value={donor.hair_style} />
          <Row label="发量" value={donor.hair_volume} />
          <Row label="唇型" value={donor.lip_shape} />
          <Row label="鼻梁" value={donor.nose_bridge} />
          <Row label="络腮胡" value={donor.beard} />
          <Row label="胡须" value={donor.mustache} />
        </Section>

        <Section title="性格爱好">
          <Row label="性格" value={donor.personality} />
          <Row label="运动健身" value={donor.hobby_sports} />
          <Row label="文化艺术" value={donor.hobby_arts} />
          <Row label="休闲娱乐" value={donor.hobby_leisure} />
          <Row label="旅游度假" value={donor.hobby_travel} />
          <Row label="小说书籍" value={donor.hobby_reading} />
          <Row label="美食饮品" value={donor.hobby_food} />
        </Section>

        <Section title="生活与健康史">
          <Row label="喝酒史" value={donor.drink_history} />
          <Row label="吸烟史" value={donor.smoke_history} />
          <Row label="个人病史" value={donor.personal_disease} />
          <Row label="现病史" value={donor.present_illness} />
          <Row label="既往病史" value={donor.past_illness} />
          <Row label="手术史" value={donor.surgery_history} />
          <Row label="个人生活史" value={donor.personal_life_hist} />
          <Row label="近6月性伴侣数" value={donor.partners_6m} />
          <Row label="性传播疾病史" value={donor.std_history} />
        </Section>

        <Section title="婚育与遗传">
          <Row label="婚育史" value={donor.marital_fertility} />
          <Row label="结婚年龄" value={donor.marriage_age} />
          <Row label="生育子女" value={donor.children_info} />
          <Row label="遗传病史" value={donor.genetic_history} />
          <Row label="染色体病" value={donor.chromosome_disease} />
          <Row label="单基因遗传病" value={donor.monogenic_disease} />
          <Row label="多基因遗传病" value={donor.polygenic_disease} />
          <Row label="近亲婚配" value={donor.consanguinity} />
        </Section>
      </div>
    </div>
  )
}
