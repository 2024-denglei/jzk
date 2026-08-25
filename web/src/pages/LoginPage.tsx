import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/user'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await login(email, password)
      navigate(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-10">
      <form onSubmit={onSubmit} className="w-full max-w-md rounded-3xl border border-line bg-white p-8 shadow-sm">
        <h1 className="font-display text-2xl font-bold text-ink">登录</h1>
        <p className="mt-1 text-sm text-ink-soft/60">使用邮箱进入用户中心</p>
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
          密码
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
          {loading ? '登录中…' : '登录'}
        </button>
        <p className="mt-4 text-center text-xs text-ink-soft/60">
          还没有账号？{' '}
          <Link to={next !== '/user' ? `/register?next=${encodeURIComponent(next)}` : '/register'} className="font-semibold text-teal-deep">
            注册
          </Link>
        </p>
      </form>
    </div>
  )
}
