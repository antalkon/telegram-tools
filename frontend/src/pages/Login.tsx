import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, Lock } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Button, Card, Field, IconButton, Input } from '../components/ui'
import { Logo } from '../layout/AppLayout'
import { api } from '../lib/api'

export default function Login() {
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const qc = useQueryClient()
  const login = useMutation({
    mutationFn: () => api('/auth/login', { method: 'POST', json: { password } }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['me'] })
      navigate((location.state as { from?: string } | null)?.from ?? '/', { replace: true })
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (password) login.mutate()
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full opacity-40 blur-3xl"
        style={{ background: 'radial-gradient(closest-side, rgb(42 171 238 / 0.45), transparent)' }}
      />
      <Card className="animate-in relative w-full max-w-sm p-6">
        <Logo />
        <h1 className="mt-6 text-lg font-semibold">Вход в панель</h1>
        <p className="mt-1 text-sm text-fg-muted">Пароль задаётся переменной окружения TGT_ADMIN_PASSWORD.</p>
        <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
          <Field label="Пароль" htmlFor="password" error={login.error?.message}>
            <Input
              id="password"
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              autoFocus
              value={password}
              invalid={!!login.error}
              onChange={(e) => setPassword(e.target.value)}
              leading={<Lock className="size-4" />}
              trailing={
                <IconButton type="button" label={show ? 'Скрыть пароль' : 'Показать пароль'} onClick={() => setShow(!show)} className="-mr-2 size-8">
                  {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </IconButton>
              }
            />
          </Field>
          <Button type="submit" variant="primary" size="lg" loading={login.isPending} disabled={!password}>
            Войти
          </Button>
        </form>
      </Card>
    </div>
  )
}
