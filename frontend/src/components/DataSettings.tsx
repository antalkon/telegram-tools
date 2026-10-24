import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ArchiveRestore, Download, Gauge, Rocket, ShieldCheck, SlidersHorizontal, Trash2, Upload } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { api, type ArchiveInfo, type ImportMode, type ImportResult, type LimitValues, type LimitsProfile, type LimitsSettings, type LimitsStats } from '../lib/api'
import { dateTime, duration, num } from '../lib/format'
import { useToast } from './Toast'
import { Badge, Button, Card, CardHeader, Dialog, Field, Input, Skeleton, Switch } from './ui'

// ---------- Telegram load ----------

const PROFILES: { value: LimitsProfile; label: string; hint: string; icon: typeof Gauge }[] = [
  { value: 'standard', label: 'Стандартный', hint: 'Как раньше: без пауз, максимальная скорость', icon: Rocket },
  { value: 'optimized', label: 'Оптимизированный', hint: 'Паузы и адаптивное замедление: медленнее, но реже FloodWait', icon: ShieldCheck },
  { value: 'custom', label: 'Свои настройки', hint: 'Каждый параметр вручную', icon: SlidersHorizontal },
]

type NumKey = Exclude<keyof LimitValues, 'adaptive'>
const FIELDS: { key: NumKey; label: string; unit: string; hint: string; step?: number }[] = [
  { key: 'request_interval', label: 'Пауза между любыми запросами', unit: 'с', hint: 'Общий минимум для всех запросов аккаунта', step: 0.1 },
  { key: 'history_interval', label: 'Чтение сообщений и участников', unit: 'с', hint: 'Между страницами по 100 сообщений', step: 0.1 },
  { key: 'heavy_interval', label: 'Тяжёлые запросы', unit: 'с', hint: 'Поиск по @username, полные профили, инвайты, похожие каналы', step: 0.5 },
  { key: 'file_interval', label: 'Загрузка файлов', unit: 'с', hint: 'Между частями аватарок', step: 0.1 },
  { key: 'jitter', label: 'Случайный разброс пауз', unit: '×', hint: '0.3 — к каждой паузе добавляется до 30%, ритм не выглядит скриптовым', step: 0.1 },
  { key: 'flood_sleep_threshold', label: 'Пережидать FloodWait до', unit: 'с', hint: 'Дольше — сбор ставит этап на паузу с таймером или откладывает его' },
  { key: 'avatar_concurrency', label: 'Аватарки параллельно', unit: 'шт', hint: 'Сколько фото качать одновременно' },
  { key: 'job_pause', label: 'Пауза между задачами аккаунта', unit: 'с', hint: 'Перед следующей задачей того же аккаунта' },
  { key: 'details_limit', label: 'Проверок каналов за запуск', unit: 'шт', hint: '«Каналы пользователей»: полные данные найденных каналов' },
  { key: 'details_ttl_days', label: 'Перепроверять каналы через', unit: 'дн', hint: '«Каналы пользователей»: данные свежее не запрашиваются' },
  { key: 'web_page_delay', label: 'Пауза между страницами t.me/s', unit: 'с', hint: 'Сбор постов без аккаунта', step: 0.5 },
]

