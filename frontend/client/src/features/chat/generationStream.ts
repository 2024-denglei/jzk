import { ApiError, authFetch, expireUserSession, extractApiError } from '../../lib/api.ts'
import type { GenerationStatus } from '../../types'
import { chatApi } from './chatApi.ts'
import { isTerminalGeneration } from './chatState.ts'

export interface GenerationEvent {
  id: string | null
  event: string
  data: Record<string, unknown>
}

export type GenerationProgressStage =
  | 'connecting'
  | 'queued'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'summarizing'
  | 'responding'
  | 'reconnecting'
  | 'stopping'
  | 'stopped'
  | 'failed'

export type GenerationProgress = {
  stage: GenerationProgressStage
  detail?: string
  count?: number
}

export function generationProgressFromEvent(event: GenerationEvent): GenerationProgress | null {
  if (event.event === 'token') return { stage: 'responding' }
  if (event.event === 'match_ready') {
    const count = Number(event.data.total)
    return { stage: 'tool_result', count: Number.isFinite(count) ? count : undefined }
  }
  if (event.event === 'agent_stage') {
    const stage = String(event.data.stage || '')
    if (stage === 'thinking' || stage === 'tool_call' || stage === 'summarizing') {
      return { stage, detail: typeof event.data.tool_name === 'string' ? event.data.tool_name : undefined }
    }
  }
  if (event.event === 'generation_status') {
    if (event.data.cancel_requested) return { stage: 'stopping' }
    return { stage: String(event.data.status) === 'queued' ? 'queued' : 'thinking' }
  }
  if (event.event === 'stopped') return { stage: 'stopped' }
  if (event.event === 'failed') return { stage: 'failed' }
  return null
}

export function createSseParser(onEvent: (event: GenerationEvent) => void) {
  let buffer = ''
  let eventName = 'message'
  let eventId: string | null = null
  let dataLines: string[] = []

  function dispatch() {
    if (!dataLines.length) return
    const raw = dataLines.join('\n')
    let data: Record<string, unknown> = {}
    try {
      const parsed: unknown = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        data = parsed as Record<string, unknown>
      }
    } catch {
      data = { text: raw }
    }
    onEvent({ id: eventId, event: eventName, data })
    eventName = 'message'
    dataLines = []
  }

  function line(value: string) {
    const text = value.endsWith('\r') ? value.slice(0, -1) : value
    if (!text) {
      dispatch()
      return
    }
    if (text.startsWith(':')) return
    const separator = text.indexOf(':')
    const field = separator < 0 ? text : text.slice(0, separator)
    const rawValue = separator < 0 ? '' : text.slice(separator + 1)
    const fieldValue = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue
    if (field === 'event') eventName = fieldValue
    else if (field === 'id') eventId = fieldValue
    else if (field === 'data') dataLines.push(fieldValue)
  }

  return {
    push(chunk: string) {
      buffer += chunk
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const value of lines) line(value)
    },
    finish() {
      if (buffer) line(buffer)
      buffer = ''
      dispatch()
    },
  }
}

async function consumeResponse(
  response: Response,
  onEvent: (event: GenerationEvent) => void,
  signal: AbortSignal,
) {
  if (!response.body) throw new Error('生成事件流没有响应正文')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSseParser(onEvent)
  while (!signal.aborted) {
    const { value, done } = await reader.read()
    if (done) break
    parser.push(decoder.decode(value, { stream: true }))
  }
  parser.push(decoder.decode())
  parser.finish()
}

function waitForRetry(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timer = window.setTimeout(resolve, milliseconds)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }, { once: true })
  })
}

export async function followGeneration(
  generationId: string,
  options: {
    signal: AbortSignal
    after?: string | null
    onEvent: (event: GenerationEvent) => void
    onReconnect?: (attempt: number) => void
  },
): Promise<GenerationStatus> {
  let after = options.after || null
  let attempt = 0
  let terminal: GenerationStatus | null = null

  while (!options.signal.aborted) {
    try {
      const query = after ? `?after=${encodeURIComponent(after)}` : ''
      const response = await authFetch(
        `/api/generations/${encodeURIComponent(generationId)}/events${query}`,
        { headers: { Accept: 'text/event-stream' }, signal: options.signal },
      )
      if (response.status === 401) expireUserSession('登录已失效，请重新登录')
      if (!response.ok) {
        const body: unknown = await response.json().catch(() => ({}))
        throw extractApiError(body, response.status)
      }
      await consumeResponse(response, (event) => {
        if (event.id) after = event.id
        const status = String(event.data.status || event.event) as GenerationStatus
        if (isTerminalGeneration(status)) terminal = status
        options.onEvent(event)
      }, options.signal)
      if (terminal) return terminal
      if (options.signal.aborted) throw new DOMException('Aborted', 'AbortError')

      const current = await chatApi.generation(generationId)
      if (isTerminalGeneration(current.status)) {
        options.onEvent({ id: after, event: current.status, data: { status: current.status } })
        return current.status
      }
    } catch (error) {
      if (options.signal.aborted || (error instanceof Error && error.name === 'AbortError')) throw error
      if (error instanceof ApiError && [400, 401, 403, 404].includes(error.status)) throw error
    }
    attempt += 1
    options.onReconnect?.(attempt)
    await waitForRetry(Math.min(500 * 2 ** Math.min(attempt, 4), 8_000), options.signal)
  }
  throw new DOMException('Aborted', 'AbortError')
}
