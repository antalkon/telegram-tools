import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { BookOpen, Bot, Check, Copy, ExternalLink, KeyRound, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api, type ApiToken } from '../lib/api'
import { dateTime, relative } from '../lib/format'
import { useToast } from './Toast'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, Field, Input, Segmented, Skeleton } from './ui'

const PLACEHOLDER = 'tgt_ВАШ_ТОКЕН'

function CopyBlock({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false)
  const copy = () => navigator.clipboard.writeText(text).then(() => (setDone(true), setTimeout(() => setDone(false), 1500)))
  return (
    <div className="relative">
      <pre className="scrollbar-thin overflow-x-auto rounded-[10px] border border-line bg-surface py-3 pr-12 pl-3 font-mono text-[12.5px] leading-relaxed whitespace-pre text-fg">{text}</pre>
      <button onClick={copy} aria-label={`Скопировать: ${label}`} title="Скопировать"
        className="absolute top-2 right-2 flex size-8 items-center justify-center rounded-md text-fg-subtle hover:bg-elevated hover:text-fg">
        {done ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
      </button>
    </div>
  )
}

function NewTokenDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (t: ApiToken & { token: string }) => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'read' | 'full'>('read')
  const [expires, setExpires] = useState<'0' | '30' | '90' | '365'>('0')
  const create = useMutation({
    mutationFn: () => api<ApiToken & { token: string }>('/settings/tokens', {
      method: 'POST', json: { name: name.trim(), scope, expires_days: expires === '0' ? null : Number(expires) },
    }),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ['api-tokens'] })
      setName('')
      onCreated(t)
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) create.mutate()
  }
  return (
    <Dialog open={open} onClose={onClose} title="Новый API-токен" description="Токен покажем один раз — сохраните его сразу">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Название" htmlFor="token-name" hint="Для кого токен: «Claude», «скрипт выгрузки»…">
          <Input id="token-name" autoFocus value={name} maxLength={64} onChange={(e) => setName(e.target.value)} placeholder="Claude Code" />
        </Field>
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Права</span>
          <Segmented label="Права токена" value={scope} onChange={setScope}
            options={[{ value: 'read', label: 'Только чтение' }, { value: 'full', label: 'Полный доступ' }]} />
          <p className="text-[12.5px] text-fg-subtle">
            {scope === 'read'
              ? 'Поиск, профили, аналитика — без изменений и без запросов в Telegram.'
              : 'Ещё метки, заметки, метаданные и запуск сборов от имени вашего Telegram-аккаунта.'}
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Срок действия</span>
          <Segmented label="Срок действия" value={expires} onChange={setExpires}
            options={[{ value: '0', label: 'Бессрочно' }, { value: '30', label: '30 дней' }, { value: '90', label: '90 дней' }, { value: '365', label: 'Год' }]} />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!name.trim()}>Создать</Button>
        </div>
      </form>
    </Dialog>
  )
}