function LimitStats() {
  const q = useQuery({ queryKey: ['limits-stats'], queryFn: () => api<LimitsStats>('/settings/limits/stats'), refetchInterval: 30_000 })
  const s = q.data
  if (!s) return null
  const slowed = Object.values(s.slowdown).flatMap((m) => Object.entries(m))
  return (
    <div className="flex flex-col gap-3 border-t border-line pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">FloodWait за 24 часа</h3>
        <span className="text-[12px] text-fg-subtle">запросов с запуска сервера: <span className="font-mono">{num(s.requests)}</span></span>
      </div>
      {s.floods === 0 ? (
        <p className="text-[13px] text-fg-subtle">Ни одного ограничения от Telegram. Счётчик сбрасывается при перезапуске сервера.</p>
      ) : (
        <>
          <p className="text-[13px] text-fg-muted">
            {num(s.floods)} раз, суммарно ждали {duration(s.wait_seconds)}.
            {slowed.length > 0 && <> Сейчас замедлены: {slowed.map(([k, v]) => `${KIND_LABELS[k] ?? k} +${v} с`).join(', ')}.</>}
          </p>
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="text-left text-fg-subtle">
                <tr className="border-b border-line">
                  <th scope="col" className="px-3 py-2 font-medium">Запрос</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Раз</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Самый долгий</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Всего</th>
                </tr>
              </thead>
              <tbody>
                {s.by_method.map((m) => (
                  <tr key={m.method} className="border-b border-line/60 last:border-0">
                    <td className="px-3 py-1.5 font-mono">{m.method}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular">{num(m.count)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular">{duration(m.max_seconds)}</td>
                    <td className="px-3 py-1.5 text-right font-mono tabular">{duration(m.total_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {s.by_method.some((m) => m.method === 'ResolveUsername') && (
            <p className="text-[12.5px] text-fg-subtle">ResolveUsername Telegram ограничивает строже всего. Помогает пауза для тяжёлых запросов 3–5 с.</p>
          )}
        </>
      )}
    </div>
  )
}

const KIND_LABELS: Record<string, string> = { heavy: 'тяжёлые', history: 'чтение', file: 'файлы', other: 'прочие' }

export function TelegramLimitsCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['limits'], queryFn: () => api<LimitsSettings>('/settings/limits') })
  const save = useMutation({
    mutationFn: (body: { profile: LimitsProfile; custom?: Partial<LimitValues> }) => api<LimitsSettings>('/settings/limits', { method: 'PUT', json: body }),
    onSuccess: (data) => qc.setQueryData(['limits'], data),
    onError: (e) => toast(e.message, 'error'),
  })
  const s = q.data
  const values = (): LimitValues => {
    const { profile: _p, presets: _pr, fields: _f, ...v } = s!
    return v
  }
  const setValue = (key: keyof LimitValues, v: number | boolean) => save.mutate({ profile: 'custom', custom: { ...values(), [key]: v } })

  return (
    <Card>
      <CardHeader icon={<Gauge className="size-4" />} title="Нагрузка на Telegram"
        description="Как часто панель обращается к Telegram от имени аккаунтов. Медленнее — значит меньше FloodWait и риска ограничений." />
      {!s ? <div className="p-5"><Skeleton className="h-28" /></div> : (
        <div className="flex flex-col gap-5 p-5">
          <div role="radiogroup" aria-label="Профиль нагрузки" className="grid gap-2 sm:grid-cols-3">
            {PROFILES.map((p) => (
              <button
                key={p.value}
                role="radio"
                aria-checked={s.profile === p.value}
                onClick={() => save.mutate({ profile: p.value })}
                className={clsx('flex items-start gap-3 rounded-xl border p-3 text-left transition-colors', s.profile === p.value ? 'border-accent/60 bg-accent-soft' : 'border-line hover:border-line-strong')}
              >
                <p.icon className={clsx('mt-0.5 size-4 shrink-0', s.profile === p.value ? 'text-accent' : 'text-fg-subtle')} aria-hidden />
                <span>
                  <span className="block text-sm font-medium">{p.label}</span>
                  <span className="block text-[12px] text-fg-subtle">{p.hint}</span>
                </span>
              </button>
            ))}
          </div>

          {s.profile === 'custom' ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {FIELDS.map((f) => (
                  <LimitField key={`${f.key}-${s[f.key]}`} f={f} value={s[f.key]} range={s.fields[f.key]}
                    presets={[s.presets.standard[f.key], s.presets.optimized[f.key]]} onSave={(v) => setValue(f.key, v)} />
                ))}
              </div>
              <Switch checked={s.adaptive} onChange={(v) => setValue('adaptive', v)} label="Адаптивное замедление"
                description="После FloodWait этот тип запросов идёт вдвое медленнее (до минуты на запрос) и возвращается к норме через 15 минут без ошибок" />
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" onClick={() => save.mutate({ profile: 'custom', custom: s.presets.standard })}>Заполнить как «Стандартный»</Button>
                <Button size="sm" variant="ghost" onClick={() => save.mutate({ profile: 'custom', custom: s.presets.optimized })}>Заполнить как «Оптимизированный»</Button>
              </div>
            </div>
          ) : (
            <dl className="grid grid-cols-2 gap-2 text-[12.5px] sm:grid-cols-4">
              {([
                ['Пауза тяжёлых', `${s.heavy_interval} с`],
                ['Чтение сообщений', `${s.history_interval} с`],
                ['Между задачами', `${s.job_pause} с`],
                ['Адаптивно', s.adaptive ? 'да' : 'нет'],
              ] as const).map(([k, v]) => (
                <div key={k} className="rounded-lg border border-line bg-surface px-3 py-2">
                  <dt className="text-[11.5px] text-fg-subtle">{k}</dt>
                  <dd className="font-mono">{v}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="text-[12.5px] text-fg-subtle">
            Всегда включено: одна задача на аккаунт за раз, повторное использование найденных @username и access hash,
            аватарки не качаются повторно, проверенные профили не перепроверяются без нужды.
          </p>
          <LimitStats />
        </div>
      )}
    </Card>
  )
}

function LimitField({ f, value, range, presets, onSave }: {
  f: (typeof FIELDS)[number]
  value: number
  range: { min: number; max: number }
  presets: [number, number]
  onSave: (v: number) => void
}) {
  const id = useId()
  return (
    <Field label={f.label} htmlFor={id} hint={<>{f.hint}. Стандарт {presets[0]}, оптим. {presets[1]}</>}>
      <Input id={id} type="number" inputMode="decimal" min={range.min} max={range.max} step={f.step ?? 1} defaultValue={value}
        className="font-mono" trailing={<span className="pr-1 text-[12px] text-fg-subtle">{f.unit}</span>}
        onBlur={(e) => {
          const v = Number(e.target.value)
          if (e.target.value !== '' && Number.isFinite(v) && v !== value) onSave(v)
        }} />
    </Field>
  )
}

// ---------- export / import / wipe ----------

const MODES: { value: ImportMode; label: string; hint: string }[] = [
  { value: 'merge', label: 'Объединить, оставить своё', hint: 'Добавить из архива то, чего нет. Совпадающие записи остаются как есть.' },
  { value: 'overwrite', label: 'Объединить, заменить совпадения', hint: 'Добавить новое, а совпадающие записи (люди, заметки, метаданные, сборы) заменить версией из архива.' },
  { value: 'replace', label: 'Полная замена', hint: 'Удалить текущие данные и загрузить архив целиком. Telegram-аккаунты заменяются, только если они есть в архиве; API-токены остаются.' },
]

const TABLE_LABELS: [string, string][] = [
  ['tg_peers', 'людей и чатов'], ['comments', 'сообщений'], ['jobs', 'сборов'], ['peer_dossiers', 'досье'],
  ['channel_posts', 'постов'], ['found_channels', 'найденных каналов'],
]

function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ImportMode>('merge')
  const [safety, setSafety] = useState(true)
  const form = (extra?: Record<string, string>) => {
    const fd = new FormData()
    fd.append('file', file!)
    Object.entries(extra ?? {}).forEach(([k, v]) => fd.append(k, v))
    return fd
  }
  const inspect = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData()
      fd.append('file', f)
      return api<ArchiveInfo>('/data/inspect', { method: 'POST', body: fd })
    },
  })
  const run = useMutation({
    mutationFn: () => api<ImportResult>('/data/import', { method: 'POST', body: form({ mode, safety_copy: String(safety) }) }),
    onSuccess: (r) => {
      qc.invalidateQueries()
      toast(`Импорт завершён за ${duration(r.seconds)}`, 'success')
    },
  })
  const close = () => {
    setFile(null)
    inspect.reset()
    run.reset()
    onClose()
  }
  const info = inspect.data
  const r = run.data
  const added = r ? Object.values(r.tables).reduce((a, t) => a + t.added, 0) : 0
  const updated = r ? Object.values(r.tables).reduce((a, t) => a + t.updated, 0) : 0

  return (
    <Dialog open={open} onClose={close} title="Импорт данных" width="max-w-lg"
      description="Архив, скачанный кнопкой «Экспорт» в этой или другой панели TG Toolkit">
      {r ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm">
            Готово: добавлено <span className="font-mono">{num(added)}</span>
            {r.mode === 'overwrite' && <>, обновлено <span className="font-mono">{num(updated)}</span></>} записей,
            файлов {num(r.files)}, аватарок {num(r.avatars)}.
          </p>
          {r.backup && <p className="text-[12.5px] text-fg-subtle">Копия прежней базы: data/backups/{r.backup}</p>}
          {r.warnings.map((w) => (
            <p key={w} className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning-soft/40 px-3 py-2 text-[12.5px]">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden /> {w}
            </p>
          ))}
          <div className="flex justify-end"><Button variant="primary" onClick={close}>Закрыть</Button></div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <input ref={input} type="file" accept=".zip,application/zip" className="sr-only" aria-label="Файл архива"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              run.reset()
              if (f) inspect.mutate(f)
              e.target.value = ''
            }} />
          <div className="flex flex-wrap items-center gap-3">
            <Button icon={<Upload className="size-4" />} loading={inspect.isPending} onClick={() => input.current?.click()}>
              {file ? 'Другой файл' : 'Выбрать архив'}
            </Button>
            {file && <span className="min-w-0 truncate text-[13px] text-fg-muted">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} МБ</span>}
          </div>
          {inspect.error && <p role="alert" className="text-[13px] text-danger">{inspect.error.message}</p>}
          {info && (
            <>
              <div className="rounded-xl border border-line bg-surface px-3 py-2.5 text-[12.5px]">
                <div className="mb-1 text-fg-subtle">Архив от {dateTime(info.created_at)}</div>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {TABLE_LABELS.filter(([t]) => info.tables[t]).map(([t, l]) => (
                    <span key={t}><span className="font-mono">{num(info.tables[t])}</span> {l}</span>
                  ))}
                  <span><span className="font-mono">{num(info.files)}</span> PDF</span>
                  <span><span className="font-mono">{num(info.avatars)}</span> аватарок</span>
                </div>
                {info.includes_sessions && (
                  <div className="mt-1.5">
                    {info.same_key ? <Badge tone="success">с Telegram-аккаунтами</Badge>
                      : <Badge tone="warning">аккаунты не перенесутся: другой TGT_SECRET_KEY</Badge>}
                  </div>
                )}
              </div>
              <div role="radiogroup" aria-label="Как импортировать" className="flex flex-col gap-2">
                {MODES.map((m) => (
                  <button key={m.value} role="radio" aria-checked={mode === m.value} onClick={() => setMode(m.value)}
                    className={clsx('rounded-xl border p-3 text-left transition-colors', mode === m.value
                      ? (m.value === 'replace' ? 'border-danger/50 bg-danger-soft/50' : 'border-accent/60 bg-accent-soft')
                      : 'border-line hover:border-line-strong')}>
                    <span className="block text-sm font-medium">{m.label}</span>
                    <span className="block text-[12px] text-fg-subtle">{m.hint}</span>
                  </button>
                ))}
              </div>
              {mode === 'replace' && (
                <Switch checked={safety} onChange={setSafety} label="Сохранить копию текущей базы"
                  description="В папку data/backups (хранятся 3 последние копии)" />
              )}
              {run.error && <p role="alert" className="text-[13px] text-danger">{run.error.message}</p>}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={close}>Отмена</Button>
                <Button variant={mode === 'replace' ? 'danger' : 'primary'} loading={run.isPending} icon={<ArchiveRestore className="size-4" />}
                  onClick={() => run.mutate()}>
                  {mode === 'replace' ? 'Заменить все данные' : 'Импортировать'}
                </Button>
              </div>
              {run.isPending && <p className="text-[12.5px] text-fg-subtle">Большие архивы загружаются несколько минут. Сборы на это время приостановлены.</p>}
            </>
          )}
        </div>
      )}
    </Dialog>
  )
}

function WipeDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [keepAccounts, setKeepAccounts] = useState(true)
  const [keepSettings, setKeepSettings] = useState(true)
  const [safety, setSafety] = useState(true)
  const [confirm, setConfirm] = useState('')
  const id = useId()
  const wipe = useMutation({
    mutationFn: () => api<{ backup: string | null }>('/data/wipe', { method: 'POST', json: { confirm, keep_accounts: keepAccounts, keep_settings: keepSettings, safety_copy: safety } }),
    onSuccess: (r) => {
      qc.invalidateQueries()
      toast(r.backup ? `Данные удалены. Копия: data/backups/${r.backup}` : 'Данные удалены', 'success')
      setConfirm('')
      onClose()
    },
  })
  return (
    <Dialog open={open} onClose={onClose} title="Очистить все данные"
      description="Удаляются источники, сборы, сообщения, люди, досье и PDF, найденные каналы, посты, мониторинги, уведомления и аватарки.">
      <div className="flex flex-col gap-4">
        <Switch checked={keepAccounts} onChange={setKeepAccounts} label="Оставить Telegram-аккаунты" />
        <Switch checked={keepSettings} onChange={setKeepSettings} label="Оставить настройки и API-токены" />
        <Switch checked={safety} onChange={setSafety} label="Сохранить копию базы перед удалением" description="В data/backups, хранятся 3 последние копии" />
        <Field label="Для подтверждения введите УДАЛИТЬ" htmlFor={id} error={wipe.error?.message}>
          <Input id={id} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Отмена</Button>
          <Button variant="danger" icon={<Trash2 className="size-4" />} disabled={confirm.trim().toUpperCase() !== 'УДАЛИТЬ'}
            loading={wipe.isPending} onClick={() => wipe.mutate()}>Удалить всё</Button>
        </div>
      </div>
    </Dialog>
  )
}

