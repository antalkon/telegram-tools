import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, Contact, ExternalLink, FileDown, Globe, History, Loader2, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { isTerminal, useJob } from '../features/collector/useJob'
import { api, type AccountAge, type ContactItem, type ContactKind, type Contacts, type HistoryItem, type Job, type Org, type UsernameSites } from '../lib/api'
import { date, dateTime, num, relative } from '../lib/format'
import { useToast } from './Toast'
import { Badge, Button, Card, CardHeader, EmptyState, ProgressBar, Skeleton } from './ui'

const CONTACT_LABELS: Record<ContactKind, string> = {
  phones: 'Телефоны', emails: 'Email', sites: 'Сайты', inn: 'ИНН', ogrn: 'ОГРН',
  wallet_ton: 'TON', wallet_eth: 'ETH / ERC-20', wallet_tron: 'TRON / TRC-20', wallet_btc: 'BTC',
}
const FIELD_LABELS: Record<string, string> = {
  first_name: 'Имя', last_name: 'Фамилия', title: 'Название', username: 'Username', photo: 'Фото', about: 'Bio', phone: 'Телефон',
}
const EXPLORERS: Partial<Record<ContactKind, (v: string) => string>> = {
  wallet_ton: (v) => `https://tonviewer.com/${v}`,
  wallet_eth: (v) => `https://etherscan.io/address/${v}`,
  wallet_tron: (v) => `https://tronscan.org/#/address/${v}`,
  wallet_btc: (v) => `https://mempool.space/address/${v}`,
}

/** "≈ 03.2016" from the id, plus "не позже …" from the earliest activity in the base. */
export function AccountAgeText({ age }: { age: AccountAge }) {
  const word = { approx: '≈', before: 'раньше', after: 'после' }[age.kind]
  const month = (iso: string) => date(iso).slice(3)
  return (
    <span title="Оценка по ID аккаунта: Telegram выдаёт ID по порядку. «Не позже» — по первой активности людей с ID не меньше этого в вашей базе">
      аккаунт создан {word} {month(age.date)}{age.not_later_than && age.kind !== 'approx' ? `, не позже ${month(age.not_later_than)}` : ''}
    </span>
  )
}

export function PdfButton({ href, label = 'PDF' }: { href: string; label?: string }) {
  return (
    <a href={href} download className="inline-flex h-10 items-center gap-2 rounded-[10px] border border-line-strong/70 bg-elevated px-4 text-sm font-medium text-fg hover:bg-muted">
      <FileDown className="size-4" aria-hidden /> {label}
    </a>
  )
}

