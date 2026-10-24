import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowLeft, Clock, Crown, EyeOff, ExternalLink, GitCompareArrows, MessageCircle, PieChart, TextSearch, Trophy, UserCheck, UserPlus, Users } from 'lucide-react'
import { TypeBadge, words } from '../components/SourceBits'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { BarList, Heatmap, SERIES, StackedBars, TimeBars, bucketLabel } from '../components/charts'
import { PeerLine, Stat, pct, useSourceMap } from '../components/PeerBits'
import { Badge, Button, Card, CardHeader, EmptyState, Segmented, Skeleton } from '../components/ui'
import { Page } from '../layout/AppLayout'
import { api, type SourceAnalytics } from '../lib/api'
import { compact, date, num, relative } from '../lib/format'
import { SourceActions } from '../components/SourceActions'
import { ChannelContactsCard, ChannelPostsCard } from '../components/ChannelExtras'
import { PdfButton } from '../components/Enrichment'

export default function ChannelAnalytics() {
  const { sourceId: raw } = useParams()
  const sourceId = Number(raw)
  const navigate = useNavigate()
  const sourceMap = useSourceMap()
  const [series, setSeries] = useState<'comments' | 'users'>('comments')
  const q = useQuery({ queryKey: ['source', sourceId], queryFn: () => api<SourceAnalytics>(`/sources/${sourceId}/analytics`) })

  if (q.isLoading)
    return (
      <Page wide>
        <Skeleton className="mb-5 h-28 rounded-[var(--radius-card)]" />
        <Skeleton className="h-80 rounded-[var(--radius-card)]" />
      </Page>
    )
  if (!q.data)
    return (
      <Page>
        <Card><EmptyState icon={<PieChart className="size-5" />} title="Источник не найден" description={q.error?.message} /></Card>
      </Page>
    )
  const a = q.data
  const s = a.source
  const seg = a.segments
  const avg = s.users ? s.comments / s.users : 0
  const coverage = s.posts_total && s.posts_with_comments != null ? s.posts_with_comments / s.posts_total : null
  const chat = s.family === 'chat'
  const w = words(s.family)
  const threadTitle = s.thread_unit === 'topic' ? 'Самые активные темы' : s.thread_unit === 'day' ? 'Самые активные дни' : 'Самые обсуждаемые посты'
  const aud = a.audience

  return (
    <Page wide>
      <button onClick={() => navigate(-1)} className="mb-4 flex items-center gap-1.5 text-[13px] text-fg-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Назад
      </button>

      <Card className="mb-5 flex flex-wrap items-center gap-4 p-5">
        <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={60} square={!chat} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[22px] font-semibold tracking-tight">{s.title}</h1>
            <TypeBadge type={s.type} />
            {s.partial && <Badge tone="warning">частичный сбор</Badge>}
            {s.hidden && <Badge><EyeOff className="size-3" aria-hidden />отключён из аналитики</Badge>}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[13px] text-fg-muted">
            {s.username && (
              <a href={`https://t.me/${s.username}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-accent">
                @{s.username} <ExternalLink className="size-3" aria-hidden />
              </a>
            )}
            {s.subscribers != null && <span>{compact(s.subscribers)} {chat ? 'участников' : 'подписчиков'}</span>}
            {s.linked_channel && <Link to={`/channels/${s.linked_channel.id}`} className="hover:text-accent">обсуждения канала «{s.linked_channel.title}»</Link>}
            <span className="text-fg-subtle">обновлён {relative(s.collected_at)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" icon={<Users className="size-4" />} onClick={() => navigate(`/users?source=${s.id}`)}>{chat ? 'Люди' : 'Комментаторы'}</Button>
          <Button variant="ghost" icon={<TextSearch className="size-4" />} onClick={() => navigate(`/search?source=${s.id}`)}>Поиск</Button>
          <PdfButton href={`/api/sources/${s.id}/report.pdf`} label="Отчёт PDF" />
          <SourceActions source={s} />
        </div>
      </Card>

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat icon={<Users className="size-3.5" />} label={w.authors} value={num(s.users)} sub={s.subscribers ? `${((s.users / s.subscribers) * 100).toFixed(2)}% ${chat ? 'участников' : 'подписчиков'}` : undefined} />
        <Stat icon={<MessageCircle className="size-3.5" />} label={w.items} value={num(s.comments)} sub={`${avg.toFixed(1)} на автора`} />
        {chat ? (
          <Stat icon={<UserCheck className="size-3.5" />} label="Участников" value={s.members_status === 'hidden' ? 'скрыты' : num(aud.members)}
            sub={aud.members ? `молчат ${pct(aud.silent / aud.members)}` : s.members_status === 'hidden' ? 'админы скрыли список' : undefined} />
        ) : (
          <Stat icon={<Activity className="size-3.5" />} label="Посты с обсуждением" value={pct(coverage)} sub={s.posts_total ? `${num(s.posts_with_comments)} из ${num(s.posts_total)}` : undefined} />
        )}
        <Stat icon={<Trophy className="size-3.5" />} label="Топ-10% пишут" value={pct(a.concentration.top10pct)} sub={`всех ${w.items.toLowerCase()}`} />
        <Stat icon={<Crown className="size-3.5" />} label="Premium" value={pct(seg.total ? seg.premium / seg.total : 0)} sub={`${num(seg.premium)} польз.`} />
      </div>

      <div className="mb-5 grid items-start gap-5 lg:grid-cols-2">
        {chat ? <ChannelContactsCard sourceId={s.id} /> : (
          <>
            <ChannelPostsCard sourceId={s.id} username={s.username} />
            <ChannelContactsCard sourceId={s.id} />
          </>
        )}
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader
              icon={<Activity className="size-4" />}
              title="Динамика обсуждений"
              description={`по ${a.timeline.bucket === 'day' ? 'дням' : a.timeline.bucket === 'week' ? 'неделям' : 'месяцам'}`}
              actions={<Segmented label="Мера" value={series} onChange={setSeries} options={[{ value: 'comments', label: chat ? 'Сообщения' : 'Комментарии' }, { value: 'users', label: 'Авторы' }]} />}
            />
            <div className="p-5">
              <TimeBars data={a.timeline} series={series} color={series === 'comments' ? SERIES[0] : SERIES[1]} height={200} />
            </div>
          </Card>

          <Card>
            <CardHeader icon={<UserPlus className="size-4" />} title="Новые и вернувшиеся" description="Активные авторы по месяцам: впервые и уже писавшие раньше" />
            <div className="p-5">
              <StackedBars
                data={a.cohorts.map((c) => ({ t: c.month, values: [c.new, c.returning] }))}
                keys={['новые', 'вернувшиеся']}
                labels={(t) => bucketLabel(`${t}-01`, 'month')}
              />
            </div>
          </Card>

          <Card>
            <CardHeader icon={<Clock className="size-4" />} title="Когда обсуждают" description="Дни недели × часы, в вашем часовом поясе" />
            <div className="p-5"><Heatmap grid={a.heatmap} /></div>
          </Card>

          <Card>
            <CardHeader icon={<MessageCircle className="size-4" />} title={threadTitle} />
            <ul className="divide-y divide-line/70">
              {a.top_posts.map((p, i) => (
                <li key={p.post_id} className="flex items-center gap-3 px-5 py-2.5 text-[13.5px]">
                  <span className="w-5 font-mono text-[12px] text-fg-subtle">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {p.label ?? `Пост #${p.post_id}`} {s.thread_unit !== 'day' && <span className="text-fg-subtle">· {date(p.first_at)}</span>}
                  </span>
                  <span className="font-mono tabular">{num(p.comments)}</span>
                  <span className="w-24 text-right text-[12px] text-fg-muted">{num(p.users)} авторов</span>
                  {p.link ? (
                    <a href={p.link} target="_blank" rel="noreferrer" aria-label={`Открыть пост ${p.post_id}`} className="text-fg-subtle hover:text-accent"><ExternalLink className="size-4" /></a>
                  ) : <span className="size-4" />}
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Card>
            <CardHeader icon={<Trophy className="size-4" />} title="Самые активные" />
            <ul className="divide-y divide-line/70">
              {a.top_users.map((u) => (
                <li key={u.peer_id} className="flex items-center gap-3 px-5 py-2.5">
                  <div className="min-w-0 flex-1"><PeerLine p={u} /></div>
                  <span className="font-mono text-[13.5px] font-semibold tabular">{num(u.comments)}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader icon={<PieChart className="size-4" />} title="Сколько пишут" description={`Авторы по числу ${chat ? 'сообщений' : 'комментариев'}`} />
            <div className="p-5">
              <BarList items={a.distribution.map((d) => ({ key: d.label, label: `${d.label} ${chat ? 'сообщ.' : 'комм.'}`, value: d.users, hint: `${num(d.comments)} ${w.items.toLowerCase()}` }))} />
              <p className="mt-4 text-[12.5px] text-fg-muted">
                1% самых активных — <span className="font-mono text-fg">{pct(a.concentration.top1pct)}</span> {w.items.toLowerCase()}, топ-10 человек — <span className="font-mono text-fg">{pct(a.concentration.top10users)}</span>.
              </p>
            </div>
          </Card>

          {chat && aud.members > 0 && (
            <Card>
              <CardHeader icon={<UserCheck className="size-4" />} title="Участники и авторы" description="Список участников против тех, кто реально пишет" />
              <div className="p-5">
                <BarList
                  format={(v) => num(v)}
                  items={[
                    { key: 'm', label: 'В списке участников', value: aud.members },
                    { key: 'a', label: 'Писали хоть раз', value: aud.authors },
                    { key: 's', label: 'Молчуны (не писали)', value: aud.silent },
                    { key: 'o', label: 'Писали, но уже не в чате', value: aud.outside },
                    { key: 'ad', label: 'Админы и владелец', value: aud.admins },
                  ]}
                />
                <Link to={`/users?source=${s.id}&presence=silent`} className="mt-3 inline-block text-[12.5px] text-accent hover:underline">Открыть молчунов →</Link>
              </div>
            </Card>
          )}

          <Card>
            <CardHeader icon={<Users className="size-4" />} title="Состав аудитории" />
            <div className="p-5">
              <BarList
                format={(v) => pct(seg.total ? v / seg.total : 0)}
                items={[
                  { key: 'u', label: 'С username', value: seg.with_username },
                  { key: 'p', label: 'Premium', value: seg.premium },
                  { key: 'c', label: 'Пишут от имени канала', value: seg.channels },
                  { key: 'd', label: 'Удалённые аккаунты', value: seg.deleted },
                  { key: 'b', label: 'Боты', value: seg.bots },
                ]}
              />
            </div>
          </Card>

          <Card>
            <CardHeader
              icon={<GitCompareArrows className="size-4" />}
              title="Пересечения с другими источниками"
              description="Доля людей отсюда, которые есть и там"
            />
            {a.overlap.length ? (
              <div className="p-5">
                <BarList
                  format={(v) => `${(v * 100).toFixed(1)}%`}
                  color={SERIES[2]}
                  items={a.overlap.slice(0, 8).map((o) => {
                    const other = sourceMap.get(o.id)
                    return {
                      key: o.id,
                      value: o.share_of_mine,
                      hint: `${num(o.shared)} общих · Jaccard ${o.jaccard}`,
                      label: (
                        <Link to={`/overlap?ids=${s.id},${o.id}`} className="flex min-w-0 items-center gap-2 hover:text-accent">
                          <Avatar id={o.id} name={other?.title ?? '?'} photoId={other?.photo_id} size={20} square={other?.family !== 'chat'} />
                          <span className="truncate">{other?.title ?? o.id}</span>
                          <span className="shrink-0 font-mono text-[11.5px] text-fg-subtle">{num(o.shared)}</span>
                        </Link>
                      ),
                    }
                  })}
                />
              </div>
            ) : (
              <EmptyState icon={<GitCompareArrows className="size-5" />} title="Нет пересечений" description="Добавьте ещё каналы или чаты, чтобы увидеть общую аудиторию" />
            )}
          </Card>
        </div>
      </div>
    </Page>
  )
}
