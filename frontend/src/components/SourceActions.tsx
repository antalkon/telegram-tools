import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BellPlus, BellRing, DownloadCloud, Eye, EyeOff, MoreHorizontal, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, INTERVALS, intervalLabel, type IndexerOptions, type Job, type Monitor, type Source } from '../lib/api'
import { num } from '../lib/format'
import { jobPath, OptionsFields, optionsFor, words } from './SourceBits'
import { useToast } from './Toast'
import { Button, Dialog, Switch } from './ui'

const ANALYTICS_KEYS = ['sources', 'overview', 'users', 'graph', 'overlap', 'source', 'user', 'monitors', 'ignored']

export function useInvalidateAnalytics() {
  const qc = useQueryClient()
  return () => ANALYTICS_KEYS.forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
}

export function useMonitors() {
  return useQuery({ queryKey: ['monitors'], queryFn: () => api<Monitor[]>('/monitors'), refetchInterval: 15_000 })
}

/** Re-run a known source with its saved settings: incremental by default, full re-index with options. */
export function useCollect() {
  const navigate = useNavigate()
  const toast = useToast()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ source, mode, options }: { source: Source; mode: 'incremental' | 'full'; options?: IndexerOptions }) =>
      api<Job>(`/sources/${source.id}/run`, { method: 'POST', json: { mode, options: options ?? {} } }),
    onSuccess: (job) => {
      qc.invalidateQueries({ queryKey: ['sources'] })
      navigate(jobPath(job))
    },
    onError: (e) => toast(e.message, 'error'),
  })
}

