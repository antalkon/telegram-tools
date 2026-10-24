import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bell, Bot, Bookmark, Database, EyeOff, Send, Settings as SettingsIcon, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { ApiTokensCard, McpCard } from '../components/ApiAccess'
import { PeerLine } from '../components/PeerBits'
import { useInvalidateAnalytics } from '../components/SourceActions'
import { useToast } from '../components/Toast'
import { Button, Card, CardHeader, EmptyState, Field, Input, Skeleton, Switch } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Account, type ApiToken, type Exclusions, type MaintenanceStats, type NotifySettings, type PeerCard } from '../lib/api'
import { num } from '../lib/format'

function NotificationsCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['notify-settings'], queryFn: () => api<NotifySettings>('/settings/notifications') })
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState<string | null>(null)
  const [panelUrl, setPanelUrl] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<NotifySettings>('/settings/notifications', { method: 'PUT', json: body }),
    onSuccess: (data) => qc.setQueryData(['notify-settings'], data),
    onError: (e) => toast(e.message, 'error'),
  })
  const test = useMutation({
    mutationFn: () => api('/settings/notifications/test', { method: 'POST' }),
    onSuccess: () => toast('Тестовое сообщение отправлено', 'success'),
    onError: (e) => toast(e.message, 'error'),
  })
  const s = q.data
  if (!s) return <Card className="p-5"><Skeleton className="h-40" /></Card>
  const targets = [
    { value: 'none', label: 'Только в панели', icon: Bell, hint: 'Колокольчик в меню' },
    { value: 'saved', label: 'Избранное Telegram', icon: Bookmark, hint: 'Saved Messages вашего аккаунта' },
    { value: 'bot', label: 'Через бота', icon: Bot, hint: 'В любой чат или канал' },
  ] as const

  return (
    <Card>
      <CardHeader icon={<Bell className="size-4" />} title="Уведомления" description="О новых комментаторах, активности избранных и ошибках мониторинга" />
      <div className="flex flex-col gap-5 p-5">
        <div role="radiogroup" aria-label="Куда отправлять" className="grid gap-2 sm:grid-cols-3">
          {targets.map((t) => (
            <button
              key={t.value}
              role="radio"
              aria-checked={s.target === t.value}
              onClick={() => save.mutate({ target: t.value, ...(t.value === 'saved' && !s.account_id && accounts.data?.[0] ? { account_id: accounts.data[0].id } : {}) })}
              className={clsx('flex items-start gap-3 rounded-xl border p-3 text-left transition-colors', s.target === t.value ? 'border-accent/60 bg-accent-soft' : 'border-line hover:border-line-strong')}
            >
              <t.icon className={clsx('mt-0.5 size-4', s.target === t.value ? 'text-accent' : 'text-fg-subtle')} aria-hidden />
              <span>
                <span className="block text-sm font-medium">{t.label}</span>
                <span className="block text-[12px] text-fg-subtle">{t.hint}</span>
              </span>
            </button>
          ))}
        </div>

        {s.target === 'saved' && (
          <Field label="Аккаунт" htmlFor="notify-account" hint="Сообщения придут в «Избранное» этого аккаунта">
            <select
              id="notify-account"
              value={s.account_id ?? ''}
              onChange={(e) => save.mutate({ account_id: Number(e.target.value) })}
              className="h-10 rounded-[10px] border border-line bg-surface px-3 text-sm"
            >
              {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.first_name ?? a.phone}{a.username ? ` (@${a.username})` : ''}</option>)}
            </select>
          </Field>
        )}
        {s.target === 'bot' && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Токен бота" htmlFor="bot-token" hint={s.bot_token_set ? 'Токен сохранён (зашифрован). Введите новый, чтобы заменить.' : 'Создайте бота у @BotFather'}>
              <Input id="bot-token" type="password" autoComplete="off" value={token} placeholder={s.bot_token_set ? '••••••••' : '123456:ABC…'} onChange={(e) => setToken(e.target.value)}
                onBlur={() => token && (save.mutate({ bot_token: token }), setToken(''))} />
            </Field>
            <Field label="chat_id" htmlFor="bot-chat" hint="Ваш ID, ID группы (-100…) или @канал. Сначала напишите боту /start">
              <Input id="bot-chat" value={chatId ?? s.bot_chat_id ?? ''} onChange={(e) => setChatId(e.target.value)}
                onBlur={() => chatId != null && save.mutate({ bot_chat_id: chatId.trim() })} className="font-mono" />
            </Field>
          </div>
        )}
        {s.target !== 'none' && (
          <>
            <Field label="Адрес панели (необязательно)" htmlFor="panel-url" hint="Для кнопки «Открыть в панели» в сообщениях, например https://tg.example.com">
              <Input id="panel-url" value={panelUrl ?? s.panel_url ?? ''} placeholder="https://" onChange={(e) => setPanelUrl(e.target.value)}
                onBlur={() => panelUrl != null && save.mutate({ panel_url: panelUrl.trim() || null })} />
            </Field>
            <div>
              <Button variant="secondary" icon={<Send className="size-4" />} loading={test.isPending} onClick={() => test.mutate()}>Отправить тест</Button>
            </div>
          </>
        )}

        <div className="flex flex-col gap-4 border-t border-line pt-5">
          <Switch checked={s.new_users} onChange={(v) => save.mutate({ new_users: v })} label="Новые люди" description="Комментаторы, авторы и участники, которых не было в прошлом сборе источника" />
          {s.new_users && (
            <div className="flex items-center gap-3 pl-0.5 text-[13px] text-fg-muted">
              <span>Сообщать, если новых хотя бы</span>
              <Input aria-label="Минимум новых" type="number" min={1} value={s.min_new_users} onChange={(e) => save.mutate({ min_new_users: Math.max(1, Number(e.target.value) || 1) })} className="w-24 font-mono" />
            </div>
          )}
          <Switch checked={s.watch} onChange={(v) => save.mutate({ watch: v })} label="Активность избранных" description="Люди со звёздочкой оставили новые комментарии" />
          <Switch checked={s.failures} onChange={(v) => save.mutate({ failures: v })} label="Ошибки мониторинга" />
        </div>
      </div>
    </Card>
  )
}

