import { keepPreviousData, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { GitCompareArrows } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { BarList } from '../components/charts'
import { ExportMenu, Flags, useSources } from '../components/PeerBits'
import { Card, CardHeader, EmptyState, Segmented, Skeleton } from '../components/ui'
import { VirtualTable, type Column } from '../components/VirtualTable'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type OverlapMatrix, type OverlapUser } from '../lib/api'
import { num, pluralRu } from '../lib/format'

const RAMP = ['#1d2840', '#173a6b', '#184f95', '#256abf', '#3987e5', '#6da7ec']

export default function Overlap() {
  const sources = useSources()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const all = useMemo(() => sources.data ?? [], [sources.data])
  const ids = (params.get('ids')?.split(',').map(Number).filter(Boolean) ?? []).filter((id) => all.some((s) => s.id === id))
  const selected = ids.length ? ids : all.slice(0, 6).map((s) => s.id)
  const [mode, setMode] = useState<'all' | 'two'>('all')
  const activeOnly = params.get('active') === '1'
  const setIds = (next: number[]) => setParams((p) => (p.set('ids', next.join(',')), p), { replace: true })
  const toggle = (id: number) => setIds(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])
  const key = selected.join(',')

  const matrix = useQuery({
    queryKey: ['overlap', key, activeOnly],
    queryFn: () => api<OverlapMatrix>(`/overlap?ids=${key}&active_only=${activeOnly}`),
    enabled: selected.length >= 2,
    placeholderData: keepPreviousData,
  })
  const minSources = mode === 'all' ? selected.length : 2
  const users = useQuery({
    queryKey: ['overlap-users', key, minSources, activeOnly],
    queryFn: () => api<{ total: number; items: OverlapUser[] }>(`/overlap/users?ids=${key}&min_sources=${minSources}&active_only=${activeOnly}&limit=2000`),
    enabled: selected.length >= 2,
    placeholderData: keepPreviousData,
  })

  const byId = new Map(all.map((s) => [s.id, s]))
  const pair = (a: number, b: number) => matrix.data?.pairs.find((p) => (p.a === a && p.b === b) || (p.a === b && p.b === a))
  const maxShared = Math.max(1, ...(matrix.data?.pairs.map((p) => p.shared) ?? [1]))

  const columns: Column<OverlapUser>[] = [
    {
      key: 'user', header: 'Пользователь', width: 'minmax(0,1fr)',
      render: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar id={u.peer_id} name={u.name} photoId={u.photo_id} size={34} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5"><span className="truncate text-[14px] font-medium">{u.name}</span><Flags p={u} /></div>
            <div className="truncate text-[12.5px] text-fg-subtle">{u.username ? `@${u.username}` : `ID ${u.peer_id}`}</div>
          </div>
        </div>
      ),
    },
    ...selected.slice(0, 6).map<Column<OverlapUser>>((sid) => ({
      key: String(sid), header: byId.get(sid)?.title.slice(0, 12) ?? String(sid), width: '96px', hideBelow: 'lg', align: 'right',
      render: (u) => <span className={clsx('font-mono text-[13px] tabular', u.by_source[sid] ? 'text-fg' : 'text-fg-subtle')}>{u.by_source[sid] ? num(u.by_source[sid]) : '—'}</span>,
    })),
    { key: 'n', header: 'Источн.', width: '76px', align: 'right', render: (u) => <span className="font-mono text-[14px] font-semibold tabular">{u.sources}</span> },
    { key: 'c', header: 'Всего', width: '80px', align: 'right', hideBelow: 'sm', render: (u) => <span className="font-mono text-[13px] tabular">{num(u.comments)}</span> },
  ]

  return (
    <Page wide>
      <PageHeader icon={<GitCompareArrows className="size-5" />} title="Пересечения аудиторий" description="Кто есть сразу в нескольких каналах и чатах: пишет или состоит в участниках" />

      {sources.isLoading ? (
        <Skeleton className="h-40 rounded-[var(--radius-card)]" />
      ) : all.length < 2 ? (
        <Card><EmptyState icon={<GitCompareArrows className="size-5" />} title="Нужно минимум 2 источника" description="Добавьте ещё один канал или чат" /></Card>
      ) : (
        <div className="flex flex-col gap-5">
          <Card className="p-4">
            <div className="mb-2 flex flex-wrap items-center gap-3 text-[13px] text-fg-muted">
              <span className="mr-auto">Источники для сравнения</span>
              <button onClick={() => setIds(all.filter((s) => s.family === 'channel').map((s) => s.id))} className="hover:text-fg">только каналы</button>
              <button onClick={() => setIds(all.filter((s) => s.family === 'chat').map((s) => s.id))} className="hover:text-fg">только чаты</button>
              <Segmented label="Кого считать" value={activeOnly ? 'active' : 'all'} onChange={(v) => setParams((p) => (v === 'active' ? p.set('active', '1') : p.delete('active'), p), { replace: true })}
                options={[{ value: 'all', label: 'Всех', hint: 'Авторов и участников чатов' }, { value: 'active', label: 'Только писавших' }]} />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {all.map((s) => {
                const on = selected.includes(s.id)
                return (
                  <button
                    key={s.id}
                    onClick={() => toggle(s.id)}
                    aria-pressed={on}
                    className={clsx('flex h-8 items-center gap-2 rounded-full border pr-3 pl-1 text-[13px] transition-colors', on ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}
                  >
                    <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={22} square={s.family !== 'chat'} />
                    {s.title}
                    <span className="font-mono text-[11px] text-fg-subtle">{num(activeOnly ? s.users : s.people)}</span>
                  </button>
                )
              })}
            </div>
          </Card>

          {selected.length < 2 ? (
            <Card><EmptyState icon={<GitCompareArrows className="size-5" />} title="Выберите хотя бы 2 источника" /></Card>
          ) : (
            <>
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <Card>
                  <CardHeader title="Матрица пересечений" description="Сколько общих людей у каждой пары источников (наведите для Jaccard)" />
                  <div className="overflow-x-auto p-5 scrollbar-thin">
                    <table className="w-full border-separate border-spacing-[3px] text-[12.5px]">
                      <thead>
                        <tr>
                          <th />
                          {selected.map((b) => (
                            <th key={b} scope="col" className="px-1 pb-1 text-left font-medium text-fg-muted"><span className="line-clamp-2 max-w-24">{byId.get(b)?.title}</span></th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {selected.map((a) => (
                          <tr key={a}>
                            <th scope="row" className="max-w-32 truncate pr-2 text-left font-medium text-fg-muted">{byId.get(a)?.title}</th>
                            {selected.map((b) => {
                              if (a === b)
                                return <td key={b} className="h-11 min-w-16 rounded-md bg-muted/40 text-center font-mono text-fg-subtle" title="Всего комментаторов">{num(byId.get(a)?.users)}</td>
                              const p = pair(a, b)
                              const v = p?.shared ?? 0
                              const c = RAMP[v ? Math.min(RAMP.length - 1, 1 + Math.floor((v / maxShared) * (RAMP.length - 1.001))) : 0]
                              return (
                                <td key={b} className="h-11 min-w-16 rounded-md p-0">
                                  <button
                                    onClick={() => setIds([a, b])}
                                    title={`${num(v)} общих · Jaccard ${p?.jaccard ?? 0} · ${((v / (byId.get(a)?.users || 1)) * 100).toFixed(1)}% аудитории «${byId.get(a)?.title}»`}
                                    className="h-full w-full rounded-md font-mono text-[13px] font-semibold text-white transition-[outline] hover:outline hover:outline-2 hover:outline-fg/70"
                                    style={{ background: c }}
                                  >
                                    {num(v)}
                                  </button>
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
                <Card>
                  <CardHeader title="Охват по числу источников" description={`Из ${num(matrix.data?.total_users)} уникальных людей`} />
                  <div className="p-5">
                    {matrix.data && (
                      <BarList
                        items={matrix.data.users_by_source_count.map((r) => ({
                          key: r.sources,
                          label: `в ${r.sources} ${pluralRu(r.sources, 'источнике', 'источниках', 'источниках')}`,
                          value: r.users,
                        }))}
                      />
                    )}
                  </div>
                </Card>
              </div>

              <Card className="overflow-visible">
                <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 sm:px-5">
                  <div className="mr-auto">
                    <span className="text-[15px] font-semibold">{num(users.data?.total)}</span>{' '}
                    <span className="text-[13px] text-fg-muted">{mode === 'all' ? 'пишут во всех выбранных' : 'пишут минимум в двух'}</span>
                  </div>
                  <Segmented label="Условие" value={mode} onChange={setMode} options={[{ value: 'all', label: 'Во всех' }, { value: 'two', label: 'В 2+' }]} />
                  <ExportMenu href={(fmt) => `/api/overlap/users?ids=${key}&min_sources=${minSources}&format=${fmt}`} />
                </div>
                {users.isLoading ? (
                  <div className="p-5"><Skeleton className="h-40" /></div>
                ) : users.data?.items.length ? (
                  <VirtualTable rows={users.data.items} columns={columns} rowKey={(u) => u.peer_id} onRowClick={(u) => navigate(`/users/${u.peer_id}`)} rowHeight={56} />
                ) : (
                  <EmptyState icon={<GitCompareArrows className="size-5" />} title="Общих комментаторов нет" description={mode === 'all' ? 'Попробуйте условие «В 2+»' : undefined} />
                )}
              </Card>
            </>
          )}
        </div>
      )}
    </Page>
  )
}
