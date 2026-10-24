import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { BarChart3, BellRing, ChevronDown, EyeOff, GitCompareArrows, Layers, Loader2, Search, TextSearch, Users } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AddSourceButton } from '../components/AddSource'
import { Avatar } from '../components/Avatar'
import { TypeBadge, words } from '../components/SourceBits'
import { SourceActions, useMonitors } from '../components/SourceActions'
import { Badge, Button, Card, EmptyState, Input, Segmented, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, intervalLabel, type Source } from '../lib/api'
import { compact, num, relative } from '../lib/format'

type Filter = 'all' | 'channel' | 'chat' | 'forum'
type Sort = 'people' | 'comments' | 'updated' | 'title'

function SourceCard({ s, picked, onPick }: { s: Source; picked?: boolean; onPick?: () => void }) {
  const navigate = useNavigate()
  const monitors = useMonitors()
  const monitor = monitors.data?.find((m) => m.source_id === s.id)
  const w = words(s.family)
  const chat = s.family === 'chat'
  const stats: [string, string, string?][] = chat
    ? [
        [w.authors, num(s.users)],
        [w.items, compact(s.comments)],
        ['Участников', s.members_status === 'hidden' ? 'скрыты' : num(s.members),
          s.members_status === 'hidden' ? 'Админы скрыли список участников' : s.members_status === 'partial' ? 'Telegram отдаёт не больше ~10 000' : undefined],
      ]
    : [
        [w.authors, num(s.users)],
        [w.items, compact(s.comments)],
        ['На 1000 подп.', s.subscribers ? ((s.users / s.subscribers) * 1000).toFixed(1) : '—'],
      ]
  return (
    <Card className={clsx('flex flex-col p-5 transition-colors', picked && 'border-accent/60', s.hidden && 'opacity-75')}>
      <div className="flex items-start gap-3">
        <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={44} square={!chat} />
        <div className="min-w-0 flex-1">
          <Link to={`/channels/${s.id}`} className="block truncate font-semibold hover:text-accent">{s.title}</Link>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-fg-muted">
            <TypeBadge type={s.type} />
            {s.username && <span>@{s.username}</span>}
            {s.subscribers != null && <span>{compact(s.subscribers)} {chat ? 'уч.' : 'подп.'}</span>}
          </div>
        </div>
        {onPick && (
          <label className="flex size-9 items-center justify-center rounded-lg hover:bg-elevated" title="Выбрать для сравнения">
            <input type="checkbox" checked={picked} onChange={onPick} className="size-4 accent-[#2aabee]" aria-label={`Сравнить ${s.title}`} />
          </label>
        )}
      </div>
      {s.linked_channel && <p className="mt-2 truncate text-[12px] text-fg-subtle">обсуждения канала «{s.linked_channel.title}»</p>}
      <div className="mt-4 grid grid-cols-3 gap-2">
        {stats.map(([k, v, hint]) => (
          <div key={k} className="rounded-lg bg-surface px-2.5 py-2" title={hint}>
            <div className="text-[11px] text-fg-subtle">{k}</div>
            <div className={clsx('font-mono text-[15px] font-semibold tabular', v === 'скрыты' && 'font-sans text-[13px] font-medium text-fg-muted')}>{v}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px] text-fg-subtle">
        <span>обновлён {relative(s.collected_at)}</span>
        {s.runs > 1 && <span>· {s.runs} сборов</span>}
        {s.running && <Badge tone="accent"><Loader2 className="size-3 animate-spin" aria-hidden />идёт сбор</Badge>}
        {s.partial && <Badge tone="warning">частично</Badge>}
        {s.members_status === 'partial' && <Badge tone="warning" title="Telegram отдаёт не больше ~10 000 участников">участники не все</Badge>}
        {s.hidden && <Badge><EyeOff className="size-3" aria-hidden />отключён</Badge>}
        {monitor && (
          <Link to="/monitoring">
            <Badge tone={monitor.last_status === 'failed' ? 'danger' : 'accent'}>
              <BellRing className="size-3" aria-hidden />
              {monitor.enabled ? intervalLabel(monitor.interval_minutes) : 'на паузе'}
            </Badge>
          </Link>
        )}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-1 border-t border-line pt-4">
        <Button size="sm" variant="ghost" icon={<BarChart3 className="size-3.5" />} onClick={() => navigate(`/channels/${s.id}`)}>Аналитика</Button>
        {!s.hidden && <Button size="sm" variant="ghost" icon={<Users className="size-3.5" />} onClick={() => navigate(`/users?source=${s.id}`)}>Люди</Button>}
        {!s.hidden && <Button size="sm" variant="ghost" icon={<TextSearch className="size-3.5" />} aria-label="Поиск по сообщениям" title="Поиск по сообщениям" onClick={() => navigate(`/search?source=${s.id}`)} />}
        <div className="ml-auto"><SourceActions source={s} compact /></div>
      </div>
    </Card>
  )
}

export default function Channels() {
  const all = useQuery({
    queryKey: ['sources', 'all'],
    queryFn: () => api<Source[]>('/sources?include_hidden=true'),
    staleTime: 15_000,
    refetchInterval: (q) => (q.state.data?.some((s) => s.running) ? 5000 : false),
  })
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filter = (params.get('type') ?? 'all') as Filter
  const sort = (params.get('sort') ?? 'people') as Sort
  const set = (k: string, v: string, dflt: string) => setParams((p) => (v === dflt ? p.delete(k) : p.set(k, v), p), { replace: true })
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState<number[]>([])
  const [showHidden, setShowHidden] = useState(false)
  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase().replace(/^@/, '')
    const rows = (all.data ?? []).filter((s) =>
      (filter === 'all' || (filter === 'forum' ? s.type === 'forum' : s.family === filter)) &&
      (!needle || s.title.toLowerCase().includes(needle) || s.username?.toLowerCase().includes(needle)))
    const by: Record<Sort, (a: Source, b: Source) => number> = {
      people: (a, b) => b.people - a.people,
      comments: (a, b) => b.comments - a.comments,
      updated: (a, b) => (b.collected_at ?? '').localeCompare(a.collected_at ?? ''),
      title: (a, b) => a.title.localeCompare(b.title, 'ru'),
    }
    return rows.sort(by[sort])
  }, [all.data, filter, sort, q])
  const visible = list.filter((s) => !s.hidden)
  const hidden = list.filter((s) => s.hidden)
  const count = (f: Filter) => (all.data ?? []).filter((s) => !s.hidden && (f === 'all' || (f === 'forum' ? s.type === 'forum' : s.family === f))).length

  return (
    <Page wide>
      <PageHeader
        icon={<Layers className="size-5" />}
        title="Источники"
        description="Каналы, группы, супергруппы и форумы: добавление, дозабор, переиндексация, мониторинг и отключение"
        actions={
          <div className="flex gap-2">
            {picked.length >= 2 && (
              <Button variant="secondary" icon={<GitCompareArrows className="size-4" />} onClick={() => navigate(`/overlap?ids=${picked.join(',')}`)}>
                Сравнить {picked.length}
              </Button>
            )}
            <AddSourceButton />
          </div>
        }
      />
      {all.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-52 rounded-[var(--radius-card)]" />)}</div>
      ) : !all.data?.length ? (
        <Card>
          <EmptyState
            icon={<Layers className="size-5" />}
            title="Пока ни одного источника"
            description="Добавьте канал (соберём комментаторов) или чат (сообщения и участников)"
            action={<AddSourceButton label="Добавить первый" />}
          />
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2.5">
            <Segmented
              label="Тип источника"
              value={filter}
              onChange={(v) => set('type', v, 'all')}
              options={[
                { value: 'all', label: `Все ${count('all')}` },
                { value: 'channel', label: `Каналы ${count('channel')}` },
                { value: 'chat', label: `Чаты ${count('chat')}`, hint: 'Группы, супергруппы и форумы' },
                ...(count('forum') ? [{ value: 'forum' as const, label: `Форумы ${count('forum')}` }] : []),
              ]}
            />
            <select aria-label="Сортировка" value={sort} onChange={(e) => set('sort', e.target.value, 'people')}
              className="h-10 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
              <option value="people">Больше людей</option>
              <option value="comments">Больше сообщений</option>
              <option value="updated">Недавно обновлённые</option>
              <option value="title">По названию</option>
            </select>
            <Input aria-label="Поиск источника" placeholder="Название или @username" value={q} onChange={(e) => setQ(e.target.value)}
              leading={<Search className="size-4" />} className="w-full sm:ml-auto sm:w-64" />
          </div>
          {visible.length > 1 && <p className="mb-3 text-[13px] text-fg-subtle">Отметьте 2+ источника, чтобы сравнить аудитории — в том числе канал с чатом.</p>}
          {visible.length === 0 && <p className="py-10 text-center text-sm text-fg-subtle">Под фильтр ничего не подходит.</p>}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {visible.map((s) => <SourceCard key={s.id} s={s} picked={picked.includes(s.id)} onPick={() => toggle(s.id)} />)}
          </div>
          {hidden.length > 0 && (
            <div className="mt-8">
              <button onClick={() => setShowHidden(!showHidden)} aria-expanded={showHidden} className="mb-3 flex items-center gap-1.5 text-[14px] font-semibold text-fg-muted hover:text-fg">
                <EyeOff className="size-4" aria-hidden /> Отключённые ({hidden.length})
                <ChevronDown className={clsx('size-4 transition-transform', showHidden && 'rotate-180')} aria-hidden />
              </button>
              {showHidden && (
                <>
                  <p className="mb-3 text-[13px] text-fg-subtle">Не участвуют в обзоре, поиске, графе, пересечениях и списке людей. Данные сохранены — включите обратно в меню «…».</p>
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{hidden.map((s) => <SourceCard key={s.id} s={s} />)}</div>
                </>
              )}
            </div>
          )}
        </>
      )}
    </Page>
  )
}
