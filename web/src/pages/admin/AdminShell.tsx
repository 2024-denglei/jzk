import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import type { AdminInfo } from './types'

const NAV = [
  { to: '/admin/dashboard', label: '工作台', icon: 'ri-dashboard-line' },
  { to: '/admin/users', label: '用户档案', icon: 'ri-user-3-line', group: '用户管理' },
  { to: '/admin/donors', label: '档案列表', icon: 'ri-archive-line', group: '捐献者管理' },
  { to: '/admin/import', label: 'Excel 导入', icon: 'ri-file-upload-line' },
  { to: '/admin/audit', label: '操作审计', icon: 'ri-history-line', group: '数据中心' },
]

export function AdminShell({ admin, children, onLogout }: { admin: AdminInfo; children: ReactNode; onLogout: () => void }) {
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
          {NAV.map((item, index) => (
            <div key={item.to}>
              {item.group ? <div className={`px-3 pb-2 text-[11px] tracking-widest text-white/35 ${index ? 'pt-5' : ''}`}>{item.group}</div> : null}
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  `mb-1 flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] transition ${
                    isActive ? 'bg-[#1d4f91] font-medium text-white' : 'text-white/72 hover:bg-white/7 hover:text-white'
                  }`
                }
              >
                <i className={`${item.icon} text-base`} />
                {item.label}
              </NavLink>
            </div>
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
              <div className="text-[10px] text-[#8792a2]">系统管理员</div>
            </div>
            <button onClick={onLogout} className="text-xs text-[#667389] hover:text-[#1677ff]">退出</button>
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto border-b border-[#dbe3ee] bg-white px-2 py-1.5 lg:hidden">
          {NAV.map((item) => (
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
