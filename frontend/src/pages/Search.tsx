import { keepPreviousData, useInfiniteQuery, useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { ChevronDown, CornerDownRight, ExternalLink, Search as SearchIcon, TextSearch, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { ExportMenu, Flags, PeerLine, useSources } from '../components/PeerBits'
import { TypeIcon } from '../components/SourceBits'
import { Button, Card, EmptyState, Input, Segmented, Skeleton } from '../components/ui'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type ContextMessage, type PeerCard, type SearchHit, type SearchResult } from '../lib/api'
import { dateTime, num, pluralRu } from '../lib/format'

const PAGE = 50

function useDebounced<T>(value: T, ms = 350) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Text with \x02…\x03 highlight markers from the API, rendered without HTML injection. */
function Highlighted({ text }: { text: string | null }) {
  if (!text) return <span className="text-fg-subtle italic">медиа без текста</span>
  // eslint-disable-next-line no-control-regex -- the API's highlight markers are control characters
  const parts = text.split(/(\x02[^\x03]*\x03)/)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('\x02') ? <mark key={i} className="rounded-[3px] bg-accent/25 px-0.5 text-fg">{p.slice(1, -1)}</mark> : <span key={i}>{p}</span>,
      )}
    </>
  )
}

function Context({ hit }: { hit: SearchHit }) {
  const q = useQuery({
    queryKey: ['context', hit.job_id, hit.msg_id],
    queryFn: () => api<{ items: ContextMessage[] }>(`/messages/context?job_id=${hit.job_id}&msg_id=${hit.msg_id}`),
  })
  if (q.isLoading) return <Skeleton className="mt-3 h-24" />
  return (
    <ol className="mt-3 flex flex-col gap-1.5 border-l-2 border-line pl-3">
      {q.data?.items.map((m) => (
        <li key={m.msg_id} className={clsx('rounded-lg px-2.5 py-1.5 text-[13px]', m.focus ? 'bg-accent-soft' : 'bg-surface')}>
          <div className="mb-0.5 flex items-center gap-2 text-[12px] text-fg-subtle">
            <Link to={`/users/${m.sender.peer_id}`} className="font-medium text-fg-muted hover:text-accent">{m.sender.name}</Link>
            <span>{dateTime(m.date)}</span>
            {m.reply_to && <CornerDownRight className="size-3" aria-label="ответ" />}
          </div>
          <p className="break-words whitespace-pre-wrap">{m.text || <span className="text-fg-subtle italic">медиа</span>}</p>
        </li>
      ))}
    </ol>
  )
}