function ExclusionsCard() {
  const qc = useQueryClient()
  const invalidate = useInvalidateAnalytics()
  const q = useQuery({ queryKey: ['exclusions'], queryFn: () => api<Exclusions>('/settings/exclusions') })
  const ignored = useQuery({ queryKey: ['ignored'], queryFn: () => api<PeerCard[]>('/ignored') })
  const save = useMutation({
    mutationFn: (body: Partial<Exclusions>) => api<Exclusions>('/settings/exclusions', { method: 'PUT', json: body }),
    onSuccess: (data) => {
      qc.setQueryData(['exclusions'], data)
      invalidate()
    },
  })
  const restore = useMutation({
    // hiding a channel and ignoring a person set the same flag
    mutationFn: (p: PeerCard) => api(`/users/${p.peer_id}/note`, { method: 'PUT', json: { ignored: false } }),
    onSuccess: invalidate,
  })
  return (
    <Card>
      <CardHeader icon={<EyeOff className="size-4" />} title="Исключения" description="Кого не показывать в списках, графах, пересечениях и уведомлениях. Данные не удаляются." />
      <div className="flex flex-col gap-4 p-5">
        {q.data && (
          <>
            <Switch checked={q.data.hide_bots} onChange={(v) => save.mutate({ hide_bots: v })} label="Скрывать ботов" />
            <Switch checked={q.data.hide_deleted} onChange={(v) => save.mutate({ hide_deleted: v })} label="Скрывать удалённые аккаунты" />
            <Switch checked={q.data.hide_channels} onChange={(v) => save.mutate({ hide_channels: v })} label="Скрывать тех, кто пишет от имени канала" description="И анонимных админов группы" />
          </>
        )}
        <div className="border-t border-line pt-4">
          <h3 className="mb-2 text-sm font-medium">Игнорируемые люди и отключённые источники</h3>
          {ignored.data?.length ? (
            <ul className="divide-y divide-line/70 rounded-xl border border-line">
              {ignored.data.map((p) => (
                <li key={p.peer_id} className="flex items-center gap-3 px-3 py-2">
                  <div className="min-w-0 flex-1"><PeerLine p={p} size={28} sub={p.kind === 'user' ? 'игнорируется' : 'источник отключён / игнорируется'} /></div>
                  <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() => restore.mutate(p)}>Вернуть</Button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon={<EyeOff className="size-5" />} title="Список пуст" description="Игнорировать человека можно в его досье, отключить источник — в его меню «…»." />
          )}
        </div>
      </div>
    </Card>
  )
}

const mb = (b: number) => `${(b / 1024 / 1024).toFixed(1)} МБ`

function MaintenanceCard() {
  const toast = useToast()
  const invalidate = useInvalidateAnalytics()
  const stats = useQuery({ queryKey: ['maintenance'], queryFn: () => api<MaintenanceStats>('/maintenance/stats') })
  const reindex = useMutation({
    mutationFn: () => api('/maintenance/reindex-search', { method: 'POST' }),
    onSuccess: () => toast('Поисковый индекс перестроен', 'success'),
    onError: (e) => toast(e.message, 'error'),
  })
  const prune = useMutation({
    mutationFn: () => api<{ pruned_runs: number }>('/maintenance/prune', { method: 'POST' }),
    onSuccess: (r) => {
      toast(`Очищено старых сборов: ${r.pruned_runs}`, 'success')
      stats.refetch()
      invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const s = stats.data
  return (
    <Card>
      <CardHeader icon={<Database className="size-4" />} title="Данные и обслуживание" description="Размер базы, поисковый индекс и старые сборы" />
      <div className="flex flex-col gap-4 p-5">
        {s ? (
          <dl className="grid grid-cols-2 gap-2 text-[13px] sm:grid-cols-4">
            {[
              ['База', mb(s.db_bytes)],
              ['Сообщений', num(s.messages)],
              ['Людей и чатов', num(s.peers)],
              ['Аватарок', `${num(s.avatars)} · ${mb(s.avatars_bytes)}`],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-surface px-3 py-2">
                <dt className="text-[11.5px] text-fg-subtle">{k}</dt>
                <dd className="font-mono">{v}</dd>
              </div>
            ))}
          </dl>
        ) : <Skeleton className="h-14" />}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <div className="min-w-0 text-[13px]">
            <div className="font-medium">Перестроить поисковый индекс</div>
            <div className="text-fg-subtle">Если поиск находит не всё — например, после ручных правок базы. Данные не меняются.</div>
          </div>
          <Button variant="secondary" loading={reindex.isPending} onClick={() => reindex.mutate()}>Перестроить</Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <div className="min-w-0 text-[13px]">
            <div className="font-medium">Очистить старые сборы</div>
            <div className="text-fg-subtle">
              {s?.stale_runs ? `${num(s.stale_runs)} прошлых сборов хранят ${num(s.stale_messages)} сообщений, которые аналитика уже не использует. Записи в истории останутся.` : 'Старых данных нет — аналитика использует только последние сборы.'}
            </div>
          </div>
          <Button variant="secondary" disabled={!s?.stale_runs} loading={prune.isPending} onClick={() => prune.mutate()}>Очистить</Button>
        </div>
      </div>
    </Card>
  )
}

export default function Settings() {
  const [fresh, setFresh] = useState<(ApiToken & { token: string }) | null>(null)
  return (
    <Page>
      <PageHeader icon={<SettingsIcon className="size-5" />} title="Настройки" description="Уведомления, исключения из аналитики, обслуживание данных, API и MCP" />
      <div className="flex flex-col gap-5">
        <NotificationsCard />
        <ExclusionsCard />
        <MaintenanceCard />
        <section id="api" className="flex scroll-mt-6 flex-col gap-5">
          <ApiTokensCard fresh={fresh} onCreated={setFresh} />
          <McpCard token={fresh?.token ?? null} />
        </section>
      </div>
    </Page>
  )
}
