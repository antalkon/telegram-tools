import { useMutation, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, Link2, Play, Smartphone } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Avatar } from '../../components/Avatar'
import { Button, Card, Field, Input, Segmented, Switch } from '../../components/ui'
import { api, type Account, type Job } from '../../lib/api'

const LINK_RE =
  /^(?:@[A-Za-z][\w]{3,31}|(?:https?:\/\/)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)\/(?:s\/)?(?:\+[\w-]+|joinchat\/[\w-]+|c\/\d+|[A-Za-z][\w]{3,31})(?:[/?#].*)?|[A-Za-z][\w]{3,31})$/

type Strategy = 'auto' | 'fast' | 'per_post'

export function CollectorForm({ compact }: { compact?: boolean }) {
  const navigate = useNavigate()
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const [channel, setChannel] = useState('')
  const [touched, setTouched] = useState(false)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [strategy, setStrategy] = useState<Strategy>('auto')
  const [avatars, setAvatars] = useState(true)
  const [incremental, setIncremental] = useState(false)

  const list = accounts.data ?? []
  const selected = accountId ?? list.find((a) => a.status === 'active')?.id ?? list[0]?.id ?? null
  // several links separated by spaces, commas or new lines start one job each
  const links = channel.split(/[\s,]+/).filter(Boolean)
  const valid = links.length > 0 && links.every((l) => LINK_RE.test(l))
  const linkError = touched && channel && !valid ? 'Укажите ссылку вида t.me/channel, @channel или t.me/+invite' : null

  const create = useMutation({
    mutationFn: async () => {
      const jobs: Job[] = []
      for (const link of links)
        jobs.push(
          await api<Job>('/tools/comment-collector/jobs', {
            method: 'POST',
            json: { channel: link, account_id: selected, strategy, download_avatars: avatars, mode: incremental ? 'incremental' : 'full' },
          }),
        )
      return jobs
    },
    onSuccess: (jobs) => navigate(jobs.length === 1 ? `/tools/comment-collector/jobs/${jobs[0].id}` : '/jobs'),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (valid && selected != null) create.mutate()
  }

  if (accounts.isSuccess && list.length === 0)
    return (
      <Card className="flex flex-wrap items-center gap-4 p-5">
        <Smartphone className="size-5 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">Нужен Telegram-аккаунт</div>
          <p className="text-[13px] text-fg-muted">Сбор комментариев идёт от имени пользовательского аккаунта.</p>
        </div>
        <Link to="/accounts" className="inline-flex h-9 items-center rounded-lg bg-accent px-3.5 text-sm font-medium text-accent-fg hover:bg-accent-hover">
          Подключить аккаунт
        </Link>
      </Card>
    )

  return (
    <Card className={clsx('p-5', compact && 'p-4')}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start">
          <div className="flex-1">
            <Field label="Ссылка на канал" htmlFor="channel" error={linkError ?? create.error?.message} hint="Публичный канал, @username или приглашение t.me/+… Можно несколько через пробел — они встанут в очередь">
              <Input
                id="channel"
                inputSize="lg"
                autoComplete="off"
                spellCheck={false}
                placeholder="https://t.me/durov"
                value={channel}
                invalid={!!linkError}
                aria-describedby={linkError ? 'channel-error' : 'channel-hint'}
                onChange={(e) => setChannel(e.target.value)}
                onBlur={() => setTouched(true)}
                leading={<Link2 className="size-4" />}
              />
            </Field>
          </div>
          <div className="md:pt-[26px]">
            <Button type="submit" variant="primary" size="lg" icon={<Play className="size-4" />} loading={create.isPending} disabled={!channel || selected == null} className="w-full md:w-auto">
              {links.length > 1 ? `Собрать ${links.length}` : 'Собрать'}
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          {list.length > 0 && (
            <div className="flex min-w-0 items-center gap-2 text-[13px] text-fg-muted">
              <span>Аккаунт:</span>
              <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Аккаунт для сбора">
                {list.map((a) => {
                  const name = a.first_name ?? a.phone
                  return (
                    <button
                      type="button"
                      key={a.id}
                      role="radio"
                      aria-checked={selected === a.id}
                      onClick={() => setAccountId(a.id)}
                      className={clsx(
                        'flex h-8 items-center gap-2 rounded-full border pr-3 pl-1 text-[13px] transition-colors duration-150',
                        selected === a.id ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg',
                      )}
                    >
                      <Avatar id={a.tg_user_id ?? a.id} name={name} photoId={a.photo_id} size={22} />
                      {name}
                      {a.status !== 'active' && <span className="size-1.5 rounded-full bg-danger" aria-label="ошибка сессии" />}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setAdvanced(!advanced)}
            aria-expanded={advanced}
            className="flex items-center gap-1 text-[13px] font-medium text-fg-muted transition-colors hover:text-fg"
          >
            Дополнительно <ChevronDown className={clsx('size-4 transition-transform duration-200', advanced && 'rotate-180')} aria-hidden />
          </button>
        </div>

        {advanced && (
          <div className="animate-in grid gap-5 rounded-xl border border-line bg-surface p-4 md:grid-cols-2">
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Режим сбора</span>
              <Segmented
                label="Режим сбора"
                value={strategy}
                onChange={setStrategy}
                options={[
                  { value: 'auto', label: 'Авто' },
                  { value: 'fast', label: 'Быстрый' },
                  { value: 'per_post', label: 'По постам' },
                ]}
              />
              <p className="text-[12.5px] text-fg-subtle">
                {strategy === 'per_post'
                  ? 'Запрос комментариев к каждому посту. Медленнее, но работает без доступа к истории группы.'
                  : strategy === 'fast'
                    ? 'Один проход по истории группы обсуждений: ~100 сообщений за запрос.'
                    : 'Быстрый проход по группе, при отсутствии доступа — переключение на «по постам».'}
              </p>
            </div>
            <div className="flex flex-col gap-4">
              <Switch checked={incremental} onChange={setIncremental} label="Только новое (дозабор)" description="Если канал уже собирался — прочитать только комментарии после прошлого сбора" />
              <Switch checked={avatars} onChange={setAvatars} label="Скачивать аватарки" description="Только тех, кого ещё нет в кэше" />
            </div>
          </div>
        )}
      </form>
    </Card>
  )
}