export function DataTransferCard() {
  const [avatars, setAvatars] = useState(true)
  const [accounts, setAccounts] = useState(false)
  const [importing, setImporting] = useState(false)
  const [wiping, setWiping] = useState(false)
  return (
    <Card>
      <CardHeader icon={<ArchiveRestore className="size-4" />} title="Перенос и очистка данных"
        description="Полная выгрузка в один ZIP, загрузка такого архива сюда или в другую панель, удаление всего собранного" />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-3">
          <div className="text-[13px] font-medium">Экспорт</div>
          <Switch checked={avatars} onChange={setAvatars} label="С аватарками" description="Архив заметно тяжелее; без них аватарки докачаются при следующих сборах" />
          <Switch checked={accounts} onChange={setAccounts} label="С Telegram-аккаунтами"
            description="Сессии зашифрованы и откроются только на панели с тем же TGT_SECRET_KEY. Храните такой архив как пароль." />
          <div>
            <a href={`/api/data/export?avatars=${avatars}&accounts=${accounts}`} download
              className="inline-flex h-10 items-center gap-2 rounded-[10px] border border-line bg-surface px-4 text-sm font-medium transition-colors hover:border-line-strong hover:bg-elevated">
              <Download className="size-4" aria-hidden /> Скачать архив
            </a>
          </div>
          <p className="text-[12.5px] text-fg-subtle">В архиве всё собранное, досье и PDF, метки и заметки, мониторинги и настройки. API-токены не выгружаются никогда.</p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <div className="min-w-0 text-[13px]">
            <div className="font-medium">Импорт</div>
            <div className="text-fg-subtle">Объединить с текущими данными или заменить их целиком</div>
          </div>
          <Button variant="secondary" icon={<Upload className="size-4" />} onClick={() => setImporting(true)}>Импортировать…</Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <div className="min-w-0 text-[13px]">
            <div className="font-medium text-danger">Очистить все данные</div>
            <div className="text-fg-subtle">Аккаунты и настройки можно оставить. Перед удалением сохраняется копия базы.</div>
          </div>
          <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setWiping(true)}>Очистить…</Button>
        </div>
      </div>
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
      <WipeDialog open={wiping} onClose={() => setWiping(false)} />
    </Card>
  )
}
