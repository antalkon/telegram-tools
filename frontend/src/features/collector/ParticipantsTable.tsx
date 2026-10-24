import { keepPreviousData, useInfiniteQuery } from '@tanstack/react-query'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'
import { ArrowDown, ArrowUp, BadgeCheck, Bot, Copy, Crown, Download, FileJson, FileSpreadsheet, FileText, Megaphone, Search, Shield, ShieldAlert, Skull, Users } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Avatar } from '../../components/Avatar'
import { useToast } from '../../components/Toast'
import { Button, Card, EmptyState, Input, Segmented, Skeleton } from '../../components/ui'
import { api, type Participant } from '../../lib/api'
import { date, num, pluralRu } from '../../lib/format'
import { UserDrawer } from './UserDrawer'

const PAGE = 200
type Kind = 'all' | 'user' | 'channel'
type Presence = 'all' | 'active' | 'silent' | 'admins'
type SortKey = 'comments' | 'posts' | 'first_at' | 'last_at' | 'name'

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

// Columns: rank | user | id | comments | posts | first | last
const GRID = 'grid grid-cols-[minmax(0,1fr)_88px] sm:grid-cols-[44px_minmax(0,1fr)_150px_88px] lg:grid-cols-[44px_minmax(0,1fr)_150px_170px_76px_110px_110px] items-center gap-x-3'

