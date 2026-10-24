import { BarChart3, BellRing, GitCompareArrows, Globe, MessagesSquare, Network, Newspaper, Radar, Send, TextSearch, UserSearch, Users, type LucideIcon } from 'lucide-react'

export interface ToolDef {
  id: string
  title: string
  description: string
  icon: LucideIcon
  path?: string // undefined = coming soon
}

// Panel tool catalog. Add new tools here; the backend registers the matching Tool.
export const TOOLS: ToolDef[] = [
  {
    id: 'comment-collector',
    title: 'Сборщик комментаторов',
    description: 'Все пользователи, оставлявшие комментарии под постами канала — с аватаркой, @username и числом комментариев.',
    icon: MessagesSquare,
    path: '/tools/comment-collector',
  },
  {
    id: 'chat-indexer',
    title: 'Индексатор чатов',
    description: 'Группы, супергруппы и форумы: вся история сообщений и список участников, если он открыт.',
    icon: Users,
    path: '/tools/chat-indexer',
  },
  {
    id: 'channel-posts',
    title: 'Посты каналов',
    description: 'Посты с просмотрами, репостами и рекламой (erid, ИНН рекламодателя) — через аккаунт или без него, через t.me/s.',
    icon: Newspaper,
    path: '/tools/channel-posts',
  },
  {
    id: 'channel-finder',
    title: 'Каналы пользователей',
    description: 'Каналы из профилей и bio, откуда репостят, кого упоминают и похожие каналы — кандидаты в источники.',
    icon: Radar,
    path: '/users/channels',
  },
  {
    id: 'username-check',
    title: 'Username на других сайтах',
    description: 'Есть ли такой же @username на ~600 публичных сайтах (база WhatsMyName). Запускается из профиля человека.',
    icon: Globe,
    path: '/users',
  },
  {
    id: 'search',
    title: 'Поиск по сообщениям',
    description: 'Полнотекстовый поиск по всем комментариям и сообщениям чатов: фразы, исключения, автор, период, контекст.',
    icon: TextSearch,
    path: '/search',
  },
  {
    id: 'user-lookup',
    title: 'Досье пользователя',
    description: 'Где человек пишет, с кем пересекается и переписывается, когда активен и не похож ли на бота.',
    icon: UserSearch,
    path: '/users',
  },
  {
    id: 'graph',
    title: 'Граф связей',
    description: 'Интерактивная карта: каналы, чаты и люди, которые связывают их аудитории.',
    icon: Network,
    path: '/graph',
  },
  {
    id: 'overlap',
    title: 'Пересечение аудиторий',
    description: 'Общие люди между каналами и чатами: матрица и выгрузка тех, кто есть везде.',
    icon: GitCompareArrows,
    path: '/overlap',
  },
  {
    id: 'channel-analytics',
    title: 'Аналитика источника',
    description: 'Динамика обсуждений, часы активности, удержание, топ постов, тем и дней, состав участников.',
    icon: BarChart3,
    path: '/channels',
  },
  {
    id: 'monitor',
    title: 'Мониторинг',
    description: 'Дозабор каналов и чатов по расписанию и уведомления о новых людях и активности избранных.',
    icon: BellRing,
    path: '/monitoring',
  },
  {
    id: 'mailer',
    title: 'Инвайтинг и рассылки',
    description: 'Работа с собранными базами.',
    icon: Send,
  },
]
