import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Layers, Megaphone, Newspaper, Star, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { PeerLine, StarButton } from '../components/PeerBits'
import { TypeBadge } from '../components/SourceBits'
import { Card, CardHeader, EmptyState, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Favorites as FavoritesData } from '../lib/api'
import { compact, num, relative } from '../lib/format'

function Section({ icon, title, count, empty, children }: { icon: ReactNode; title: string; count: number; empty: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader icon={icon} title={`${title}${count ? ` · ${count}` : ''}`} />
      {count ? <ul className="divide-y divide-line/70">{children}</ul> : <p className="px-5 py-6 text-[13px] text-fg-subtle">{empty}</p>}
    </Card>
  )
}

function Row({ children, peerId }: { children: ReactNode; peerId: number }) {
  return (
    <li className="flex items-center gap-3 px-4 py-2.5 sm:px-5">
      <div className="min-w-0 flex-1">{children}</div>
      <StarButton peerId={peerId} starred />
    </li>
  )
}

export default function Favorites() {
  const q = useQuery({ queryKey: ['favorites'], queryFn: () => api<FavoritesData>('/favorites') })
  const f = q.data
  const total = f ? f.users.length + f.sources.length + f.channels.length : 0
  return (
    <Page>
      <PageHeader icon={<Star className="size-5" />} title="Избранное" description="Люди, источники и каналы, отмеченные звёздочкой" />
      {!f ? (
        <div className="flex flex-col gap-5">{[0, 1].map((i) => <Skeleton key={i} className="h-40 rounded-[var(--radius-card)]" />)}</div>
      ) : !total ? (
        <Card>
          <EmptyState icon={<Star className="size-5" />} title="Пока пусто"
            description="Нажмите на звёздочку у человека, источника или найденного канала, и он появится здесь. Об активности избранных людей приходят уведомления." />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          <Section icon={<Users className="size-4" />} title="Люди" count={f.users.length} empty="Отметьте человека звёздочкой в списке или в его досье.">
            {f.users.map((p) => (
              <Row key={p.peer_id} peerId={p.peer_id}>
                <PeerLine p={{ ...p, starred: false }} size={34} sub={p.tags.length ? p.tags.join(', ') : undefined} />
              </Row>
            ))}
          </Section>
          <Section icon={<Layers className="size-4" />} title="Источники" count={f.sources.length} empty="Звёздочка есть на карточке источника и на его странице аналитики.">
            {f.sources.map((s) => (
              <Row key={s.id} peerId={s.id}>
                <Link to={`/channels/${s.id}`} className="group flex min-w-0 items-center gap-2.5">
                  <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={34} square={s.family !== 'chat'} />
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-[13.5px] font-medium group-hover:text-accent">{s.title}</span>
                      <TypeBadge type={s.type} />
                    </div>
                    <div className="truncate text-[12px] text-fg-subtle">
                      {num(s.people)} людей · {compact(s.comments)} сообщений · обновлён {relative(s.collected_at)}
                    </div>
                  </div>
                </Link>
              </Row>
            ))}
          </Section>
          <Section icon={<Megaphone className="size-4" />} title="Другие каналы и чаты" count={f.channels.length}
            empty="Отмечайте каналы на страницах «Каналы пользователей» и «Посты каналов».">
            {f.channels.map((c) => (
              <Row key={c.peer_id} peerId={c.peer_id}>
                <div className="flex min-w-0 items-center gap-2.5">
                  <Avatar id={c.peer_id} name={c.name} photoId={c.photo_id} size={34} square />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] font-medium">{c.name}</div>
                    <div className="flex flex-wrap items-center gap-x-3 text-[12px] text-fg-subtle">
                      {c.username && (
                        <a href={`https://t.me/${c.username}`} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-accent">
                          @{c.username} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      )}
                      {c.members_count != null && <span>{compact(c.members_count)} подп.</span>}
                      {c.posts > 0 && (
                        <Link to={`/tools/channel-posts?channel=${c.peer_id}`} className="flex items-center gap-1 text-accent hover:underline">
                          <Newspaper className="size-3" aria-hidden /> {num(c.posts)} постов
                        </Link>
                      )}
                      {c.found && <Link to="/users/channels?status=starred" className="hover:text-accent">в найденных каналах</Link>}
                    </div>
                  </div>
                </div>
              </Row>
            ))}
          </Section>
        </div>
      )}
    </Page>
  )
}
