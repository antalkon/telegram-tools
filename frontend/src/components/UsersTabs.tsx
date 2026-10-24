import clsx from 'clsx'
import { Radar, Users } from 'lucide-react'
import { NavLink } from 'react-router-dom'

/** Switch between the people list and the channels found through them. */
export function UsersTabs() {
  const tab = (to: string, label: string, Icon: typeof Users) => (
    <NavLink
      to={to}
      end
      className={({ isActive }) => clsx(
        'flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-[13px] font-medium transition-colors duration-150',
        isActive ? 'bg-elevated text-fg shadow-sm' : 'text-fg-muted hover:text-fg',
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </NavLink>
  )
  return (
    <nav aria-label="Раздел пользователей" className="inline-flex rounded-[10px] border border-line bg-surface p-1">
      {tab('/users', 'Люди', Users)}
      {tab('/users/channels', 'Каналы пользователей', Radar)}
    </nav>
  )
}
