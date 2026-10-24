import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Info, Network } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { InteractiveGraph } from '../components/InteractiveGraph'
import { useSources } from '../components/PeerBits'
import { Card, EmptyState, Segmented, Skeleton } from '../components/ui'
import { ExportMenu, GRAPH_FORMATS } from '../components/PeerBits'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type GraphData } from '../lib/api'
import { num } from '../lib/format'

export default function GraphPage() {
  const sources = useSources()
  const [params, setParams] = useSearchParams()
  const mode = (params.get('mode') ?? 'people') as 'people' | 'sources'
  const min = params.get('min') ?? '2'
  const limit = params.get('limit') ?? '300'
  const family = params.get('family') ?? 'all'
  const active = params.get('active') ?? '0'
  const set = (k: string, v: string) => setParams((p) => (p.set(k, v), p), { replace: true })

  const q = useQuery({
    queryKey: ['graph', mode, min, limit, family, active],
    queryFn: () => api<GraphData>(`/graph?mode=${mode}&min_sources=${min}&limit=${limit}&family=${family}&active_only=${active === '1'}`),
    placeholderData: keepPreviousData,
  })

  return (
    <Page wide>
      <PageHeader
        icon={<Network className="size-5" />}
        title="Граф связей"
        description={mode === 'people' ? 'Каналы, чаты и люди, которые есть сразу в нескольких из них' : 'Источники, связанные общей аудиторией'}
        actions={<ExportMenu label="Экспорт графа" formats={GRAPH_FORMATS}
          href={(fmt) => `/api/graph?mode=${mode}&min_sources=${min}&limit=${limit}&family=${family}&active_only=${active === '1'}&format=${fmt}`} />}
      />
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <Segmented label="Режим" value={mode} onChange={(v) => set('mode', v)} options={[{ value: 'people', label: 'Люди ↔ источники' }, { value: 'sources', label: 'Источник ↔ источник' }]} />
        <Segmented label="Какие источники" value={family} onChange={(v) => set('family', v)} options={[{ value: 'all', label: 'Все' }, { value: 'channel', label: 'Каналы' }, { value: 'chat', label: 'Чаты' }]} />
        <Segmented label="Кого считать" value={active} onChange={(v) => set('active', v)} options={[{ value: '0', label: 'Всех', hint: 'Авторов и участников чатов' }, { value: '1', label: 'Писавших' }]} />
        {mode === 'people' && (
          <>
            <Segmented
              label="Минимум каналов"
              value={min}
              onChange={(v) => set('min', v)}
              options={[{ value: '1', label: 'Все' }, { value: '2', label: '2+ ист.' }, { value: '3', label: '3+' }, { value: '4', label: '4+' }]}
            />
            <Segmented label="Сколько людей" value={limit} onChange={(v) => set('limit', v)} options={[{ value: '100', label: '100' }, { value: '300', label: '300' }, { value: '1000', label: '1000' }]} />
          </>
        )}
        {q.data && (
          <span className="ml-auto flex items-center gap-1.5 text-[12.5px] text-fg-muted">
            <Info className="size-3.5" aria-hidden />
            {mode === 'people'
              ? `${num(q.data.nodes.filter((n) => n.type === 'user').length)} из ${num(q.data.matching_users)} людей · ${num(q.data.links.length)} связей`
              : `${num(q.data.nodes.length)} источников · ${num(q.data.links.length)} пересечений`}
          </span>
        )}
      </Card>
      {(sources.data?.length ?? 0) < 1 ? (
        <Card><EmptyState icon={<Network className="size-5" />} title="Граф пуст" description="Добавьте хотя бы один канал или чат" /></Card>
      ) : q.data ? (
        <InteractiveGraph data={q.data} height={Math.max(520, Math.min(860, window.innerHeight - 260))} />
      ) : (
        <Skeleton className="h-[600px] rounded-xl" />
      )}
      <p className="mt-3 text-[12.5px] text-fg-subtle">
        Размер узла — число людей или активность, толщина линии — число сообщений (или общих людей). Наведите на узел, чтобы подсветить его связи; клик — открыть, убрать с графа или игнорировать.
      </p>
    </Page>
  )
}
