import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { GitCompareArrows, History, Layers, LayoutDashboard, LogOut, Menu, Network, Settings as SettingsIcon, Smartphone, TextSearch, Users, X } from 'lucide-react'
import { NotificationBell } from '../components/NotificationBell'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { IconButton } from '../components/ui'
import { api } from '../lib/api'
import { TOOLS } from '../lib/tools'

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="9" fill="#2AABEE" />
        <path
          d="M7.5 15.6l14.2-5.5c.7-.2 1.2.2 1 1.1l-2.4 11.4c-.2.8-.7 1-1.4.6l-3.6-2.7-1.8 1.7c-.2.2-.4.4-.8.4l.3-3.7 6.7-6c.3-.3-.1-.4-.4-.2l-8.3 5.2-3.6-1.1c-.8-.2-.8-.8.1-1.2z"
          fill="#fff"
        />
      </svg>
      <div className="leading-tight">
        <div className="font-mono text-[14px] font-semibold tracking-tight">TG Toolkit</div>
        <div className="text-[11px] text-fg-subtle">Telegram-инструменты</div>
      </div>
    </div>
  )
}

function NavItem({ to, icon, children, end, soon }: { to?: string; icon: ReactNode; children: ReactNode; end?: boolean; soon?: boolean }) {
  const base = 'group flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium transition-colors duration-150'
  if (!to || soon)
    return (
      <div className={clsx(base, 'cursor-default text-fg-subtle')} aria-disabled="true">
        <span className="opacity-70">{icon}</span>
        <span className="flex-1 truncate">{children}</span>
        <span className="rounded border border-line px-1 text-[10px] tracking-wide uppercase">скоро</span>
      </div>
    )
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(base, isActive ? 'bg-accent-soft text-fg' : 'text-fg-muted hover:bg-elevated hover:text-fg')
      }
    >
      {({ isActive }) => (
        <>
          <span className={clsx(isActive ? 'text-accent' : 'text-fg-subtle group-hover:text-fg-muted')}>{icon}</span>
          <span className="flex-1 truncate">{children}</span>
        </>
      )}
    </NavLink>
  )
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      qc.clear()
      navigate('/login')
    },
  })
  return (
    <nav aria-label="Основная навигация" className="scrollbar-thin flex h-full flex-col gap-5 overflow-y-auto px-3 py-4" onClick={(e) => (e.target as HTMLElement).closest('a') && onNavigate?.()}>
      <div className="flex items-center justify-between px-2">
        <Logo />
        {!onNavigate && <NotificationBell />}
      </div>
      <div className="flex flex-col gap-0.5">
        <NavItem to="/" end icon={<LayoutDashboard className="size-4" />}>Обзор</NavItem>
        <NavItem to="/users" icon={<Users className="size-4" />}>Пользователи</NavItem>
        <NavItem to="/channels" icon={<Layers className="size-4" />}>Источники</NavItem>
        <NavItem to="/search" icon={<TextSearch className="size-4" />}>Поиск</NavItem>
        <NavItem to="/overlap" icon={<GitCompareArrows className="size-4" />}>Пересечения</NavItem>
        <NavItem to="/graph" icon={<Network className="size-4" />}>Граф связей</NavItem>
      </div>
      <div>
        <div className="px-2.5 pb-2 text-[11px] font-semibold tracking-wider text-fg-subtle uppercase">Сбор данных</div>
        <div className="flex flex-col gap-0.5">
          {TOOLS.filter((t) => !t.path || t.path.startsWith('/tools/') || t.path === '/monitoring').map((t) => (
            <NavItem key={t.id} to={t.path} soon={!t.path} icon={<t.icon className="size-4" />}>
              {t.title}
            </NavItem>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-0.5">
        <NavItem to="/jobs" icon={<History className="size-4" />}>История задач</NavItem>
        <NavItem to="/accounts" icon={<Smartphone className="size-4" />}>Аккаунты</NavItem>
        <NavItem to="/settings" icon={<SettingsIcon className="size-4" />}>Настройки</NavItem>
      </div>
      <div className="mt-auto">
        <button
          onClick={() => logout.mutate()}
          className="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] font-medium text-fg-muted transition-colors duration-150 hover:bg-elevated hover:text-fg"
        >
          <LogOut className="size-4 text-fg-subtle" /> Выйти
        </button>
      </div>
    </nav>
  )
}

export function AppLayout() {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname])

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[256px_1fr]">
      <aside className="sticky top-0 hidden h-dvh border-r border-line bg-surface/60 lg:block">
        <Sidebar />
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-bg/85 px-4 backdrop-blur lg:hidden">
        <Logo />
        <div className="flex items-center gap-1">
          <NotificationBell />
          <IconButton label="Открыть меню" onClick={() => setOpen(true)}>
            <Menu className="size-5" />
          </IconButton>
        </div>
      </header>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} aria-hidden />
          <div className="animate-in absolute inset-y-0 left-0 w-72 border-r border-line bg-surface">
            <IconButton label="Закрыть меню" onClick={() => setOpen(false)} className="absolute top-3 right-3">
              <X className="size-5" />
            </IconButton>
            <Sidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}

      <main className="min-w-0">
        <Suspense fallback={<div className="p-8"><div className="h-40 animate-pulse rounded-[var(--radius-card)] bg-card" /></div>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}

export function PageHeader({ title, description, actions, icon }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="flex min-w-0 items-center gap-3.5">
        {icon && (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-accent/25 bg-accent-soft text-accent">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-tight text-balance">{title}</h1>
          {description && <p className="mt-0.5 text-sm text-fg-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={clsx('mx-auto w-full px-4 py-6 sm:px-6 lg:px-8 lg:py-8', wide ? 'max-w-[1400px]' : 'max-w-5xl')}>{children}</div>
}
