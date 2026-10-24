import { Maximize2, Minus, Plus } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { forceCollide } from 'd3-force-3d'
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from 'react-force-graph-2d'
import { avatarUrl, type GraphData, type GraphLink, type GraphNode } from '../lib/api'
import { initials, num } from '../lib/format'
import { SERIES } from './charts'
import { IconButton } from './ui'

type N = NodeObject<GraphNode>
type L = LinkObject<GraphNode, GraphLink>

// identity = shape + color: users are circles (blue), sources orange — channels rounded squares, chats circles with a
// double ring; the focused user has an aqua ring
const COLOR = { user: SERIES[0], source: SERIES[2], focus: SERIES[1] }
const LINK = {
  comments: 'rgba(154,168,189,0.22)',
  shared: 'rgba(217,89,38,0.45)',
  thread: 'rgba(57,135,229,0.55)',
  reply: 'rgba(25,158,112,0.85)',
}

const images = new Map<string, HTMLImageElement | null>()
function avatarImage(photoId: string | null, onLoad: () => void) {
  if (!photoId) return null
  if (images.has(photoId)) return images.get(photoId) ?? null
  images.set(photoId, null)
  const img = new Image()
  img.onload = () => {
    images.set(photoId, img)
    onLoad()
  }
  img.src = avatarUrl(photoId)!
  return null
}

function radius(n: GraphNode) {
  if (n.type === 'focus') return 16
  if (n.type === 'source') return Math.min(30, 9 + Math.sqrt(n.value) * 0.55)
  return Math.min(14, 3.5 + Math.sqrt(n.value) * 0.9)
}

const endId = (e: L['source']) => (typeof e === 'object' && e ? (e as N).id : e) as string
const isChat = (n: GraphNode) => n.type === 'source' && !!n.source_type && n.source_type !== 'channel'

