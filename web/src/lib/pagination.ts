const VISIBLE_PAGE_COUNT = 6

/**
 * 首页和尾页由独立按钮承载，数字页码随当前页滑动并保持当前页可见。
 */
export function getPaginationPages(totalPages: number, currentPage: number): number[] {
  const normalizedTotal = Math.max(1, Math.floor(totalPages))
  const innerPageCount = Math.max(0, normalizedTotal - 2)

  if (innerPageCount <= VISIBLE_PAGE_COUNT) {
    return Array.from({ length: innerPageCount }, (_, index) => index + 2)
  }

  const normalizedCurrent = Math.min(normalizedTotal, Math.max(1, Math.floor(currentPage)))
  const maxStart = normalizedTotal - VISIBLE_PAGE_COUNT
  const start = Math.max(2, Math.min(normalizedCurrent - 2, maxStart))

  return Array.from({ length: VISIBLE_PAGE_COUNT }, (_, index) => start + index)
}
