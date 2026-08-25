import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/user'
  const [email, setEmail] = useState('')
  const [nickname, setNickname] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await register(email, password, nickname)
      navigate(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-10">
      <form onSubmit={onSubmit} className="w-full max-w-md rounded-3xl border border-line bg-white p-8 shadow-sm">
        <h1 className="font-display text-2xl font-bold text-ink">注册</h1>
        <p className="mt-1 text-sm text-ink-soft/60">创建账号以同步收藏、对话与偏好</p>
        {error && <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</div>}
        <label className="mt-6 block text-xs font-medium text-ink-soft/70">
          邮箱
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <label className="mt-4 block text-xs font-medium text-ink-soft/70">
          昵称（可选）
          <input
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <label className="mt-4 block text-xs font-medium text-ink-soft/70">
          密码（至少 6 位）
          <input
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-xl bg-teal-deep py-2.5 text-sm font-semibold text-white disabled:opacity-60"
        >
          {loading ? '注册中…' : '创建账号'}
        </button>
        <p className="mt-4 text-center text-xs text-ink-soft/60">
          已有账号？{' '}
          <Link to={next !== '/user' ? `/login?next=${encodeURIComponent(next)}` : '/login'} className="font-semibold text-teal-deep">
            登录
          </Link>
        </p>
      </form>
    </div>
  )
}
