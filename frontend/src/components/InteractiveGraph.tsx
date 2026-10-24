import { useMutation } from '@tanstack/react-query'
import { ArrowRight, EyeOff, Undo2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type GraphData, type GraphNode } from '../lib/api'
import { num } from '../lib/format'
import { Avatar } from './Avatar'
import { ForceGraph } from './ForceGraph'
import { useInvalidateAnalytics } from './SourceActions'
import { useToast } from './Toast'
import { Button, IconButton } from './ui'

/** Force graph + a panel for the clicked node: open it, drop it from this view, or ignore it everywhere. */
export function InteractiveGraph({ data, height, focusId }: { data: GraphData; height?: number; focusId?: string }) {
  const navigate = useNavigate()
  const toast = useToast()
  const invalidate = useInvalidateAnalytics()
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [removed, setRemoved] = useState<Map<string, string>>(new Map()) // id -> label

  const shown = useMemo(() => {
    if (!removed.size) return data
    return {
      ...data,
      nodes: data.nodes.filter((n) => !removed.has(n.id)),
      links: data.links.filter((l) => !removed.has(l.source) && !removed.has(l.target)),
    }
  }, [data, removed])

  const ignore = useMutation({
    mutationFn: (n: GraphNode) =>
      n.type === 'source'
        ? api(`/sources/${n.peer_id}/hidden`, { method: 'PUT', json: { hidden: true } })
        : api(`/users/${n.peer_id}/note`, { method: 'PUT', json: { ignored: true } }),
    onSuccess: (_, n) => {
      setSelected(null)
      invalidate()
      toast(n.type === 'source' ? `«${n.label}» отключён из аналитики` : `${n.label} теперь игнорируется`, 'success')
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const drop = (n: GraphNode) => {
    setRemoved((m) => new Map(m).set(n.id, n.label))
    setSelected(null)
  }
  const links = selected ? data.links.filter((l) => l.source === selected.id || l.target === selected.id).length : 0
  const open = (n: GraphNode) => navigate(n.type === 'source' ? `/channels/${n.peer_id}` : `/users/${n.peer_id}`)

  return (
    <div className="relative">
      <ForceGraph data={shown} height={height} focusId={focusId} onNodeClick={(n) => setSelected(n)} />

      {selected && (
        <div role="dialog" aria-label={selected.label} className="animate-in absolute bottom-3 left-3 z-10 w-72 rounded-xl border border-line-strong bg-elevated p-3 shadow-2xl">
          <div className="flex items-start gap-2.5">
            <Avatar id={selected.peer_id} name={selected.label} photoId={selected.photo_id} size={36} square={selected.type === 'source'} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold">{selected.label}</div>
              <div className="text-[12px] text-fg-muted">
                {selected.type === 'source' ? `${selected.source_type && selected.source_type !== 'channel' ? 'чат' : 'канал'} · ${num(selected.value)} людей` : `${links} связей${selected.sources ? ` · ${selected.sources} источников` : ''}`}
              </div>
            </div>
            <IconButton label="Закрыть" className="-mt-1 -mr-1 size-7" onClick={() => setSelected(null)}><X className="size-4" /></IconButton>
          </div>
          <div className="mt-3 flex flex-col gap-1.5">
            <Button size="sm" variant="primary" icon={<ArrowRight className="size-3.5" />} onClick={() => open(selected)}>
              {selected.type === 'source' ? 'Аналитика источника' : 'Открыть досье'}
            </Button>
            {selected.type !== 'focus' && (
              <>
                <Button size="sm" variant="secondary" icon={<EyeOff className="size-3.5" />} onClick={() => drop(selected)}>Убрать с графа</Button>
                <Button size="sm" variant="ghost" className="text-danger hover:text-danger" loading={ignore.isPending} onClick={() => ignore.mutate(selected)}
                  title={selected.type === 'source' ? 'Отключить источник из всей аналитики' : 'Не показывать в списках, графах и уведомлениях'}>
                  {selected.type === 'source' ? 'Отключить источник' : 'Игнорировать везде'}
                </Button>
              </>
            )}
          </div>
        </div>
      )}

      {removed.size > 0 && (
        <div className="absolute top-12 left-3 z-10 flex items-center gap-2 rounded-lg border border-line bg-bg/85 px-2.5 py-1.5 text-[12px] text-fg-muted backdrop-blur">
          <span title={[...removed.values()].join(', ')}>Убрано с графа: {removed.size}</span>
          <button onClick={() => setRemoved(new Map())} className="flex items-center gap-1 text-accent hover:underline">
            <Undo2 className="size-3" aria-hidden /> вернуть
          </button>
        </div>
      )}
    </div>
  )
}
