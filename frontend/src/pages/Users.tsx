import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { EyeOff, Search, Star, Tag, Users as UsersIcon } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { ExportMenu, Flags, SourceStack, useSources } from '../components/PeerBits'
import { Badge, Card, EmptyState, Input, Segmented, Skeleton } from '../components/ui'
import { VirtualTable, type Column } from '../components/VirtualTable'
import { UsersTabs } from '../components/UsersTabs'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type UserRow } from '../lib/api'
import { num, pluralRu, relative } from '../lib/format'

const PAGE = 200

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export default function Users() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebounced(search)
  const minSources = params.get('min') ?? '1'
  const sourceId = params.get('source') ?? ''
  const tag = params.get('tag') ?? ''
  const starred = params.get('starred') === '1'
  const ignoredOnly = params.get('ignored') === '1'
  const kind = (params.get('kind') ?? 'all') as 'all' | 'user' | 'channel'
  const presence = (params.get('presence') ?? 'all') as 'all' | 'active' | 'silent'
  const family = (params.get('family') ?? 'all') as 'all' | 'channel' | 'chat'
  const sortParam = params.get('sort') ?? '-comments'
  const sort = { key: sortParam.replace(/^-/, ''), desc: sortParam.startsWith('-') }

  const set = useCallback(
    (k: string, v: string | null) =>
      setParams(
        (p) => {
          if (v == null || v === '' || v === 'all' || (k === 'min' && v === '1')) p.delete(k)
          else p.set(k, v)
          return p
        },
        { replace: true },
      ),
    [setParams],
  )
  useEffect(() => set('q', q), [q, set])

  const sources = useSources()
  const tags = useQuery({ queryKey: ['tags'], queryFn: () => api<{ tag: string; count: number }[]>('/tags') })

  const filters = { search: q, sort: sortParam, min_sources: minSources, kind, presence, family, ...(sourceId && { source_id: sourceId }), ...(tag && { tag }), ...(starred && { starred: 'true' }), ...(ignoredOnly && { show_ignored: 'true' }) }
  const query = useInfiniteQuery({
    queryKey: ['users', filters],
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    queryFn: ({ pageParam }) =>
      api<{ total: number; items: UserRow[] }>(`/users?${new URLSearchParams({ ...filters, offset: String(pageParam), limit: String(PAGE) })}`),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((s, p) => s + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const rows = query.data?.pages.flatMap((p) => p.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query
  const more = useCallback(() => hasNextPage && !isFetchingNextPage && fetchNextPage(), [hasNextPage, isFetchingNextPage, fetchNextPage])

  const columns: Column<UserRow>[] = [
    {
      key: 'user', header: 'Пользователь', width: 'minmax(0,1fr)', sortKey: 'name',
      render: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar id={u.peer_id} name={u.name} photoId={u.photo_id} size={36} />
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className={clsx('truncate text-[14px] font-medium', u.is_deleted && 'text-fg-subtle')}>{u.name}</span>
              <Flags p={u} />
            </div>
            <div className="flex min-w-0 items-center gap-1.5 text-[12.5px]">
              <span className={clsx('truncate', u.username ? 'text-accent/90' : 'text-fg-subtle')}>{u.username ? `@${u.username}` : `ID ${u.peer_id}`}</span>
              <span className="hidden gap-1 sm:flex">{u.tags.slice(0, 2).map((t) => <Badge key={t} tone="accent" className="h-[18px]">{t}</Badge>)}</span>
            </div>
          </div>
        </div>
      ),
    },
    { key: 'where', header: 'Где найден', width: '140px', hideBelow: 'sm', render: (u) => <SourceStack ids={u.source_ids} /> },
    {
      key: 'sources', header: 'Ист.', width: '48px', sortKey: 'sources', align: 'right',
      render: (u) => <span className={clsx('font-mono text-[14px] font-semibold tabular', u.sources > 1 ? 'text-fg' : 'text-fg-subtle')}>{u.sources}</span>,
    },
    {
      key: 'comments', header: 'Сообщ.', width: '76px', sortKey: 'comments', align: 'right',
      render: (u) => u.comments
        ? <span className="font-mono text-[14px] font-semibold tabular">{num(u.comments)}</span>
        : <span className="text-[12px] text-fg-subtle" title="Только в списке участников, не писал">участник</span>,
    },
    { key: 'posts', header: 'Обсужд.', width: '80px', sortKey: 'posts', align: 'right', hideBelow: 'lg', render: (u) => <span className="font-mono text-[13px] text-fg-muted tabular">{num(u.posts)}</span> },
    { key: 'last', header: 'Активность', width: '120px', sortKey: 'last_at', hideBelow: 'lg', render: (u) => <span className="text-[13px] text-fg-muted">{relative(u.last_at)}</span> },
  ]

  const exportHref = (fmt: string) => `/api/users?${new URLSearchParams({ ...filters, format: fmt })}`

  return (
    <Page wide>
      <PageHeader
        icon={<UsersIcon className="size-5" />}
        title="Пользователи"
        description="Все, кого нашли инструменты: комментаторы каналов, авторы и участники чатов — объединённые по всем источникам"
        actions={<UsersTabs />}
      />
      <Card className="overflow-visible">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <div className="mr-auto flex items-center gap-2">
              <span className="text-[15px] font-semibold">{num(total)}</span>
              <span className="text-[13px] text-fg-muted">{pluralRu(total, 'пользователь', 'пользователя', 'пользователей')}</span>
            </div>
            <Input
              aria-label="Поиск по имени, @username, ID или заметке"
              placeholder="Имя, @username, ID, заметка, ФИО, телефон, email, текст PDF"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leading={<Search className="size-4" />}
              className="w-full sm:w-72"
            />
            <ExportMenu href={exportHref} />
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Segmented
              label="Пересечения"
              value={minSources}
              onChange={(v) => set('min', v)}
              options={[
                { value: '1', label: 'Все' },
                { value: '2', label: '2+ источника' },
                { value: '3', label: '3+' },
                { value: '4', label: '4+' },
              ]}
            />
            <Segmented label="Тип" value={kind} onChange={(v) => set('kind', v)} options={[{ value: 'all', label: 'Все' }, { value: 'user', label: 'Люди' }, { value: 'channel', label: 'Каналы' }]} />
            <Segmented label="Активность" value={presence} onChange={(v) => set('presence', v)}
              options={[{ value: 'all', label: 'Все' }, { value: 'active', label: 'Писали' }, { value: 'silent', label: 'Молчуны', hint: 'Есть в участниках чатов, но ничего не писали' }]} />
            <Segmented label="Где" value={family} onChange={(v) => set('family', v)}
              options={[{ value: 'all', label: 'Везде' }, { value: 'channel', label: 'В каналах' }, { value: 'chat', label: 'В чатах' }]} />
            <select
              aria-label="Источник"
              value={sourceId}
              onChange={(e) => set('source', e.target.value)}
              className="h-10 max-w-56 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg"
            >
              <option value="">Все источники</option>
              {sources.data?.map((s) => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
            {!!tags.data?.length && (
              <select aria-label="Метка" value={tag} onChange={(e) => set('tag', e.target.value)} className="h-10 max-w-48 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
                <option value="">Любая метка</option>
                {tags.data.map((t) => (
                  <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>
                ))}
              </select>
            )}
            <button
              aria-pressed={starred}
              onClick={() => set('starred', starred ? null : '1')}
              className={clsx('flex h-10 items-center gap-1.5 rounded-[10px] border px-3 text-[13px] transition-colors', starred ? 'border-warning/50 bg-warning-soft text-warning' : 'border-line text-fg-muted hover:text-fg')}
            >
              <Star className={clsx('size-4', starred && 'fill-warning')} aria-hidden /> Избранные
            </button>
            <button
              aria-pressed={ignoredOnly}
              onClick={() => set('ignored', ignoredOnly ? null : '1')}
              className={clsx('flex h-10 items-center gap-1.5 rounded-[10px] border px-3 text-[13px] transition-colors', ignoredOnly ? 'border-danger/40 bg-danger-soft text-danger' : 'border-line text-fg-muted hover:text-fg')}
            >
              <EyeOff className="size-4" aria-hidden /> Игнорируемые
            </button>
            {tag && (
              <span className="flex items-center gap-1 text-[12.5px] text-fg-subtle"><Tag className="size-3.5" aria-hidden />фильтр по метке</span>
            )}
          </div>
        </div>
        {query.isLoading ? (
          <div className="flex flex-col gap-2 p-5">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-11" />)}</div>
        ) : rows.length === 0 ? (
          <EmptyState icon={<UsersIcon className="size-5" />} title="Никого не нашли" description={sources.data?.length ? 'Измените фильтры' : 'Добавьте хотя бы один канал или чат в «Источниках»'} />
        ) : (
          <VirtualTable
            rows={rows}
            columns={columns}
            rowKey={(u) => u.peer_id}
            sort={sort}
            onSort={(k) => set('sort', sort.key === k ? `${sort.desc ? '' : '-'}${k}` : `${k === 'name' ? '' : '-'}${k}`)}
            onRowClick={(u) => navigate(`/users/${u.peer_id}`)}
            onEndReached={more}
          />
        )}
        {isFetchingNextPage && <div className="px-5 py-3 text-center text-[13px] text-fg-subtle">Загрузка…</div>}
      </Card>
    </Page>
  )
}
