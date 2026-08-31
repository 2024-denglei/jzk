import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ADMIN_MAIN_CHROME,
  adminPageShellClass,
  adminStickyTableCardClass,
  adminViewportHeightClass,
} from './adminLayout.ts'

test('视口高度扣除 AdminShell 顶栏与主区 padding', () => {
  assert.equal(ADMIN_MAIN_CHROME, '62px + 3rem')
  assert.equal(adminViewportHeightClass(), `h-[calc(100vh-${ADMIN_MAIN_CHROME})]`)
})

test('页面壳与表格卡片类名包含内部滚动所需结构', () => {
  const shell = adminPageShellClass()
  assert.match(shell, /\bflex\b/)
  assert.match(shell, /min-h-0/)
  assert.match(shell, /flex-col/)
  assert.match(shell, /gap-4/)
  assert.match(shell, /h-\[calc\(100vh-62px \+ 3rem\)\]/)

  const card = adminStickyTableCardClass('extra-class')
  assert.match(card, /flex-1/)
  assert.match(card, /overflow-hidden/)
  assert.match(card, /min-h-0/)
  assert.match(card, /extra-class/)
})

test('额外 class 可覆盖默认间距', () => {
  const shell = adminPageShellClass('gap-0')
  assert.match(shell, /gap-0/)
  assert.doesNotMatch(shell, /gap-4/)
})
