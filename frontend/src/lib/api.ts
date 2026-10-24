export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string }
    return (first.msg ?? 'Ошибка валидации').replace(/^Value error, /, '')
  }
  return 'Что-то пошло не так'
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const res = await fetch(`/api${path}`, {
    credentials: 'same-origin',
    ...rest,
    headers: { ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (!res.ok) {
    let message = res.statusText
    try {
      message = detailMessage((await res.json()).detail)
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('tgt:unauthorized'))
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

export const avatarUrl = (photoId: string | null | undefined) =>
  photoId ? `/api/media/avatars/${photoId}.jpg` : undefined

// ---------- types ----------

export interface ApiToken {
  id: number
  name: string
  prefix: string
  scope: 'read' | 'full'
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}

export interface Account {
  id: number
  phone: string
  tg_user_id: number | null
  first_name: string | null
  last_name: string | null
  username: string | null
  photo_id: string | null
  status: 'active' | 'error'
  last_error: string | null
  created_at: string
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type Phase = 'queued' | 'starting' | 'resolve' | 'scan' | 'members' | 'saving' | 'avatars' | JobStatus

/** channel = comments under posts; the rest are chats indexed for messages and members */
export type SourceType = 'channel' | 'supergroup' | 'forum' | 'gigagroup' | 'group'
export type Family = 'channel' | 'chat'
export type MembersStatus = 'ok' | 'partial' | 'hidden' | 'skipped'

export const SOURCE_TYPES: Record<SourceType, { label: string; plural: string }> = {
  channel: { label: 'Канал', plural: 'Каналы' },
  supergroup: { label: 'Супергруппа', plural: 'Супергруппы' },
  forum: { label: 'Форум', plural: 'Форумы' },
  gigagroup: { label: 'Гигагруппа', plural: 'Гигагруппы' },
  group: { label: 'Группа', plural: 'Группы' },
}
export const familyOf = (t: SourceType | undefined): Family => (!t || t === 'channel' ? 'channel' : 'chat')

export interface ChannelInfo {
  id: number
  title: string
  username: string | null
  photo_id: string | null
  subscribers: number | null
  group_title?: string | null
  group_username?: string | null
  type?: SourceType
  linked_channel?: { id: number; title: string; username: string | null } | null
}

export interface CollectorProgress {
  phase?: Phase
  channel?: ChannelInfo
  strategy?: 'fast' | 'per_post' | 'history'
  posts_total?: number
  posts_done?: number
  posts_with_comments?: number
  messages_total?: number
  messages_scanned?: number
  comments?: number
  unique_users?: number
  rate?: number
  avatars_total?: number
  avatars_done?: number
  avatars_cached?: number
  avatars_skipped?: number
  avatars_interrupted?: boolean
  flood_wait_until?: string | null
  members_total?: number | null
  members_done?: number
  members_status?: MembersStatus
}

export interface CollectorResult {
  channel: ChannelInfo
  strategy: 'fast' | 'per_post'
  mode: 'full' | 'incremental'
  upgraded_to_full: boolean
  base_job_id: number
  new_comments: number
  new_users: number | null
  new_user_ids: number[]
  total_comments: number
  total_users: number
  avatars: { downloaded: number; cached: number; failed: number; skipped: number }
  comments: number
  unique_users: number
  posts_total: number
  posts_with_comments: number
  orphaned: number
  duration_sec: number
  // chat indexer
  type: SourceType
  thread_unit: 'post' | 'topic' | 'day'
  members: number
  people: number
  members_status: MembersStatus
  members_fetched: number
  new_authors: number
  last_msg_id: number | null
}

export interface IndexerOptions {
  since?: string | null
  max_messages?: number | null
  index_messages?: boolean
  collect_members?: boolean
  download_avatars?: boolean
  strategy?: 'auto' | 'fast' | 'per_post'
}

export interface Job {
  id: number
  tool: string
  status: JobStatus
  account_id: number | null
  input: { channel: string; mode?: 'full' | 'incremental'; monitor_id?: number | null } & IndexerOptions
  progress: CollectorProgress
  result: Partial<CollectorResult>
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Participant {
  peer_id: number
  kind: 'user' | 'channel' | 'chat'
  name: string
  first_name: string | null
  last_name: string | null
  username: string | null
  usernames: string[]
  link: string | null
  phone: string | null
  photo_id: string | null
  comments: number
  posts: number
  first_at: string | null
  last_at: string | null
  is_bot: boolean
  is_premium: boolean
  is_verified: boolean
  is_scam: boolean
  is_deleted: boolean
  member: boolean
  role: 'creator' | 'admin' | 'member' | null
}

export interface ParticipantComment {
  msg_id: number
  post_id: number
  date: string
  text: string | null
  thread?: string | null
  link: string | null
}

// ---------- insights ----------

export interface PeerCard {
  peer_id: number
  kind: 'user' | 'channel' | 'chat'
  name: string
  username: string | null
  usernames: string[]
  link: string | null
  photo_id: string | null
  phone: string | null
  is_bot: boolean
  is_premium: boolean
  is_verified: boolean
  is_scam: boolean
  is_deleted: boolean
  tags: string[]
  starred: boolean
  ignored: boolean
}

export interface Source {
  id: number
  type: SourceType
  family: Family
  tool: 'comment-collector' | 'chat-indexer'
  title: string
  username: string | null
  link: string | null
  photo_id: string | null
  subscribers: number | null
  group_title: string | null
  linked_channel: { id: number; title: string; username: string | null } | null
  job_id: number
  partial: boolean
  collected_at: string | null
  /** people who wrote (comments / messages) */
  users: number
  /** chats: people in the member list */
  members: number
  people: number
  /** comments (channels) or messages (chats) */
  comments: number
  members_status: MembersStatus | null
  thread_unit: 'post' | 'topic' | 'day'
  posts_total: number | null
  posts_with_comments: number | null
  runs: number
  hidden?: boolean
  starred?: boolean
  running: boolean
  options: IndexerOptions
  input: string | null
  monitor: { id: number; enabled: boolean; interval_minutes: number } | null
}

export interface ResolvedSource {
  id: number
  type: SourceType
  type_label: string
  title: string
  username: string | null
  members_count: number | null
  members_visible: boolean
  about: string
  linked_chat: { id: number; title: string; username: string | null; type: SourceType; exists: boolean } | null
  is_member: boolean
  tool: 'comment-collector' | 'chat-indexer'
  exists: boolean
}

export interface SearchHit {
  job_id: number
  msg_id: number
  post_id: number
  date: string
  text: string | null
  sender: PeerCard
  source: { id: number; title: string; username: string | null; photo_id: string | null; type: SourceType; family: Family }
  thread: string | null
  link: string | null
}
export interface SearchResult {
  total: number
  items: SearchHit[]
  query: string | null
  facets: { source_id: number; title: string; count: number }[]
  top_senders: (PeerCard & { count: number })[]
}
export interface ContextMessage {
  msg_id: number
  sender: PeerCard
  date: string
  text: string | null
  focus: boolean
  reply_to: number | null
  link: string | null
}

export interface MaintenanceStats {
  db_bytes: number
  avatars: number
  avatars_bytes: number
  messages: number
  jobs: number
  peers: number
  members: number
  stale_runs: number
  stale_messages: number
}

export interface UserRow extends PeerCard {
  comments: number
  member: boolean
  sources: number
  posts: number
  first_at: string | null
  last_at: string | null
  source_ids: number[]
  note: string | null
}

export interface TimePoint {
  t: string
  comments: number
  users: number
}
export interface Timeline {
  bucket: 'day' | 'week' | 'month'
  points: TimePoint[]
}

export interface ProfileChannel {
  key: string
  peer_id: number | null
  title: string
  username: string | null
  type: SourceType | null
  members_count: number | null
  private: boolean
  via: FoundVia[]
  is_source: boolean
  link: string | null
}

export const DOSSIER_FIELDS = ['full_name', 'email', 'phone', 'country', 'city', 'address', 'passport'] as const
export type DossierField = (typeof DOSSIER_FIELDS)[number]
export interface DossierFile {
  id: number
  filename: string
  size: number
  pages: number | null
  has_text: boolean
  created_at: string
}
export type Dossier = Record<DossierField, string | null> & { updated_at: string | null; files: DossierFile[] }
export interface PeopleSearchResult {
  total: number
  items: (PeerCard & { matches: { file_id: number | null; filename: string | null; snippet: string }[] })[]
}

export type ContactKind = 'phones' | 'emails' | 'sites' | 'inn' | 'ogrn' | 'wallet_ton' | 'wallet_eth' | 'wallet_tron' | 'wallet_btc'
export interface Org {
  name: string | null
  short_name: string | null
  inn: string | null
  ogrn: string | null
  kpp: string | null
  kind: 'ЮЛ' | 'ИП'
  registered: string | null
  closed: string | null
  head: string | null
  region: string | null
  url: string
}
export interface ContactItem {
  value: string
  count: number
  refs: { kind: 'bio' | 'about' | 'message' | 'post'; link?: string | null; source?: string | null; post_id?: number }[]
  org?: Org | null
}
export type Contacts = Partial<Record<ContactKind, ContactItem[]>>
export interface HistoryItem { field: string; old: string | null; new: string | null; changed_at: string }
export interface AccountAge { kind: 'approx' | 'before' | 'after'; date: string; not_later_than?: string }
export interface UsernameSites { username: string; checked: number; checked_at: string | null; found: { site: string; category: string | null; url: string }[] }
export interface ChannelPost {
  channel_key: string
  channel_id: number | null
  username: string | null
  post_id: number
  date: string | null
  text: string | null
  views: number | null
  forwards: number | null
  replies: number | null
  media: boolean
  links: string[]
  via: 'account' | 'web'
  forwarded_from: { id: number | null; name: string | null; username: string | null } | null
  ad: { erid: string | null; advertiser: string | null; inn: string | null } | null
  link: string | null
}
export interface PostChannel {
  key: string
  channel_id: number | null
  username: string | null
  title: string
  posts: number
  ads: number
  collected_at: string | null
  newest: string | null
  oldest: string | null
  avg_views: number | null
  via: ('account' | 'web')[]
  starred: boolean
}
export interface Advertiser {
  inn: string | null
  advertiser: string | null
  posts: number
  channels: number
  last_at: string | null
  channel_keys: string[]
  org: Org | null
}

export interface UserProfile {
  peer: PeerCard
  note: string | null
  dossier: Dossier
  /** E.164 numbers found in the bio */
  bio_phones: string[]
  account_age: AccountAge | null
  /** channels and groups the account is not in: their creation date */
  created_at: string | null
  history: HistoryItem[]
  about: string | null
  profile_checked_at: string | null
  channels: ProfileChannel[]
  totals: { comments: number; posts: number; sources: number; active_sources: number; member_of: number; first_at: string | null; last_at: string | null }
  sources: {
    source: Source; comments: number; posts: number; first_at: string | null; last_at: string | null
    member: boolean; role: Participant['role']; rank: number | null; of: number; share: number
  }[]
  signals: Partial<{
    comments: number
    avg_length: number
    media_only_share: number
    duplicate_share: number
    top_duplicate: string | null
    link_share: number
    active_days: number
    max_per_day: number
    spam_score: number
  }>
}

export interface UserComment {
  source: { id: number; title: string; username: string | null; photo_id: string | null; type: SourceType; family: Family }
  msg_id: number
  post_id: number
  date: string
  text: string | null
  thread: string | null
  reply_to: PeerCard | null
  link: string | null
}

export interface Connections {
  co_commenters: (PeerCard & { shared_posts: number; their_comments: number; overlap: number })[]
  dialogs: (PeerCard & { replied_to: number; replied_by: number })[]
}

export interface GraphNode {
  id: string
  type: 'focus' | 'source' | 'user'
  peer_id: number
  label: string
  photo_id: string | null
  value: number
  sources?: number
  source_type?: SourceType
}
export interface GraphLink {
  source: string
  target: string
  kind: 'comments' | 'thread' | 'reply' | 'shared'
  weight: number
  jaccard?: number
}
export interface GraphData {
  nodes: GraphNode[]
  links: GraphLink[]
  hidden_users?: number
  matching_users?: number
}

export interface SourceAnalytics {
  source: Source
  timeline: Timeline
  heatmap: number[][]
  distribution: { label: string; users: number; comments: number }[]
  concentration: { top1pct: number; top10pct: number; top10users: number }
  segments: { total: number; premium: number; with_username: number; bots: number; deleted: number; channels: number }
  top_posts: { post_id: number; comments: number; users: number; first_at: string; label: string; link: string | null }[]
  audience: { members: number; authors: number; silent: number; outside: number; admins: number }
  cohorts: { month: string; new: number; returning: number }[]
  top_users: (PeerCard & { comments: number; posts: number })[]
  overlap: { id: number; shared: number; jaccard: number; share_of_mine: number }[]
}

export interface Overview {
  totals: { sources: number; channels: number; chats: number; members: number; users: number; comments: number; multi_source_users: number; jobs: number; accounts: number }
  activity: Timeline
  top_users: (PeerCard & { comments: number; sources: number })[]
  top_crossover: (PeerCard & { comments: number; sources: number })[]
  sources: Source[]
}

export interface OverlapMatrix {
  sources: { id: number; users: number }[]
  pairs: { a: number; b: number; shared: number; jaccard: number }[]
  users_by_source_count: { sources: number; users: number }[]
  total_users: number
}

export interface OverlapUser extends PeerCard {
  sources: number
  comments: number
  by_source: Record<string, number>
}

// ---------- monitoring & notifications ----------

export interface Monitor {
  id: number
  source_id: number | null
  channel: string
  tool: 'comment-collector' | 'chat-indexer'
  options: IndexerOptions
  title: string
  username: string | null
  photo_id: string | null
  account_id: number | null
  interval_minutes: number
  enabled: boolean
  notify: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_job_id: number | null
  last_status: JobStatus | null
  last_error: string | null
  last_new_users: number | null
  created_at: string
}

export interface AppEvent {
  id: number
  created_at: string
  kind: 'new_users' | 'watch' | 'job_failed' | 'info'
  title: string
  payload: { count?: number; people?: { peer_id: number; name: string; username: string | null; photo_id?: string | null }[]; detail?: string; path?: string }
  source_id: number | null
  job_id: number | null
  monitor_id: number | null
  read: boolean
  delivery: 'sent' | 'error' | null
  delivery_error: string | null
}

export interface NotifySettings {
  target: 'none' | 'saved' | 'bot'
  account_id: number | null
  bot_token_set: boolean
  bot_chat_id: string | null
  panel_url: string | null
  new_users: boolean
  watch: boolean
  failures: boolean
  min_new_users: number
}

export interface Exclusions {
  hide_bots: boolean
  hide_deleted: boolean
  hide_channels: boolean
}

export const INTERVALS = [
  { value: 60, label: 'каждый час' },
  { value: 180, label: 'каждые 3 ч' },
  { value: 360, label: 'каждые 6 ч' },
  { value: 720, label: 'каждые 12 ч' },
  { value: 1440, label: 'раз в сутки' },
  { value: 10080, label: 'раз в неделю' },
]
export const intervalLabel = (m: number) => INTERVALS.find((i) => i.value === m)?.label ?? `каждые ${m} мин`

// ---------- channel finder ----------

export type FoundVia = 'personal' | 'bio' | 'sender'

export interface FoundChannel {
  key: string
  peer_id: number | null
  type: SourceType | null
  family: Family | null
  title: string
  username: string | null
  link: string | null
  members_count: number | null
  about: string | null
  photo_id: string | null
  private: boolean
  dismissed: boolean
  found_at: string | null
  checked_at: string | null
  is_source: boolean
  starred: boolean
  via: { personal: number; bio: number; forward: number; mention: number; similar: number; sender: boolean }
  users: number
  people: PeerCard[]
}

export interface FoundChannelsPage {
  total: number
  counts: { new: number; sources: number; dismissed: number; starred: number; all: number }
  items: FoundChannel[]
}

export interface FinderOptions {
  source_ids?: number[]
  presence?: 'all' | 'active'
  recheck?: boolean
  limit?: number
  check_bio?: boolean
  resolve_mentions?: boolean
  include_senders?: boolean
  use_usernames?: boolean
  from_forwards?: boolean
  from_mentions?: boolean
  mentions_limit?: number
  similar_channels?: boolean
}

export interface FinderProgress {
  phase?: 'queued' | 'starting' | 'select' | 'profiles' | 'resolve' | 'similar' | 'details' | 'avatars' | JobStatus
  users_total?: number
  users_done?: number
  found?: number
  no_access?: number
  resolve_total?: number
  resolve_done?: number
  details_total?: number
  details_done?: number
  avatars_total?: number
  avatars_done?: number
  flood_wait_until?: string | null
}

export interface FinderResult {
  users_total: number
  checked: number
  personal: number
  with_bio_refs: number
  no_access: number
  via_username: number
  senders: number
  resolved: number
  resolve_cached: number
  deferred: number
  details: number
  new_channels: number
  forwards?: number
  mentions?: number
  similar?: number
  found_total: number
  postponed_sec: number | null
  blocked?: Partial<Record<FinderBlock, string>>
  waiting_username?: number
  failures?: Record<string, string>
  duration_sec: number
}

/** Request kinds Telegram can ban for hours, independently of each other. */
export type FinderBlock = 'resolve' | 'full_user' | 'invite' | 'full_channel'

export interface DiscoveryStats {
  people: number
  checked: number
  personal: number
  with_bio: number
  found: number
  dismissed: number
  last_job: Job | null
  blocked: Partial<Record<FinderBlock, string>>
}

export interface Favorites {
  users: PeerCard[]
  sources: Source[]
  channels: (PeerCard & { posts: number; found: boolean; members_count: number | null })[]
}

export type LimitsProfile = 'standard' | 'optimized' | 'custom'
export interface LimitValues {
  request_interval: number
  history_interval: number
  heavy_interval: number
  file_interval: number
  jitter: number
  flood_sleep_threshold: number
  avatar_concurrency: number
  details_limit: number
  details_ttl_days: number
  web_page_delay: number
  job_pause: number
  adaptive: boolean
}
export type LimitsSettings = LimitValues & {
  profile: LimitsProfile
  presets: Record<'standard' | 'optimized', LimitValues>
  fields: Record<Exclude<keyof LimitValues, 'adaptive'>, { min: number; max: number }>
}
export interface LimitsStats {
  hours: number
  floods: number
  wait_seconds: number
  requests: number
  by_method: { method: string; count: number; max_seconds: number; total_seconds: number }[]
  last: { at: string; account_id: number | null; method: string; seconds: number }[]
  slowdown: Record<string, Record<string, number>>
}

export interface ArchiveInfo {
  created_at: string | null
  tables: Record<string, number>
  files: number
  avatars: number
  includes_sessions: boolean
  same_key: boolean
}
export type ImportMode = 'replace' | 'merge' | 'overwrite'
export interface ImportResult {
  mode: ImportMode
  tables: Record<string, { added: number; updated: number; skipped: number }>
  warnings: string[]
  orphans_removed: number
  backup: string | null
  files: number
  avatars: number
  seconds: number
}
