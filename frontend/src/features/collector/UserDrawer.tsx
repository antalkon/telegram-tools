import { useQuery } from '@tanstack/react-query'
import { ArrowRight, ExternalLink, MessageCircle, Network } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Avatar } from '../../components/Avatar'
import { Badge, Drawer, Skeleton } from '../../components/ui'
import { api, type Participant, type ParticipantComment } from '../../lib/api'
import { date, dateTime, num } from '../../lib/format'

export function UserDrawer({ jobId, participant: p, chat, onClose }: { jobId: number; participant: Participant | null; chat?: boolean; onClose: () => void }) {
  const comments = useQuery({
    queryKey: ['participant-comments', jobId, p?.peer_id],
    queryFn: () => api<ParticipantComment[]>(`/jobs/${jobId}/participants/${p!.peer_id}/comments`),
    enabled: !!p,
  })
  if (!p) return null
  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <div className="flex items-center gap-3">
          <Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={40} />
          <div className="min-w-0">
            <div className="truncate font-semibold">{p.name}</div>
            {p.username ? (
              <a href={`https://t.me/${p.username}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[13px] text-accent hover:underline">
                @{p.username} <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : (
              <span className="text-[13px] text-fg-subtle">без username</span>
            )}
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-5 p-5">
        <Link
          to={`/users/${p.peer_id}`}
          className="flex items-center justify-between rounded-xl border border-accent/30 bg-accent-soft px-4 py-3 text-sm font-medium transition-colors hover:border-accent/60"
        >
          <span className="flex items-center gap-2"><Network className="size-4 text-accent" aria-hidden />Открыть досье: граф, связи, все каналы</span>
          <ArrowRight className="size-4 text-accent" aria-hidden />
        </Link>
        <div className="flex flex-wrap gap-1.5">
          <Badge>{p.kind === 'user' ? 'Пользователь' : 'Канал'}</Badge>
          {p.is_premium && <Badge tone="accent">Premium</Badge>}
          {p.is_verified && <Badge tone="accent">Верифицирован</Badge>}
          {p.is_bot && <Badge>Бот</Badge>}
          {p.is_scam && <Badge tone="danger">Scam / Fake</Badge>}
          {p.is_deleted && <Badge>Удалён</Badge>}
          {p.member && <Badge tone="success">{p.role === 'creator' ? 'Владелец' : p.role === 'admin' ? 'Админ' : 'Участник'}</Badge>}
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          {(
            [
              ['ID', String(p.peer_id), true],
              [chat ? 'Сообщений' : 'Комментариев', num(p.comments), true],
              [chat ? 'Дней / тем' : 'Постов', num(p.posts), true],
              ['Телефон', p.phone ? `+${p.phone}` : '—', true],
              ['Первый', date(p.first_at), false],
              ['Последний', date(p.last_at), false],
            ] as const
          ).map(([k, v, mono]) => (
            <div key={k} className="rounded-lg border border-line bg-surface px-3 py-2">
              <dt className="text-[12px] text-fg-subtle">{k}</dt>
              <dd className={mono ? 'mt-0.5 font-mono' : 'mt-0.5'}>{v}</dd>
            </div>
          ))}
        </dl>
        {p.usernames.length > 1 && (
          <div className="text-[13px] text-fg-muted">Другие username: {p.usernames.slice(1).map((u) => `@${u}`).join(', ')}</div>
        )}

        <div>
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <MessageCircle className="size-4 text-fg-subtle" aria-hidden /> {chat ? 'Последние сообщения' : 'Последние комментарии'}
          </h3>
          {comments.isLoading ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {comments.data?.map((c) => (
                <li key={c.msg_id} className="rounded-lg border border-line bg-surface px-3 py-2.5">
                  <div className="mb-1 flex items-center justify-between gap-2 text-[12px] text-fg-subtle">
                    <span>{c.thread ?? `пост #${c.post_id}`} · {dateTime(c.date)}</span>
                    {c.link && (
                      <a href={c.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                        открыть <ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </div>
                  <p className="text-[13.5px] break-words whitespace-pre-wrap">{c.text || <span className="text-fg-subtle italic">медиа без текста</span>}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Drawer>
  )
}
