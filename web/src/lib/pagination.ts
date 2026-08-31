const VISIBLE_EDGE_PAGE_COUNT = 3

/**
 * 分页页码固定展示首页三页和末尾三页；页数较少时展示全部页码。
 */
export function getPaginationPages(totalPages: number): number[] {
  const normalizedTotal = Math.max(1, Math.floor(totalPages))

  if (normalizedTotal <= VISIBLE_EDGE_PAGE_COUNT * 2) {
    return Array.from({ length: normalizedTotal }, (_, index) => index + 1)
  }

  return [
    ...Array.from({ length: VISIBLE_EDGE_PAGE_COUNT }, (_, index) => index + 1),
    ...Array.from(
      { length: VISIBLE_EDGE_PAGE_COUNT },
      (_, index) => normalizedTotal - VISIBLE_EDGE_PAGE_COUNT + index + 1,
    ),
  ]
}
