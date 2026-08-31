const VISIBLE_INNER_EDGE_PAGE_COUNT = 3

/**
 * 首页和尾页由独立按钮承载，数字页码展示紧邻两端的各三页。
 */
export function getPaginationPages(totalPages: number): number[] {
  const normalizedTotal = Math.max(1, Math.floor(totalPages))
  const innerPageCount = Math.max(0, normalizedTotal - 2)

  if (innerPageCount <= VISIBLE_INNER_EDGE_PAGE_COUNT * 2) {
    return Array.from({ length: innerPageCount }, (_, index) => index + 2)
  }

  return [
    ...Array.from({ length: VISIBLE_INNER_EDGE_PAGE_COUNT }, (_, index) => index + 2),
    ...Array.from(
      { length: VISIBLE_INNER_EDGE_PAGE_COUNT },
      (_, index) => normalizedTotal - VISIBLE_INNER_EDGE_PAGE_COUNT + index,
    ),
  ]
}
