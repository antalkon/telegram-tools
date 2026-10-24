const nf = new Intl.NumberFormat('ru-RU')
export const num = (n: number | null | undefined) => (n == null ? '—' : nf.format(n))

export function compact(n: number | null | undefined): string {
  if (n == null) return '—'
  return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

const df = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
const dtf = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
export const date = (iso: string | null | undefined) => (iso ? df.format(new Date(iso)) : '—')
export const dateTime = (iso: string | null | undefined) => (iso ? dtf.format(new Date(iso)) : '—')

export function relative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  const rtf = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' })
  if (diff < 60) return 'только что'
  if (diff < 3600) return rtf.format(-Math.round(diff / 60), 'minute')
  if (diff < 86400) return rtf.format(-Math.round(diff / 3600), 'hour')
  if (diff < 86400 * 30) return rtf.format(-Math.round(diff / 86400), 'day')
  return date(iso)
}

export function duration(sec: number | null | undefined): string {
  if (sec == null) return '—'
  if (sec < 60) return `${Math.round(sec)} с`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  if (m < 60) return `${m} мин ${s} с`
  return `${Math.floor(m / 60)} ч ${m % 60} мин`
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.slice(0, 2).map((p) => [...p][0] ?? '')
  return letters.join('').toUpperCase() || '?'
}

// Same palette idea Telegram uses for empty avatars: stable color by peer id.
const AVATAR_COLORS = [
  ['#e17076', '#ff885e'],
  ['#7bc862', '#a0de7e'],
  ['#65aadd', '#72d5fd'],
  ['#a695e7', '#e0a2f3'],
  ['#ee7aae', '#ff9fc2'],
  ['#6ec9cb', '#53edd6'],
  ['#faa774', '#ffcd6a'],
]
export function avatarGradient(id: number): string {
  const [a, b] = AVATAR_COLORS[Math.abs(id) % AVATAR_COLORS.length]
  return `linear-gradient(160deg, ${b}, ${a})`
}

export function pluralRu(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return one
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few
  return many
}
