import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BadgeCheck, Bot, Crown, Download, FileJson, FileSpreadsheet, FileText, Megaphone, ShieldAlert, Skull, Star } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type PeerCard, type Source } from '../lib/api'
import { Avatar } from './Avatar'
import { useToast } from './Toast'
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

// lists that show stars: refreshed after a change
const STAR_KEYS = ['favorites', 'sources', 'source', 'users', 'user', 'discovery', 'posts']

/** Star toggle for a person, source or channel (all keyed by the marked peer id). */
export function StarButton({ peerId, starred, withLabel, className }: { peerId: number; starred: boolean; withLabel?: boolean; className?: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const save = useMutation({
    mutationFn: (v: boolean) => api(`/favorites/${peerId}`, { method: 'PUT', json: { starred: v } }),
    onSuccess: () => STAR_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
    onError: (e) => toast(e.message, 'error'),
  })
  const on = save.isPending ? !!save.variables : starred  // optimistic while saving
  const label = on ? 'Убрать из избранного' : 'В избранное'
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={withLabel ? undefined : label}
      title={withLabel ? undefined : label}
      onClick={(e) => {
        e.preventDefault()
        e.stopPropagation()
        save.mutate(!on)
      }}
      onKeyDown={(e) => e.stopPropagation()}  // inside clickable table rows: Enter / Space toggle the star only
      className={clsx(
        'flex shrink-0 items-center justify-center gap-1 rounded-full transition-colors duration-150',
        withLabel ? 'h-7 border px-2.5 text-[12.5px]' : 'size-8',
        on ? (withLabel ? 'border-warning/50 bg-warning-soft text-warning' : 'text-warning') : withLabel ? 'border-line text-fg-muted hover:text-fg' : 'text-fg-subtle hover:bg-elevated hover:text-warning',
        className,
      )}
    >
      <Star className={clsx('size-4', on && 'fill-warning')} aria-hidden />
      {withLabel && (on ? 'В избранном' : 'В избранное')}
    </button>
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

type ExportItem = { fmt: string; label: string; icon: typeof FileText }
const TABLE_FORMATS: ExportItem[] = [
  { fmt: 'xlsx', label: 'Excel (.xlsx)', icon: FileSpreadsheet },
  { fmt: 'csv', label: 'CSV', icon: FileText },
  { fmt: 'json', label: 'JSON', icon: FileJson },
]
export const GRAPH_FORMATS: ExportItem[] = [
  { fmt: 'gexf', label: 'GEXF (Gephi)', icon: FileText },
  { fmt: 'graphml', label: 'GraphML (yEd, Maltego)', icon: FileText },
]

export function ExportMenu<F extends string = 'xlsx' | 'csv' | 'json'>({ href, label = 'Экспорт', formats = TABLE_FORMATS, size = 'md' }: {
  href: (fmt: F) => string; label?: string; formats?: ExportItem[]; size?: 'sm' | 'md'
}) {
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
  const items = formats
  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" size={size} icon={<Download className="size-4" />} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </Button>
      {open && (
        <div role="menu" className="animate-in absolute right-0 z-30 mt-2 w-48 overflow-hidden rounded-xl border border-line-strong bg-elevated p-1 shadow-2xl">
          {items.map((it) => (
            <a
              key={it.fmt}
              role="menuitem"
              href={href(it.fmt as F)}
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

/** Text with \x02…\x03 highlight markers from the API, rendered without HTML injection. */
export function Highlighted({ text }: { text: string | null }) {
  if (!text) return <span className="text-fg-subtle italic">медиа без текста</span>
  // eslint-disable-next-line no-control-regex -- the API's highlight markers are control characters
  const parts = text.split(/(\x02[^\x03]*\x03)/)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('\x02') ? <mark key={i} className="rounded-[3px] bg-accent/25 px-0.5 text-fg">{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>,
      )}
    </>
  )
}
