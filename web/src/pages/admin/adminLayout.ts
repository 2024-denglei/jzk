/** AdminShell sticky header (62px) + main vertical padding (lg:p-6 → 3rem). */
export const ADMIN_MAIN_CHROME = '62px + 3rem'

/** Fill remaining viewport under the admin chrome so panels can scroll internally. */
export function adminViewportHeightClass(): string {
  return `h-[calc(100vh-${ADMIN_MAIN_CHROME})]`
}

/** Page root that fills the admin viewport and stacks a sticky table panel. */
export function adminPageShellClass(extra = 'gap-4'): string {
  return ['flex min-h-0 flex-col', adminViewportHeightClass(), extra].filter(Boolean).join(' ')
}

/** White card: fixed toolbar + scrollable body + fixed footer (pagination). */
export function adminStickyTableCardClass(extra = ''): string {
  return ['flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-[#dce4ee] bg-white', extra]
    .filter(Boolean)
    .join(' ')
}
