import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import type { AdminInfo } from './types'
import { ADMIN_PERMISSIONS, hasAdminPermission } from './adminPermissions'

const NAV_SECTIONS = [
  {
    label: '总览',
    icon: 'ri-layout-grid-line',
    items: [{ to: '/admin/dashboard', label: '工作台', icon: 'ri-dashboard-line', permission: ADMIN_PERMISSIONS.dashboardView }],
  },
  {
    label: '用户管理',
    icon: 'ri-user-settings-line',
    items: [{ to: '/admin/users', label: '用户档案', icon: 'ri-user-3-line', permission: ADMIN_PERMISSIONS.usersView }],
  },
  {
    label: '捐精人管理',
    icon: 'ri-folder-user-line',
    items: [
      { to: '/admin/donors', label: '捐精人档案', icon: 'ri-archive-line', permission: ADMIN_PERMISSIONS.donorsView },
      { to: '/admin/import', label: 'Excel 导入', icon: 'ri-file-upload-line', permission: ADMIN_PERMISSIONS.donorsImport },
    ],
  },
  {
    label: '管理员中心',
    icon: 'ri-admin-line',
    items: [
      { to: '/admin/requests/mine', label: '我的申请', icon: 'ri-time-line', permission: ADMIN_PERMISSIONS.requestsViewOwn },
      { to: '/admin/admins', label: '管理员信息', icon: 'ri-shield-user-line', permission: ADMIN_PERMISSIONS.adminsView },
      { to: '/admin/requests/review', label: '操作审批', icon: 'ri-task-line', permission: ADMIN_PERMISSIONS.requestsReview },
    ],
  },
]

export function AdminShell({ admin, children, onLogout }: { admin: AdminInfo; children: ReactNode; onLogout: () => void }) {
  const navSections = NAV_SECTIONS
    .map((section) => ({ ...section, items: section.items.filter((item) => hasAdminPermission(admin.permissions, item.permission)) }))
    .filter((section) => section.items.length)
  const navItems = navSections.flatMap((section) => section.items)
  return (
    <div className="min-h-screen bg-[#f3f6fa] text-[#132238]">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[218px] flex-col bg-[#142641] text-white lg:flex">
        <div className="flex h-[62px] items-center gap-3 border-b border-white/8 px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1677ff] text-sm font-bold">智</div>
          <div>
            <div className="text-[15px] font-semibold tracking-wide">智育管理平台</div>
            <div className="mt-0.5 text-[10px] text-white/45">运营管理后台</div>
          </div>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {navSections.map((section, index) => (
            <section key={section.label} className={index ? 'mt-5' : ''}>
              <div className="flex items-center gap-2 px-2.5 pb-2 text-[13px] font-semibold text-white/88">
                <i className={`${section.icon} text-[15px] text-[#72aefc]`} />
                <span>{section.label}</span>
              </div>
              <div className="ml-[17px] border-l border-white/10 pl-2">
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `mb-1 flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[12px] transition ${
                        isActive
                          ? 'bg-[#245b9f] font-medium text-white shadow-[inset_3px_0_0_#69a9ff]'
                          : 'text-white/58 hover:bg-white/7 hover:text-white/90'
                      }`
                    }
                  >
                    <i className={`${item.icon} text-[14px]`} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </section>
          ))}
        </nav>
      </aside>

      <div className="lg:pl-[218px]">
        <header className="sticky top-0 z-30 flex h-[62px] items-center justify-between border-b border-[#dbe3ee] bg-white px-4 lg:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#1677ff] text-sm font-bold text-white">智</div>
            <span className="text-sm font-semibold">智育管理平台</span>
          </div>
          <nav className="hidden items-center gap-1 overflow-x-auto lg:flex">
            <span className="text-xs text-[#7b8798]">管理后台</span>
            <span className="text-xs text-[#aab3c0]">/</span>
            <span className="text-xs font-medium text-[#27364d]">运营工作台</span>
          </nav>
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1d4f91] text-xs font-semibold text-white">
              {(admin.display_name || admin.username).slice(0, 1)}
            </div>
            <div className="hidden text-right sm:block">
              <div className="text-xs font-medium">{admin.display_name || admin.username}</div>
              <div className="text-[10px] text-[#8792a2]">{admin.role === 'super_admin' ? '超级管理员' : '普通管理员'}</div>
            </div>
            <button onClick={onLogout} className="text-xs text-[#667389] hover:text-[#1677ff]">退出</button>
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b border-[#dbe3ee] bg-white px-2 py-1.5 lg:hidden">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `shrink-0 rounded-md px-3 py-2 text-xs ${isActive ? 'bg-[#e8f2ff] font-medium text-[#1677ff]' : 'text-[#667389]'}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <main className="min-h-[calc(100vh-62px)] p-4 lg:p-6">{children}</main>
      </div>
    </div>
  )
}
