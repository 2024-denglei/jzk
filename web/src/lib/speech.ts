// 浏览器语音：Web Speech API 识别 + SpeechSynthesis 播报
// 与旧版 HTML 原型一致；后端 voice/ 为云 ASR/TTS 预留

export type SpeechSupport = {
  recognition: boolean
  synthesis: boolean
}

type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null
  onerror: ((ev: { error: string }) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionEventLike = {
  resultIndex: number
  results: ArrayLike<{
    isFinal: boolean
    0: { transcript: string }
  }>
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionLike
    webkitSpeechRecognition?: new () => SpeechRecognitionLike
  }
}

export function getSpeechSupport(): SpeechSupport {
  if (typeof window === 'undefined') {
    return { recognition: false, synthesis: false }
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  return {
    recognition: Boolean(SR),
    synthesis: 'speechSynthesis' in window,
  }
}

export function speakText(text: string, maxChars = 200) {
  if (!getSpeechSupport().synthesis) return
  const plain = text
    .replace(/\*\*/g, '')
    .replace(/[#>`*_~]/g, '')
    .replace(/\n+/g, ' ')
    .trim()
  if (!plain) return
  window.speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(plain.slice(0, maxChars))
  u.lang = 'zh-CN'
  u.rate = 1
  u.pitch = 1
  window.speechSynthesis.speak(u)
}

export function stopSpeaking() {
  if (getSpeechSupport().synthesis) window.speechSynthesis.cancel()
}

export type SpeechInputHandlers = {
  /** 实时展示（已确认片段 + 当前临时结果） */
  onInterim?: (text: string) => void
  /** 静默超时或手动结束后提交整段 */
  onFinal?: (text: string) => void
  onError?: (message: string) => void
  onEnd?: () => void
}

export type SpeechRecognizerOptions = {
  /**
   * 说话停顿多久后视为说完并触发 onFinal。
   * 默认 2200ms；设为 0 则仅手动 stop/abort 才提交。
   */
  silenceMs?: number
}

export type SpeechRecognizerController = {
  start: () => void
  /** 手动结束：立刻提交当前累计文本 */
  stop: () => void
  abort: () => void
}

/**
 * 连续聆听：短暂停顿不会立刻提交；累计最终结果，
 * 静默一段时间后再 onFinal。Chrome 中途 onend 会自动续听。
 */
export function createSpeechRecognizer(
  handlers: SpeechInputHandlers,
  options: SpeechRecognizerOptions = {},
): SpeechRecognizerController | null {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) return null

  const silenceMs = options.silenceMs ?? 2200
  const recognition = new SR()
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true

  let active = false
  let intentionalStop = false
  let committed = ''
  let lastInterim = ''
  let silenceTimer: ReturnType<typeof setTimeout> | null = null

  function clearSilenceTimer() {
    if (silenceTimer != null) {
      clearTimeout(silenceTimer)
      silenceTimer = null
    }
  }

  function displayText(interim = '') {
    return `${committed}${interim}`.replace(/\s+/g, ' ').trim()
  }

  function fullText() {
    return displayText(lastInterim)
  }

  function commitFinal() {
    clearSilenceTimer()
    const text = fullText()
    committed = ''
    lastInterim = ''
    intentionalStop = true
    active = false
    try {
      recognition.stop()
    } catch {
      /* ignore */
    }
    if (text) handlers.onFinal?.(text)
    else handlers.onEnd?.()
  }

  function scheduleSilenceCommit() {
    if (silenceMs <= 0) return
    clearSilenceTimer()
    silenceTimer = setTimeout(() => {
      if (!active) return
      if (!fullText()) return
      commitFinal()
    }, silenceMs)
  }

  recognition.onresult = (e) => {
    if (!active) return
    let interim = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const row = e.results[i]
      const piece = row[0]?.transcript || ''
      if (row.isFinal) {
        committed += piece
        lastInterim = ''
      } else {
        interim += piece
      }
    }
    if (interim) lastInterim = interim
    const shown = displayText(lastInterim)
    if (shown) handlers.onInterim?.(shown)
    if (fullText()) scheduleSilenceCommit()
    else clearSilenceTimer()
  }

  recognition.onerror = (e) => {
    if (e.error === 'not-allowed') {
      active = false
      intentionalStop = true
      clearSilenceTimer()
      handlers.onError?.('请允许麦克风权限后再试。')
      handlers.onEnd?.()
      return
    }
    if (e.error !== 'aborted' && e.error !== 'no-speech') {
      handlers.onError?.(`语音识别出错：${e.error}`)
    }
  }

  recognition.onend = () => {
    clearSilenceTimer()
    // Chrome 在 continuous 下仍常因短停顿结束会话 → 未主动停止则续听
    if (active && !intentionalStop) {
      try {
        recognition.start()
        if (fullText()) scheduleSilenceCommit()
        return
      } catch {
        /* 可能已在启动中，忽略 */
      }
    }
    active = false
    intentionalStop = false
    handlers.onEnd?.()
  }

  return {
    start() {
      intentionalStop = false
      active = true
      committed = ''
      lastInterim = ''
      clearSilenceTimer()
      recognition.start()
    },
    stop() {
      if (!active && !fullText()) {
        intentionalStop = true
        try {
          recognition.stop()
        } catch {
          /* ignore */
        }
        handlers.onEnd?.()
        return
      }
      commitFinal()
    },
    abort() {
      intentionalStop = true
      active = false
      committed = ''
      lastInterim = ''
      clearSilenceTimer()
      try {
        recognition.abort()
      } catch {
        /* ignore */
      }
      handlers.onEnd?.()
    },
  }
}