function Hit({ hit }: { hit: SearchHit }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="border-b border-line/70 px-4 py-3.5 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <PeerLine p={hit.sender} size={30} />
        <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-fg-muted">
          <span className="text-fg-subtle">в</span>
          <Avatar id={hit.source.id} name={hit.source.title} photoId={hit.source.photo_id} size={18} square={hit.source.family === 'channel'} />
          <Link to={`/channels/${hit.source.id}`} className="truncate hover:text-accent">{hit.source.title}</Link>
          <TypeIcon type={hit.source.type} className="size-3 shrink-0 text-fg-subtle" />
          {hit.thread && <span className="truncate text-fg-subtle">· {hit.thread}</span>}
        </span>
        <span className="ml-auto text-[12px] text-fg-subtle">{dateTime(hit.date)}</span>
      </div>
      <p className="mt-2 text-[14px] leading-relaxed break-words whitespace-pre-wrap"><Highlighted text={hit.text} /></p>
      <div className="mt-2 flex flex-wrap gap-3 text-[12.5px]">
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-1 text-fg-muted hover:text-fg">
          Контекст <ChevronDown className={clsx('size-3.5 transition-transform', open && 'rotate-180')} aria-hidden />
        </button>
        {hit.link && (
          <a href={hit.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
            Открыть в Telegram <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
      </div>
      {open && <Context hit={hit} />}
    </li>
  )
}

export default function Search() {
  const sources = useSources()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim())
  const source = params.get('source') ?? ''
  const family = (params.get('family') ?? 'all') as 'all' | 'channel' | 'chat'
  const sender = params.get('sender') ?? ''
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  const sort = (params.get('sort') ?? 'relevance') as 'relevance' | 'newest' | 'oldest'
  const set = useCallback(
    (k: string, v: string | null) => setParams((p) => (v == null || v === '' || v === 'all' || (k === 'sort' && v === 'relevance') ? p.delete(k) : p.set(k, v), p), { replace: true }),
    [setParams],
  )
  useEffect(() => set('q', q), [q, set])
  const senderCard = useQuery({
    queryKey: ['peers', sender],
    queryFn: () => api<PeerCard[]>(`/peers?ids=${sender}`),
    enabled: !!sender,
    select: (r) => r[0],
  })

  const filters = {
    q, sort, family,
    ...(source && { source_ids: source }), ...(sender && { sender_id: sender }), ...(from && { date_from: from }), ...(to && { date_to: to }),
  }
  const browse = !q && !sender && !source && !from && !to
  const query = useInfiniteQuery({
    queryKey: ['search', filters],
    initialPageParam: 0,
    placeholderData: keepPreviousData,
    enabled: !browse,
    queryFn: ({ pageParam }) => api<SearchResult>(`/search/messages?${new URLSearchParams({ ...filters, offset: String(pageParam), limit: String(PAGE) })}`),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((s, p) => s + p.items.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const first = query.data?.pages[0]
  const hits = query.data?.pages.flatMap((p) => p.items) ?? []
  const total = first?.total ?? 0

  return (
    <Page wide>
      <PageHeader icon={<TextSearch className="size-5" />} title="Поиск по сообщениям" description="По всем комментариям каналов и сообщениям чатов, что собраны в панели" />
      <Card className="mb-4 flex flex-col gap-3 p-4">
        <Input
          inputSize="lg"
          autoFocus
          aria-label="Что искать"
          placeholder='Слова, "точная фраза", -исключить'
          value={text}
          onChange={(e) => setText(e.target.value)}
          leading={<SearchIcon className="size-4" />}
          trailing={text && <button onClick={() => setText('')} aria-label="Очистить" className="flex size-7 items-center justify-center rounded-md text-fg-subtle hover:text-fg"><X className="size-4" /></button>}
        />
        <div className="flex flex-wrap items-center gap-2.5">
          <Segmented label="Где искать" value={family} onChange={(v) => set('family', v)} options={[{ value: 'all', label: 'Везде' }, { value: 'channel', label: 'Комментарии' }, { value: 'chat', label: 'Чаты' }]} />
          <select aria-label="Источник" value={source} onChange={(e) => set('source', e.target.value)} className="h-10 max-w-60 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
            <option value="">Все источники</option>
            {sources.data?.filter((s) => family === 'all' || s.family === family).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-[13px] text-fg-muted">
            с <input type="date" value={from} onChange={(e) => set('from', e.target.value)} className="h-10 rounded-[10px] border border-line bg-surface px-2 text-fg" aria-label="С даты" />
          </label>
          <label className="flex items-center gap-1.5 text-[13px] text-fg-muted">
            по <input type="date" value={to} onChange={(e) => set('to', e.target.value)} className="h-10 rounded-[10px] border border-line bg-surface px-2 text-fg" aria-label="По дату" />
          </label>
          <select aria-label="Сортировка" value={sort} onChange={(e) => set('sort', e.target.value)} className="h-10 rounded-[10px] border border-line bg-surface px-3 text-[13px] text-fg">
            <option value="relevance">По релевантности</option>
            <option value="newest">Сначала новые</option>
            <option value="oldest">Сначала старые</option>
          </select>
          {sender && (
            <span className="flex h-10 items-center gap-2 rounded-[10px] border border-accent/40 bg-accent-soft pr-1 pl-2 text-[13px]">
              <UserRound className="size-4 text-accent" aria-hidden />
              {senderCard.data ? <>{senderCard.data.name}<Flags p={senderCard.data} /></> : `ID ${sender}`}
              <button onClick={() => set('sender', null)} aria-label="Убрать фильтр по автору" className="flex size-7 items-center justify-center rounded-md hover:bg-elevated"><X className="size-3.5" /></button>
            </span>
          )}
          {!browse && total > 0 && <div className="ml-auto"><ExportMenu href={(fmt) => `/api/search/messages?${new URLSearchParams({ ...filters, format: fmt })}`} /></div>}
        </div>
      </Card>

      {browse ? (
        <Card>
          <EmptyState icon={<TextSearch className="size-5" />} title="Что ищем?"
            description={<>Слова ищутся по началу: «велосип» найдёт «велосипеды». Фразу берите в кавычки, лишнее исключайте минусом. Без слов можно смотреть ленту автора или источника — выберите фильтр.</>} />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
          <Card className="overflow-hidden">
            <div className="flex items-center gap-2 border-b border-line px-4 py-3 sm:px-5">
              <span className="text-[15px] font-semibold">{num(total)}</span>
              <span className="text-[13px] text-fg-muted">{pluralRu(total, 'сообщение', 'сообщения', 'сообщений')}</span>
              {query.isFetching && !query.isFetchingNextPage && <span className="ml-auto text-[12px] text-fg-subtle">ищем…</span>}
            </div>
            {query.isLoading ? (
              <div className="flex flex-col gap-2 p-5">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
            ) : hits.length === 0 ? (
              <EmptyState icon={<SearchIcon className="size-5" />} title="Ничего не нашли" description="Попробуйте другие слова или уберите фильтры" />
            ) : (
              <ul>{hits.map((h) => <Hit key={`${h.job_id}:${h.msg_id}`} hit={h} />)}</ul>
            )}
            {query.hasNextPage && (
              <div className="p-4 text-center">
                <Button variant="secondary" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>Показать ещё</Button>
              </div>
            )}
          </Card>

          <div className="flex flex-col gap-4">
            {!!first?.facets.length && (
              <Card className="p-4">
                <h3 className="mb-2 text-[13px] font-semibold text-fg-muted">Где встречается</h3>
                <ul className="flex flex-col gap-0.5">
                  {first.facets.map((f) => (
                    <li key={f.source_id}>
                      <button onClick={() => set('source', source === String(f.source_id) ? null : String(f.source_id))} aria-pressed={source === String(f.source_id)}
                        className={clsx('flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px] transition-colors', source === String(f.source_id) ? 'bg-accent-soft text-fg' : 'text-fg-muted hover:bg-elevated hover:text-fg')}>
                        <span className="min-w-0 flex-1 truncate">{f.title}</span>
                        <span className="font-mono text-[12px] tabular">{num(f.count)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
            {!!first?.top_senders.length && (
              <Card className="p-4">
                <h3 className="mb-2 text-[13px] font-semibold text-fg-muted">Чаще всех пишут об этом</h3>
                <ul className="flex flex-col gap-2">
                  {first.top_senders.map((p) => (
                    <li key={p.peer_id} className="flex items-center gap-2">
                      <div className="min-w-0 flex-1"><PeerLine p={p} size={26} /></div>
                      <button onClick={() => set('sender', String(p.peer_id))} className="font-mono text-[12px] text-fg-muted tabular hover:text-accent" title="Только его сообщения">{num(p.count)}</button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </div>
      )}
    </Page>
  )
}
