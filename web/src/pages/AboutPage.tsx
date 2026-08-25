import { Link } from 'react-router-dom'

export function AboutPage() {
  return (
    <div className="min-h-full bg-gradient-to-b from-mist/40 to-sand">
      <div className="mx-auto max-w-3xl px-6 py-14">
        <p className="text-xs font-semibold tracking-[0.2em] text-teal">ABOUT</p>
        <h1 className="font-display mt-3 text-4xl font-bold text-ink">关于智育匹配</h1>
        <p className="mt-4 text-base leading-relaxed text-ink-soft/75">
          我们相信，生育相关的选择应当建立在清晰信息与充分理解之上。智育匹配把结构化筛选与智能对话结合，
          帮助您在保护隐私的前提下，更从容地比较与决策。
        </p>

        <section className="mt-12">
          <h2 className="font-display text-2xl font-bold">我们的使命</h2>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft/75">
            用可信的数据呈现与可解释的匹配逻辑，降低信息不对称，让每一次筛选都更有依据，也更有温度。
          </p>
        </section>

        <section className="mt-10">
          <h2 className="font-display text-2xl font-bold">匹配方式</h2>
          <ul className="mt-4 space-y-3 text-sm leading-relaxed text-ink-soft/75">
            <li>
              <strong className="text-ink">条件筛选：</strong>
              按学历、体征、外貌、气质等维度组合条件，并可拖拽设定优先级；必要时系统会提示已放宽的条件。
            </li>
            <li>
              <strong className="text-ink">智能对话：</strong>
              用自然语言描述期望，助手逐步澄清并推荐候选人，适合探索阶段。
            </li>
          </ul>
        </section>

        <section className="mt-10">
          <h2 className="font-display text-2xl font-bold">数据与隐私</h2>
          <p className="mt-3 text-sm leading-relaxed text-ink-soft/75">
            展示信息经过脱敏处理，仅呈现匹配所需字段。账号数据（收藏、历史、对话摘要与筛选偏好）与捐献档案分离存储，
            仅用于改善您的个人使用体验。请勿将本系统作为唯一医学决策依据，重要决定请咨询专业医疗机构。
          </p>
        </section>

        <section className="mt-10 rounded-3xl bg-teal-deep px-6 py-8 text-white">
          <h2 className="font-display text-2xl font-bold">开始使用</h2>
          <p className="mt-2 text-sm text-white/80">进入查找页，从筛选或对话任意一端开始。注册后可同步收藏与偏好。</p>
          <Link
            to="/donors"
            className="mt-5 inline-flex rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-teal-deep"
          >
            查找捐献者
          </Link>
        </section>
      </div>
    </div>
  )
}
