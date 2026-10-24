import { useQuery } from '@tanstack/react-query'
import { Contact, Eye, Megaphone, Newspaper, Repeat2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type Advertiser, type Contacts, type PeerCard, type PostChannel } from '../lib/api'
import { compact, num, relative } from '../lib/format'
import { ContactsView } from './Enrichment'
import { Card, CardHeader, Skeleton } from './ui'

/** Posts, ads and forward sources of a channel source, with a way to collect posts if there are none. */
export function ChannelPostsCard({ sourceId, username }: { sourceId: number; username: string | null }) {
  const channels = useQuery({ queryKey: ['posts', 'channels'], queryFn: () => api<PostChannel[]>('/posts/channels') })
  const mine = channels.data?.find((c) => c.channel_id === sourceId)
  const ads = useQuery({ queryKey: ['posts', 'ads', String(sourceId)], queryFn: () => api<Advertiser[]>(`/posts/ads?channel=${sourceId}`), enabled: !!mine })
  const fwd = useQuery({
    queryKey: ['posts', 'fwd', sourceId],
    queryFn: () => api<(PeerCard & { posts: number; fallback_name: string | null; fallback_username: string | null })[]>(`/posts/forward-sources?channel_id=${sourceId}&limit=8`),
    enabled: !!mine,
  })
  const link = `/tools/channel-posts?${new URLSearchParams(mine ? { channel: String(sourceId) } : { link: username ? `@${username}` : '' })}`
  return (
    <Card>
      <CardHeader icon={<Newspaper className="size-4" />} title="Посты и реклама"
        description={mine ? `${num(mine.posts)} постов собрано ${relative(mine.collected_at)}` : 'Посты канала ещё не собирались'}
        actions={<Link to={link} className="inline-flex h-8 items-center rounded-lg px-2.5 text-[13px] font-medium text-accent hover:bg-elevated">{mine ? 'Все посты →' : 'Собрать посты →'}</Link>} />
      <div className="flex flex-col gap-4 p-5">
        {channels.isLoading ? <Skeleton className="h-12" /> : !mine ? (
          <p className="text-[13px] text-fg-muted">
            Посты дают просмотры, репосты, рекламу с ИНН рекламодателей и каналы, из которых здесь репостят.
            {username ? ' Этот канал публичный — его можно собрать без аккаунта, через t.me/s.' : ''}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-fg-muted">
              <span className="inline-flex items-center gap-1"><Eye className="size-3.5" aria-hidden />в среднем {mine.avg_views != null ? compact(mine.avg_views) : '—'}</span>
              <span className="inline-flex items-center gap-1"><Megaphone className="size-3.5" aria-hidden />рекламных {num(mine.ads)}</span>
            </div>
            {!!ads.data?.length && (
              <div>
                <h3 className="mb-1.5 text-[12px] font-medium text-fg-subtle">Рекламодатели</h3>
                <ul className="flex flex-col gap-1 text-[13px]">
                  {ads.data.slice(0, 6).map((a) => (
                    <li key={`${a.inn}:${a.advertiser}`} className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate">{a.org?.short_name ?? a.advertiser ?? 'не указан'}</span>
                      {a.inn && <span className="font-mono text-[12px] text-fg-subtle">ИНН {a.inn}</span>}
                      <span className="font-mono text-[12px] text-fg-muted">{num(a.posts)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!!fwd.data?.length && (
              <div>
                <h3 className="mb-1.5 text-[12px] font-medium text-fg-subtle">Откуда репостит</h3>
                <ul className="flex flex-col gap-1 text-[13px]">
                  {fwd.data.map((f) => (
                    <li key={f.peer_id} className="flex items-center gap-2">
                      <Repeat2 className="size-3.5 shrink-0 text-fg-subtle" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{f.name !== String(f.peer_id) ? f.name : f.fallback_name ?? f.peer_id}{f.username ? ` · @${f.username}` : ''}</span>
                      <span className="font-mono text-[12px] text-fg-muted">{num(f.posts)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  )
}

export function ChannelContactsCard({ sourceId }: { sourceId: number }) {
  const q = useQuery({ queryKey: ['channel-contacts', sourceId], queryFn: () => api<{ about: string | null; contacts: Contacts }>(`/channels/${sourceId}/contacts`) })
  return (
    <Card>
      <CardHeader icon={<Contact className="size-4" />} title="Контакты" description="Из описания и собранных постов: телефоны, email, сайты, кошельки, ИНН" />
      <div className="flex flex-col gap-3 p-5">
        {q.isLoading ? <Skeleton className="h-12" /> : (
          <>
            {q.data?.about && <p className="text-[13px] whitespace-pre-line text-fg-muted">{q.data.about}</p>}
            <ContactsView contacts={q.data?.contacts} empty="Контактов не найдено" />
          </>
        )}
      </div>
    </Card>
  )
}
