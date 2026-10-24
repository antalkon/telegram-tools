import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, EyeOff, Link2, Play, Plus, ScanSearch, Smartphone, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, familyOf, type IndexerOptions, type Job, type ResolvedSource } from '../lib/api'
import { compact } from '../lib/format'
import { Avatar } from './Avatar'
import { AccountPicker, defaultAccount, jobPath, OptionsFields, optionsFor, TypeBadge, useAccounts } from './SourceBits'
import { useToast } from './Toast'
import { Button, Dialog, Field } from './ui'

type Checked = { link: string; info?: ResolvedSource; error?: string; withLinked?: boolean }

const splitLinks = (raw: string) => [...new Set(raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean))]

/**
 * Paste links of any kind → see what each one is (channel / supergroup / forum / group, size,
 * whether members are visible) → pick depth and what to collect → start. Nothing is read from
 * Telegram beyond the preview until «Запустить».
 */
export function AddSourceForm({ onDone, autoFocus, initialLinks }: { onDone?: () => void; autoFocus?: boolean; initialLinks?: string[] }) {
  const navigate = useNavigate()
  const toast = useToast()
  const qc = useQueryClient()
  const accounts = useAccounts()
  const [raw, setRaw] = useState(initialLinks?.join('\n') ?? '')
  const [accountId, setAccountId] = useState<number | null>(null)
  const [checked, setChecked] = useState<Checked[]>([])
  const [chatOpts, setChatOpts] = useState<IndexerOptions>({})
  const [channelOpts, setChannelOpts] = useState<IndexerOptions>({})
  const account = accountId ?? defaultAccount(accounts.data)

  const resolve = useMutation({
    mutationFn: async () => {
      const out: Checked[] = []
      for (const link of splitLinks(raw)) {
        try {
          const info = await api<ResolvedSource>('/sources/resolve', { method: 'POST', json: { link, account_id: account } })
          out.push({ link, info, withLinked: false })
        } catch (e) {
          out.push({ link, error: (e as Error).message })
        }
        setChecked([...out])
      }
      return out
    },
    onMutate: () => setChecked([]),
  })

  // links handed in (e.g. from «Каналы пользователей»): check them right away
  const autoChecked = useRef(false)
  useEffect(() => {
    if (initialLinks?.length && account != null && !autoChecked.current) {
      autoChecked.current = true
      resolve.mutate()
    }
  }, [initialLinks, account, resolve])

  const ready = checked.filter((c) => c.info)
  const families = new Set(ready.flatMap((c) => [familyOf(c.info!.type), ...(c.withLinked ? ['chat' as const] : [])]))

  const start = useMutation({
    mutationFn: async () => {
      const jobs: Job[] = []
      for (const c of ready) {
        const fam = familyOf(c.info!.type)
        const options = { ...optionsFor(fam, fam === 'chat' ? chatOpts : channelOpts), ...(c.withLinked ? optionsFor('chat', chatOpts) : {}) }
        const linked = c.withLinked && c.info!.linked_chat
        jobs.push(...(await api<Job[]>('/sources/add', {
          method: 'POST',
          json: {
            link: c.link, tool: c.info!.tool, account_id: account, options,
            linked_link: linked ? (linked.username ? `@${linked.username}` : String(linked.id)) : null,
          },
        })))
      }
      return jobs
    },
    onSuccess: (jobs) => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['sources'] })
      toast(jobs.length === 1 ? 'Сбор запущен' : `Запущено задач: ${jobs.length} — они выполнятся по очереди`, 'success')
      onDone?.()
      navigate(jobs.length === 1 ? jobPath(jobs[0]) : '/jobs')
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (accounts.isSuccess && !accounts.data.length)
    return (
      <div className="flex flex-wrap items-center gap-4">
        <Smartphone className="size-5 text-accent" aria-hidden />
        <div className="min-w-0 flex-1 text-sm">
          <div className="font-semibold">Нужен Telegram-аккаунт</div>
          <p className="text-[13px] text-fg-muted">Чтение каналов и чатов идёт от имени пользовательского аккаунта.</p>
        </div>
        <Link to="/accounts" className="inline-flex h-9 items-center rounded-lg bg-accent px-3.5 text-sm font-medium text-accent-fg hover:bg-accent-hover">Подключить</Link>
      </div>
    )

  const n = splitLinks(raw).length
  return (
    <div className="flex flex-col gap-4">
      <Field label="Ссылки" htmlFor="source-links" hint="Канал, группа, супергруппа или форум: t.me/name, @name, t.me/+приглашение, t.me/c/123, -100…; можно несколько через пробел или с новой строки">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <div className="flex flex-1 items-start gap-2 rounded-[10px] border border-line-strong/70 bg-surface px-3 py-2.5 focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgb(42_171_238/0.18)]">
            <Link2 className="mt-0.5 size-4 shrink-0 text-fg-subtle" aria-hidden />
            <textarea
              id="source-links"
              autoFocus={autoFocus}
              rows={Math.min(5, Math.max(1, raw.split('\n').length))}
              spellCheck={false}
              placeholder="https://t.me/durov  @some_chat"
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.metaKey || e.ctrlKey) && n && resolve.mutate()}
              className="min-h-6 flex-1 resize-none bg-transparent text-[15px] text-fg outline-none placeholder:text-fg-subtle"
            />
          </div>
          <Button variant={ready.length ? 'secondary' : 'primary'} icon={<ScanSearch className="size-4" />} loading={resolve.isPending} disabled={!n || account == null} onClick={() => resolve.mutate()} className="h-11">
            Проверить{n > 1 ? ` ${n}` : ''}
          </Button>
        </div>
      </Field>
      <AccountPicker value={account} onChange={setAccountId} />

      {checked.length > 0 && (
        <ul className="flex flex-col gap-2" aria-live="polite">
          {checked.map((c, i) => (
            <li key={c.link} className={clsx('rounded-xl border px-3.5 py-3', c.error ? 'border-danger/30 bg-danger-soft/40' : 'border-line bg-surface')}>
              {c.error ? (
                <div className="flex items-start gap-2.5 text-sm">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
                  <div className="min-w-0">
                    <div className="truncate font-medium">{c.link}</div>
                    <div className="text-[13px] text-fg-muted">{c.error}</div>
                  </div>
                </div>
              ) : (
                <ResolvedRow c={c} onLinked={(v) => setChecked((list) => list.map((x, j) => (j === i ? { ...x, withLinked: v } : x)))}
                  onRemove={() => setChecked((list) => list.filter((_, j) => j !== i))} />
              )}
            </li>
          ))}
        </ul>
      )}

      {ready.length > 0 && (
        <div className="flex flex-col gap-4">
          {families.has('chat') && (
            <section className="rounded-xl border border-line bg-surface p-4">
              <h3 className="mb-3 text-[13px] font-semibold text-fg-muted">Чаты: что собирать</h3>
              <OptionsFields family="chat" value={chatOpts} onChange={setChatOpts} />
            </section>
          )}
          {families.has('channel') && (
            <section className="rounded-xl border border-line bg-surface p-4">
              <h3 className="mb-3 text-[13px] font-semibold text-fg-muted">Каналы: комментарии</h3>
              <OptionsFields family="channel" value={channelOpts} onChange={setChannelOpts} />
            </section>
          )}
          <div className="flex justify-end">
            <Button variant="primary" size="lg" icon={<Play className="size-4" />} loading={start.isPending} onClick={() => start.mutate()}>
              Запустить{ready.length > 1 ? ` (${ready.length})` : ''}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function ResolvedRow({ c, onLinked, onRemove }: { c: Checked; onLinked: (v: boolean) => void; onRemove: () => void }) {
  const s = c.info!
  const chat = familyOf(s.type) === 'chat'
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-3">
        <Avatar id={s.id} name={s.title} size={40} square={!chat} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-semibold">{s.title}</span>
            <TypeBadge type={s.type} />
            {s.exists && <span className="text-[12px] text-warning">уже добавлен — будет полная переиндексация</span>}
          </div>
          <div className="flex flex-wrap gap-x-3 text-[12.5px] text-fg-muted">
            {s.username && <span>@{s.username}</span>}
            {s.members_count != null && <span>{compact(s.members_count)} {chat ? 'участников' : 'подписчиков'}</span>}
            {chat && (s.members_visible
              ? <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 className="size-3" aria-hidden />участники видны</span>
              : <span className="inline-flex items-center gap-1"><EyeOff className="size-3" aria-hidden />список участников скрыт — будут только авторы сообщений</span>)}
            {!chat && !s.linked_chat && <span className="text-danger">комментарии выключены — собирать нечего</span>}
          </div>
          {s.about && <p className="mt-1 line-clamp-2 text-[12.5px] text-fg-subtle">{s.about}</p>}
        </div>
        <button onClick={onRemove} aria-label={`Убрать ${s.title}`} className="flex size-8 items-center justify-center rounded-lg text-fg-subtle hover:bg-elevated hover:text-fg">
          <X className="size-4" />
        </button>
      </div>
      {s.linked_chat && !chat && (
        <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line/70 px-3 py-2 text-[13px] hover:bg-elevated/60">
          <input type="checkbox" checked={!!c.withLinked} onChange={(e) => onLinked(e.target.checked)} className="mt-0.5 size-4 accent-[#2aabee]" />
          <span>
            Ещё и проиндексировать чат обсуждений «{s.linked_chat.title}» как отдельный источник
            <span className="block text-fg-subtle">Все его сообщения (не только комментарии) и участники — для поиска и пересечений{s.linked_chat.exists ? ' · уже добавлен' : ''}</span>
          </span>
        </label>
      )}
      {!s.is_member && chat && <p className="text-[12.5px] text-fg-subtle">Аккаунт не состоит в чате: у публичных групп история обычно доступна и так.</p>}
    </div>
  )
}

export function AddSourceDialog({ open, onClose, links }: { open: boolean; onClose: () => void; links?: string[] }) {
  return (
    <Dialog open={open} onClose={onClose} width="max-w-2xl" title="Добавить источник"
      description="Каналы собираются по комментариям; группы, супергруппы и форумы — по сообщениям и участникам.">
      {/* remount per link set so a new selection is checked from scratch */}
      {open && <AddSourceForm key={links?.join(',')} onDone={onClose} autoFocus={!links?.length} initialLinks={links} />}
    </Dialog>
  )
}

export function AddSourceButton({ size = 'md', label = 'Добавить источник' }: { size?: 'sm' | 'md'; label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="primary" size={size} icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>{label}</Button>
      <AddSourceDialog open={open} onClose={() => setOpen(false)} />
    </>
  )
}