export function ForceGraph({
  data,
  height = 520,
  onNodeClick,
  focusId,
}: {
  data: GraphData
  height?: number
  onNodeClick?: (n: GraphNode) => void
  focusId?: string
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<N | null>(null)
  const [, redraw] = useState(0)

  useLayoutEffect(() => {
    if (!wrap.current) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])

  // force-graph mutates its input, so hand it a copy
  const graph = useMemo(() => ({ nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) }), [data])
  const neighbors = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const l of data.links) {
      if (!m.has(l.source)) m.set(l.source, new Set())
      if (!m.has(l.target)) m.set(l.target, new Set())
      m.get(l.source)!.add(l.target)
      m.get(l.target)!.add(l.source)
    }
    return m
  }, [data])

  const mounted = width > 0
  useEffect(() => {
    const g = fg.current
    if (!g) return
    // big graphs: channels push apart hard, people barely repel and settle between their channels
    const big = graph.nodes.length > 120
    g.d3Force('charge')?.strength((n: N) => (n.type === 'source' ? (big ? -2200 : -420) : n.type === 'focus' ? -300 : big ? -12 : -90))
    g.d3Force('link')
      ?.distance((l: L) => (l.kind === 'comments' ? (big ? 170 : 90) : l.kind === 'shared' ? 220 : 70))
      .strength((l: L) => (big && l.kind === 'comments' ? 0.12 : 0.5))
    g.d3Force('collide', forceCollide<N>((n) => radius(n) + 4).iterations(2))
    g.d3ReheatSimulation()
  }, [graph, mounted]) // the graph mounts only once the width is known

  // fit everything, but don't zoom small graphs in so far that nodes look huge
  const fit = () => {
    const g = fg.current
    if (!g) return
    g.zoomToFit(0, 50)
    if (g.zoom() > 1.8) g.zoom(1.8, 0)
  }

  const active = hover?.id as string | undefined
  const isLit = (id: string) => !active || id === active || neighbors.get(active)?.has(id)

  return (
    <div ref={wrap} className="relative overflow-hidden rounded-xl border border-line bg-surface" style={{ height }}>
      {width > 0 && (
        <ForceGraph2D<GraphNode, GraphLink>
          ref={fg}
          graphData={graph}
          width={width}
          height={height}
          backgroundColor="rgba(0,0,0,0)"
          cooldownTicks={160}
          onEngineStop={fit}
          nodeLabel={() => ''}
          onNodeHover={(n) => setHover(n)}
          onNodeClick={(n) => onNodeClick?.(n as GraphNode)}
          linkColor={(l) => {
            const lit = !active || endId(l.source) === active || endId(l.target) === active
            return lit ? LINK[l.kind as keyof typeof LINK] : 'rgba(154,168,189,0.05)'
          }}
          linkWidth={(l) => 0.4 + Math.log2(1 + (l.weight as number)) * (l.kind === 'comments' ? 0.35 : 0.7)}
          linkLineDash={(l) => (l.kind === 'thread' ? [3, 3] : null)}
          nodePointerAreaPaint={(n, color, ctx) => {
            ctx.fillStyle = color
            ctx.beginPath()
            ctx.arc(n.x!, n.y!, radius(n) + 3, 0, 2 * Math.PI)
            ctx.fill()
          }}
          nodeCanvasObject={(n, ctx, scale) => {
            const r = radius(n)
            const x = n.x!
            const y = n.y!
            const lit = isLit(n.id as string)
            ctx.globalAlpha = lit ? 1 : 0.15
            const shape = () => {
              ctx.beginPath()
              if (n.type === 'source' && !isChat(n)) ctx.roundRect(x - r, y - r, r * 2, r * 2, r * 0.45)
              else ctx.arc(x, y, r, 0, 2 * Math.PI)
            }
            const img = avatarImage(n.photo_id, () => redraw((v) => v + 1))
            shape()
            if (img) {
              ctx.save()
              ctx.clip()
              ctx.drawImage(img, x - r, y - r, r * 2, r * 2)
              ctx.restore()
            } else {
              ctx.fillStyle = COLOR[n.type]
              ctx.fill()
              if (r * scale > 9) {
                ctx.fillStyle = 'rgba(255,255,255,0.92)'
                ctx.font = `600 ${r * 0.8}px "IBM Plex Sans", sans-serif`
                ctx.textAlign = 'center'
                ctx.textBaseline = 'middle'
                ctx.fillText(initials(n.label), x, y + r * 0.05)
              }
            }
            // type ring keeps identity visible on top of avatars
            shape()
            ctx.lineWidth = (n.type === 'focus' ? 3 : 1.6) / Math.sqrt(scale)
            ctx.strokeStyle = n.id === active || n.id === focusId ? '#f1f5f9' : COLOR[n.type]
            ctx.stroke()
            if (isChat(n)) {
              ctx.beginPath()
              ctx.arc(x, y, r + 3 / Math.sqrt(scale), 0, 2 * Math.PI)
              ctx.lineWidth = 1 / Math.sqrt(scale)
              ctx.stroke()
            }

            // users get a label when hovered or when zoomed in far enough to fit them
            const showLabel = n.type !== 'user' || n.id === active || scale > 2.2
            if (showLabel) {
              const fs = 12 / scale // constant ~12px on screen
              ctx.font = `${n.type === 'user' ? 500 : 600} ${fs}px "IBM Plex Sans", sans-serif`
              ctx.textAlign = 'center'
              ctx.textBaseline = 'top'
              const label = n.label.length > 26 ? n.label.slice(0, 25) + '…' : n.label
              const w = ctx.measureText(label).width
              ctx.fillStyle = 'rgba(11,17,32,0.82)'
              const pad = 3 / scale
              ctx.fillRect(x - w / 2 - pad, y + r + pad, w + pad * 2, fs + pad * 1.5)
              ctx.fillStyle = '#e2e8f0'
              ctx.fillText(label, x, y + r + pad * 1.6)
            }
            ctx.globalAlpha = 1
          }}
        />
      )}

      {/* legend: shape + color + label */}
      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg border border-line bg-bg/80 px-2.5 py-1.5 text-[11.5px] text-fg-muted backdrop-blur">
        {data.nodes.some((n) => n.type === 'focus') && (
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-full border-2" style={{ borderColor: COLOR.focus, background: COLOR.focus }} />пользователь</span>
        )}
        {data.nodes.some((n) => n.type === 'source' && !isChat(n)) && (
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-[4px]" style={{ background: COLOR.source }} />канал</span>
        )}
        {data.nodes.some(isChat) && (
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-full outline-1 outline-offset-1" style={{ background: COLOR.source, outlineColor: COLOR.source, outlineStyle: 'solid' }} />чат</span>
        )}
        {data.nodes.some((n) => n.type === 'user') && (
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-full" style={{ background: COLOR.user }} />люди</span>
        )}
        {data.links.some((l) => l.kind === 'thread') && (
          <span className="flex items-center gap-1.5"><span className="h-0 w-4 border-t-2 border-dashed" style={{ borderColor: LINK.thread }} />одни посты</span>
        )}
        {data.links.some((l) => l.kind === 'reply') && (
          <span className="flex items-center gap-1.5"><span className="h-0 w-4 border-t-2" style={{ borderColor: LINK.reply }} />переписка</span>
        )}
      </div>

      <div className="absolute right-3 bottom-3 flex flex-col gap-1 rounded-lg border border-line bg-bg/80 p-1 backdrop-blur">
        <IconButton label="Приблизить" className="size-8" onClick={() => fg.current?.zoom((fg.current?.zoom() ?? 1) * 1.4, 250)}>
          <Plus className="size-4" />
        </IconButton>
        <IconButton label="Отдалить" className="size-8" onClick={() => fg.current?.zoom((fg.current?.zoom() ?? 1) / 1.4, 250)}>
          <Minus className="size-4" />
        </IconButton>
        <IconButton label="Показать всё" className="size-8" onClick={fit}>
          <Maximize2 className="size-4" />
        </IconButton>
      </div>

      {hover && (
        <div className="pointer-events-none absolute right-3 top-3 max-w-64 rounded-lg border border-line-strong bg-elevated px-3 py-2 text-[12.5px] shadow-xl">
          <div className="font-semibold">{hover.label}</div>
          <div className="text-fg-muted">
            {hover.type === 'source'
              ? `${isChat(hover) ? 'чат' : 'канал'} · ${num(hover.value)} людей`
              : hover.type === 'focus'
                ? 'выбранный пользователь'
                : hover.sources
                  ? `${hover.sources} каналов · ${num(hover.value)} комм.`
                  : `${num(hover.value)} общих постов`}
          </div>
          <div className="mt-0.5 text-fg-subtle">{neighbors.get(hover.id as string)?.size ?? 0} связей · клик — открыть</div>
        </div>
      )}
    </div>
  )
}
