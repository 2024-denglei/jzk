import type { CandidateSyncOptions } from '../types'

export const DESKTOP_CHAT_MEDIA = '(min-width: 1280px)'

/** 移动端是否在同步对话结果后关闭聊天抽屉。 */
export function shouldCloseMobileChatOnSync(options?: CandidateSyncOptions): boolean {
  return Boolean(options?.focusMiddle)
}

/** 跳转时保留当前 URL 查询参数（如 chatId / branchId）。 */
export function donorsPathWithSearch(pathname: string, searchParams: URLSearchParams): string {
  const query = searchParams.toString()
  return query ? `${pathname}?${query}` : pathname
}
