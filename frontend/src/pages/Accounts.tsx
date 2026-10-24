import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, ExternalLink, KeyRound, Plus, RefreshCw, ShieldCheck, Smartphone, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'
import { Badge, Button, Card, Dialog, EmptyState, Field, IconButton, Input, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Account } from '../lib/api'
import { relative } from '../lib/format'

type Step = 'creds' | 'code' | 'password'

function AddAccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [step, setStep] = useState<Step>('creds')
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [loginId, setLoginId] = useState('')
  const [delivery, setDelivery] = useState('')

  const reset = () => {
    setStep('creds')
    setCode('')
    setPassword('')
    setLoginId('')
  }
  const close = () => {
    reset()
    onClose()
  }
  const done = (acc: Account) => {
    qc.invalidateQueries({ queryKey: ['accounts'] })
    toast(`Аккаунт ${acc.first_name ?? acc.phone} подключён`, 'success')
    close()
  }

  const start = useMutation({
    mutationFn: () =>
      api<{ login_id: string; delivery: string }>('/accounts/login/start', {
        method: 'POST',
        json: { api_id: Number(apiId), api_hash: apiHash.trim(), phone: phone.trim() },
      }),
    onSuccess: (r) => {
      setLoginId(r.login_id)
      setDelivery(r.delivery)
      setStep('code')
    },
  })
  const sendCode = useMutation({
    mutationFn: () =>
      api<{ status: 'ok' | 'password_required'; account?: Account }>('/accounts/login/code', {
        method: 'POST',
        json: { login_id: loginId, code: code.trim() },
      }),
    onSuccess: (r) => (r.status === 'ok' && r.account ? done(r.account) : setStep('password')),
  })
  const sendPassword = useMutation({
    mutationFn: () =>
      api<{ status: 'ok'; account: Account }>('/accounts/login/password', { method: 'POST', json: { login_id: loginId, password } }),
    onSuccess: (r) => done(r.account),
  })

  const apiIdValid = /^\d{3,12}$/.test(apiId)
  const apiHashValid = /^[0-9a-fA-F]{32}$/.test(apiHash.trim())
  const phoneValid = /^\+?\d[\d\s-]{6,}$/.test(phone.trim())

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (step === 'creds' && apiIdValid && apiHashValid && phoneValid) start.mutate()
    if (step === 'code' && code.trim().length >= 3) sendCode.mutate()
    if (step === 'password' && password) sendPassword.mutate()
  }

  const steps: { key: Step; label: string }[] = [
    { key: 'creds', label: 'Данные' },
    { key: 'code', label: 'Код' },
    { key: 'password', label: '2FA' },
  ]
  const idx = steps.findIndex((s) => s.key === step)

  return (
    <Dialog open={open} onClose={close} title="Подключить Telegram-аккаунт" description="Сессия хранится на вашем сервере в зашифрованном виде.">
      <ol className="mb-5 flex items-center gap-2" aria-label="Шаги входа">
        {steps.map((s, i) => (
          <li key={s.key} className="flex flex-1 items-center gap-2">
            <span
              className={clsx(
                'flex size-6 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-semibold',
                i < idx ? 'bg-success text-black' : i === idx ? 'bg-accent text-accent-fg' : 'bg-muted text-fg-subtle',
              )}
              aria-current={i === idx ? 'step' : undefined}
            >
              {i < idx ? '✓' : i + 1}
            </span>
            <span className={clsx('text-[13px]', i === idx ? 'text-fg' : 'text-fg-subtle')}>{s.label}</span>
            {i < steps.length - 1 && <span className="h-px flex-1 bg-line" />}
          </li>
        ))}
      </ol>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {step === 'creds' && (
          <>
            <a
              href="https://my.telegram.org/apps"
              target="_blank"
              rel="noreferrer"
              className="flex items-start gap-2.5 rounded-lg border border-line bg-surface p-3 text-[13px] text-fg-muted transition-colors hover:border-accent/40"
            >
              <KeyRound className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <span>
                api_id и api_hash выдаются на <span className="text-accent">my.telegram.org → API development tools</span>
                <ExternalLink className="ml-1 inline size-3" aria-hidden />
              </span>
            </a>
            <div className="grid gap-4 sm:grid-cols-[140px_1fr]">
              <Field label="api_id" htmlFor="api_id">
                <Input id="api_id" inputMode="numeric" autoComplete="off" value={apiId} onChange={(e) => setApiId(e.target.value.replace(/\D/g, ''))} placeholder="1234567" className="font-mono" />
              </Field>
              <Field label="api_hash" htmlFor="api_hash" error={apiHash && !apiHashValid ? '32 hex-символа' : null}>
                <Input id="api_hash" autoComplete="off" spellCheck={false} value={apiHash} invalid={!!apiHash && !apiHashValid} onChange={(e) => setApiHash(e.target.value)} placeholder="0123456789abcdef…" className="font-mono" />
              </Field>
            </div>
            <Field label="Номер телефона" htmlFor="phone" hint="В международном формате, например +7 999 123-45-67">
              <Input id="phone" type="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+7 999 123-45-67" leading={<Smartphone className="size-4" />} />
            </Field>
            {start.error && <p role="alert" className="text-[13px] text-danger">{start.error.message}</p>}
            <Button type="submit" variant="primary" loading={start.isPending} disabled={!apiIdValid || !apiHashValid || !phoneValid}>
              Получить код
            </Button>
          </>
        )}

        {step === 'code' && (
          <>
            <p className="text-sm text-fg-muted">
              {delivery === 'app' ? 'Код отправлен в приложение Telegram на другом устройстве.' : 'Код отправлен по SMS.'} Номер: <span className="font-mono text-fg">{phone}</span>
            </p>
            <Field label="Код подтверждения" htmlFor="code" error={sendCode.error?.message}>
              <Input
                id="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                autoFocus
                value={code}
                invalid={!!sendCode.error}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                className="font-mono tracking-[0.3em]"
                inputSize="lg"
                placeholder="12345"
              />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={reset}>Назад</Button>
              <Button type="submit" variant="primary" className="flex-1" loading={sendCode.isPending} disabled={code.length < 3}>
                Подтвердить
              </Button>
            </div>
          </>
        )}

        {step === 'password' && (
          <>
            <p className="flex items-start gap-2 text-sm text-fg-muted">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              На аккаунте включена двухэтапная аутентификация. Введите облачный пароль.
            </p>
            <Field label="Пароль 2FA" htmlFor="tfa" error={sendPassword.error?.message}>
              <Input id="tfa" type="password" autoComplete="current-password" autoFocus value={password} invalid={!!sendPassword.error} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Button type="submit" variant="primary" loading={sendPassword.isPending} disabled={!password}>
              Войти
            </Button>
          </>
        )}
      </form>
    </Dialog>
  )
}

