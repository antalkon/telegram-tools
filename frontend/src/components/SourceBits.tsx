import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { Hash, Megaphone, MessagesSquare, Users, UsersRound, type LucideIcon } from 'lucide-react'
import { api, SOURCE_TYPES, type Account, type Family, type IndexerOptions, type Job, type SourceType } from '../lib/api'
import { Avatar } from './Avatar'
import { Input, Segmented, Switch } from './ui'

const TYPE_ICONS: Record<SourceType, LucideIcon> = {
  channel: Megaphone,
  supergroup: Users,
  forum: Hash,
  gigagroup: UsersRound,
  group: MessagesSquare,
}

export function TypeIcon({ type, className = 'size-3.5' }: { type?: SourceType; className?: string }) {
  const Icon = TYPE_ICONS[type ?? 'channel']
  return <Icon className={className} aria-hidden />
}

/** Neutral chip naming the source type; icon + label, never color alone. */
export function TypeBadge({ type, className }: { type?: SourceType; className?: string }) {
  const t = type ?? 'channel'
  return (
    <span className={clsx('inline-flex h-5 items-center gap-1 rounded-md border border-line bg-surface px-1.5 text-[11.5px] font-medium text-fg-muted', className)}>
      <TypeIcon type={t} className="size-3" />
      {SOURCE_TYPES[t].label}
    </span>
  )
}

/** Words that differ between channels (comments under posts) and chats (messages). */
export function words(family: Family | undefined) {
  return family === 'chat'
    ? { item: 'сообщение', items: 'Сообщений', authors: 'Писали', threads: 'Дней / тем', author: 'автор' }
    : { item: 'комментарий', items: 'Комментариев', authors: 'Комментаторов', threads: 'Постов', author: 'комментатор' }
}

/** Where a job's results live: collectors have a per-job page, the other tools a page of their own. */
const TOOL_PAGES: Record<string, string> = {
  'channel-posts': '/tools/channel-posts', 'channel-finder': '/users/channels', 'username-check': '/users',
}
export const jobPath = (job: Pick<Job, 'id' | 'tool'>) => TOOL_PAGES[job.tool] ?? `/tools/${job.tool}/jobs/${job.id}`

export function useAccounts() {
  return useQuery({ queryKey: ['accounts'], queryFn: () => api<Account[]>('/accounts') })
}

export function AccountPicker({ value, onChange }: { value: number | null; onChange: (id: number) => void }) {
  const accounts = useAccounts()
  const list = accounts.data ?? []
  if (list.length < 2) return null
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2 text-[13px] text-fg-muted">
      <span>Аккаунт:</span>
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Аккаунт">
        {list.map((a) => {
          const name = a.first_name ?? a.phone
          return (
            <button
              type="button"
              key={a.id}
              role="radio"
              aria-checked={value === a.id}
              onClick={() => onChange(a.id)}
              className={clsx(
                'flex h-8 items-center gap-2 rounded-full border pr-3 pl-1 text-[13px] transition-colors duration-150',
                value === a.id ? 'border-accent/60 bg-accent-soft text-fg' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg',
              )}
            >
              <Avatar id={a.tg_user_id ?? a.id} name={name} photoId={a.photo_id} size={22} />
              {name}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export const defaultAccount = (list: Account[] | undefined) => list?.find((a) => a.status === 'active')?.id ?? list?.[0]?.id ?? null

type Depth = 'all' | 'since' | 'last'
const depthOf = (o: IndexerOptions): Depth => (o.since ? 'since' : o.max_messages ? 'last' : 'all')

/** Per-run settings. Chats: depth, messages, members; channels: collection strategy. */
export function OptionsFields({ family, value, onChange }: { family: Family; value: IndexerOptions; onChange: (v: IndexerOptions) => void }) {
  const set = (patch: IndexerOptions) => onChange({ ...value, ...patch })
  const depth = depthOf(value)
  if (family === 'channel')
    return (
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Режим сбора комментариев</span>
          <Segmented
            label="Режим сбора"
            value={value.strategy ?? 'auto'}
            onChange={(v) => set({ strategy: v })}
            options={[{ value: 'auto', label: 'Авто' }, { value: 'fast', label: 'Быстрый' }, { value: 'per_post', label: 'По постам' }]}
          />
          <p className="text-[12.5px] text-fg-subtle">«По постам» медленнее, но работает без доступа к истории группы обсуждений.</p>
        </div>
        <Switch checked={value.download_avatars ?? true} onChange={(v) => set({ download_avatars: v })} label="Скачивать аватарки" description="Только тех, кого ещё нет в кэше" />
      </div>
    )
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Глубина истории</span>
        <Segmented
          label="Глубина истории"
          value={depth}
          onChange={(d) => set(d === 'all' ? { since: null, max_messages: null } : d === 'since' ? { since: value.since ?? monthAgo(), max_messages: null } : { since: null, max_messages: value.max_messages ?? 10000 })}
          options={[{ value: 'all', label: 'Вся' }, { value: 'since', label: 'С даты' }, { value: 'last', label: 'Последние N' }]}
        />
        {depth === 'since' && (
          <Input type="date" aria-label="Начиная с даты" value={value.since ?? ''} onChange={(e) => set({ since: e.target.value || null })} className="w-48" />
        )}
        {depth === 'last' && (
          <Input type="number" min={100} step={1000} aria-label="Сколько последних сообщений" value={value.max_messages ?? ''} onChange={(e) => set({ max_messages: Number(e.target.value) || null })} className="w-48"
            trailing={<span className="text-[12px] text-fg-subtle">сообщ.</span>} />
        )}
        <p className="text-[12.5px] text-fg-subtle">Большие чаты: начните с последних месяцев, а дозабор потом будет читать только новое.</p>
      </div>
      <div className="flex flex-col gap-4">
        <Switch checked={value.index_messages ?? true} onChange={(v) => set({ index_messages: v })} label="Сообщения" description="История для поиска, активности и связей «кто кому отвечает»" />
        <Switch checked={value.collect_members ?? true} onChange={(v) => set({ collect_members: v })} label="Участники" description="Список участников, если админы его не скрыли (Telegram отдаёт до ~10 000)" />
        <Switch checked={value.download_avatars ?? true} onChange={(v) => set({ download_avatars: v })} label="Аватарки" description="Только тех, кого ещё нет в кэше" />
      </div>
    </div>
  )
}

function monthAgo() {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)
  return d.toISOString().slice(0, 10)
}

/** Only the options that apply to a tool, so a channel never gets chat settings. */
export function optionsFor(family: Family, o: IndexerOptions): IndexerOptions {
  return family === 'channel'
    ? { strategy: o.strategy ?? 'auto', download_avatars: o.download_avatars ?? true }
    : { since: o.since ?? null, max_messages: o.max_messages ?? null, index_messages: o.index_messages ?? true,
        collect_members: o.collect_members ?? true, download_avatars: o.download_avatars ?? true }
}

