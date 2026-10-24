import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, Bell, CheckCheck, Send, Star, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type AppEvent } from '../lib/api'
import { relative } from '../lib/format'
import { Avatar } from './Avatar'
import { Drawer, EmptyState } from './ui'

const ICONS = { new_users: UserPlus, watch: Star, job_failed: AlertTriangle, info: Bell }
const TONE = { new_users: 'text-success', watch: 'text-warning', job_failed: 'text-danger', info: 'text-accent' }

export function NotificationBell() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const q = useQuery({
    queryKey: ['events'],
    queryFn: () => api<{ unread: number; items: AppEvent[] }>('/events?limit=60'),
    refetchInterval: 30_000,
  })
  const read = useMutation({
    mutationFn: () => api('/events/read', { method: 'POST', json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['events'] }),
  })
  const unread = q.data?.unread ?? 0
  const close = () => {
    setOpen(false)
    if (unread) read.mutate()
  }
  const go = (e: AppEvent) => {
    close()
    navigate(e.payload.path ?? (e.job_id ? `/tools/comment-collector/jobs/${e.job_id}` : '/monitoring'))
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label={unread ? `Уведомления: ${unread} новых` : 'Уведомления'}
        className="relative inline-flex size-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-elevated hover:text-fg"
      >
        <Bell className="size-[18px]" />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-danger px-1 font-mono text-[10.5px] font-semibold text-white ring-2 ring-surface">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      <Drawer
        open={open}
        onClose={close}
        title={
          <div className="flex items-center justify-between gap-2 pr-2">
            <span className="font-semibold">Уведомления</span>
            {unread > 0 && (
              <button onClick={() => read.mutate()} className="flex items-center gap-1 text-[12.5px] text-accent hover:underline">
                <CheckCheck className="size-3.5" aria-hidden /> прочитать все
              </button>
            )}
          </div>
        }
      >
        {!q.data?.items.length ? (
          <EmptyState icon={<Bell className="size-5" />} title="Пока тихо" description="Здесь появятся новые комментаторы и события мониторинга." action={<Link to="/monitoring" onClick={close} className="text-sm text-accent hover:underline">Настроить мониторинг</Link>} />
        ) : (
          <ul className="divide-y divide-line/70">
            {q.data.items.map((e) => {
              const Icon = ICONS[e.kind] ?? Bell
              const people = e.payload.people ?? []
              return (
                <li key={e.id}>
                  <button onClick={() => go(e)} className={clsx('flex w-full gap-3 px-5 py-3.5 text-left transition-colors hover:bg-elevated/60', !e.read && 'bg-accent-soft/40')}>
                    <Icon className={clsx('mt-0.5 size-4 shrink-0', TONE[e.kind])} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-[13.5px] font-medium">{e.title}</span>
                        {!e.read && <span className="mt-1.5 size-2 shrink-0 rounded-full bg-accent" aria-label="новое" />}
                      </div>
                      {e.payload.detail && <p className="mt-0.5 line-clamp-2 text-[12.5px] text-fg-muted">{e.payload.detail}</p>}
                      {people.length > 0 && (
                        <div className="mt-2 flex items-center">
                          <div className="flex -space-x-1.5">
                            {people.slice(0, 6).map((p) => (
                              <span key={p.peer_id} className="rounded-full ring-2 ring-card" title={p.name}>
                                <Avatar id={p.peer_id} name={p.name} photoId={p.photo_id} size={22} />
                              </span>
                            ))}
                          </div>
                          {(e.payload.count ?? people.length) > 6 && <span className="ml-2 text-[12px] text-fg-subtle">+{(e.payload.count ?? people.length) - 6}</span>}
                        </div>
                      )}
                      <div className="mt-1.5 flex items-center gap-2 text-[11.5px] text-fg-subtle">
                        <span>{relative(e.created_at)}</span>
                        {e.delivery === 'sent' && <span className="flex items-center gap-1"><Send className="size-3" aria-hidden />отправлено в Telegram</span>}
                        {e.delivery === 'error' && <span className="text-danger" title={e.delivery_error ?? ''}>не доставлено в Telegram</span>}
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Drawer>
    </>
  )
}