export function ReindexDialog({ source, open, onClose }: { source: Source; open: boolean; onClose: () => void }) {
  const collect = useCollect()
  const [opts, setOpts] = useState<IndexerOptions>(() => optionsFor(source.family, source.options))
  return (
    <Dialog open={open} onClose={onClose} width="max-w-2xl" title={`Переиндексировать «${source.title}»`}
      description={source.family === 'chat'
        ? 'Новый полный проход по истории и участникам. Аналитика переключится на него, когда он закончится; до этого остаётся прежний.'
        : 'Новый полный сбор комментариев. Аналитика переключится на него, когда он закончится.'}>
      <div className="flex flex-col gap-5">
        <OptionsFields family={source.family} value={opts} onChange={setOpts} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" icon={<RefreshCw className="size-4" />} loading={collect.isPending}
            onClick={() => collect.mutate({ source, mode: 'full', options: optionsFor(source.family, opts) }, { onSuccess: onClose })}>
            Запустить
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

export function MonitorDialog({ source, monitor, open, onClose }: { source: Source; monitor?: Monitor; open: boolean; onClose: () => void }) {
  const toast = useToast()
  const invalidate = useInvalidateAnalytics()
  const [interval, setInterval_] = useState(monitor?.interval_minutes ?? 360)
  const [notify, setNotify] = useState(monitor?.notify ?? true)
  const [members, setMembers] = useState(monitor?.options?.collect_members ?? source.options.collect_members ?? true)
  const chat = source.family === 'chat'
  const options = chat ? { collect_members: members } : {}
  const save = useMutation({
    mutationFn: () =>
      monitor
        ? api(`/monitors/${monitor.id}`, { method: 'PATCH', json: { interval_minutes: interval, notify, enabled: true, options } })
        : api('/monitors', { method: 'POST', json: { source_id: source.id, interval_minutes: interval, notify, run_now: true, options } }),
    onSuccess: () => {
      invalidate()
      toast(monitor ? 'Мониторинг обновлён' : 'Мониторинг включён — первый дозабор уже запущен', 'success')
      onClose()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  return (
    <Dialog open={open} onClose={onClose} title={`Мониторинг «${source.title}»`}
      description={chat ? 'Панель будет сама дочитывать новые сообщения, обновлять участников и сообщать о новых людях.' : 'Панель будет сама дозабирать новые комментарии и сообщать о новых людях.'}>
      <div className="flex flex-col gap-5">
        <div>
          <div className="mb-2 text-sm font-medium">Как часто проверять</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {INTERVALS.map((i) => (
              <button
                key={i.value}
                aria-pressed={interval === i.value}
                onClick={() => setInterval_(i.value)}
                className={clsx('h-10 rounded-[10px] border text-[13px] transition-colors', interval === i.value ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}
              >
                {i.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12.5px] text-fg-subtle">Чем чаще, тем быстрее узнаёте о новых людях. Дозабор читает только новые сообщения — это дёшево.</p>
        </div>
        {chat && <Switch checked={members} onChange={setMembers} label="Обновлять участников" description="Кто вступил и вышел. В больших чатах это дольше, чем просто новые сообщения" />}
        <Switch checked={notify} onChange={setNotify} label="Уведомлять" description={chat ? 'О новых участниках и авторах, сообщениях избранных и ошибках' : 'О новых комментаторах, активности избранных и ошибках'} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="primary" icon={<BellRing className="size-4" />} loading={save.isPending} onClick={() => save.mutate()}>
            {monitor ? 'Сохранить' : 'Включить'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function Menu({ children, label }: { children: ReactNode; label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <button
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="inline-flex size-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-elevated hover:text-fg"
      >
        <MoreHorizontal className="size-4" />
      </button>
      {open && (
        <div role="menu" onClick={() => setOpen(false)} className="animate-in absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-xl border border-line-strong bg-elevated p-1 shadow-2xl">
          {children}
        </div>
      )}
    </div>
  )
}

function MenuItem({ icon, children, onClick, danger }: { icon: ReactNode; children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className={clsx('flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm transition-colors', danger ? 'text-danger hover:bg-danger-soft' : 'text-fg-muted hover:bg-muted hover:text-fg')}
    >
      {icon}
      {children}
    </button>
  )
}

/** Primary «Дозабрать» button + menu with the rest of the source actions. */
export function SourceActions({ source, compact }: { source: Source; compact?: boolean }) {
  const toast = useToast()
  const invalidate = useInvalidateAnalytics()
  const collect = useCollect()
  const monitors = useMonitors()
  const monitor = monitors.data?.find((m) => m.source_id === source.id)
  const [monitorOpen, setMonitorOpen] = useState(false)
  const [reindexOpen, setReindexOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const w = words(source.family)

  const hide = useMutation({
    mutationFn: (hidden: boolean) => api(`/sources/${source.id}/hidden`, { method: 'PUT', json: { hidden } }),
    onSuccess: (_, hidden) => {
      invalidate()
      toast(hidden ? 'Источник отключён — вернуть можно в «Источники → Отключённые»' : 'Источник снова в аналитике', 'success')
    },
  })
  const stopMonitor = useMutation({
    mutationFn: () => api(`/monitors/${monitor!.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      invalidate()
      toast('Мониторинг выключен', 'success')
    },
  })
  const remove = useMutation({
    mutationFn: () => api<{ deleted_jobs: number }>(`/sources/${source.id}`, { method: 'DELETE' }),
    onSuccess: (r) => {
      invalidate()
      toast(`Данные источника удалены (${r.deleted_jobs} сборов)`, 'success')
      setConfirmDelete(false)
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const busy = collect.isPending && collect.variables?.source.id === source.id

  return (
    <div className="flex items-center gap-1.5">
      <Button
        size={compact ? 'sm' : 'md'}
        variant="secondary"
        icon={<DownloadCloud className="size-4" />}
        loading={busy && collect.variables?.mode === 'incremental'}
        disabled={source.running}
        onClick={() => collect.mutate({ source, mode: 'incremental' })}
        title={source.running ? 'Сбор уже идёт' : `Прочитать только новые ${source.family === 'chat' ? 'сообщения' : 'комментарии'} с прошлого сбора`}
      >
        Дозабрать
      </Button>
      <Menu label="Действия с источником">
        <MenuItem icon={monitor ? <BellRing className="size-4 text-accent" /> : <BellPlus className="size-4" />} onClick={() => setMonitorOpen(true)}>
          {monitor ? `Мониторинг: ${intervalLabel(monitor.interval_minutes)}` : 'Включить мониторинг'}
        </MenuItem>
        {monitor && <MenuItem icon={<BellPlus className="size-4 opacity-50" />} onClick={() => stopMonitor.mutate()}>Выключить мониторинг</MenuItem>}
        <MenuItem icon={<RefreshCw className="size-4" />} onClick={() => setReindexOpen(true)}>Переиндексировать…</MenuItem>
        {source.hidden ? (
          <MenuItem icon={<Eye className="size-4" />} onClick={() => hide.mutate(false)}>Включить в аналитику</MenuItem>
        ) : (
          <MenuItem icon={<EyeOff className="size-4" />} onClick={() => hide.mutate(true)}>Отключить из аналитики</MenuItem>
        )}
        <div className="my-1 h-px bg-line" />
        <MenuItem icon={<Trash2 className="size-4" />} danger onClick={() => setConfirmDelete(true)}>Удалить данные</MenuItem>
      </Menu>

      {monitorOpen && <MonitorDialog source={source} monitor={monitor} open onClose={() => setMonitorOpen(false)} />}
      {reindexOpen && <ReindexDialog source={source} open onClose={() => setReindexOpen(false)} />}
      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={`Удалить «${source.title}»?`}
        description="Это нельзя отменить."
      >
        <ul className="mb-5 list-disc space-y-1 pl-5 text-sm text-fg-muted">
          <li>все сборы ({source.runs}) и {num(source.comments)} {w.items.toLowerCase()}{source.members ? `, список из ${num(source.members)} участников` : ''};</li>
          <li>источник пропадёт из поиска, графа, пересечений и досье людей;</li>
          <li>его мониторинг и уведомления тоже удалятся.</li>
        </ul>
        <p className="mb-5 text-[13px] text-fg-subtle">Если нужно просто убрать его из аналитики — лучше «Отключить»: данные останутся.</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Отмена</Button>
          <Button variant="secondary" icon={<EyeOff className="size-4" />} onClick={() => (hide.mutate(true), setConfirmDelete(false))}>Отключить</Button>
          <Button variant="danger" icon={<Trash2 className="size-4" />} loading={remove.isPending} onClick={() => remove.mutate()}>Удалить</Button>
        </div>
      </Dialog>
    </div>
  )
}
