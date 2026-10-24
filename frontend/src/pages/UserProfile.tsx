import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Activity, ArrowLeft, EyeOff, CalendarClock, Copy, CornerDownRight, ExternalLink, Hash, Layers, Radar, MessageCircle, MessagesSquare, Network, Plus, ShieldAlert, Star, TextSearch, UserCheck, X, Megaphone,
} from 'lucide-react'
import { TypeIcon } from '../components/SourceBits'
import { useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { BarList, Heatmap, TimeBars } from '../components/charts'
import { InteractiveGraph } from '../components/InteractiveGraph'
import { Flags, PeerLine, Stat, pct } from '../components/PeerBits'
import { useToast } from '../components/Toast'
import { Badge, Card, CardHeader, EmptyState, Segmented, Skeleton } from '../components/ui'
import { Page } from '../layout/AppLayout'
import { api, type Connections, type GraphData, type Timeline, type UserComment, type UserProfile as Profile } from '../lib/api'
import { date, dateTime, num, relative } from '../lib/format'

function TagEditor({ peerId, tags, starred, note, ignored }: { peerId: number; tags: string[]; starred: boolean; note: string | null; ignored: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [input, setInput] = useState('')
  const [text, setText] = useState(note ?? '')
  const save = useMutation({
    mutationFn: (body: { tags?: string[]; note?: string; starred?: boolean; ignored?: boolean }) => api(`/users/${peerId}/note`, { method: 'PUT', json: body }),
    onSuccess: (_, body) => {
      for (const k of ['user', 'users', 'tags', 'graph', 'overview', 'overlap', 'source', 'ignored']) qc.invalidateQueries({ queryKey: [k] })
      if (body.ignored !== undefined)
        toast(body.ignored ? 'Пользователь исключён из списков, графов и уведомлений' : 'Пользователь снова учитывается', 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const add = () => {
    const t = input.trim()
    if (t && !tags.includes(t)) save.mutate({ tags: [...tags, t] })
    setInput('')
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          onClick={() => save.mutate({ starred: !starred })}
          aria-pressed={starred}
          className={clsx('flex h-7 items-center gap-1 rounded-full border px-2.5 text-[12.5px] transition-colors', starred ? 'border-warning/50 bg-warning-soft text-warning' : 'border-line text-fg-muted hover:text-fg')}
        >
          <Star className={clsx('size-3.5', starred && 'fill-warning')} aria-hidden /> {starred ? 'В избранном' : 'В избранное'}
        </button>
        <button
          onClick={() => save.mutate({ ignored: !ignored })}
          aria-pressed={ignored}
          title="Не показывать в списках, графах, пересечениях и уведомлениях"
          className={clsx('flex h-7 items-center gap-1 rounded-full border px-2.5 text-[12.5px] transition-colors', ignored ? 'border-danger/40 bg-danger-soft text-danger' : 'border-line text-fg-muted hover:text-fg')}
        >
          <EyeOff className="size-3.5" aria-hidden /> {ignored ? 'Игнорируется' : 'Игнорировать'}
        </button>
        {tags.map((t) => (
          <span key={t} className="flex h-7 items-center gap-1 rounded-full bg-accent-soft pr-1 pl-2.5 text-[12.5px] text-accent">
            <Link to={`/users?tag=${encodeURIComponent(t)}`} className="hover:underline">{t}</Link>
            <button aria-label={`Убрать метку ${t}`} onClick={() => save.mutate({ tags: tags.filter((x) => x !== t) })} className="rounded-full p-0.5 hover:bg-accent/20">
              <X className="size-3" />
            </button>
          </span>
        ))}
        <span className="flex h-7 items-center rounded-full border border-dashed border-line-strong pl-2.5">
          <input
            aria-label="Новая метка"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e: KeyboardEvent) => e.key === 'Enter' && (e.preventDefault(), add())}
            placeholder="метка"
            className="w-20 bg-transparent text-[12.5px] outline-none placeholder:text-fg-subtle"
          />
          <button aria-label="Добавить метку" onClick={add} className="px-1.5 text-fg-muted hover:text-fg">
            <Plus className="size-3.5" />
          </button>
        </span>
      </div>
      <textarea
        aria-label="Заметка"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => text !== (note ?? '') && save.mutate({ note: text })}
        placeholder="Заметка о пользователе — сохраняется при выходе из поля"
        rows={2}
        className="w-full resize-y rounded-[10px] border border-line bg-surface px-3 py-2 text-[13.5px] outline-none placeholder:text-fg-subtle focus:border-accent"
      />
    </div>
  )
}

function Signals({ s }: { s: Profile['signals'] }) {
  if (!s.comments) return null
  const score = s.spam_score ?? 0
  const tone = score >= 60 ? 'danger' : score >= 30 ? 'warning' : 'success'
  return (
    <Card>
      <CardHeader icon={<ShieldAlert className="size-4" />} title="Поведенческие сигналы" description="Эвристики по текстам комментариев" />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex items-center gap-3">
          <div className={clsx('font-mono text-3xl font-semibold tabular', tone === 'danger' ? 'text-danger' : tone === 'warning' ? 'text-warning' : 'text-success')}>{score}</div>
          <div>
            <div className="text-sm font-medium">
              {tone === 'danger' ? 'Похоже на спам/бота' : tone === 'warning' ? 'Есть подозрительные признаки' : 'Выглядит как живой человек'}
            </div>
            <div className="text-[12px] text-fg-subtle">индекс подозрительности 0–100</div>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-[13px]">
          {[
            ['Средняя длина', `${s.avg_length} симв.`],
            ['Повторы текста', pct(s.duplicate_share)],
            ['Со ссылками', pct(s.link_share)],
            ['Только медиа', pct(s.media_only_share)],
            ['Активных дней', num(s.active_days)],
            ['Макс. в день', num(s.max_per_day)],
          ].map(([k, v]) => (
            <div key={k} className="rounded-lg border border-line bg-surface px-3 py-2">
              <dt className="text-[11.5px] text-fg-subtle">{k}</dt>
              <dd className="font-mono">{v}</dd>
            </div>
          ))}
        </dl>
        {s.top_duplicate && (
          <p className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg-muted">
            Чаще всего пишет: <span className="text-fg">«{s.top_duplicate}»</span>
          </p>
        )}
      </div>
    </Card>
  )
}

function ConnectionsCard({ peerId }: { peerId: number }) {
  const q = useQuery({ queryKey: ['user', peerId, 'connections'], queryFn: () => api<Connections>(`/users/${peerId}/connections?limit=30`) })
  const [tab, setTab] = useState<'co' | 'dialogs'>('co')
  const items = tab === 'co' ? q.data?.co_commenters : q.data?.dialogs
  return (
    <Card>
      <CardHeader
        icon={<MessagesSquare className="size-4" />}
        title="Связи"
        description={tab === 'co' ? 'Кто чаще всего комментирует те же посты' : 'С кем переписывается в ответах'}
        actions={<Segmented label="Тип связи" value={tab} onChange={setTab} options={[{ value: 'co', label: 'Рядом' }, { value: 'dialogs', label: 'Диалоги' }]} />}
      />
      <div className="max-h-[420px] overflow-y-auto scrollbar-thin">
        {q.isLoading ? (
          <div className="flex flex-col gap-2 p-5"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
        ) : !items?.length ? (
          <EmptyState icon={<Network className="size-5" />} title={tab === 'co' ? 'Нет общих постов' : 'Нет переписок'} description={tab === 'dialogs' ? 'Ответы между комментаторами сохраняются при новых сборах' : undefined} />
        ) : (
          <ul className="divide-y divide-line/70">
            {items.map((p) => (
              <li key={p.peer_id} className="flex items-center gap-3 px-5 py-2.5">
                <div className="min-w-0 flex-1"><PeerLine p={p} /></div>
                {'shared_posts' in p ? (
                  <div className="text-right">
                    <div className="font-mono text-[13.5px] font-semibold tabular">{num(p.shared_posts)}</div>
                    <div className="text-[11px] text-fg-subtle">общих постов · {pct(p.overlap)}</div>
                  </div>
                ) : (
                  <div className="text-right">
                    <div className="font-mono text-[13.5px] font-semibold tabular">{num(p.replied_to + p.replied_by)}</div>
                    <div className="text-[11px] text-fg-subtle">→ {p.replied_to} · ← {p.replied_by}</div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

function CommentsFeed({ peerId, sources }: { peerId: number; sources: Profile['sources'] }) {
  const [sourceId, setSourceId] = useState<number | null>(null)
  const q = useQuery({
    queryKey: ['user', peerId, 'comments', sourceId],
    queryFn: () => api<UserComment[]>(`/users/${peerId}/comments?limit=100${sourceId != null ? `&source_id=${sourceId}` : ''}`),
  })
  return (
    <Card>
      <CardHeader icon={<MessageCircle className="size-4" />} title="Сообщения и комментарии" description="Последние 100, по всем источникам"
        actions={<Link to={`/search?sender=${peerId}${sourceId != null ? `&source=${sourceId}` : ''}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium text-fg-muted hover:bg-elevated hover:text-fg"><TextSearch className="size-3.5" aria-hidden />Искать в его сообщениях</Link>} />
      {sources.length > 1 && (
        <div className="flex flex-wrap gap-1.5 border-b border-line px-5 py-3">
          {[{ id: null as number | null, title: 'Все' }, ...sources.filter((s) => s.comments).map((s) => ({ id: s.source.id, title: s.source.title }))].map((s) => (
            <button
              key={String(s.id)}
              onClick={() => setSourceId(s.id)}
              aria-pressed={sourceId === s.id}
              className={clsx('h-7 rounded-full border px-2.5 text-[12.5px] transition-colors', sourceId === s.id ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}
            >
              {s.title}
            </button>
          ))}
        </div>
      )}
      <ul className="max-h-[560px] divide-y divide-line/70 overflow-y-auto scrollbar-thin">
        {q.isLoading && <li className="p-5"><Skeleton className="h-14" /></li>}
        {q.data?.map((c) => (
          <li key={`${c.source.id}:${c.msg_id}`} className="px-5 py-3">
            <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12px] text-fg-subtle">
              <Link to={`/channels/${c.source.id}`} className="flex items-center gap-1.5 text-fg-muted hover:text-accent">
                <Avatar id={c.source.id} name={c.source.title} photoId={c.source.photo_id} size={16} square={c.source.family !== 'chat'} /> {c.source.title}
              </Link>
              <span>{c.thread ?? `пост #${c.post_id}`}</span>
              <span>{dateTime(c.date)}</span>
              {c.reply_to && (
                <Link to={`/users/${c.reply_to.peer_id}`} className="flex items-center gap-1 text-fg-muted hover:text-accent">
                  <CornerDownRight className="size-3" aria-hidden /> ответ {c.reply_to.username ? `@${c.reply_to.username}` : c.reply_to.name}
                </Link>
              )}
              {c.link && (
                <a href={c.link} target="_blank" rel="noreferrer" className="ml-auto flex items-center gap-1 text-accent hover:underline">
                  открыть <ExternalLink className="size-3" aria-hidden />
                </a>
              )}
            </div>
            <p className="text-[13.5px] break-words whitespace-pre-wrap">{c.text || <span className="text-fg-subtle italic">медиа без текста</span>}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function UserProfile() {
  const { peerId: raw } = useParams()
  const peerId = Number(raw)
  const navigate = useNavigate()
  const toast = useToast()
  const profile = useQuery({ queryKey: ['user', peerId], queryFn: () => api<Profile>(`/users/${peerId}`) })
  const activity = useQuery({ queryKey: ['user', peerId, 'activity'], queryFn: () => api<{ timeline: Timeline; heatmap: number[][] }>(`/users/${peerId}/activity`) })
  const graph = useQuery({ queryKey: ['user', peerId, 'graph'], queryFn: () => api<GraphData>(`/users/${peerId}/graph?limit=25`) })

  if (profile.isLoading)
    return (
      <Page wide>
        <Skeleton className="mb-5 h-36 rounded-[var(--radius-card)]" />
        <Skeleton className="h-96 rounded-[var(--radius-card)]" />
      </Page>
    )
  if (!profile.data)
    return (
      <Page>
        <Card><EmptyState icon={<Hash className="size-5" />} title="Пользователь не найден" description={profile.error?.message} /></Card>
      </Page>
    )
  const { peer: p, totals, sources, signals, note, about, channels } = profile.data
  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(`Скопировано: ${v}`, 'success'))

  return (
    <Page wide>
      <button onClick={() => navigate(-1)} className="mb-4 flex items-center gap-1.5 text-[13px] text-fg-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Назад
      </button>

      <Card className="mb-5 p-5">
        <div className="flex flex-wrap items-start gap-5">
          <Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={76} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[22px] font-semibold tracking-tight">{p.name}</h1>
              <Flags p={p} />
              {p.is_premium && <Badge tone="accent">Premium</Badge>}
              {p.kind !== 'user' && <Badge><Megaphone className="size-3" aria-hidden />Канал</Badge>}
              {p.ignored && <Badge tone="danger"><EyeOff className="size-3" aria-hidden />игнорируется</Badge>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13.5px] text-fg-muted">
              {p.username ? (
                <a href={`https://t.me/${p.username}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-accent hover:underline">
                  @{p.username} <ExternalLink className="size-3" aria-hidden />
                </a>
              ) : (
                <span className="text-fg-subtle">без username</span>
              )}
              <button onClick={() => copy(String(p.peer_id))} className="flex items-center gap-1 font-mono hover:text-fg" aria-label={`Скопировать ID ${p.peer_id}`}>
                ID {p.peer_id} <Copy className="size-3" aria-hidden />
              </button>
              {p.usernames.length > 1 && <span>также: {p.usernames.slice(1).map((u) => `@${u}`).join(', ')}</span>}
              {p.phone && <span className="font-mono">+{p.phone}</span>}
              {p.username && (
                <a href={`tg://resolve?domain=${p.username}`} className="flex items-center gap-1 hover:text-fg">открыть в Telegram</a>
              )}
            </div>
            {about && <p className="mt-2 max-w-2xl text-[13.5px] whitespace-pre-line text-fg-muted">{about}</p>}
            <div className="mt-4 max-w-2xl">
              <TagEditor key={p.peer_id} peerId={p.peer_id} tags={p.tags} starred={p.starred} note={note} ignored={p.ignored} />
            </div>
          </div>
        </div>
      </Card>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat icon={<MessageCircle className="size-3.5" />} label="Сообщений" value={num(totals.comments)} sub="комментарии + чаты" />
        <Stat icon={<Layers className="size-3.5" />} label="Источников" value={num(totals.sources)}
          sub={totals.member_of ? `пишет в ${num(totals.active_sources)}, состоит в ${num(totals.member_of)}` : undefined} />
        <Stat icon={<Hash className="size-3.5" />} label="Обсуждений" value={num(totals.posts)} sub="постов, тем и дней" />
        <Stat icon={<CalendarClock className="size-3.5" />} label="Первый" value={<span className="text-[17px]">{date(totals.first_at)}</span>} />
        <Stat icon={<Activity className="size-3.5" />} label="Последний" value={<span className="text-[17px]">{date(totals.last_at)}</span>} sub={relative(totals.last_at)} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader
              icon={<Network className="size-4" />}
              title="Граф связей"
              description="Каналы и чаты, где он есть, и люди, с которыми он пересекается в обсуждениях и переписке"
            />
            <div className="p-3">
              {graph.data ? (
                graph.data.nodes.length > 1 ? (
                  <InteractiveGraph data={graph.data} focusId={`u:${peerId}`} />
                ) : (
                  <EmptyState icon={<Network className="size-5" />} title="Связей пока нет" />
                )
              ) : (
                <Skeleton className="h-[520px] rounded-xl" />
              )}
            </div>
          </Card>

          <Card>
            <CardHeader icon={<Activity className="size-4" />} title="Активность" description="Сообщения и комментарии по времени" />
            <div className="flex flex-col gap-6 p-5">
              {activity.data ? (
                <>
                  <TimeBars data={activity.data.timeline} />
                  <div>
                    <h3 className="mb-3 text-[13px] font-medium text-fg-muted">Когда пишет (дни × часы, ваше время)</h3>
                    <Heatmap grid={activity.data.heatmap} />
                  </div>
                </>
              ) : (
                <Skeleton className="h-48" />
              )}
            </div>
          </Card>

          <CommentsFeed peerId={peerId} sources={sources} />
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader icon={<Layers className="size-4" />} title="Где пишет" description="Место в рейтинге авторов каждого канала и чата" />
            <div className="p-5">
              {sources.some((s) => s.comments) ? (
                <BarList
                  items={sources.filter((s) => s.comments).map((s) => ({
                    key: s.source.id,
                    value: s.comments,
                    hint: `${pct(s.share, 1)} всех ${s.source.family === 'chat' ? 'сообщений чата' : 'комментариев канала'}`,
                    label: (
                      <Link to={`/channels/${s.source.id}`} className="flex min-w-0 items-center gap-2 hover:text-accent">
                        <Avatar id={s.source.id} name={s.source.title} photoId={s.source.photo_id} size={20} square={s.source.family !== 'chat'} />
                        <span className="truncate">{s.source.title}</span>
                        <TypeIcon type={s.source.type} className="size-3 shrink-0 text-fg-subtle" />
                        {s.rank != null && <span className="shrink-0 font-mono text-[11.5px] text-fg-subtle">#{s.rank} из {num(s.of)}</span>}
                      </Link>
                    ),
                  }))}
                />
              ) : (
                <p className="text-[13px] text-fg-subtle">Ничего не писал — найден только в списках участников.</p>
              )}
            </div>
          </Card>
          {sources.some((s) => s.member) && (
            <Card>
              <CardHeader icon={<UserCheck className="size-4" />} title="Состоит в чатах" description="По спискам участников" />
              <ul className="flex flex-col gap-1 p-3">
                {sources.filter((s) => s.member).map((s) => (
                  <li key={s.source.id}>
                    <Link to={`/channels/${s.source.id}`} className="flex h-10 items-center gap-2.5 rounded-lg px-2 text-[13.5px] hover:bg-elevated">
                      <Avatar id={s.source.id} name={s.source.title} photoId={s.source.photo_id} size={24} />
                      <span className="min-w-0 flex-1 truncate">{s.source.title}</span>
                      {s.role && s.role !== 'member' && <Badge tone="warning">{s.role === 'creator' ? 'владелец' : 'админ'}</Badge>}
                      <span className="font-mono text-[12px] text-fg-subtle tabular">{s.comments ? `${num(s.comments)} сообщ.` : 'молчит'}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {channels.length > 0 && (
            <Card>
              <CardHeader icon={<Radar className="size-4" />} title="Его каналы" description="Из профиля и bio — найдены поиском каналов пользователей" />
              <ul className="flex flex-col gap-1 p-3">
                {channels.map((c) => (
                  <li key={c.key} className="flex min-h-10 items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13.5px] hover:bg-elevated">
                    {c.type ? <TypeIcon type={c.type} className="size-4 shrink-0 text-fg-subtle" /> : <Megaphone className="size-4 shrink-0 text-fg-subtle" aria-hidden />}
                    <div className="min-w-0 flex-1">
                      {c.is_source && c.peer_id
                        ? <Link to={`/channels/${c.peer_id}`} className="block truncate hover:text-accent">{c.title}</Link>
                        : <span className="block truncate">{c.title}</span>}
                      <span className="text-[12px] text-fg-subtle">
                        {c.via.includes('personal') ? 'в профиле' : 'в bio'}
                        {c.username && ` · @${c.username}`}
                        {c.members_count != null && ` · ${num(c.members_count)}`}
                      </span>
                    </div>
                    {c.is_source ? <Badge tone="success">источник</Badge> : c.private ? <Badge tone="warning">приватный</Badge> : null}
                    {c.link && (
                      <a href={c.link} target="_blank" rel="noreferrer" aria-label={`Открыть ${c.title} в Telegram`} className="rounded-md p-1 text-fg-subtle hover:text-fg">
                        <ExternalLink className="size-3.5" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
              <div className="border-t border-line px-5 py-3">
                <Link to="/users/channels" className="text-[12.5px] text-accent hover:underline">Все найденные каналы →</Link>
              </div>
            </Card>
          )}
          <ConnectionsCard peerId={peerId} />
          <Signals s={signals} />
        </div>
      </div>
    </Page>
  )
}
