import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Building2, Eye, ExternalLink, Globe, Loader2, Megaphone, Newspaper, Play, Repeat2, Search, Smartphone } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AccountPicker, defaultAccount, useAccounts } from '../components/SourceBits'
import { ExportMenu } from '../components/PeerBits'
import { useToast } from '../components/Toast'
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, ProgressBar, Segmented, Skeleton } from '../components/ui'
import { isTerminal, useJob } from '../features/collector/useJob'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Advertiser, type ChannelPost, type Job, type Org, type PostChannel } from '../lib/api'
import { compact, dateTime, num, relative } from '../lib/format'

const PAGE = 30

function useDebounced<T>(value: T, ms = 350) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function CollectCard({ initial }: { initial: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const accounts = useAccounts()
  const [link, setLink] = useState(initial)
  const [via, setVia] = useState<'web' | 'account'>('web')
  const [limit, setLimit] = useState(500)
  const [since, setSince] = useState('')
  const [accountId, setAccountId] = useState<number | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const account = accountId ?? defaultAccount(accounts.data)
  const job = useJob(jobId)
  const start = useMutation({
    mutationFn: () => api<Job>('/tools/channel-posts/jobs', {
      method: 'POST', json: { channel: link.trim(), via, limit, since: since || null, account_id: via === 'account' ? account : null },
    }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast(e.message, 'error'),
  })
  const status = job.data?.status
  useEffect(() => {
    if (!isTerminal(status)) return
    qc.invalidateQueries({ queryKey: ['posts'] })
  }, [status, qc])
  const p = (job.data?.progress ?? {}) as { posts_done?: number; posts_total?: number; ads?: number; pages?: number; channel?: { title?: string } }
  const r = (job.data?.result ?? {}) as { posts?: number; ads?: number; channel?: { title?: string } }
  const running = !!job.data && !isTerminal(status)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (link.trim()) start.mutate()
  }
  return (
    <Card>
      <CardHeader icon={<Newspaper className="size-4" />} title="Собрать посты" description="Текст, просмотры, репосты, ссылки и маркировка рекламы (erid, ИНН рекламодателя)" />
      <form onSubmit={submit} className="flex flex-col gap-4 p-5">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto]">
          <Field label="Канал" htmlFor="posts-link">
            <Input id="posts-link" placeholder="@channel или https://t.me/channel" value={link} onChange={(e) => setLink(e.target.value)} />
          </Field>
          <Field label="Сколько последних постов" htmlFor="posts-limit">
            <Input id="posts-limit" type="number" min={1} max={100000} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 1)} className="w-40" />
          </Field>
          <Field label="Не старше" htmlFor="posts-since">
            <Input id="posts-since" type="date" value={since} onChange={(e) => setSince(e.target.value)} className="w-44" />
          </Field>
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-medium">Как собирать</span>
          <Segmented label="Как собирать" value={via} onChange={setVia} options={[
            { value: 'web', label: 'Без аккаунта (t.me/s)', hint: 'Публичная веб-версия канала' },
            { value: 'account', label: 'Через Telegram-аккаунт' },
          ]} />
          <p className="flex items-start gap-1.5 text-[12.5px] text-fg-subtle">
            {via === 'web' ? <Globe className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : <Smartphone className="mt-0.5 size-3.5 shrink-0" aria-hidden />}
            {via === 'web'
              ? 'Только публичные каналы с @username и включённым веб-превью. Не тратит лимиты аккаунта; нет числа репостов и комментариев, просмотры округлены (1.2K).'
              : 'Любой канал, который видит аккаунт, включая приватные. Точные просмотры, репосты и комментарии; расходует лимиты Telegram.'}
          </p>
        </div>
        {via === 'account' && <AccountPicker value={account} onChange={setAccountId} />}
        {running ? (
          <div className="flex flex-col gap-2">
            <ProgressBar label="Сбор постов" value={p.posts_total ? ((p.posts_done ?? 0) / p.posts_total) * 100 : undefined} indeterminate={!p.posts_total} />
            <span className="text-[12.5px] text-fg-muted">
              {p.channel?.title && <b className="text-fg">{p.channel.title}: </b>}{num(p.posts_done ?? 0)} постов · рекламных {num(p.ads ?? 0)}
            </span>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" variant="primary" icon={<Play className="size-4" />} loading={start.isPending}
              disabled={!link.trim() || (via === 'account' && account == null)}>Собрать</Button>
            {status === 'done' && <span className="text-[13px] text-fg-muted">Готово: {r.channel?.title} — {num(r.posts ?? 0)} постов, рекламных {num(r.ads ?? 0)}</span>}
            {status === 'failed' && <span className="text-[13px] text-danger">{job.data?.error}</span>}
          </div>
        )}
      </form>
    </Card>
  )
}