function OrgCard({ org }: { org: Org }) {
  return (
    <div className="mt-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-2 font-medium text-fg">
        {org.short_name || org.name}
        <Badge>{org.kind}</Badge>
        {org.closed && <Badge tone="danger">ликвидирован {org.closed}</Badge>}
      </div>
      <div className="mt-0.5 text-fg-muted">
        ИНН {org.inn} · ОГРН {org.ogrn}{org.kpp ? ` · КПП ${org.kpp}` : ''} · с {org.registered}{org.region ? ` · ${org.region}` : ''}
      </div>
      {org.head && <div className="text-fg-muted">{org.head}</div>}
      <a href={org.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">ЕГРЮЛ <ExternalLink className="size-3" aria-hidden /></a>
    </div>
  )
}

/** ИНН / ОГРН with a button that looks the company up in ЕГРЮЛ (cached on the server). */
function OrgLookup({ item }: { item: ContactItem }) {
  const toast = useToast()
  const [org, setOrg] = useState<Org | null | undefined>(item.org)
  const look = useMutation({
    mutationFn: () => api<{ found: boolean; orgs: Org[] }>(`/orgs/${item.value}`),
    onSuccess: (r) => (r.found ? setOrg(r.orgs[0]) : (setOrg(null), toast('В ЕГРЮЛ/ЕГРИП не найдено', 'error'))),
    onError: (e) => toast(e.message, 'error'),
  })
  return (
    <div>
      <span className="font-mono">{item.value}</span>
      {org === undefined && (
        <button onClick={() => look.mutate()} disabled={look.isPending} className="ml-2 inline-flex items-center gap-1 text-[12px] text-accent hover:underline">
          {look.isPending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Building2 className="size-3" aria-hidden />} проверить в ЕГРЮЛ
        </button>
      )}
      {org && <OrgCard org={org} />}
    </div>
  )
}

export function ContactsView({ contacts, empty = 'Контактов не найдено' }: { contacts: Contacts | undefined; empty?: string }) {
  const kinds = (Object.keys(CONTACT_LABELS) as ContactKind[]).filter((k) => contacts?.[k]?.length)
  if (!kinds.length) return <p className="text-[13px] text-fg-subtle">{empty}</p>
  return (
    <dl className="flex flex-col gap-3">
      {kinds.map((k) => (
        <div key={k}>
          <dt className="mb-1 text-[11.5px] text-fg-subtle">{CONTACT_LABELS[k]}</dt>
          <dd className="flex flex-col gap-1.5 text-[13.5px]">
            {contacts![k]!.map((item) => (
              <div key={item.value} className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  {k === 'inn' || k === 'ogrn' ? (
                    <OrgLookup item={item} />
                  ) : k === 'sites' ? (
                    <a href={item.value} target="_blank" rel="noreferrer nofollow" className="break-all text-accent hover:underline">{item.value}</a>
                  ) : k === 'emails' ? (
                    <a href={`mailto:${item.value}`} className="break-all text-accent hover:underline">{item.value}</a>
                  ) : k === 'phones' ? (
                    <a href={`tel:${item.value}`} className="font-mono hover:text-accent">{item.value}</a>
                  ) : EXPLORERS[k] ? (
                    <a href={EXPLORERS[k]!(item.value)} target="_blank" rel="noreferrer" className="font-mono text-[12.5px] break-all hover:text-accent">{item.value}</a>
                  ) : (
                    <span className="font-mono">{item.value}</span>
                  )}
                  <span className="text-[12px] text-fg-subtle">
                    {item.refs.map((r, i) => {
                      const label = r.kind === 'bio' ? 'в bio' : r.kind === 'about' ? 'в описании' : r.kind === 'post' ? `пост #${r.post_id}` : r.source ?? 'сообщение'
                      return r.link ? <a key={i} href={r.link} target="_blank" rel="noreferrer" className="mr-2 hover:text-accent">{label}</a> : <span key={i} className="mr-2">{label}</span>
                    })}
                    {item.count > item.refs.length && `и ещё ${num(item.count - item.refs.length)}`}
                  </span>
                </div>
              </div>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function UserContactsCard({ peerId }: { peerId: number }) {
  const q = useQuery({ queryKey: ['user', peerId, 'contacts'], queryFn: () => api<Contacts>(`/users/${peerId}/contacts`) })
  return (
    <Card>
      <CardHeader icon={<Contact className="size-4" />} title="Контакты из bio и сообщений" description="Телефоны, email, сайты, кошельки, ИНН — что человек сам писал публично" />
      <div className="p-5">{q.isLoading ? <Skeleton className="h-16" /> : <ContactsView contacts={q.data} empty="В bio и сообщениях контактов нет" />}</div>
    </Card>
  )
}

export function HistoryCard({ history }: { history: HistoryItem[] }) {
  if (!history.length) return null
  return (
    <Card>
      <CardHeader icon={<History className="size-4" />} title="История профиля" description="Что менялось между сборами: имя, username, фото, bio, телефон" />
      <ol className="max-h-[360px] divide-y divide-line/70 overflow-y-auto scrollbar-thin">
        {history.map((h, i) => (
          <li key={i} className="px-5 py-2.5 text-[13px]">
            <div className="flex items-center gap-2 text-[12px] text-fg-subtle">
              <Badge>{FIELD_LABELS[h.field] ?? h.field}</Badge> {dateTime(h.changed_at)}
            </div>
            {h.field === 'photo' ? (
              <p className="mt-1 text-fg-muted">сменил фото профиля</p>
            ) : (
              <p className="mt-1 break-words">
                <span className="text-fg-subtle line-through">{h.old || '—'}</span> → <span>{h.new || '—'}</span>
              </p>
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}

/** The same @username on other public sites (WhatsMyName list, checked on demand). */
export function UsernameSitesCard({ username }: { username: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [jobId, setJobId] = useState<number | null>(null)
  const job = useJob(jobId)
  const q = useQuery({ queryKey: ['username-sites', username.toLowerCase()], queryFn: () => api<UsernameSites>(`/usernames/${username}/sites`) })
  const start = useMutation({
    mutationFn: () => api<Job>('/tools/username-check/jobs', { method: 'POST', json: { usernames: [username] } }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast(e.message, 'error'),
  })
  const running = job.data && !isTerminal(job.data.status)
  const p = (job.data?.progress ?? {}) as { checks_total?: number; checks_done?: number; found?: number }
  const status = job.data?.status
  const error = job.data?.error
  useEffect(() => {
    if (jobId == null || !isTerminal(status)) return
    qc.invalidateQueries({ queryKey: ['username-sites', username.toLowerCase()] })
    if (status === 'failed') toast(error ?? 'Проверка не удалась', 'error')
  }, [jobId, status, error, qc, toast, username])
  const data = q.data
  const byCat = new Map<string, UsernameSites['found']>()
  for (const f of data?.found ?? []) byCat.set(f.category ?? 'другое', [...(byCat.get(f.category ?? 'другое') ?? []), f])
  return (
    <Card>
      <CardHeader
        icon={<Globe className="size-4" />}
        title={`@${username} на других сайтах`}
        description={data?.checked_at ? `Проверено ${relative(data.checked_at)} на ${num(data.checked)} сайтах` : 'Есть ли такой же username на ~600 публичных сайтах (база WhatsMyName)'}
        actions={!running && <Button size="sm" variant="secondary" icon={<Search className="size-3.5" aria-hidden />} loading={start.isPending} onClick={() => start.mutate()}>{data?.checked ? 'Проверить снова' : 'Проверить'}</Button>}
      />
      <div className="p-5">
        {running ? (
          <div className="flex flex-col gap-2">
            <ProgressBar label="Проверка сайтов" value={p.checks_total ? ((p.checks_done ?? 0) / p.checks_total) * 100 : undefined} indeterminate={!p.checks_total} />
            <span className="text-[12.5px] text-fg-muted">{num(p.checks_done ?? 0)} из {num(p.checks_total ?? 0)} · найдено {num(p.found ?? 0)}</span>
          </div>
        ) : q.isLoading ? (
          <Skeleton className="h-10" />
        ) : !data?.checked ? (
          <p className="text-[13px] text-fg-subtle">Ещё не проверялось. Проверка занимает около минуты и не использует Telegram-аккаунт. Совпадение имени ещё не значит, что это тот же человек.</p>
        ) : !data.found.length ? (
          <EmptyState icon={<Globe className="size-5" />} title="Нигде не найден" />
        ) : (
          <div className="flex flex-col gap-3">
            {[...byCat.entries()].map(([cat, items]) => (
              <div key={cat}>
                <div className="mb-1 text-[11.5px] text-fg-subtle">{cat}</div>
                <div className="flex flex-wrap gap-1.5">
                  {items.map((f) => (
                    <a key={f.site} href={f.url} target="_blank" rel="noreferrer nofollow"
                      className={clsx('inline-flex h-7 items-center gap-1 rounded-full border border-line px-2.5 text-[12.5px] text-fg-muted hover:border-accent/60 hover:text-fg')}>
                      {f.site} <ExternalLink className="size-3" aria-hidden />
                    </a>
                  ))}
                </div>
              </div>
            ))}
            <p className="text-[12px] text-fg-subtle">Совпадение имени ещё не значит, что это тот же человек — проверяйте по содержимому.</p>
          </div>
        )}
      </div>
    </Card>
  )
}
