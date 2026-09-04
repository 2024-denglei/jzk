import test from 'node:test'
import assert from 'node:assert/strict'
import { ADMIN_PERMISSIONS, firstAllowedAdminPath, hasAdminPermission } from './adminPermissions.ts'

test('checks explicit capabilities returned by the backend', () => {
  const permissions = [ADMIN_PERMISSIONS.usersView, ADMIN_PERMISSIONS.donorsView]
  assert.equal(hasAdminPermission(permissions, ADMIN_PERMISSIONS.usersView), true)
  assert.equal(hasAdminPermission(permissions, ADMIN_PERMISSIONS.usersControl), false)
})

test('selects the first route an administrator may visit', () => {
  assert.equal(firstAllowedAdminPath([ADMIN_PERMISSIONS.donorsView]), '/admin/donors')
  assert.equal(firstAllowedAdminPath([]), '/admin/forbidden')
})

