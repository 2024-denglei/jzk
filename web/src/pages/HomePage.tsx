import { Link } from 'react-router-dom'

export function HomePage() {
  return (
    <div className="min-h-full">
      <section className="relative flex min-h-[calc(100vh-3.5rem)] items-end overflow-hidden bg-teal-deep text-white md:items-center">
        <div className="animate-drift absolute inset-0 bg-[radial-gradient(ellipse_at_70%_35%,rgba(216,236,239,0.28),transparent_55%),linear-gradient(160deg,#0b3d4a_0%,#0f6b6d_48%,#1a8a7a_100%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(10,36,48,0.72),transparent_45%)]" />

        <div className="relative z-10 mx-auto w-full max-w-5xl px-6 pb-16 pt-20 md:pb-24 md:pt-10">
          <div className="animate-fade-up font-display text-sm tracking-[0.28em] text-mist/90">智育匹配</div>
          <h1 className="animate-fade-up-delay font-display mt-4 max-w-2xl text-4xl font-bold leading-tight md:text-6xl">
            以科学与温度
            <br />
            遇见合适的可能
          </h1>
          <p className="animate-fade-up-delay mt-5 max-w-xl text-sm leading-relaxed text-white/80 md:text-base">
            智能筛选与对话匹配，帮助您在可信档案中清晰比较、从容选择。
          </p>
          <div className="animate-fade-up-delay mt-8 flex flex-wrap gap-3">
            <Link
              to="/donors"
              className="rounded-full bg-white px-6 py-3 text-sm font-semibold text-teal-deep shadow-lg shadow-black/10 transition hover:-translate-y-0.5"
            >
              查找捐献者
            </Link>
            <Link
              to="/about"
              className="rounded-full border border-white/35 px-6 py-3 text-sm font-medium text-white/90 backdrop-blur transition hover:bg-white/10"
            >
              了解我们
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-16">
        <h2 className="font-display text-2xl font-bold text-ink">两种方式，同一目标</h2>
        <p className="mt-2 max-w-2xl text-sm text-ink-soft/70">
          既可以用结构化条件精准筛选，也可以用自然语言对话逐步澄清期望——结果都会汇总成清晰的候选人卡片。
        </p>
        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <div className="rounded-3xl border border-line bg-white p-6">
            <div className="mb-3 text-teal">
              <i className="ri-filter-3-line text-2xl" />
            </div>
            <h3 className="text-lg font-semibold">条件筛选</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-soft/70">
              学历、身高、血型、气质等维度自由组合，并支持优先级排序，让更重要的条件被优先满足。
            </p>
          </div>
          <div className="rounded-3xl border border-line bg-white p-6">
            <div className="mb-3 text-teal">
              <i className="ri-chat-smile-3-line text-2xl" />
            </div>
            <h3 className="text-lg font-semibold">智能对话</h3>
            <p className="mt-2 text-sm leading-relaxed text-ink-soft/70">
              像咨询顾问一样描述您的想法，系统边理解边推荐，适合尚在探索偏好的阶段。
            </p>
          </div>
        </div>
        <div className="mt-10">
          <Link to="/donors" className="text-sm font-semibold text-teal-deep underline-offset-4 hover:underline">
            立即开始查找 →
          </Link>
        </div>
      </section>
    </div>
  )
}
