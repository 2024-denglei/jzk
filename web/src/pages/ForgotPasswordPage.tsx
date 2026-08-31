import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { VerificationCodeField } from '../components/VerificationCodeField'
import { api } from '../lib/api'

export function ForgotPasswordPage() {
  const navigate = useNavigate()
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致')
      return
    }
    setLoading(true)
    try {
      await api.post('/api/auth/reset-password', { phone, code, new_password: password })
      navigate('/login', { replace: true, state: { passwordReset: true } })
    } catch (err) {
      setError(err instanceof Error ? err.message : '密码重置失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4 py-10">
      <form onSubmit={onSubmit} className="w-full max-w-md rounded-3xl border border-line bg-white p-8 shadow-sm">
        <h1 className="font-display text-2xl font-bold text-ink">找回密码</h1>
        <p className="mt-1 text-sm text-ink-soft/60">验证注册手机号后设置新密码</p>
        {error && <div className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">{error}</div>}
        <label className="mt-6 block text-xs font-medium text-ink-soft/70">
          注册手机号
          <input
            type="tel"
            required
            autoComplete="tel"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <VerificationCodeField
          phone={phone}
          purpose="reset_password"
          code={code}
          onCodeChange={setCode}
          onError={setError}
        />
        <label className="mt-4 block text-xs font-medium text-ink-soft/70">
          新密码（至少 6 位）
          <input
            type="password"
            required
            minLength={6}
            maxLength={72}
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <label className="mt-4 block text-xs font-medium text-ink-soft/70">
          确认新密码
          <input
            type="password"
            required
            minLength={6}
            maxLength={72}
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            className="mt-1.5 w-full rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="mt-6 w-full rounded-xl bg-teal-deep py-2.5 text-sm font-semibold text-white disabled:opacity-60"
        >
          {loading ? '提交中…' : '重置密码'}
        </button>
        <p className="mt-4 text-center text-xs text-ink-soft/60">
          <Link to="/login" className="font-semibold text-teal-deep">返回登录</Link>
        </p>
      </form>
    </div>
  )
}