function ExportMenu({ jobId, kind, presence }: { jobId: number; kind: Kind; presence: Presence }) {
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
  ]
  return (
    <div ref={ref} className="relative">
      <Button variant="primary" size="md" icon={<Download className="size-4" />} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Экспорт
      </Button>
      {open && (
        <div role="menu" className="animate-in absolute right-0 z-20 mt-2 w-48 overflow-hidden rounded-xl border border-line-strong bg-elevated p-1 shadow-2xl">
          {items.map((it) => (
            <a
              key={it.fmt}
              role="menuitem"
              href={`/api/jobs/${jobId}/export?format=${it.fmt}&kind=${kind}&presence=${presence}`}
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

function Flags({ p }: { p: Participant }) {
  return (
    <>
      {p.kind !== 'user' && <Megaphone className="size-3.5 shrink-0 text-fg-subtle" aria-label="канал" />}
      {p.is_verified && <BadgeCheck className="size-3.5 shrink-0 text-accent" aria-label="верифицирован" />}
      {p.is_premium && <Crown className="size-3.5 shrink-0 text-[#a78bfa]" aria-label="premium" />}
      {p.is_bot && <Bot className="size-3.5 shrink-0 text-fg-muted" aria-label="бот" />}
      {p.is_scam && <ShieldAlert className="size-3.5 shrink-0 text-danger" aria-label="scam" />}
      {p.is_deleted && <Skull className="size-3.5 shrink-0 text-fg-subtle" aria-label="удалён" />}
      {p.role === 'creator' && <span title="владелец чата"><Shield className="size-3.5 shrink-0 fill-warning/40 text-warning" aria-label="владелец" /></span>}
      {p.role === 'admin' && <span title="админ чата"><Shield className="size-3.5 shrink-0 text-warning" aria-label="админ" /></span>}
    </>
  )
}

export function ParticipantsTable({ jobId, chat }: { jobId: number; chat?: boolean }) {
  const toast = useToast()
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState<Kind>('all')
  const [presence, setPresence] = useState<Presence>('all')
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'comments', desc: true })
  const [selected, setSelected] = useState<Participant | null>(null)
  const q = useDebounced(search)

  const query = useInfiniteQuery({
    queryKey: ['participants', jobId, q, kind, presence, sort],
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    queryFn: ({ pageParam }) =>
      api<{ total: number; items: Participant[] }>(
        `/jobs/${jobId}/participants?` +
          new URLSearchParams({ search: q, kind, presence, sort: `${sort.desc ? '-' : ''}${sort.key}`, offset: String(pageParam), limit: String(PAGE) }),
      ),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((s, p) => s + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })

  const rows = query.data?.pages.flatMap((p) => p.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0
  const maxComments = rows[0] && sort.key === 'comments' && sort.desc ? rows[0].comments : Math.max(1, ...rows.map((r) => r.comments))

  const listRef = useRef<HTMLDivElement>(null)
  const [scrollMargin, setScrollMargin] = useState(0)
  const hasRows = rows.length > 0
  useLayoutEffect(() => {
    if (listRef.current) setScrollMargin(listRef.current.getBoundingClientRect().top + window.scrollY)
  }, [hasRows])
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => 60,
    overscan: 12,
    scrollMargin,
  })
  const items = virtualizer.getVirtualItems()
  const lastIndex = items.at(-1)?.index ?? 0
  useEffect(() => {
    if (lastIndex >= rows.length - 30 && query.hasNextPage && !query.isFetchingNextPage) query.fetchNextPage()
  }, [lastIndex, rows.length, query])

  const toggleSort = (key: SortKey) => setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== 'name' }))
  const SortHead = ({ k, children, className, wideOnly }: { k: SortKey; children: string; className?: string; wideOnly?: boolean }) => {
    const active = sort.key === k
    return (
      <button
        onClick={() => toggleSort(k)}
        aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : 'none'}
        className={clsx('items-center gap-1 transition-colors hover:text-fg', wideOnly ? 'hidden lg:inline-flex' : 'inline-flex', active && 'text-fg', className)}
      >
        {children}
        {active && (sort.desc ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUp className="size-3" aria-hidden />)}
      </button>
    )
  }

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast(`Скопировано: ${text}`, 'success')
    } catch {
      toast('Не удалось скопировать', 'error')
    }
  }

  return (
    <Card className="overflow-visible">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 sm:px-5">
        <div className="mr-auto flex items-center gap-2">
          <h2 className="text-[15px] font-semibold">{chat ? 'Люди чата' : 'Комментаторы'}</h2>
          <span className="rounded-md bg-muted px-1.5 font-mono text-[12px] text-fg-muted tabular">{num(total)}</span>
        </div>
        {chat && (
          <Segmented
            label="Активность"
            value={presence}
            onChange={setPresence}
            options={[
              { value: 'all', label: 'Все' },
              { value: 'active', label: 'Писали' },
              { value: 'silent', label: 'Молчуны', hint: 'Участники без единого сообщения' },
              { value: 'admins', label: 'Админы' },
            ]}
          />
        )}
        <Segmented
          label="Тип"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'all', label: 'Все' },
            { value: 'user', label: 'Люди' },
            { value: 'channel', label: 'Каналы' },
          ]}
        />
        <Input
          aria-label="Поиск по имени, @username или ID"
          placeholder="Имя, @username, ID"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          leading={<Search className="size-4" />}
          className="w-full sm:w-64"
        />
        <ExportMenu jobId={jobId} kind={kind} presence={presence} />
      </div>

      <div className={clsx(GRID, 'sticky top-14 z-10 border-b border-line bg-card/95 px-4 py-2.5 text-[12px] font-medium text-fg-muted backdrop-blur sm:px-5 lg:top-0')} role="row">
        <span className="hidden sm:block">#</span>
        <SortHead k="name">Пользователь</SortHead>
        <span className="hidden sm:block">ID</span>
        <SortHead k="comments" className="justify-self-end lg:justify-self-start">{chat ? 'Сообщения' : 'Комментарии'}</SortHead>
        <SortHead k="posts" wideOnly className="justify-self-end">{chat ? 'Дней' : 'Постов'}</SortHead>
        <SortHead k="first_at" wideOnly>Первый</SortHead>
        <SortHead k="last_at" wideOnly>Последний</SortHead>
      </div>

      {query.isLoading ? (
        <div className="flex flex-col gap-2 p-5">
          {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-11" />)}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Users className="size-5" />}
          title={q ? 'Никого не нашли' : chat ? 'Никого нет' : 'Комментаторов нет'}
          description={q ? 'Попробуйте другой запрос' : chat ? 'Под эти фильтры никто не подходит' : 'У постов канала нет комментариев'}
        />
      ) : (
        <div ref={listRef} role="table" aria-rowcount={total} className="relative" style={{ height: virtualizer.getTotalSize() }}>
          {items.map((vi) => {
            const p = rows[vi.index]
            return (
              <div
                key={p.peer_id}
                role="row"
                tabIndex={0}
                onClick={() => setSelected(p)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setSelected(p))}
                className={clsx(GRID, 'absolute inset-x-0 cursor-pointer border-b border-line/60 px-4 transition-colors duration-100 hover:bg-elevated/70 focus-visible:bg-elevated sm:px-5')}
                style={{ height: vi.size, transform: `translateY(${vi.start - virtualizer.options.scrollMargin}px)` }}
              >
                <span className="hidden font-mono text-[12px] text-fg-subtle tabular sm:block">{vi.index + 1}</span>
                <div className="flex min-w-0 items-center gap-3">
                  <Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={36} />
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className={clsx('truncate text-[14px] font-medium', p.is_deleted && 'text-fg-subtle')}>{p.name}</span>
                      <Flags p={p} />
                    </div>
                    {p.username ? (
                      <a href={`https://t.me/${p.username}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="block truncate text-[12.5px] text-accent/90 hover:text-accent hover:underline">
                        @{p.username}
                      </a>
                    ) : (
                      <span className="block text-[12.5px] text-fg-subtle">без username</span>
                    )}
                  </div>
                </div>
                <button
                  onClick={(e) => (e.stopPropagation(), copy(String(p.peer_id)))}
                  className="group hidden items-center gap-1.5 justify-self-start rounded px-1 font-mono text-[12.5px] text-fg-muted tabular transition-colors hover:text-fg sm:inline-flex"
                  aria-label={`Скопировать ID ${p.peer_id}`}
                >
                  {p.peer_id}
                  <Copy className="size-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                </button>
                <div className="flex items-center justify-end gap-2.5 lg:justify-start">
                  <span className={clsx('min-w-[2.5ch] text-right font-mono text-[14px] font-semibold tabular', !p.comments && 'text-fg-subtle')}>{p.comments ? num(p.comments) : '—'}</span>
                  <span className="hidden h-1.5 flex-1 overflow-hidden rounded-full bg-muted lg:block" aria-hidden>
                    <span className="block h-full rounded-full bg-accent/80" style={{ width: `${Math.max(3, (p.comments / maxComments) * 100)}%` }} />
                  </span>
                </div>
                <span className="hidden text-right font-mono text-[13px] text-fg-muted tabular lg:block">{num(p.posts)}</span>
                <span className="hidden text-[13px] text-fg-muted lg:block">{date(p.first_at)}</span>
                <span className="hidden text-[13px] text-fg-muted lg:block">{date(p.last_at)}</span>
              </div>
            )
          })}
        </div>
      )}
      {query.isFetchingNextPage && <div className="px-5 py-3 text-center text-[13px] text-fg-subtle">Загрузка…</div>}
      {rows.length > 0 && !query.hasNextPage && (
        <div className="px-5 py-3 text-center text-[12.5px] text-fg-subtle">
          {num(total)} {pluralRu(total, 'участник', 'участника', 'участников')}
        </div>
      )}

      <UserDrawer jobId={jobId} participant={selected} chat={chat} onClose={() => setSelected(null)} />
    </Card>
  )
}