export function ApiTokensCard({ fresh, onCreated }: { fresh: (ApiToken & { token: string }) | null; onCreated: (t: ApiToken & { token: string }) => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [now] = useState(() => Date.now())
  const tokens = useQuery({ queryKey: ['api-tokens'], queryFn: () => api<ApiToken[]>('/settings/tokens') })
  const revoke = useMutation({
    mutationFn: (t: ApiToken) => api(`/settings/tokens/${t.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-tokens'] })
      toast('Токен отозван', 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  return (
    <Card>
      <CardHeader
        icon={<KeyRound className="size-4" />}
        title="API-токены"
        description="Для HTTP API и MCP-сервера. Заголовок: Authorization: Bearer tgt_…"
        actions={
          <>
            <a href="/api/docs" target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-fg-muted hover:bg-elevated hover:text-fg">
              <BookOpen className="size-3.5" aria-hidden /> Документация API <ExternalLink className="size-3" aria-hidden />
            </a>
            <Button size="sm" variant="primary" icon={<Plus className="size-3.5" aria-hidden />} onClick={() => setOpen(true)}>Создать токен</Button>
          </>
        }
      />
      {fresh && (
        <div className="flex flex-col gap-2 border-b border-line bg-success/5 px-5 py-4">
          <div className="flex items-center gap-2 text-[13px] font-medium text-success">
            <Check className="size-4" aria-hidden /> Токен «{fresh.name}» создан — скопируйте его сейчас, потом он не будет показан
          </div>
          <CopyBlock text={fresh.token} label="токен" />
        </div>
      )}
      {tokens.isLoading ? (
        <div className="p-5"><Skeleton className="h-12" /></div>
      ) : !tokens.data?.length ? (
        <EmptyState icon={<KeyRound className="size-5" />} title="Токенов пока нет" description="Создайте токен, чтобы работать с панелью из скриптов или подключить ИИ-агента по MCP" />
      ) : (
        <ul className="divide-y divide-line/70">
          {tokens.data.map((t) => {
            const expired = !!t.expires_at && new Date(t.expires_at).getTime() < now
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-medium">{t.name}</span>
                    <Badge tone={t.scope === 'full' ? 'warning' : 'neutral'}>{t.scope === 'full' ? 'полный доступ' : 'только чтение'}</Badge>
                    {expired && <Badge tone="danger">истёк</Badge>}
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-fg-subtle">
                    <span className="font-mono">{t.prefix}…</span>
                    <span>создан {dateTime(t.created_at)}</span>
                    <span>{t.last_used_at ? `использован ${relative(t.last_used_at)}` : 'ещё не использовался'}</span>
                    {t.expires_at && !expired && <span>до {dateTime(t.expires_at)}</span>}
                  </div>
                </div>
                <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" aria-hidden />} loading={revoke.isPending && revoke.variables?.id === t.id}
                  onClick={() => confirm(`Отозвать токен «${t.name}»? Все, кто им пользуется, потеряют доступ.`) && revoke.mutate(t)}>
                  Отозвать
                </Button>
              </li>
            )
          })}
        </ul>
      )}
      <NewTokenDialog open={open} onClose={() => setOpen(false)} onCreated={(t) => (setOpen(false), onCreated(t))} />
    </Card>
  )
}

type Client = 'claude-code' | 'json' | 'desktop' | 'curl'

export function McpCard({ token }: { token: string | null }) {
  const [client, setClient] = useState<Client>('claude-code')
  const origin = window.location.origin
  const url = `${origin}/mcp`
  const t = token ?? PLACEHOLDER
  const snippets: Record<Client, { text: string; hint: string }> = {
    'claude-code': {
      text: `claude mcp add --transport http tg-toolkit ${url} \\\n  --header "Authorization: Bearer ${t}"`,
      hint: 'Выполните в терминале — сервер появится в Claude Code (проверка: /mcp).',
    },
    json: {
      text: JSON.stringify({ mcpServers: { 'tg-toolkit': { url, headers: { Authorization: `Bearer ${t}` } } } }, null, 2),
      hint: 'Cursor (.cursor/mcp.json), Windsurf, VS Code и другие клиенты с поддержкой Streamable HTTP.',
    },
    desktop: {
      text: JSON.stringify({ mcpServers: { 'tg-toolkit': { command: 'npx', args: ['-y', 'mcp-remote', url, '--header', `Authorization:Bearer ${t}`] } } }, null, 2),
      hint: 'Claude Desktop: добавьте в claude_desktop_config.json (нужен Node.js) и перезапустите приложение.',
    },
    curl: {
      text: `curl -H "Authorization: Bearer ${t}" \\\n  "${origin}/api/users?limit=5"`,
      hint: 'Обычный HTTP API — все эндпоинты описаны в документации.',
    },
  }
  const local = /^(localhost|127\.|\[::1\])/.test(window.location.hostname)
  return (
    <Card>
      <CardHeader icon={<Bot className="size-4" />} title="MCP для ИИ-агентов" description="Claude, Cursor и другие агенты ищут, читают профили и аналитику, ведут метки и запускают сборы" />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-fg-muted">Адрес сервера:</span>
          <code className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-[12.5px]">{url}</code>
          <span className="text-fg-subtle">Streamable HTTP, тот же API-токен</span>
        </div>
        <Segmented label="Клиент" value={client} onChange={setClient} options={[
          { value: 'claude-code', label: 'Claude Code' }, { value: 'json', label: 'Cursor и др.' },
          { value: 'desktop', label: 'Claude Desktop' }, { value: 'curl', label: 'curl' },
        ]} />
        <CopyBlock text={snippets[client].text} label="конфигурация" />
        <p className="-mt-2 text-[12.5px] text-fg-subtle">
          {snippets[client].hint}
          {!token && ' Подставьте свой токен вместо tgt_ВАШ_ТОКЕН — или создайте новый, и он подставится сам.'}
        </p>
        {local && (
          <p className={clsx('flex items-start gap-2 rounded-[10px] border border-warning/30 bg-warning-soft px-3 py-2 text-[12.5px] text-warning')}>
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Панель открыта по локальному адресу — агент на другой машине до неё не достучится. Для удалённого доступа укажите адрес, по которому панель доступна из сети (через HTTPS).
          </p>
        )}
        <details className="text-[13px]">
          <summary className="cursor-pointer text-fg-muted hover:text-fg">Что умеют инструменты</summary>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-fg-muted">
            <li><b className="text-fg">Чтение:</b> обзор базы, источники и их аналитика, пересечения аудиторий, полнотекстовый поиск по сообщениям и контекст, поиск людей по метаданным и PDF, список людей с фильтрами, профиль, сообщения и связи человека, текст прикреплённых PDF, найденные каналы, задачи.</li>
            <li><b className="text-fg">Изменения</b> (полный доступ): метки, заметки, избранное, игнор, метаданные.</li>
            <li><b className="text-fg">Telegram</b> (полный доступ): предпросмотр ссылки, сбор комментаторов канала, индексация чата, дозабор источника, поиск каналов пользователей.</li>
          </ul>
        </details>
      </div>
    </Card>
  )
}
