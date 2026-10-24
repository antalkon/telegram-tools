import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowRight, GitCompareArrows, Layers, MessageCircle, Smartphone, Trophy, Users } from 'lucide-react'
import { AddSourceButton } from '../components/AddSource'
import { TypeIcon } from '../components/SourceBits'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { SERIES, TimeBars } from '../components/charts'
import { PeerLine, Stat } from '../components/PeerBits'
import { Badge, Card, CardHeader, EmptyState, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Account, type Overview } from '../lib/api'
import { compact, num } from '../lib/format'
import { TOOLS } from '../lib/tools'

function ToolsGrid() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {TOOLS.map((t) => {
        const body = (
          <>
            <div className="flex items-start justify-between">
              <div className="flex size-10 items-center justify-center rounded-xl border border-line bg-elevated text-accent transition-colors group-hover:border-accent/40">
                <t.icon className="size-5" aria-hidden />
              </div>
              {t.path ? <ArrowRight className="size-4 text-fg-subtle transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden /> : <Badge>Скоро</Badge>}
            </div>
            <h3 className="mt-4 text-[15px] font-semibold">{t.title}</h3>
            <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">{t.description}</p>
          </>
        )
        return t.path ? (
          <Link key={t.id} to={t.path} className="group rounded-[var(--radius-card)] border border-line bg-card p-5 shadow-[var(--shadow-card)] transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-accent/40">
            {body}
          </Link>
        ) : (
          <div key={t.id} className="rounded-[var(--radius-card)] border border-dashed border-line bg-card/50 p-5 opacity-70">{body}</div>
        )
      })}
    </div>
  )
}

export default function Home() {
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const ov = useQuery({ queryKey: ['overview'], queryFn: () => api<Overview>('/overview') })
  const t = ov.data?.totals

  return (
    <Page wide>
      <PageHeader title="Обзор" description="Всё, что собрано: каналы, чаты, люди и их пересечения" actions={<AddSourceButton size="sm" />} />

      {accounts.isSuccess && accounts.data.length === 0 && (
        <Card className="animate-in mb-6 flex flex-wrap items-center gap-4 border-accent/30 bg-accent-soft p-4">
          <Smartphone className="size-5 shrink-0 text-accent" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">Подключите Telegram-аккаунт</div>
            <div className="text-[13px] text-fg-muted">Инструменты работают от имени вашего аккаунта через MTProto.</div>
          </div>
          <Link to="/accounts" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-accent px-3.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover">
            Подключить <ArrowRight className="size-4" />
          </Link>
        </Card>
      )}

      {ov.isLoading ? (
        <Skeleton className="mb-6 h-28 rounded-[var(--radius-card)]" />
      ) : t && t.sources > 0 ? (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Link to="/channels"><Stat icon={<Layers className="size-3.5" />} label="Источников" value={num(t.sources)} sub={`каналов ${num(t.channels)} · чатов ${num(t.chats)}`} /></Link>
            <Link to="/users"><Stat icon={<Users className="size-3.5" />} label="Уникальных людей" value={num(t.users)} sub={t.members ? `${num(t.members)} только в участниках` : undefined} /></Link>
            <Link to="/search"><Stat icon={<MessageCircle className="size-3.5" />} label="Сообщений и комментариев" value={compact(t.comments)} sub="искать →" /></Link>
            <Link to="/users?min=2"><Stat icon={<GitCompareArrows className="size-3.5" />} label="Есть в 2+ источниках" value={num(t.multi_source_users)} sub={t.users ? `${((t.multi_source_users / t.users) * 100).toFixed(1)}% людей` : undefined} /></Link>
          </div>

          <div className="mb-8 grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-5">
              <Card>
                <CardHeader icon={<Activity className="size-4" />} title="Активность за 90 дней" description="Комментарии и сообщения во всех источниках" />
                <div className="p-5"><TimeBars data={ov.data!.activity} color={SERIES[0]} /></div>
              </Card>
              <Card>
                <CardHeader icon={<Layers className="size-4" />} title="Источники" actions={<Link to="/channels" className="text-[13px] text-accent hover:underline">все</Link>} />
                <ul className="divide-y divide-line/70">
                  {ov.data!.sources.map((s) => (
                    <li key={s.id}>
                      <Link to={`/channels/${s.id}`} className="flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-elevated/60">
                        <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={30} square={s.family !== 'chat'} />
                        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{s.title}</span>
                        <TypeIcon type={s.type} className="size-3.5 shrink-0 text-fg-subtle" />
                        <span className="font-mono text-[13px] tabular" title="людей">{num(s.people)}</span>
                        <span className="w-24 text-right text-[12px] text-fg-subtle">{compact(s.comments)} {s.family === 'chat' ? 'сообщ.' : 'комм.'}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
            <div className="flex min-w-0 flex-col gap-5">
              <Card>
                <CardHeader icon={<GitCompareArrows className="size-4" />} title="Есть везде" description="Больше всего источников" actions={<Link to="/graph" className="text-[13px] text-accent hover:underline">граф</Link>} />
                <ul className="divide-y divide-line/70">
                  {ov.data!.top_crossover.map((u) => (
                    <li key={u.peer_id} className="flex items-center gap-3 px-5 py-2.5">
                      <div className="min-w-0 flex-1"><PeerLine p={u} /></div>
                      <span className="text-right text-[12px] text-fg-muted"><span className="font-mono text-[13.5px] font-semibold text-fg">{u.sources}</span> кан.</span>
                    </li>
                  ))}
                  {!ov.data!.top_crossover.length && <li className="px-5 py-6 text-center text-[13px] text-fg-subtle">Пока нет людей в нескольких источниках</li>}
                </ul>
              </Card>
              <Card>
                <CardHeader icon={<Trophy className="size-4" />} title="Самые активные" />
                <ul className="divide-y divide-line/70">
                  {ov.data!.top_users.map((u) => (
                    <li key={u.peer_id} className="flex items-center gap-3 px-5 py-2.5">
                      <div className="min-w-0 flex-1"><PeerLine p={u} /></div>
                      <span className="font-mono text-[13.5px] font-semibold tabular">{num(u.comments)}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          </div>
        </>
      ) : (
        <Card className="mb-8">
          <EmptyState
            icon={<Layers className="size-5" />}
            title="Данных пока нет"
            description="Добавьте канал или чат — здесь появится аналитика"
            action={<AddSourceButton label="Добавить источник" />}
          />
        </Card>
      )}

      <h2 className="mb-3 text-[15px] font-semibold">Инструменты</h2>
      <ToolsGrid />
    </Page>
  )
}
