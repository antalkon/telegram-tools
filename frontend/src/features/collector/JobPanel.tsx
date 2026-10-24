import { useMutation } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertOctagon, Ban, BarChart3, BellRing, Check, Clock, DownloadCloud, ExternalLink, EyeOff, Hourglass, MessageCircle, SkipForward, Square, TextSearch, UserCheck, UserPlus, Users, Zap } from 'lucide-react'
import { TypeBadge } from '../../components/SourceBits'
import { useQuery } from '@tanstack/react-query'
import { PeerLine } from '../../components/PeerBits'
import { Link } from 'react-router-dom'
import { useEffect, useState, type ReactNode } from 'react'
import { Avatar } from '../../components/Avatar'
import { Badge, Button, Card, ProgressBar } from '../../components/ui'
import { api, type Job, type PeerCard, type Phase } from '../../lib/api'
import { compact, duration, num, relative } from '../../lib/format'
import { isTerminal } from './useJob'

const STEPS: { key: Phase; label: string }[] = [
  { key: 'resolve', label: 'Канал' },
  { key: 'scan', label: 'Комментарии' },
  { key: 'avatars', label: 'Аватарки' },
  { key: 'done', label: 'Готово' },
]
const CHAT_STEPS: { key: Phase; label: string }[] = [
  { key: 'resolve', label: 'Чат' },
  { key: 'scan', label: 'Сообщения' },
  { key: 'members', label: 'Участники' },
  { key: 'avatars', label: 'Аватарки' },
  { key: 'done', label: 'Готово' },
]
const PHASE_ORDER: Phase[] = ['queued', 'starting', 'resolve', 'scan', 'members', 'saving', 'avatars', 'done']

function stepState(phase: Phase | undefined, step: Phase, chat: boolean): 'done' | 'active' | 'todo' {
  const cur = PHASE_ORDER.indexOf(phase === 'saving' ? (chat ? 'members' : 'scan') : (phase ?? 'queued'))
  const idx = PHASE_ORDER.indexOf(step)
  if (phase === 'done') return 'done'
  if (cur > idx) return 'done'
  if (cur === idx) return 'active'
  return 'todo'
}

function useCountdown(until: string | null | undefined) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!until) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [until])
  return until ? Math.max(0, Math.round((new Date(until).getTime() - now) / 1000)) : 0
}

function Stat({ icon, label, value, sub }: { icon: ReactNode; label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-1.5 text-[12px] text-fg-muted">
        <span className="text-fg-subtle">{icon}</span>
        {label}
      </div>
      <div className="mt-1 font-mono text-[22px] font-semibold tabular tracking-tight">{value}</div>
      {sub && <div className="text-[12px] text-fg-subtle">{sub}</div>}
    </div>
  )
}