function PostItem({ p }: { p: ChannelPost }) {
  const [open, setOpen] = useState(false)
  const long = (p.text?.length ?? 0) > 420
  return (
    <li className="border-b border-line/70 px-4 py-3.5 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-fg-muted">
        <span className="font-medium text-fg">{p.username ? `@${p.username}` : p.channel_key}</span>
        <span>{dateTime(p.date)}</span>
        {p.views != null && <span className="inline-flex items-center gap-1"><Eye className="size-3.5" aria-hidden />{compact(p.views)}</span>}
        {p.forwards != null && <span className="inline-flex items-center gap-1"><Repeat2 className="size-3.5" aria-hidden />{num(p.forwards)}</span>}
        {p.forwarded_from && (
          <Badge title="Пост переслан из другого канала">
            <Repeat2 className="size-3" aria-hidden />
            {p.forwarded_from.username ? `из @${p.forwarded_from.username}` : p.forwarded_from.name && p.forwarded_from.name !== 'скрыто' ? `из ${p.forwarded_from.name}` : 'репост, источник скрыт'}
          </Badge>
        )}
        {p.ad && (
          <Badge tone="warning" title={p.ad.erid ? `erid ${p.ad.erid}` : 'Помечено как реклама'}>
            <Megaphone className="size-3" aria-hidden />реклама{p.ad.advertiser ? `: ${p.ad.advertiser}` : ''}{p.ad.inn ? ` · ИНН ${p.ad.inn}` : ''}
          </Badge>
        )}
        {p.link && (
          <a href={p.link} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-accent hover:underline">
            открыть <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
      <p className={clsx('mt-1.5 text-[13.5px] leading-relaxed break-words whitespace-pre-wrap', !open && long && 'line-clamp-6')}>
        {p.text || <span className="text-fg-subtle italic">{p.media ? 'медиа без текста' : 'пусто'}</span>}
      </p>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-1 text-[12.5px] text-fg-muted hover:text-fg">{open ? 'Свернуть' : 'Показать полностью'}</button>
      )}
    </li>
  )
}

function OrgCell({ inn, org }: { inn: string | null; org: Org | null }) {
  const toast = useToast()
  const [found, setFound] = useState<Org | null | undefined>(org ?? undefined)
  const look = useMutation({
    mutationFn: () => api<{ found: boolean; orgs: Org[] }>(`/orgs/${inn}`),
    onSuccess: (r) => setFound(r.found ? r.orgs[0] : null),
    onError: (e) => toast(e.message, 'error'),
  })
  if (!inn) return <span className="text-fg-subtle">—</span>
  if (found) {
    return (
      <span>
        <a href={found.url} target="_blank" rel="noreferrer" className="hover:text-accent">{found.short_name || found.name}</a>
        <span className="block text-[12px] text-fg-subtle">{found.kind} · с {found.registered}{found.region ? ` · ${found.region}` : ''}{found.closed ? ` · ликвидирован ${found.closed}` : ''}</span>
      </span>
    )
  }
  return (
    <button onClick={() => look.mutate()} disabled={look.isPending || found === null} className="inline-flex items-center gap-1 text-[12.5px] text-accent hover:underline disabled:text-fg-subtle disabled:no-underline">
      {look.isPending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Building2 className="size-3" aria-hidden />}
      {found === null ? 'не найдено в ЕГРЮЛ' : 'проверить в ЕГРЮЛ'}
    </button>
  )
}

