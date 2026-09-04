export const ADMIN_PERMISSIONS = {
  dashboardView: 'dashboard:view',
  usersView: 'users:view',
  usersControl: 'users:control',
  usersControlRequest: 'users:control_request',
  donorsView: 'donors:view',
  donorsWrite: 'donors:write',
  donorsWriteRequest: 'donors:write_request',
  donorsImport: 'donors:import',
  requestsViewOwn: 'requests:view_own',
  requestsReview: 'requests:review',
  adminsView: 'admins:view',
  adminsManage: 'admins:manage',
} as const

export function hasAdminPermission(permissions: readonly string[] | undefined, permission: string): boolean {
  return Boolean(permissions?.includes(permission))
}

export function firstAllowedAdminPath(permissions: readonly string[] | undefined): string {
  const candidates = [
    [ADMIN_PERMISSIONS.dashboardView, '/admin/dashboard'],
    [ADMIN_PERMISSIONS.usersView, '/admin/users'],
    [ADMIN_PERMISSIONS.donorsView, '/admin/donors'],
    [ADMIN_PERMISSIONS.requestsViewOwn, '/admin/requests/mine'],
    [ADMIN_PERMISSIONS.adminsView, '/admin/admins'],
  ]
  return candidates.find(([permission]) => hasAdminPermission(permissions, permission))?.[1] || '/admin/forbidden'
}
