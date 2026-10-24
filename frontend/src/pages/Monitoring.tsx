import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, BellRing, CheckCircle2, Loader2, Pause, Play, Plus, Settings2, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { useSources } from '../components/PeerBits'
import { TypeBadge } from '../components/SourceBits'
import { MonitorDialog, useInvalidateAnalytics, useMonitors } from '../components/SourceActions'
import { useToast } from '../components/Toast'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, IconButton, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, intervalLabel, type Monitor, type NotifySettings, type Source } from '../lib/api'
import { num, relative } from '../lib/format'

function until(iso: string | null) {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 60000
  if (diff <= 1) return 'вот-вот'
  if (diff < 60) return `через ${Math.round(diff)} мин`
  if (diff < 60 * 24) return `через ${Math.round(diff / 60)} ч`
  return `через ${Math.round(diff / 1440)} дн`
}

function Status({ m }: { m: Monitor }) {
  if (!m.enabled) return <Badge><Pause className="size-3" aria-hidden />на паузе</Badge>
  if (m.last_status === 'running') return <Badge tone="accent"><Loader2 className="size-3 animate-spin" aria-hidden />дозабирает</Badge>
  if (m.last_status === 'failed') return <Badge tone="danger"><AlertTriangle className="size-3" aria-hidden />ошибка</Badge>
  if (m.last_status === 'done') return <Badge tone="success"><CheckCircle2 className="size-3" aria-hidden />работает</Badge>
  return <Badge tone="warning">ждёт запуска</Badge>
}

function MonitorRow({ m, source }: { m: Monitor; source?: Source }) {
  const toast = useToast()
  const invalidate = useInvalidateAnalytics()
  const [edit, setEdit] = useState(false)
  const patch = useMutation({
    mutationFn: (body: Partial<Monitor>) => api(`/monitors/${m.id}`, { method: 'PATCH', json: body }),
    onSuccess: invalidate,
  })
  const run = useMutation({
    mutationFn: () => api<{ job_id: number }>(`/monitors/${m.id}/run`, { method: 'POST' }),
    onSuccess: () => {
      invalidate()
      toast('Дозабор запущен', 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const remove = useMutation({ mutationFn: () => api(`/monitors/${m.id}`, { method: 'DELETE' }), onSuccess: invalidate })
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4">
      <Avatar id={m.source_id ?? m.id} name={m.title} photoId={m.photo_id} size={40} square />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {m.source_id ? (
            <Link to={`/channels/${m.source_id}`} className="truncate font-semibold hover:text-accent">{m.title}</Link>
          ) : (
            <span className="truncate font-semibold">{m.title}</span>
          )}
          <Status m={m} />
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12.5px] text-fg-muted">
          <span>{intervalLabel(m.interval_minutes)}</span>
          {m.last_run_at && (
            <span>
              последний {m.last_job_id ? <Link to={`/tools/comment-collector/jobs/${m.last_job_id}`} className="hover:text-accent">{relative(m.last_run_at)}</Link> : relative(m.last_run_at)}
            </span>
          )}
          {m.enabled && <span>следующий {until(m.next_run_at)}</span>}
          {m.last_new_users != null && <span className={m.last_new_users ? 'text-success' : ''}>+{num(m.last_new_users)} новых</span>}
          {!m.notify && <span className="text-fg-subtle">без уведомлений</span>}
        </div>
        {m.last_status === 'failed' && m.last_error && <p className="mt-1 text-[12.5px] text-danger">{m.last_error}</p>}
      </div>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="secondary" icon={<Zap className="size-3.5" />} loading={run.isPending} disabled={m.last_status === 'running'} onClick={() => run.mutate()}>
          Сейчас
        </Button>
        <IconButton label={m.enabled ? 'Поставить на паузу' : 'Возобновить'} onClick={() => patch.mutate({ enabled: !m.enabled })}>
          {m.enabled ? <Pause className="size-4" /> : <Play className="size-4" />}
        </IconButton>
        {source && (
          <IconButton label="Настроить" onClick={() => setEdit(true)}>
            <Settings2 className="size-4" />
          </IconButton>
        )}
        <IconButton label="Удалить мониторинг" className="hover:text-danger" onClick={() => remove.mutate()}>
          <Trash2 className="size-4" />
        </IconButton>
      </div>
      {edit && source && <MonitorDialog source={source} monitor={m} open onClose={() => setEdit(false)} />}
    </li>
  )
}

function AddMonitor({ open, onClose, taken }: { open: boolean; onClose: () => void; taken: Set<number> }) {
  const sources = useSources()
  const [picked, setPicked] = useState<Source | null>(null)
  const free = (sources.data ?? []).filter((s) => !taken.has(s.id))
  if (picked) return <MonitorDialog source={picked} open onClose={() => (setPicked(null), onClose())} />
  return (
    <Dialog open={open} onClose={onClose} title="Что мониторить?" description="Новые каналы и чаты сначала добавьте в «Источниках» — потом их можно поставить на мониторинг.">
      {free.length ? (
        <ul className="-mx-2 max-h-96 overflow-y-auto scrollbar-thin">
          {free.map((s) => (
            <li key={s.id}>
              <button onClick={() => setPicked(s)} className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-elevated">
                <Avatar id={s.id} name={s.title} photoId={s.photo_id} size={32} square={s.family !== 'chat'} />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{s.title}</span>
                <TypeBadge type={s.type} />
                <span className="font-mono text-[12px] text-fg-subtle">{num(s.people)} чел.</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-fg-muted">Все источники уже на мониторинге.</p>
      )}
    </Dialog>
  )
}

export default function Monitoring() {
  const monitors = useMonitors()
  const sources = useSources()
  const notify = useQuery({ queryKey: ['notify-settings'], queryFn: () => api<NotifySettings>('/settings/notifications') })
  const [adding, setAdding] = useState(false)
  const byId = new Map((sources.data ?? []).map((s) => [s.id, s]))
  const add = <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Добавить</Button>

  return (
    <Page>
      <PageHeader
        icon={<BellRing className="size-5" />}
        title="Мониторинг"
        description="Дозабор новых комментариев по расписанию и уведомления о новых людях"
        actions={monitors.data?.length ? add : undefined}
      />
      {notify.data?.target === 'none' && (
        <Card className="mb-5 flex flex-wrap items-center gap-3 border-warning/30 bg-warning-soft p-4 text-sm">
          <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden />
          <span className="flex-1">Уведомления сейчас видны только в панели (колокольчик). Можно присылать их в Telegram.</span>
          <Link to="/settings" className="font-medium text-accent hover:underline">Настроить доставку</Link>
        </Card>
      )}
      <Card>
        <CardHeader title="На мониторинге" description="Каждый запуск читает только сообщения после прошлого сбора; у чатов — ещё и обновляет участников" />
        {monitors.isLoading ? (
          <div className="p-5"><Skeleton className="h-14" /></div>
        ) : monitors.data?.length ? (
          <ul className={clsx('divide-y divide-line')}>{monitors.data.map((m) => <MonitorRow key={m.id} m={m} source={m.source_id ? byId.get(m.source_id) : undefined} />)}</ul>
        ) : (
          <EmptyState icon={<BellRing className="size-5" />} title="Пока ничего не мониторится" description="Выберите канал или чат — панель будет сама дочитывать новое и присылать новых людей." action={add} />
        )}
      </Card>
      <AddMonitor open={adding} onClose={() => setAdding(false)} taken={new Set((monitors.data ?? []).map((m) => m.source_id ?? 0))} />
    </Page>
  )
}
