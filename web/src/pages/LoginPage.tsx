import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { VerificationCodeField } from '../components/VerificationCodeField'
import { useAuth } from '../context/AuthContext'

type LoginMode = 'password' | 'code'

export function LoginPage() {
  const { login, loginWithCode } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = params.get('next') || '/user'
  const [mode, setMode] = useState<LoginMode>('password')
  const [identifier, setIdentifier] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (mode === 'password') await login(identifier, password)
      else await loginWithCode(phone, code)
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
        <p className="mt-1 text-sm text-ink-soft/60">使用密码或手机验证码进入用户中心</p>

        <div className="mt-5 grid grid-cols-2 rounded-xl bg-sand p-1 text-xs font-medium">
          <button
            type="button"
            onClick={() => { setMode('password'); setError('') }}
            className={`rounded-lg px-3 py-2 ${mode === 'password' ? 'bg-white text-teal-deep shadow-sm' : 'text-ink-soft/55'}`}
          >
            密码登录
          </button>
          <button
            type="button"
            onClick={() => { setMode('code'); setError('') }}
            className={`rounded-lg px-3 py-2 ${mode === 'code' ? 'bg-white text-teal-deep shadow-sm' : 'text-ink-soft/55'}`}
          >
            验证码登录
          </button>
        </div>

        {error && <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</div>}

        {mode === 'password' ? (
          <>
            <label className="mt-6 block text-xs font-medium text-ink-soft/70">
              邮箱或手机号
              <input
                type="text"
                required
                autoComplete="username"
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                placeholder="name@example.com / 13800000000"
                className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
              />
            </label>
            <label className="mt-4 block text-xs font-medium text-ink-soft/70">
              密码
              <input
                type="password"
                required
                minLength={6}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
              />
            </label>
            <div className="mt-2 text-right">
              <Link to="/forgot-password" className="text-xs font-medium text-teal-deep">忘记密码？</Link>
            </div>
          </>
        ) : (
          <>
            <label className="mt-6 block text-xs font-medium text-ink-soft/70">
              手机号
              <input
                type="tel"
                required
                autoComplete="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="请输入中国大陆手机号"
                className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
              />
            </label>
            <VerificationCodeField
              phone={phone}
              purpose="login"
              code={code}
              onCodeChange={setCode}
              onError={setError}
            />
          </>
        )}

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
