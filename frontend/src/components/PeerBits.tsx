import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { BadgeCheck, Bot, Crown, Download, FileJson, FileSpreadsheet, FileText, Megaphone, ShieldAlert, Skull, Star } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type PeerCard, type Source } from '../lib/api'
import { Avatar } from './Avatar'
import { Button } from './ui'

export function useSources() {
  return useQuery({ queryKey: ['sources'], queryFn: () => api<Source[]>('/sources'), staleTime: 30_000 })
}

export function useSourceMap() {
  const q = useSources()
  return new Map((q.data ?? []).map((s) => [s.id, s]))
}

type FlagPeer = Pick<PeerCard, 'kind' | 'is_verified' | 'is_premium' | 'is_bot' | 'is_scam' | 'is_deleted'> & { starred?: boolean }

export function Flags({ p }: { p: FlagPeer }) {
  return (
    <>
      {p.starred && <Star className="size-3.5 shrink-0 fill-warning text-warning" aria-label="избранное" />}
      {p.kind !== 'user' && <Megaphone className="size-3.5 shrink-0 text-fg-subtle" aria-label="канал" />}
      {p.is_verified && <BadgeCheck className="size-3.5 shrink-0 text-accent" aria-label="верифицирован" />}
      {p.is_premium && <Crown className="size-3.5 shrink-0 text-[#a78bfa]" aria-label="premium" />}
      {p.is_bot && <Bot className="size-3.5 shrink-0 text-fg-muted" aria-label="бот" />}
      {p.is_scam && <ShieldAlert className="size-3.5 shrink-0 text-danger" aria-label="scam" />}
      {p.is_deleted && <Skull className="size-3.5 shrink-0 text-fg-subtle" aria-label="удалён" />}
    </>
  )
}

/** Avatar + name + @username, linking to the global user profile. */
export function PeerLine({ p, size = 32, sub }: { p: PeerCard; size?: number; sub?: ReactNode }) {
  return (
    <Link to={`/users/${p.peer_id}`} className="group flex min-w-0 items-center gap-2.5">
      <Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={size} />
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className={clsx('truncate text-[13.5px] font-medium group-hover:text-accent', p.is_deleted && 'text-fg-subtle')}>{p.name}</span>
          <Flags p={p} />
        </div>
        <div className="truncate text-[12px] text-fg-subtle">{sub ?? (p.username ? `@${p.username}` : `ID ${p.peer_id}`)}</div>
      </div>
    </Link>
  )
}

export function SourceStack({ ids, max = 4 }: { ids: number[]; max?: number }) {
  const map = useSourceMap()
  const shown = ids.slice(0, max)
  return (
    <div className="flex items-center">
      <div className="flex -space-x-1.5">
        {shown.map((id) => {
          const s = map.get(id)
          return (
            <span key={id} title={s?.title} className="rounded-[28%] ring-2 ring-card">
              <Avatar id={id} name={s?.title ?? '?'} photoId={s?.photo_id} size={22} square />
            </span>
          )
        })}
      </div>
      {ids.length > max && <span className="ml-1.5 font-mono text-[11.5px] text-fg-subtle">+{ids.length - max}</span>}
    </div>
  )
}

export function ExportMenu({ href, label = 'Экспорт' }: { href: (fmt: 'xlsx' | 'csv' | 'json') => string; label?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  const items = [
    { fmt: 'xlsx', label: 'Excel (.xlsx)', icon: FileSpreadsheet },
    { fmt: 'csv', label: 'CSV', icon: FileText },
    { fmt: 'json', label: 'JSON', icon: FileJson },
  ] as const
  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" icon={<Download className="size-4" />} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </Button>
      {open && (
        <div role="menu" className="animate-in absolute right-0 z-30 mt-2 w-48 overflow-hidden rounded-xl border border-line-strong bg-elevated p-1 shadow-2xl">
          {items.map((it) => (
            <a
              key={it.fmt}
              role="menuitem"
              href={href(it.fmt)}
              download
              onClick={() => setOpen(false)}
              className="flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-sm text-fg-muted transition-colors hover:bg-muted hover:text-fg"
            >
              <it.icon className="size-4" aria-hidden /> {it.label}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export function Stat({ icon, label, value, sub, tone }: { icon?: ReactNode; label: string; value: ReactNode; sub?: ReactNode; tone?: 'danger' | 'warning' }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-1.5 text-[12px] text-fg-muted">
        {icon && <span className="text-fg-subtle">{icon}</span>}
        {label}
      </div>
      <div className={clsx('mt-1 font-mono text-[22px] font-semibold tracking-tight tabular', tone === 'danger' && 'text-danger', tone === 'warning' && 'text-warning')}>
        {value}
      </div>
      {sub && <div className="text-[12px] text-fg-subtle">{sub}</div>}
    </div>
  )
}

export const pct = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
