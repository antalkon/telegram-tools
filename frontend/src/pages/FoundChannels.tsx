import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AtSign, ChevronDown, Clock, ExternalLink, Eye, EyeOff, Layers, Lock, Megaphone, Play, Plus, Radar, Search, Square, UserRound, Users as UsersIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AddSourceDialog } from '../components/AddSource'
import { Avatar } from '../components/Avatar'
import { ExportMenu, PeerLine, Stat, useSources } from '../components/PeerBits'
import { AccountPicker, defaultAccount, TypeBadge, useAccounts } from '../components/SourceBits'
import { useToast } from '../components/Toast'
import { Badge, Button, Card, CardHeader, EmptyState, Input, ProgressBar, Segmented, Skeleton, Switch } from '../components/ui'
import { UsersTabs } from '../components/UsersTabs'
import { isTerminal, useJob } from '../features/collector/useJob'
import { Page, PageHeader } from '../layout/AppLayout'
import {
  api, type DiscoveryStats, type FinderBlock, type FinderOptions, type FinderProgress, type FinderResult, type FoundChannel, type FoundChannelsPage, type Job, type PeerCard,
} from '../lib/api'
import { compact, num, pluralRu, relative } from '../lib/format'

const PAGE = 60

const PHASES: Record<string, string> = {
  queued: 'В очереди', starting: 'Запуск', select: 'Выбираем людей', profiles: 'Читаем профили',
  resolve: 'Проверяем ссылки из bio', details: 'Уточняем каналы', avatars: 'Аватарки',
}

const BLOCKS: Record<FinderBlock, string> = {
  resolve: 'поиск по @username',
  full_user: 'чтение профилей',
  invite: 'проверка ссылок-приглашений',
  full_channel: 'сведения о каналах',
}

function Blocks({ blocked }: { blocked?: DiscoveryStats['blocked'] }) {
  const items = Object.entries(blocked ?? {}) as [FinderBlock, string][]
  if (!items.length) return null
  const at = (iso: string) => new Date(iso).toLocaleString('ru', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-soft/40 px-3 py-2 text-[12.5px]" role="status">
      <Clock className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
      <div className="flex flex-col gap-0.5">
        {items.map(([k, until]) => (
          <span key={k}><b className="font-medium text-fg">Telegram временно запретил {BLOCKS[k]}</b> — до {at(until)}.</span>
        ))}
        <span className="text-fg-muted">
          Остальное запуск делает как обычно; то, что упёрлось в запрет, не помечается проверенным и доделается после него.
          {items.some(([k]) => k === 'resolve') && ' Профили без сохранённого доступа и @упоминания из bio ждут окончания запрета.'}
        </span>
      </div>
    </div>
  )
}

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** The link the «add source» dialog understands for a found channel. */
const addLink = (c: FoundChannel) => (c.username ? `@${c.username}` : c.link ?? String(c.peer_id))

// ---------- run ----------