function AccountRow({ a }: { a: Account }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [confirm, setConfirm] = useState(false)
  const name = [a.first_name, a.last_name].filter(Boolean).join(' ') || a.phone
  const check = useMutation({
    mutationFn: () => api<Account>(`/accounts/${a.id}/check`, { method: 'POST' }),
    onSuccess: () => toast('Сессия активна', 'success'),
    onError: (e) => toast(e.message, 'error'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['accounts'] }),
  })
  const remove = useMutation({
    mutationFn: () => api(`/accounts/${a.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['accounts'] })
      toast('Аккаунт удалён', 'success')
    },
  })
  return (
    <li className="flex flex-wrap items-center gap-4 px-5 py-4">
      <Avatar id={a.tg_user_id ?? a.id} name={name} photoId={a.photo_id} size={44} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-semibold">{name}</span>
          {a.status === 'active' ? (
            <Badge tone="success"><CheckCircle2 className="size-3" aria-hidden />Активен</Badge>
          ) : (
            <Badge tone="danger"><AlertTriangle className="size-3" aria-hidden />Ошибка</Badge>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[13px] text-fg-muted">
          {a.username && <span>@{a.username}</span>}
          <span className="font-mono">{a.phone}</span>
          <span className="text-fg-subtle">добавлен {relative(a.created_at)}</span>
        </div>
        {a.last_error && <p className="mt-1 text-[13px] text-danger">{a.last_error}</p>}
      </div>
      <div className="flex items-center gap-1">
        <IconButton label="Проверить сессию" onClick={() => check.mutate()} disabled={check.isPending}>
          <RefreshCw className={clsx('size-4', check.isPending && 'animate-spin')} />
        </IconButton>
        <IconButton label="Удалить аккаунт" onClick={() => setConfirm(true)} className="hover:text-danger">
          <Trash2 className="size-4" />
        </IconButton>
      </div>
      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Удалить аккаунт?" description="Сессия будет удалена из панели. Сам Telegram-аккаунт не пострадает.">
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirm(false)}>Отмена</Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()} icon={<Trash2 className="size-4" />}>Удалить</Button>
        </div>
      </Dialog>
    </li>
  )
}

export default function Accounts() {
  const [open, setOpen] = useState(false)
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
  const add = (
    <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
      Добавить аккаунт
    </Button>
  )
  return (
    <Page>
      <PageHeader title="Аккаунты" description="Telegram-аккаунты, от имени которых работают инструменты" icon={<Smartphone className="size-5" />} actions={accounts.data?.length ? add : undefined} />
      <Card>
        {accounts.isLoading ? (
          <div className="flex flex-col gap-3 p-5">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : accounts.data?.length ? (
          <ul className="divide-y divide-line">{accounts.data.map((a) => <AccountRow key={a.id} a={a} />)}</ul>
        ) : (
          <EmptyState
            icon={<Smartphone className="size-5" />}
            title="Нет подключённых аккаунтов"
            description="Для сбора данных нужен пользовательский аккаунт: Bot API не умеет читать историю чужих каналов. Лучше использовать отдельный аккаунт."
            action={add}
          />
        )}
      </Card>
      <AddAccountDialog open={open} onClose={() => setOpen(false)} />
    </Page>
  )
}
