import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Copy, Download, FileText, IdCard, Paperclip, Pencil, Trash2, Upload } from 'lucide-react'
import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { api, DOSSIER_FIELDS, type Dossier, type DossierField, type DossierFile } from '../lib/api'
import { dateTime, num } from '../lib/format'
import { useToast } from './Toast'
import { Badge, Button, Card, CardHeader, Field, Input } from './ui'

const LABELS: Record<DossierField, { label: string; placeholder: string; type?: string; mono?: boolean; wide?: boolean }> = {
  full_name: { label: 'ФИО', placeholder: 'Иванов Иван Иванович', wide: true },
  email: { label: 'Email', placeholder: 'name@example.com', type: 'email' },
  phone: { label: 'Телефон', placeholder: '+7 999 123-45-67', type: 'tel', mono: true },
  country: { label: 'Страна', placeholder: 'Россия' },
  city: { label: 'Город', placeholder: 'Москва' },
  address: { label: 'Адрес', placeholder: 'Улица, дом, кв', wide: true },
  passport: { label: 'Паспорт', placeholder: 'Серия и номер', mono: true },
}

const size = (b: number) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} КБ` : `${(b / 1024 / 1024).toFixed(1)} МБ`)

function useRefresh(peerId: number) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['user', peerId] })
    qc.invalidateQueries({ queryKey: ['users'] })
    qc.invalidateQueries({ queryKey: ['people-search'] })
  }
}

/** Hand-entered details about the person; searchable from the people list and the search page. */
/** Phones Telegram itself gave: the profile phone (when visible) and numbers written in the bio. */
function TelegramPhones({ tgPhone, bioPhones, copy }: { tgPhone: string | null; bioPhones: string[]; copy: (v: string) => void }) {
  const items = [...(tgPhone ? [{ v: tgPhone, label: 'в профиле Telegram' }] : []),
    ...bioPhones.filter((v) => v !== tgPhone).map((v) => ({ v, label: 'в bio' }))]
  if (!items.length) return null
  return (
    <div className="flex flex-col gap-1.5 border-t border-line px-5 py-3">
      <span className="text-[11.5px] text-fg-subtle">Телефоны из Telegram — собраны автоматически</span>
      <ul className="flex flex-wrap gap-x-5 gap-y-1">
        {items.map(({ v, label }) => (
          <li key={v} className="group flex items-center gap-1.5 text-[13.5px]">
            <a href={`tel:${v}`} className="font-mono hover:text-accent">{v}</a>
            <span className="text-[12px] text-fg-subtle">{label}</span>
            <button onClick={() => copy(v)} aria-label={`Скопировать ${v}`}
              className="rounded p-1 text-fg-subtle opacity-60 transition-opacity hover:text-fg group-hover:opacity-100 focus-visible:opacity-100">
              <Copy className="size-3" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DossierCard({ peerId, dossier, tgPhone = null, bioPhones = [] }: { peerId: number; dossier: Dossier; tgPhone?: string | null; bioPhones?: string[] }) {
  const toast = useToast()
  const refresh = useRefresh(peerId)
  const empty = DOSSIER_FIELDS.every((f) => !dossier[f])
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Record<DossierField, string>>(() => Object.fromEntries(DOSSIER_FIELDS.map((f) => [f, dossier[f] ?? ''])) as Record<DossierField, string>)
  const save = useMutation({
    mutationFn: (body: Record<DossierField, string>) => api<Dossier>(`/users/${peerId}/dossier`, { method: 'PUT', json: body }),
    onSuccess: () => {
      refresh()
      setEditing(false)
      toast('Метаданные сохранены', 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const start = () => {
    setForm(Object.fromEntries(DOSSIER_FIELDS.map((f) => [f, dossier[f] ?? ''])) as Record<DossierField, string>)
    setEditing(true)
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(form)
  }
  const copy = (v: string) => navigator.clipboard.writeText(v).then(() => toast(`Скопировано: ${v}`, 'success'))

  return (
    <Card>
      <CardHeader
        icon={<IdCard className="size-4" />}
        title="Метаданные"
        description="Внесены вручную, ищутся в списке людей и в поиске"
        actions={!editing && !empty && <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" aria-hidden />} onClick={start}>Изменить</Button>}
      />
      {editing ? (
        <form onSubmit={submit} className="flex flex-col gap-4 p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            {DOSSIER_FIELDS.map((f) => (
              <div key={f} className={clsx(LABELS[f].wide && 'sm:col-span-2')}>
                <Field label={LABELS[f].label} htmlFor={`dossier-${f}`}>
                  <Input
                    id={`dossier-${f}`}
                    type={LABELS[f].type ?? 'text'}
                    value={form[f]}
                    placeholder={LABELS[f].placeholder}
                    maxLength={f === 'phone' || f === 'passport' ? 64 : 255}
                    autoComplete="off"
                    onChange={(e) => setForm({ ...form, [f]: e.target.value })}
                  />
                </Field>
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setEditing(false)}>Отмена</Button>
            <Button type="submit" variant="primary" loading={save.isPending}>Сохранить</Button>
          </div>
        </form>
      ) : empty ? (
        <div className="flex flex-col items-start gap-3 p-5">
          <p className="text-[13px] text-fg-muted">ФИО, email, телефон, адрес, паспорт — всё, что известно о человеке помимо Telegram.</p>
          <Button size="sm" icon={<Pencil className="size-3.5" aria-hidden />} onClick={start}>Заполнить</Button>
        </div>
      ) : (
        <dl className="grid gap-x-4 gap-y-3 p-5 sm:grid-cols-2">
          {DOSSIER_FIELDS.filter((f) => dossier[f]).map((f) => (
            <div key={f} className={clsx('group min-w-0', LABELS[f].wide && 'sm:col-span-2')}>
              <dt className="text-[11.5px] text-fg-subtle">{LABELS[f].label}</dt>
              <dd className="flex min-w-0 items-center gap-1.5 text-[13.5px]">
                {f === 'email' ? (
                  <a href={`mailto:${dossier[f]}`} className="min-w-0 break-all text-accent hover:underline">{dossier[f]}</a>
                ) : f === 'phone' ? (
                  <a href={`tel:${dossier[f]!.replace(/[^\d+]/g, '')}`} className="truncate font-mono hover:text-accent">{dossier[f]}</a>
                ) : (
                  <span className={clsx('break-words', LABELS[f].mono && 'font-mono')}>{dossier[f]}</span>
                )}
                <button onClick={() => copy(dossier[f]!)} aria-label={`Скопировать: ${LABELS[f].label}`}
                  className="shrink-0 rounded p-1 text-fg-subtle opacity-60 transition-opacity hover:text-fg group-hover:opacity-100 focus-visible:opacity-100">
                  <Copy className="size-3" />
                </button>
              </dd>
            </div>
          ))}
          {dossier.updated_at && <p className="text-[11.5px] text-fg-subtle sm:col-span-2">Изменено {dateTime(dossier.updated_at)}</p>}
        </dl>
      )}
      <TelegramPhones tgPhone={tgPhone} bioPhones={bioPhones} copy={copy} />
    </Card>
  )
}

/** PDFs attached to the profile; their text layer is indexed for search. */
export function FilesCard({ peerId, files }: { peerId: number; files: DossierFile[] }) {
  const toast = useToast()
  const refresh = useRefresh(peerId)
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const upload = useMutation({
    mutationFn: (list: File[]) => {
      const body = new FormData()
      for (const f of list) body.append('files', f)
      return api<DossierFile[]>(`/users/${peerId}/files`, { method: 'POST', body })
    },
    onSuccess: (added) => {
      refresh()
      const scans = added.filter((f) => !f.has_text).length
      toast(scans ? `Загружено: ${added.length}. Без текстового слоя (скан): ${scans} — ищется только по имени файла` : `Загружено файлов: ${added.length}`, 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const remove = useMutation({
    mutationFn: (f: DossierFile) => api(`/users/${peerId}/files/${f.id}`, { method: 'DELETE' }),
    onSuccess: () => refresh(),
    onError: (e) => toast(e.message, 'error'),
  })
  const send = (list: FileList | null) => {
    const pdfs = Array.from(list ?? []).filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    if (list?.length && pdfs.length < list.length) toast('Можно прикреплять только PDF', 'error')
    if (pdfs.length) upload.mutate(pdfs)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDrag(false)
    send(e.dataTransfer.files)
  }

  return (
    <Card>
      <CardHeader
        icon={<Paperclip className="size-4" />}
        title="Документы"
        description="PDF к профилю — текст из них попадает в поиск"
        actions={files.length > 0 && <Button size="sm" variant="ghost" icon={<Upload className="size-3.5" aria-hidden />} loading={upload.isPending} onClick={() => input.current?.click()}>Добавить</Button>}
      />
      <input ref={input} type="file" accept="application/pdf,.pdf" multiple hidden onChange={(e) => (send(e.target.files), (e.target.value = ''))} />
      {files.length > 0 && (
        <ul className="divide-y divide-line/70">
          {files.map((f) => (
            <li key={f.id} className="flex items-center gap-3 px-5 py-2.5">
              <FileText className="size-5 shrink-0 text-fg-subtle" aria-hidden />
              <div className="min-w-0 flex-1">
                <a href={`/api/users/${peerId}/files/${f.id}`} target="_blank" rel="noreferrer" title={f.filename} className="block truncate text-[13.5px] hover:text-accent">{f.filename}</a>
                <div className="flex flex-wrap items-center gap-x-2 text-[12px] text-fg-subtle">
                  <span>{size(f.size)}</span>
                  {f.pages != null && <span>{num(f.pages)} стр.</span>}
                  <span>{dateTime(f.created_at)}</span>
                  {!f.has_text && <Badge tone="warning" className="h-5 text-[11px]" title="В файле нет текстового слоя — ищется только по имени">скан</Badge>}
                </div>
              </div>
              <a href={`/api/users/${peerId}/files/${f.id}?download=true`} aria-label={`Скачать ${f.filename}`} title="Скачать"
                className="rounded-md p-1.5 text-fg-subtle hover:bg-elevated hover:text-fg">
                <Download className="size-4" />
              </a>
              <button
                aria-label={`Удалить ${f.filename}`}
                title="Удалить"
                disabled={remove.isPending}
                onClick={() => confirm(`Удалить «${f.filename}»?`) && remove.mutate(f)}
                className="rounded-md p-1.5 text-fg-subtle hover:bg-danger-soft hover:text-danger"
              >
                <Trash2 className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="p-4">
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => (e.preventDefault(), setDrag(true))}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          disabled={upload.isPending}
          className={clsx(
            'flex w-full flex-col items-center gap-1 rounded-[10px] border border-dashed px-4 text-center transition-colors duration-150',
            files.length ? 'py-3' : 'py-6',
            drag ? 'border-accent bg-accent-soft' : 'border-line-strong text-fg-muted hover:border-accent/60 hover:text-fg',
          )}
        >
          <Upload className="size-4" aria-hidden />
          <span className="text-[13px]">{upload.isPending ? 'Загружаем…' : 'Перетащите PDF сюда или нажмите, чтобы выбрать'}</span>
          {!files.length && <span className="text-[12px] text-fg-subtle">до 25 МБ на файл</span>}
        </button>
      </div>
    </Card>
  )
}
