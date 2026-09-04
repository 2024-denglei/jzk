import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export type CodePurpose = 'register' | 'login' | 'reset_password'

interface Props {
  phone: string
  purpose: CodePurpose
  code: string
  onCodeChange: (code: string) => void
  onError: (message: string) => void
}

interface SendCodeResponse {
  ok: boolean
  expires_in: number
  retry_after: number
  test_code?: string
}

export function VerificationCodeField({ phone, purpose, code, onCodeChange, onError }: Props) {
  const [sending, setSending] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [testCode, setTestCode] = useState('')

  useEffect(() => {
    if (countdown <= 0) return
    const timer = window.setInterval(() => setCountdown((value) => Math.max(0, value - 1)), 1000)
    return () => window.clearInterval(timer)
  }, [countdown])

  async function sendCode() {
    setSending(true)
    setTestCode('')
    onError('')
    try {
      const data = await api.post<SendCodeResponse>('/api/auth/send-code', { phone, purpose })
      setCountdown(data.retry_after)
      setTestCode(data.test_code || '')
    } catch (error) {
      onError(error instanceof Error ? error.message : '验证码发送失败')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="mt-4">
      <label className="block text-xs font-medium text-ink-soft/70">
        手机验证码
        <span className="mt-1.5 flex gap-2">
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            minLength={6}
            maxLength={6}
            pattern="\d{6}"
            value={code}
            onChange={(event) => onCodeChange(event.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="6 位验证码"
            className="min-w-0 flex-1 rounded-xl border border-line px-3 py-2.5 text-sm outline-none focus:border-teal"
          />
          <button
            type="button"
            disabled={!phone.trim() || sending || countdown > 0}
            onClick={() => void sendCode()}
            className="shrink-0 rounded-xl border border-teal/30 px-3 py-2 text-xs font-semibold text-teal-deep disabled:cursor-not-allowed disabled:opacity-50"
          >
            {sending ? '生成中…' : countdown > 0 ? `${countdown} 秒` : '获取验证码'}
          </button>
        </span>
      </label>
      {testCode && (
        <div className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          测试验证码：<span className="font-mono text-sm font-bold tracking-widest">{testCode}</span>
          <span className="ml-2 text-amber-700/70">（测试环境直接展示）</span>
        </div>
      )}
    </div>
  )
}