function FinderCard({ stats }: { stats?: DiscoveryStats }) {
  const qc = useQueryClient()
  const toast = useToast()
  const accounts = useAccounts()
  const sources = useSources()
  const [accountId, setAccountId] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [opts, setOpts] = useState<FinderOptions>({ presence: 'all', limit: 2000, check_bio: true, resolve_mentions: true, use_usernames: true, recheck: false })
  const [sourceId, setSourceId] = useState('')
  const account = accountId ?? defaultAccount(accounts.data)
  const set = (patch: FinderOptions) => setOpts((o) => ({ ...o, ...patch }))

  const lastId = stats?.last_job?.id ?? null
  const job = useJob(lastId && !isTerminal(stats?.last_job?.status) ? lastId : null)
  const live: Job | null | undefined = job.data ?? stats?.last_job
  const running = !!live && !isTerminal(live.status)
  // counters and the list catch up at every phase change and at the end
  const phase = (job.data?.progress as FinderProgress | undefined)?.phase
  useEffect(() => {
    if (phase) qc.invalidateQueries({ queryKey: ['discovery'] })
  }, [phase, qc])

  const start = useMutation({
    mutationFn: () => api<Job>('/tools/channel-finder/jobs', {
      method: 'POST',
      json: { account_id: account, options: { ...opts, source_ids: sourceId ? [Number(sourceId)] : [] } },
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['discovery'] }),
    onError: (e) => toast(e.message, 'error'),
  })
  const cancel = useMutation({ mutationFn: () => api(`/jobs/${live!.id}/cancel`, { method: 'POST' }) })

  const left = stats ? stats.people - stats.checked : 0
  return (
    <Card>
      <CardHeader
        icon={<Radar className="size-4" />}
        title="Поиск каналов"
        description="Личный канал из профиля, ссылки t.me и @упоминания в bio, каналы, от имени которых писали. Только чтение: никуда не вступаем и ничего не отправляем."
      />
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <div className="grid grid-cols-2 gap-2 self-start">
          <Stat icon={<UserRound className="size-4" />} label="Профилей проверено" value={stats ? `${num(stats.checked)} / ${num(stats.people)}` : '—'}
            sub={stats && left > 0 ? `ещё ${num(left)} не проверены` : 'все проверены'} />
          <Stat icon={<Megaphone className="size-4" />} label="Личных каналов" value={num(stats?.personal ?? 0)} sub="в профилях" />
          <Stat icon={<AtSign className="size-4" />} label="С текстом в bio" value={num(stats?.with_bio ?? 0)} />
          <Stat icon={<Layers className="size-4" />} label="Найдено" value={num(stats?.found ?? 0)} sub={stats?.dismissed ? `скрыто ${num(stats.dismissed)}` : 'каналов и чатов'} />
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {running && live ? (
            <Progress job={live} onCancel={() => cancel.mutate()} cancelling={cancel.isPending} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2.5">
                <select aria-label="Чьи профили проверять" value={sourceId} onChange={(e) => setSourceId(e.target.value)}
                  className="h-10 max-w-64 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
                  <option value="">Люди из всех источников</option>
                  {sources.data?.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
                </select>
                <Segmented label="Кого проверять" value={opts.presence ?? 'all'} onChange={(v) => set({ presence: v })}
                  options={[{ value: 'all', label: 'Всех' }, { value: 'active', label: 'Только писавших', hint: 'Без молчунов из списков участников' }]} />
                <Input type="number" min={1} max={100000} step={500} aria-label="Сколько профилей за запуск" value={opts.limit ?? ''}
                  onChange={(e) => set({ limit: Number(e.target.value) || undefined })} className="w-36"
                  trailing={<span className="text-[12px] text-fg-subtle">проф.</span>} />
              </div>
              <AccountPicker value={account} onChange={setAccountId} />
              <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                className="flex w-fit items-center gap-1 text-[13px] text-fg-muted hover:text-fg">
                Параметры <ChevronDown className={clsx('size-4 transition-transform', open && 'rotate-180')} aria-hidden />
              </button>
              {open && (
                <div className="grid gap-4 rounded-xl border border-line bg-surface p-4 md:grid-cols-2">
                  <Switch checked={opts.check_bio ?? true} onChange={(v) => set({ check_bio: v, resolve_mentions: v })} label="Ссылки и @ в bio"
                    description="t.me/…, t.me/+…, @name — оставляем только каналы и чаты, пользователей и ботов отбрасываем" />
                  <Switch checked={opts.use_usernames ?? true} onChange={(v) => set({ use_usernames: v })} label="Искать по @username"
                    description="Если к человеку нет сохранённого доступа. Медленнее и тратит лимит Telegram на поиск имён" />
                  <Switch checked={opts.recheck ?? false} onChange={(v) => set({ recheck: v })} label="Перепроверить"
                    description="Заново прочитать уже проверенные профили — bio и каналы могли поменяться" />
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button variant="primary" icon={<Play className="size-4" />} loading={start.isPending} disabled={account == null} onClick={() => start.mutate()}>
                  Найти каналы
                </Button>
                <span className="text-[12.5px] text-fg-subtle">Telegram ограничивает частоту запросов: тысяча профилей — это десятки минут.</span>
              </div>
            </>
          )}
          {!running && live && <LastRun job={live} />}
          <Blocks blocked={stats?.blocked} />
        </div>
      </div>
    </Card>
  )
}

function Progress({ job, onCancel, cancelling }: { job: Job; onCancel: () => void; cancelling: boolean }) {
  const p = job.progress as FinderProgress
  const [done, total] =
    p.phase === 'resolve' ? [p.resolve_done, p.resolve_total]
      : p.phase === 'details' ? [p.details_done, p.details_total]
        : p.phase === 'avatars' ? [p.avatars_done, p.avatars_total]
          : [p.users_done, p.users_total]
  const flood = p.flood_wait_until ? Math.max(0, Math.round((new Date(p.flood_wait_until).getTime() - Date.now()) / 1000)) : 0
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-accent/30 bg-accent-soft/40 p-4" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{PHASES[p.phase ?? 'starting'] ?? 'Работаем'}</span>
        {total ? <span className="font-mono text-[13px] text-fg-muted tabular">{num(done ?? 0)} / {num(total)}</span> : null}
        <Button size="sm" variant="ghost" className="ml-auto" icon={<Square className="size-3.5" />} loading={cancelling} onClick={onCancel}>Остановить</Button>
      </div>
      <ProgressBar label="Прогресс поиска" value={total ? ((done ?? 0) / total) * 100 : undefined} indeterminate={!total} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-fg-muted">
        {p.found != null && <span>личных каналов: {num(p.found)}</span>}
        {!!p.no_access && <span>нет доступа: {num(p.no_access)}</span>}
        {flood > 0 && <span className="inline-flex items-center gap-1 text-warning"><Clock className="size-3.5" aria-hidden />пауза Telegram {flood} с</span>}
      </div>
      <p className="text-[12px] text-fg-subtle">Найденное сохраняется по ходу — остановить можно в любой момент.</p>
    </div>
  )
}

function LastRun({ job }: { job: Job }) {
  const r = job.result as unknown as Partial<FinderResult>
  if (job.status === 'failed') return <p className="text-[13px] text-danger">Последний запуск не удался: {job.error}</p>
  if (r.users_total == null) return null
  const hints: string[] = []
  if (r.deferred) hints.push(`${num(r.deferred)} ${pluralRu(r.deferred, 'ссылка', 'ссылки', 'ссылок')} из bio ждут снятия запрета Telegram`)
  const waiting = r.waiting_username ?? 0
  if (waiting) hints.push(`${num(waiting)} ${pluralRu(waiting, 'профиль', 'профиля', 'профилей')} ждут снятия запрета на поиск по @username`)
  const lost = (r.no_access ?? 0) - waiting
  const STEP: Record<string, string> = { profiles: 'чтение профилей', resolve: 'проверка ссылок из bio', details: 'сведения о каналах' }
  for (const [k, v] of Object.entries(r.failures ?? {})) hints.push(`Шаг «${STEP[k] ?? k}» прервался: ${v}. Остальные шаги выполнены`)
  if (lost > 0) hints.push(`${num(lost)} ${pluralRu(lost, 'профиль', 'профиля', 'профилей')} без доступа и без @username: переиндексируйте их источники — Telegram выдаст доступ заново`)
  return (
    <div className="flex flex-col gap-1 text-[13px] text-fg-muted">
      <p>
        {job.status === 'cancelled' ? 'Остановлен' : 'Готово'} {relative(job.finished_at)}: проверено {num(r.checked ?? 0)} из {num(r.users_total)},
        личных каналов {num(r.personal ?? 0)}, ссылок проверено {num(r.resolved ?? 0)}, новых каналов <b className="text-fg">{num(r.new_channels ?? 0)}</b>.
      </p>
      {hints.map((h) => <p key={h} className="text-[12.5px] text-warning">{h}</p>)}
    </div>
  )
}

// ---------- list ----------

function ViaBadges({ c }: { c: FoundChannel }) {
  return (
    <span className="flex flex-wrap gap-1">
      {c.via.personal > 0 && <Badge tone="accent" title="Канал закреплён в профиле"><UserRound className="size-3" aria-hidden />в профиле{c.via.personal > 1 ? ` ×${c.via.personal}` : ''}</Badge>}
      {c.via.bio > 0 && <Badge title="Ссылка или @упоминание в bio"><AtSign className="size-3" aria-hidden />в bio{c.via.bio > 1 ? ` ×${c.via.bio}` : ''}</Badge>}
      {c.via.sender && <Badge title="Писал в источниках от имени канала"><Megaphone className="size-3" aria-hidden />писал как канал</Badge>}
    </span>
  )
}

function People({ c }: { c: FoundChannel }) {
  const [open, setOpen] = useState(false)
  const all = useQuery({
    queryKey: ['discovery', 'users', c.key],
    queryFn: () => api<(PeerCard & { via: string[] })[]>(`/discovery/channels/${encodeURIComponent(c.key)}/users`),
    enabled: open,
  })
  if (!c.users) return null
  return (
    <div className="min-w-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-2 text-[12.5px] text-fg-muted hover:text-fg">
        <span className="flex -space-x-1.5">
          {c.people.slice(0, 5).map((p) => (
            <span key={p.peer_id} className="rounded-full ring-2 ring-card"><Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={22} /></span>
          ))}
        </span>
        у {num(c.users)} {pluralRu(c.users, 'человека', 'человек', 'человек')}
        <ChevronDown className={clsx('size-3.5 transition-transform', open && 'rotate-180')} aria-hidden />
      </button>
      {open && (
        <div className="mt-2 grid gap-2 rounded-lg border border-line bg-surface p-3 sm:grid-cols-2">
          {(all.data ?? c.people.map((p) => ({ ...p, via: [] }))).map((p) => (
            <PeerLine key={p.peer_id} p={p} size={28} sub={p.via.includes('personal') ? 'канал в профиле' : p.via.includes('bio') ? 'упомянут в bio' : undefined} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ c, picked, onPick, onIndex, onDismiss }: {
  c: FoundChannel; picked: boolean; onPick: () => void; onIndex: () => void; onDismiss: () => void
}) {
  const chat = c.family === 'chat'
  return (
    <li className={clsx('flex gap-3 px-4 py-4 sm:px-5', picked && 'bg-accent-soft/30')}>
      <label className="flex size-9 shrink-0 items-center justify-center rounded-lg hover:bg-elevated" title="Выбрать">
        <input type="checkbox" checked={picked} onChange={onPick} disabled={c.is_source} className="size-4 accent-[#2aabee]" aria-label={`Выбрать ${c.title}`} />
      </label>
      <Avatar id={c.peer_id ?? c.key.length} name={c.title} photoId={c.photo_id} size={44} square={!chat} />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate font-semibold">{c.title}</span>
          {c.type ? <TypeBadge type={c.type} /> : <Badge>тип уточнится</Badge>}
          {c.private && <Badge tone="warning" title="Ссылка-приглашение: чтобы индексировать, аккаунт должен вступить"><Lock className="size-3" aria-hidden />приватный</Badge>}
          {c.is_source && c.peer_id && <Link to={`/channels/${c.peer_id}`}><Badge tone="success">уже источник</Badge></Link>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-muted">
          {c.username && <span className="text-accent/90">@{c.username}</span>}
          {c.members_count != null && <span>{compact(c.members_count)} {chat ? 'участников' : 'подписчиков'}</span>}
          <ViaBadges c={c} />
        </div>
        {c.about && <p className="line-clamp-2 text-[12.5px] text-fg-subtle">{c.about}</p>}
        <People c={c} />
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-start">
        {!c.is_source && !c.dismissed && <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={onIndex}>Индексировать</Button>}
        <Button size="sm" variant="ghost" icon={c.dismissed ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />} onClick={onDismiss}
          aria-label={c.dismissed ? 'Вернуть в предложения' : 'Скрыть из предложений'} title={c.dismissed ? 'Вернуть' : 'Скрыть'} />
        {c.link && (
          <a href={c.link} target="_blank" rel="noreferrer" aria-label="Открыть в Telegram" title="Открыть в Telegram"
            className="flex size-8 items-center justify-center rounded-lg text-fg-muted hover:bg-elevated hover:text-fg">
            <ExternalLink className="size-3.5" />
          </a>
        )}
      </div>
    </li>
  )
}

export default function FoundChannels() {
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') ?? 'new') as 'new' | 'sources' | 'dismissed' | 'all'
  const type = (params.get('type') ?? 'all') as 'all' | 'channel' | 'chat' | 'private'
  const via = (params.get('via') ?? 'all') as 'all' | 'personal' | 'bio' | 'sender'
  const sort = params.get('sort') ?? 'users'
  const set = (k: string, v: string, dflt: string) => setParams((p) => (v === dflt ? p.delete(k) : p.set(k, v), p), { replace: true })
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const [limit, setLimit] = useState(PAGE)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [indexing, setIndexing] = useState<string[] | null>(null)

  const stats = useQuery({
    queryKey: ['discovery', 'stats'],
    queryFn: () => api<DiscoveryStats>('/discovery/stats'),
    refetchInterval: (qr) => (qr.state.data?.last_job && !isTerminal(qr.state.data.last_job.status) ? 4000 : false),
  })
  const running = !!stats.data?.last_job && !isTerminal(stats.data.last_job.status)
  const filters = { status, type, via, q, sort }
  const list = useQuery({
    queryKey: ['discovery', 'channels', filters, limit],
    queryFn: () => api<FoundChannelsPage>(`/discovery/channels?${new URLSearchParams({ ...filters, limit: String(limit) })}`),
    placeholderData: keepPreviousData,
    refetchInterval: running ? 8000 : false,  // found channels appear while the finder runs
  })
  const items = useMemo(() => list.data?.items ?? [], [list.data])
  useEffect(() => setPicked(new Set()), [status, type, via, q])

  const dismiss = useMutation({
    mutationFn: ({ keys, dismissed }: { keys: string[]; dismissed: boolean }) =>
      api('/discovery/channels/dismiss', { method: 'POST', json: { keys, dismissed } }),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ['discovery'] })
      setPicked(new Set())
      toast(v.dismissed ? `Скрыто: ${v.keys.length}` : 'Возвращено в предложения', 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const toggle = (k: string) => setPicked((s) => {
    const n = new Set(s)
    if (n.has(k)) n.delete(k)
    else n.add(k)
    return n
  })
  const pickedItems = items.filter((c) => picked.has(c.key))
  const counts = list.data?.counts
  const exportHref = (fmt: string) => `/api/discovery/channels?${new URLSearchParams({ ...filters, format: fmt })}`

  return (
    <Page wide>
      <PageHeader
        icon={<Radar className="size-5" />}
        title="Каналы пользователей"
        description="Каналы и чаты, которые люди из базы держат в профиле или упоминают в bio — кандидаты на индексацию"
        actions={<UsersTabs />}
      />
      <div className="flex flex-col gap-5">
        <FinderCard stats={stats.data} />

        <Card className="overflow-visible">
          <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <Segmented label="Статус" value={status} onChange={(v) => set('status', v, 'new')}
                options={[
                  { value: 'new', label: `Предложения ${counts?.new ?? ''}`.trim() },
                  { value: 'sources', label: `Уже источники ${counts?.sources ?? ''}`.trim() },
                  { value: 'dismissed', label: `Скрытые ${counts?.dismissed ?? ''}`.trim() },
                ]} />
              <Input aria-label="Поиск по названию, @username или описанию" placeholder="Название, @username, описание" value={search}
                onChange={(e) => setSearch(e.target.value)} leading={<Search className="size-4" />} className="w-full sm:ml-auto sm:w-72" />
              <ExportMenu href={exportHref} />
            </div>
            <div className="flex flex-wrap items-center gap-2.5">
              <Segmented label="Тип" value={type} onChange={(v) => set('type', v, 'all')}
                options={[{ value: 'all', label: 'Все' }, { value: 'channel', label: 'Каналы' }, { value: 'chat', label: 'Чаты' }, { value: 'private', label: 'Приватные', hint: 'Только по ссылке-приглашению' }]} />
              <select aria-label="Откуда" value={via} onChange={(e) => set('via', e.target.value, 'all')}
                className="h-10 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
                <option value="all">Откуда угодно</option>
                <option value="personal">Канал в профиле</option>
                <option value="bio">Ссылка в bio</option>
                <option value="sender">Писали от имени канала</option>
              </select>
              <select aria-label="Сортировка" value={sort} onChange={(e) => set('sort', e.target.value, 'users')}
                className="h-10 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
                <option value="users">Больше людей указали</option>
                <option value="members">Больше подписчиков</option>
                <option value="found">Недавно найденные</option>
                <option value="title">По названию</option>
              </select>
            </div>
          </div>

          {pickedItems.length > 0 && (
            <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-line bg-card/95 px-4 py-2.5 backdrop-blur sm:px-5">
              <span className="text-[13px] font-medium">Выбрано {pickedItems.length}</span>
              {status !== 'dismissed' && (
                <Button size="sm" variant="primary" icon={<Plus className="size-3.5" />} onClick={() => setIndexing(pickedItems.map(addLink))}>
                  Проиндексировать
                </Button>
              )}
              <Button size="sm" variant="secondary" icon={status === 'dismissed' ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
                onClick={() => dismiss.mutate({ keys: pickedItems.map((c) => c.key), dismissed: status !== 'dismissed' })}>
                {status === 'dismissed' ? 'Вернуть' : 'Скрыть'}
              </Button>
              <button type="button" onClick={() => setPicked(new Set())} className="ml-auto text-[12.5px] text-fg-muted hover:text-fg">Снять выбор</button>
            </div>
          )}

          {list.isLoading ? (
            <div className="flex flex-col gap-2 p-5">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
          ) : items.length === 0 ? (
            <EmptyState
              icon={<UsersIcon className="size-5" />}
              title={counts?.all ? 'Под фильтр ничего не подходит' : 'Пока ничего не найдено'}
              description={counts?.all ? 'Измените фильтры или статус' : 'Запустите поиск выше: проверим профили людей из ваших источников'}
            />
          ) : (
            <>
              {status !== 'sources' && (
                <div className="flex items-center gap-2 border-b border-line px-4 py-2 text-[12.5px] text-fg-subtle sm:px-5">
                  <button type="button" className="hover:text-fg"
                    onClick={() => setPicked(new Set(items.filter((c) => !c.is_source).map((c) => c.key)))}>
                    Выбрать все на странице
                  </button>
                  <span>· {num(list.data?.total ?? 0)} {pluralRu(list.data?.total ?? 0, 'результат', 'результата', 'результатов')}</span>
                </div>
              )}
              <ul className="divide-y divide-line">
                {items.map((c) => (
                  <Row key={c.key} c={c} picked={picked.has(c.key)} onPick={() => toggle(c.key)}
                    onIndex={() => setIndexing([addLink(c)])} onDismiss={() => dismiss.mutate({ keys: [c.key], dismissed: !c.dismissed })} />
                ))}
              </ul>
              {(list.data?.total ?? 0) > items.length && (
                <div className="border-t border-line p-3 text-center">
                  <Button variant="ghost" size="sm" loading={list.isFetching} onClick={() => setLimit((l) => l + PAGE)}>Показать ещё</Button>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
      <AddSourceDialog open={indexing != null} onClose={() => setIndexing(null)} links={indexing ?? undefined} />
    </Page>
  )
}
