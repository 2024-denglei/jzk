import type { Candidate, MatchResultDescriptor } from '../types'

export type MatchPageState = {
  resultSetId: string
  total: number
  pages: Record<number, Candidate[]>
  cursors: Record<number, string | null>
}

export function createMatchPageState(result: MatchResultDescriptor): MatchPageState {
  const cursors: Record<number, string | null> = { 1: null }
  if (result.next_cursor) cursors[2] = result.next_cursor
  return {
    resultSetId: result.result_set_id,
    total: result.total,
    pages: { 1: result.items },
    cursors,
  }
}

export function cacheMatchPage(
  state: MatchPageState,
  page: number,
  items: Candidate[],
  nextCursor?: string | null,
): MatchPageState {
  const cursors = { ...state.cursors }
  if (nextCursor) cursors[page + 1] = nextCursor
  return {
    ...state,
    pages: { ...state.pages, [page]: items },
    cursors,
  }
}