function AdsTable({ channel }: { channel: string }) {
  const q = useQuery({ queryKey: ['posts', 'ads', channel], queryFn: () => api<Advertiser[]>(`/posts/ads${channel ? `?channel=${encodeURIComponent(channel)}` : ''}`) })
  if (q.isLoading) return <div className="p-5"><Skeleton className="h-24" /></div>
  if (!q.data?.length) return <EmptyState icon={<Megaphone className="size-5" />} title="Рекламы не найдено" description="Посты с маркировкой erid или «Реклама … ИНН»" />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead className="text-left text-[12px] text-fg-subtle">
          <tr className="border-b border-line">
            <th className="px-5 py-2 font-medium">Рекламодатель в посте</th><th className="px-3 py-2 font-medium">ИНН</th>
            <th className="px-3 py-2 font-medium">ЕГРЮЛ</th><th className="px-3 py-2 text-right font-medium">Постов</th>
            <th className="px-3 py-2 text-right font-medium">Каналов</th><th className="px-5 py-2 font-medium">Последний</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line/70">
          {q.data.map((a) => (
            <tr key={`${a.inn}:${a.advertiser}`}>
              <td className="px-5 py-2.5">{a.advertiser ?? <span className="text-fg-subtle">не указан</span>}</td>
              <td className="px-3 py-2.5 font-mono">{a.inn ?? '—'}</td>
              <td className="px-3 py-2.5"><OrgCell inn={a.inn} org={a.org} /></td>
              <td className="px-3 py-2.5 text-right font-mono">{num(a.posts)}</td>
              <td className="px-3 py-2.5 text-right font-mono">{num(a.channels)}</td>
              <td className="px-5 py-2.5 text-fg-muted">{relative(a.last_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ChannelPosts() {
  const [params, setParams] = useSearchParams()
  const channel = params.get('channel') ?? ''
  const tab = (params.get('tab') ?? 'posts') as 'posts' | 'ads'
  const set = (k: string, v: string | null) => setParams((p) => (v ? p.set(k, v) : p.delete(k), p), { replace: true })
  const [text, setText] = useState('')
  const q = useDebounced(text.trim())
  const [adsOnly, setAdsOnly] = useState(false)
  const [fwdOnly, setFwdOnly] = useState(false)
  const [sort, setSort] = useState<'date' | 'views' | 'forwards' | 'oldest'>('date')
  const channels = useQuery({ queryKey: ['posts', 'channels'], queryFn: () => api<PostChannel[]>('/posts/channels') })
  const filters = { q, sort, ads_only: String(adsOnly), forwarded_only: String(fwdOnly), ...(channel && { channel }) }
  const list = useInfiniteQuery({
    queryKey: ['posts', 'list', filters],
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    queryFn: ({ pageParam }) => api<{ total: number; items: ChannelPost[] }>(`/posts?${new URLSearchParams({ ...filters, offset: String(pageParam), limit: String(PAGE) })}`),
    getNextPageParam: (last, pages) => {
      const n = pages.reduce((s, p) => s + p.items.length, 0)
      return n < last.total ? n : undefined
    },
  })
  const items = list.data?.pages.flatMap((p) => p.items) ?? []
  const total = list.data?.pages[0]?.total ?? 0
  const prefill = params.get('link') ?? (channel.startsWith('@') ? channel : '')

  return (
    <Page wide>
      <PageHeader icon={<Newspaper className="size-5" />} title="Посты каналов"
        description="Посты с просмотрами, репостами и рекламой — через Telegram-аккаунт или без него, через публичную веб-версию t.me/s" />
      <div className="flex flex-col gap-5">
        <CollectCard key={prefill} initial={prefill} />

        {!!channels.data?.length && (
          <Card className="p-4">
            <div className="flex flex-wrap gap-1.5">
              <button onClick={() => set('channel', null)} aria-pressed={!channel}
                className={clsx('h-8 rounded-full border px-3 text-[12.5px] transition-colors', !channel ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}>
                Все каналы
              </button>
              {channels.data.map((c) => {
                const key = c.channel_id ? String(c.channel_id) : c.key
                return (
                  <button key={c.key} onClick={() => set('channel', key)} aria-pressed={channel === key}
                    title={`${num(c.posts)} постов · средн. просмотров ${c.avg_views != null ? compact(c.avg_views) : '—'} · собрано ${relative(c.collected_at)} (${c.via.map((v) => (v === 'web' ? 'без аккаунта' : 'аккаунт')).join(', ')})`}
                    className={clsx('flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-colors', channel === key ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}>
                    {c.title}<span className="font-mono text-[11.5px] text-fg-subtle">{num(c.posts)}</span>
                    {c.ads > 0 && <Megaphone className="size-3 text-warning" aria-label={`рекламных: ${c.ads}`} />}
                  </button>
                )
              })}
            </div>
            {channel && channel.startsWith('-100') && (
              <Link to={`/channels/${channel}`} className="mt-3 inline-block text-[12.5px] text-accent hover:underline">Аналитика этого канала →</Link>
            )}
          </Card>
        )}

        <Card className="overflow-visible">
          <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <Segmented label="Раздел" value={tab} onChange={(v) => set('tab', v === 'posts' ? null : v)}
                options={[{ value: 'posts', label: `Посты ${total ? num(total) : ''}`.trim() }, { value: 'ads', label: 'Рекламодатели' }]} />
              {tab === 'posts' && (
                <>
                  <Input aria-label="Поиск по тексту" placeholder="Текст поста" value={text} onChange={(e) => setText(e.target.value)}
                    leading={<Search className="size-4" />} className="w-full sm:ml-auto sm:w-64" />
                  <ExportMenu href={(fmt) => `/api/posts?${new URLSearchParams({ ...filters, format: fmt })}`} />
                </>
              )}
            </div>
            {tab === 'posts' && (
              <div className="flex flex-wrap items-center gap-2.5">
                <Segmented label="Сортировка" value={sort} onChange={setSort} options={[
                  { value: 'date', label: 'Новые' }, { value: 'views', label: 'Просмотры' }, { value: 'forwards', label: 'Репосты' }, { value: 'oldest', label: 'Старые' },
                ]} />
                <button onClick={() => setAdsOnly(!adsOnly)} aria-pressed={adsOnly}
                  className={clsx('flex h-8 items-center gap-1 rounded-full border px-3 text-[12.5px]', adsOnly ? 'border-warning/50 bg-warning-soft text-warning' : 'border-line text-fg-muted hover:text-fg')}>
                  <Megaphone className="size-3.5" aria-hidden />Только реклама
                </button>
                <button onClick={() => setFwdOnly(!fwdOnly)} aria-pressed={fwdOnly}
                  className={clsx('flex h-8 items-center gap-1 rounded-full border px-3 text-[12.5px]', fwdOnly ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:text-fg')}>
                  <Repeat2 className="size-3.5" aria-hidden />Только репосты
                </button>
              </div>
            )}
          </div>
          {tab === 'ads' ? (
            <AdsTable channel={channel} />
          ) : list.isLoading ? (
            <div className="flex flex-col gap-2 p-5">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
          ) : !items.length ? (
            <EmptyState icon={<Newspaper className="size-5" />} title={channels.data?.length ? 'Ничего не нашли' : 'Постов пока нет'}
              description={channels.data?.length ? 'Уберите фильтры' : 'Соберите посты канала формой выше'} />
          ) : (
            <ul>{items.map((p) => <PostItem key={`${p.channel_key}:${p.post_id}`} p={p} />)}</ul>
          )}
          {tab === 'posts' && list.hasNextPage && (
            <div className="p-4 text-center">
              <Button variant="secondary" loading={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>Показать ещё</Button>
            </div>
          )}
        </Card>
      </div>
    </Page>
  )
}