export function JobPanel({ job }: { job: Job }) {
  const p = job.progress ?? {}
  const r = job.result ?? {}
  const ch = r.channel ?? p.channel
  const running = !isTerminal(job.status)
  const flood = useCountdown(p.flood_wait_until)
  const cancel = useMutation({ mutationFn: () => api(`/jobs/${job.id}/cancel`, { method: 'POST' }) })
  const skipAvatars = useMutation({ mutationFn: () => api(`/jobs/${job.id}/skip-avatars`, { method: 'POST' }) })
  const incremental = (r.mode ?? job.input.mode) === 'incremental' && !r.upgraded_to_full
  const chat = job.tool === 'chat-indexer'
  const steps = chat ? CHAT_STEPS : STEPS
  const membersStatus = r.members_status ?? p.members_status

  let pct: number | undefined
  let detail = ''
  if (p.phase === 'scan' && p.strategy === 'history') {
    pct = p.messages_total ? Math.min(100, ((p.messages_scanned ?? 0) / p.messages_total) * 100) : undefined
    detail = `${num(p.messages_scanned)}${p.messages_total ? ` из ~${num(p.messages_total)}` : ''} сообщений · ${num(p.unique_users)} авторов`
  } else if (p.phase === 'members') {
    pct = p.members_total ? Math.min(100, ((p.members_done ?? 0) / p.members_total) * 100) : undefined
    detail = `${num(p.members_done)}${p.members_total ? ` из ${num(p.members_total)}` : ''} участников`
  } else if (p.phase === 'scan' && p.strategy === 'fast' && p.messages_total) {
    pct = ((p.messages_scanned ?? 0) / p.messages_total) * 100
    detail = `${num(p.messages_scanned)} из ${num(p.messages_total)} сообщений группы`
  } else if (p.phase === 'scan' && p.strategy === 'per_post' && p.posts_total) {
    pct = ((p.posts_done ?? 0) / p.posts_total) * 100
    detail = `${num(p.posts_done)} из ${num(p.posts_total)} постов`
  } else if (p.phase === 'avatars' && p.avatars_total) {
    pct = ((p.avatars_done ?? 0) / p.avatars_total) * 100
    detail = `${num(p.avatars_done)} из ${num(p.avatars_total)} новых аватарок${p.avatars_cached ? ` · ${num(p.avatars_cached)} уже есть` : ''}`
  } else if (p.phase === 'saving') detail = 'Сохранение результатов…'
  else if (p.phase === 'resolve' || p.phase === 'starting') detail = chat ? 'Получение информации о чате…' : 'Получение информации о канале…'
  else if (p.phase === 'queued') detail = 'В очереди: аккаунт занят другой задачей'

  return (
    <Card className="animate-in overflow-hidden">
      {/* channel header */}
      <div className="flex flex-wrap items-center gap-4 border-b border-line px-5 py-4">
        {ch ? (
          <Avatar id={ch.id} name={ch.title} photoId={ch.photo_id} size={48} />
        ) : (
          <div className="size-12 animate-pulse rounded-full bg-muted" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-[16px] font-semibold">{ch?.title ?? job.input.channel}</h2>
            {ch?.type && <TypeBadge type={ch.type} />}
            <StatusBadge status={job.status} />
            {incremental && <Badge tone="accent"><DownloadCloud className="size-3" aria-hidden />дозабор</Badge>}
            {job.input.monitor_id && <Badge><BellRing className="size-3" aria-hidden />мониторинг</Badge>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[13px] text-fg-muted">
            {ch?.username && (
              <a href={`https://t.me/${ch.username}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-accent">
                @{ch.username} <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
            {ch?.subscribers != null && <span>{compact(ch.subscribers)} {chat ? 'участников' : 'подписчиков'}</span>}
            {ch?.group_title && <span className="text-fg-subtle">обсуждения: {ch.group_title}</span>}
            {ch?.linked_channel && <span className="text-fg-subtle">обсуждения канала «{ch.linked_channel.title}»</span>}
            <span className="text-fg-subtle">#{job.id} · {relative(job.created_at)}</span>
          </div>
        </div>
        {running && p.phase === 'avatars' && (
          <Button variant="ghost" size="sm" icon={<SkipForward className="size-3.5" />} loading={skipAvatars.isPending} disabled={skipAvatars.isSuccess} onClick={() => skipAvatars.mutate()}
            title="Данные уже сохранены — аватарки докачаются при следующем сборе">
            {skipAvatars.isSuccess ? 'Завершаем…' : 'Пропустить аватарки'}
          </Button>
        )}
        {running && (
          <Button variant="secondary" size="sm" icon={<Square className="size-3.5" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
            Остановить
          </Button>
        )}
        {!running && ch && job.status !== 'failed' && (
          <div className="flex gap-2">
            <Link to={`/channels/${ch.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong/70 bg-elevated px-3 text-[13px] font-medium hover:bg-muted">
              <BarChart3 className="size-3.5" aria-hidden /> Аналитика
            </Link>
            <Link to={`/users?source=${ch.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-fg-muted hover:bg-elevated hover:text-fg">
              <Users className="size-3.5" aria-hidden /> В «Пользователях»
            </Link>
            <Link to={`/search?source=${ch.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-fg-muted hover:bg-elevated hover:text-fg">
              <TextSearch className="size-3.5" aria-hidden /> Поиск
            </Link>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-5 px-5 py-5">
        {/* stepper */}
        {job.status !== 'failed' && job.status !== 'cancelled' && (
          <ol className={clsx('grid gap-2', chat ? 'grid-cols-5' : 'grid-cols-4')} aria-label="Этапы">
            {steps.map((s) => {
              const st = stepState(p.phase, s.key, chat)
              return (
                <li key={s.key} className="flex flex-col gap-2" aria-current={st === 'active' ? 'step' : undefined}>
                  <div className={clsx('h-1 rounded-full transition-colors duration-300', st === 'done' ? 'bg-success' : st === 'active' ? 'bg-accent' : 'bg-muted')} />
                  <span className={clsx('flex items-center gap-1 text-[12px]', st === 'todo' ? 'text-fg-subtle' : 'text-fg')}>
                    {st === 'done' && <Check className="size-3 text-success" aria-hidden />}
                    {s.label}
                  </span>
                </li>
              )
            })}
          </ol>
        )}

        {running && (
          <div className="flex flex-col gap-2">
            <ProgressBar label="Прогресс сбора" value={pct} indeterminate={pct === undefined} />
            <div className="flex flex-wrap justify-between gap-2 text-[13px] text-fg-muted">
              <span>{detail}</span>
              {pct !== undefined && <span className="font-mono tabular">{pct.toFixed(1)}%</span>}
            </div>
          </div>
        )}

        {flood > 0 && (
          <div role="status" className="flex items-center gap-3 rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-sm">
            <Hourglass className="size-4 shrink-0 text-warning" aria-hidden />
            <span>
              Telegram попросил подождать (FloodWait). Продолжим через <span className="font-mono font-semibold tabular">{flood} с</span>.
            </span>
          </div>
        )}

        {job.status === 'failed' && (
          <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm">
            <AlertOctagon className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
            <div>
              <div className="font-semibold text-danger">Сбор не удался</div>
              <div className="text-fg-muted">{job.error}</div>
            </div>
          </div>
        )}
        {job.status === 'cancelled' && (
          <div className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm text-fg-muted">
            <Ban className="size-4 shrink-0" aria-hidden /> Сбор остановлен — ниже данные, собранные до остановки.
          </div>
        )}

        {r.upgraded_to_full && (
          <p className="rounded-xl border border-line bg-surface px-4 py-3 text-[13px] text-fg-muted">
            {chat ? 'Чат индексировался впервые' : 'Канал собирался впервые'}, поэтому вместо дозабора выполнен полный сбор. Следующие запуски будут читать только новое.
          </p>
        )}
        {!running && membersStatus === 'hidden' && (
          <p className="flex items-start gap-2 rounded-xl border border-line bg-surface px-4 py-3 text-[13px] text-fg-muted">
            <EyeOff className="mt-0.5 size-4 shrink-0" aria-hidden /> Админы скрыли список участников: в людях чата только авторы сообщений (и админы, если их видно).
          </p>
        )}
        {!running && membersStatus === 'partial' && (
          <p className="rounded-xl border border-warning/30 bg-warning-soft px-4 py-3 text-[13px] text-fg-muted">
            Telegram отдал не всех участников (лимит ~10 000 у больших групп): получено {num(r.members_fetched)} из {num(ch?.subscribers)}. Авторы сообщений собраны полностью.
          </p>
        )}

        {chat ? (
          incremental ? (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat icon={<MessageCircle className="size-3.5" />} label="Новых сообщений" value={num(r.new_comments ?? p.messages_scanned ?? 0)} />
              <Stat icon={<UserPlus className="size-3.5" />} label="Новых людей" value={r.new_users != null ? `+${num(r.new_users)}` : '…'} sub={r.new_users ? `из них написали: ${num(r.new_authors)}` : undefined} />
              <Stat icon={<Users className="size-3.5" />} label="Всего людей" value={r.total_users != null ? num(r.total_users) : '…'} sub={r.members != null ? `участников: ${num(r.members)}` : undefined} />
              <Stat icon={<Clock className="size-3.5" />} label={running ? 'Скорость' : 'Длительность'} value={running ? (p.rate ? `${num(p.rate)}/с` : '—') : duration(r.duration_sec)} />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat icon={<MessageCircle className="size-3.5" />} label="Сообщений" value={num(r.comments ?? p.messages_scanned ?? 0)} sub={r.posts_with_comments ? `${num(r.posts_with_comments)} ${r.thread_unit === 'topic' ? 'тем' : 'дней'}` : undefined} />
              <Stat icon={<Users className="size-3.5" />} label="Писали" value={num(r.unique_users ?? p.unique_users ?? 0)} sub={r.new_users ? `+${num(r.new_users)} новых людей` : undefined} />
              <Stat icon={<UserCheck className="size-3.5" />} label="Участников" value={membersStatus === 'hidden' ? 'скрыты' : membersStatus === 'skipped' ? '—' : num(r.members ?? p.members_done ?? 0)}
                sub={r.people ? `всего людей: ${num(r.people)}` : undefined} />
              <Stat icon={<Clock className="size-3.5" />} label={running ? 'Скорость' : 'Длительность'} value={running ? (p.rate ? `${num(p.rate)}/с` : '—') : duration(r.duration_sec)} />
            </div>
          )
        ) : incremental ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat icon={<MessageCircle className="size-3.5" />} label="Новых комментариев" value={num(r.new_comments ?? p.comments ?? 0)} />
            <Stat icon={<UserPlus className="size-3.5" />} label="Новых людей" value={r.new_users != null ? `+${num(r.new_users)}` : '…'} sub={r.total_users ? `всего ${num(r.total_users)}` : undefined} />
            <Stat icon={<Users className="size-3.5" />} label="Всего комментариев" value={r.total_comments != null ? num(r.total_comments) : '…'} />
            <Stat icon={<Clock className="size-3.5" />} label={running ? 'Скорость' : 'Длительность'} value={running ? (p.rate ? `${num(p.rate)}/с` : '—') : duration(r.duration_sec)} />
          </div>
        ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat icon={<Users className="size-3.5" />} label="Пользователей" value={num(r.unique_users ?? p.unique_users ?? 0)} sub={r.new_users ? `+${num(r.new_users)} новых` : undefined} />
          <Stat icon={<MessageCircle className="size-3.5" />} label="Комментариев" value={num(r.comments ?? p.comments ?? 0)} />
          <Stat
            icon={<Zap className="size-3.5" />}
            label="Постов с комментариями"
            value={num(r.posts_with_comments ?? p.posts_with_comments ?? 0)}
            sub={(() => {
              const total = r.posts_total ?? p.posts_total
              const v = r.posts_with_comments ?? p.posts_with_comments ?? 0
              return total ? (v <= total ? `из ${num(total)} постов` : `в т.ч. удалённые посты (сейчас ${num(total)})`) : undefined
            })()}
          />
          <Stat
            icon={<Clock className="size-3.5" />}
            label={running ? 'Скорость' : 'Длительность'}
            value={running ? (p.rate ? `${num(p.rate)}/с` : '—') : duration(r.duration_sec)}
            sub={(r.strategy ?? p.strategy) && `режим: ${(r.strategy ?? p.strategy) === 'fast' ? 'быстрый' : 'по постам'}`}
          />
        </div>
        )}

        {r.avatars && !running && (
          <p className="text-[12.5px] text-fg-subtle">
            Аватарки: скачано {num(r.avatars.downloaded)}, уже были {num(r.avatars.cached)}
            {r.avatars.failed ? `, недоступно ${num(r.avatars.failed)}` : ''}
            {r.avatars.skipped ? `, отложено ${num(r.avatars.skipped)} (докачаются при следующем сборе)` : ''}
          </p>
        )}
        {p.avatars_interrupted && <p className="text-[12.5px] text-fg-subtle">Сервер перезапускался во время загрузки аватарок — данные сохранены, аватарки докачаются при следующем сборе.</p>}

        {!running && !!r.new_user_ids?.length && <NewPeople ids={r.new_user_ids} total={r.new_users ?? r.new_user_ids.length} />}
      </div>
    </Card>
  )
}

function NewPeople({ ids, total }: { ids: number[]; total: number }) {
  const q = useQuery({ queryKey: ['peers', ids.slice(0, 60).join(',')], queryFn: () => api<PeerCard[]>(`/peers?ids=${ids.slice(0, 60).join(',')}`) })
  return (
    <div className="rounded-xl border border-success/25 bg-success-soft/40 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <UserPlus className="size-4 text-success" aria-hidden /> Новые люди с прошлого сбора
        <span className="font-mono text-[12px] text-fg-muted">+{num(total)}</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {q.data?.map((p) => (
          <li key={p.peer_id} className="min-w-0 rounded-lg bg-card px-2.5 py-2"><PeerLine p={p} size={28} /></li>
        ))}
      </ul>
      {total > 60 && <p className="mt-2 text-[12.5px] text-fg-subtle">Показаны первые 60.</p>}
    </div>
  )
}

export function StatusBadge({ status }: { status: Job['status'] }) {
  switch (status) {
    case 'done':
      return <Badge tone="success">Готово</Badge>
    case 'failed':
      return <Badge tone="danger">Ошибка</Badge>
    case 'cancelled':
      return <Badge>Остановлено</Badge>
    case 'queued':
      return <Badge tone="warning">В очереди</Badge>
    default:
      return (
        <Badge tone="accent">
          <span className="relative flex size-1.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-accent opacity-75" />
            <span className="relative inline-flex size-1.5 rounded-full bg-accent" />
          </span>
          Идёт сбор
        </Badge>
      )
  }
}
