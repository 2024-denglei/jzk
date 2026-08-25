import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const NAV = [
  { to: '/', label: '首页', end: true },
  { to: '/donors', label: '查找捐献者' },
  { to: '/about', label: '关于我们' },
  { to: '/user', label: '用户中心' },
]

export function AppLayout() {
  const { user } = useAuth()
  const location = useLocation()
  const isWorkbench = location.pathname === '/donors' || /^\/donors\/[^/]+$/.test(location.pathname)
  const onDonors = isWorkbench

  return (
    <div className={`flex min-h-full flex-col ${isWorkbench ? 'h-full overflow-hidden' : ''}`}>
      <header className="z-40 flex h-14 shrink-0 items-center justify-between border-b border-line/70 bg-white/92 px-4 backdrop-blur-md md:px-7">
        <NavLink to="/" className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-deep text-white">
            <i className="ri-heart-pulse-line text-base" />
          </div>
          <div className="leading-tight">
            <div className="font-display text-[15px] font-bold tracking-wide text-ink">智育匹配</div>
            <div className="text-[10px] tracking-wider text-ink-soft/45 uppercase">Matching Studio</div>
          </div>
        </NavLink>

        <nav className="hidden items-center gap-0.5 md:flex">
          {NAV.map((item) => {
            const donorsActive = item.to === '/donors' && onDonors
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => {
                  const active = isActive || donorsActive
                  return `relative rounded-md px-3.5 py-2 text-[13px] font-medium transition-colors ${
                    active ? 'text-teal-deep' : 'text-ink-soft/55 hover:text-ink'
                  }`
                }}
              >
                {({ isActive }) => {
                  const active = isActive || donorsActive
                  return (
                    <>
                      {item.label}
                      <span
                        className={`absolute inset-x-3.5 -bottom-0.5 h-[2px] rounded-full transition-opacity ${
                          active ? 'bg-teal opacity-100' : 'opacity-0'
                        }`}
                      />
                    </>
                  )
                }}
              </NavLink>
            )
          })}
        </nav>

        <div className="flex items-center gap-2">
          {user ? (
            <NavLink
              to="/user"
              className="rounded-md border border-line/80 px-3 py-1.5 text-xs font-medium text-ink-soft/70 transition hover:border-teal/30 hover:text-teal-deep"
            >
              {user.nickname}
            </NavLink>
          ) : (
            <NavLink
              to="/login"
              className="rounded-md border border-teal-deep/20 bg-teal-deep/95 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-teal-deep"
            >
              登录
            </NavLink>
          )}
        </div>
      </header>

      <nav className="flex gap-1 overflow-x-auto border-b border-line bg-white px-2 py-1 md:hidden">
        {NAV.map((item) => {
          const donorsActive = item.to === '/donors' && onDonors
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `shrink-0 rounded-md px-3 py-2 text-xs font-medium ${
                  isActive || donorsActive ? 'bg-mist/80 text-teal-deep' : 'text-ink-soft/60'
                }`
              }
            >
              {item.label}
            </NavLink>
          )
        })}
      </nav>

      <main className={`min-h-0 flex-1 ${isWorkbench ? 'overflow-hidden' : ''}`}>
        <Outlet />
      </main>
    </div>
  )
}
