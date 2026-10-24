/* Lightweight SVG/HTML charts in the panel's dark theme.
   Colors (validated for the dark card surface): series-1 blue, series-2 aqua; sequential = one blue ramp. */
import clsx from 'clsx'
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Timeline } from '../lib/api'
import { compact, num } from '../lib/format'

export const SERIES = ['#3987e5', '#199e70', '#d95926'] as const
// sequential blue ramp, dark mode: near-zero recedes toward the surface, magnitude gets lighter
const RAMP = ['#1d2840', '#173a6b', '#184f95', '#256abf', '#3987e5', '#6da7ec', '#b7d3f6']

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

function niceMax(v: number) {
  if (v <= 4) return 4
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
export function bucketLabel(t: string, bucket: Timeline['bucket'], long = false) {
  const [y, m, d] = t.split('-').map(Number)
  if (bucket === 'month') return long ? `${MONTHS[m - 1]} ${y}` : `${MONTHS[m - 1]} ${String(y).slice(2)}`
  if (bucket === 'week') return long ? `неделя с ${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`
  return long ? `${d} ${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]}`
}

export function Tooltip({ x, y, children, width }: { x: number; y: number; children: ReactNode; width: number }) {
  const left = Math.min(Math.max(x, 70), width - 70)
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-line-strong bg-elevated px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-xl"
      style={{ left, top: y - 8 }}
    >
      {children}
    </div>
  )
}

/** Bars over time; single measure (pick it with the series prop). */
export function TimeBars({
  data,
  series = 'comments',
  height = 180,
  color = SERIES[0],
}: {
  data: Timeline
  series?: 'comments' | 'users'
  height?: number
  color?: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const pts = data.points
  const padL = 36
  const padB = 22
  const innerW = Math.max(0, width - padL)
  const innerH = height - padB - 8
  const max = niceMax(Math.max(1, ...pts.map((p) => p[series])))
  const step = pts.length ? innerW / pts.length : 0
  const gap = step > 6 ? 2 : step > 3 ? 1 : 0
  const bw = Math.max(1, step - gap)
  const ticks = [0, max / 2, max]
  const labelEvery = Math.max(1, Math.ceil(pts.length / Math.max(1, Math.floor(innerW / 70))))

  if (!pts.length) return <div className="flex h-40 items-center justify-center text-sm text-fg-subtle">Нет данных</div>

  return (
    <div ref={ref} className="relative w-full select-none" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Динамика: ${pts.length} точек, максимум ${num(Math.max(...pts.map((p) => p[series])))}`}>
          {ticks.map((t) => {
            const y = 8 + innerH - (t / max) * innerH
            return (
              <g key={t}>
                <line x1={padL} x2={width} y1={y} y2={y} stroke="var(--color-line)" strokeDasharray={t ? '2 4' : undefined} />
                <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="11" fill="var(--color-fg-subtle)" className="font-mono">
                  {compact(t)}
                </text>
              </g>
            )
          })}
          {pts.map((p, i) => {
            const h = Math.max(p[series] ? 2 : 0, (p[series] / max) * innerH)
            const x = padL + i * step + gap / 2
            const y = 8 + innerH - h
            const r = Math.min(4, bw / 2, h)
            return (
              <path
                key={p.t}
                d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${y + h} Z`}
                fill={color}
                opacity={hover == null || hover === i ? 1 : 0.45}
              />
            )
          })}
          {pts.map((p, i) =>
            i % labelEvery === 0 ? (
              <text key={p.t} x={padL + i * step + step / 2} y={height - 6} textAnchor="middle" fontSize="11" fill="var(--color-fg-subtle)">
                {bucketLabel(p.t, data.bucket)}
              </text>
            ) : null,
          )}
          {/* hit area bigger than the marks */}
          <rect
            x={padL}
            y={0}
            width={innerW}
            height={height - padB}
            fill="transparent"
            onMouseMove={(e) => {
              const bx = e.currentTarget.getBoundingClientRect()
              setHover(Math.min(pts.length - 1, Math.max(0, Math.floor((e.clientX - bx.left) / step))))
            }}
            onMouseLeave={() => setHover(null)}
          />
        </svg>
      )}
      {hover != null && pts[hover] && (
        <Tooltip x={padL + hover * step + step / 2} y={8 + innerH - (pts[hover][series] / max) * innerH} width={width}>
          <div className="text-fg-muted">{bucketLabel(pts[hover].t, data.bucket, true)}</div>
          <div>
            <span className="font-mono font-semibold">{num(pts[hover].comments)}</span> комм. ·{' '}
            <span className="font-mono font-semibold">{num(pts[hover].users)}</span> польз.
          </div>
        </Tooltip>
      )}
    </div>
  )
}

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const TZ_OFFSET_HOURS = -new Date().getTimezoneOffset() / 60 // hours ahead of UTC

/** Weekday x hour grid. Input is UTC [Mon..Sun][0..23]; shown in the viewer's timezone. */
export function Heatmap({ grid }: { grid: number[][] }) {
  const [hover, setHover] = useState<{ d: number; h: number } | null>(null)
  const offset = TZ_OFFSET_HOURS
  const local = useMemo(() => {
    const out = Array.from({ length: 7 }, () => Array(24).fill(0) as number[])
    grid.forEach((row, d) =>
      row.forEach((v, h) => {
        // shift the UTC hour into local time, carrying into the previous/next weekday
        const abs = d * 24 + h + Math.round(offset) + 7 * 24
        out[Math.floor(abs / 24) % 7][abs % 24] += v
      }),
    )
    return out
  }, [grid, offset])
  const max = Math.max(1, ...local.flat())
  const total = local.flat().reduce((a, b) => a + b, 0)
  const color = (v: number) => (v === 0 ? RAMP[0] : RAMP[Math.min(RAMP.length - 1, 1 + Math.floor((v / max) * (RAMP.length - 1.001)))])
  const peak = local.flatMap((row, d) => row.map((v, h) => ({ v, d, h }))).sort((a, b) => b.v - a.v)[0]

  return (
    <div>
      <div className="grid grid-cols-[28px_repeat(24,minmax(0,1fr))] gap-[2px]" role="grid" aria-label="Активность по дням недели и часам">
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} className="text-center font-mono text-[10px] text-fg-subtle">
            {h % 3 === 0 ? h : ''}
          </span>
        ))}
        {local.map((row, d) => (
          <div key={d} role="row" className="contents">
            <span className="text-[11px] leading-[18px] text-fg-muted">{DAYS[d]}</span>
            {row.map((v, h) => (
              <span
                key={h}
                role="gridcell"
                aria-label={`${DAYS[d]} ${h}:00 — ${v}`}
                onMouseEnter={() => setHover({ d, h })}
                onMouseLeave={() => setHover(null)}
                className={clsx('h-[18px] rounded-[3px] transition-[outline] duration-75', hover?.d === d && hover?.h === h && 'outline outline-2 outline-fg/70')}
                style={{ background: color(v) }}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-[12px] text-fg-muted">
        <span>
          {hover ? (
            <>
              {DAYS[hover.d]}, {hover.h}:00–{hover.h + 1}:00 — <span className="font-mono font-semibold text-fg">{num(local[hover.d][hover.h])}</span> комм. (
              {total ? ((local[hover.d][hover.h] / total) * 100).toFixed(1) : 0}%)
            </>
          ) : peak && peak.v ? (
            <>
              Пик: {DAYS[peak.d]}, {peak.h}:00 · время UTC{offset >= 0 ? '+' : ''}
              {offset}
            </>
          ) : (
            'Нет данных'
          )}
        </span>
        <span className="flex items-center gap-1.5">
          меньше
          {RAMP.slice(1).map((c) => (
            <span key={c} className="size-3 rounded-[3px]" style={{ background: c }} />
          ))}
          больше
        </span>
      </div>
    </div>
  )
}

/** Two-part stacked monthly bars (e.g. new vs returning commenters). */
export function StackedBars({
  data,
  keys,
  labels,
  height = 170,
}: {
  data: { t: string; values: number[] }[]
  keys: [string, string]
  labels: (t: string) => string
  height?: number
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const padL = 36
  const padB = 22
  const innerW = Math.max(0, width - padL)
  const innerH = height - padB - 8
  const max = niceMax(Math.max(1, ...data.map((d) => d.values[0] + d.values[1])))
  const step = data.length ? innerW / data.length : 0
  const gap = step > 6 ? 2 : 1
  const bw = Math.max(1, step - gap)
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(innerW / 56))))
  return (
    <div>
      <div className="mb-2 flex gap-4 text-[12px] text-fg-muted">
        {keys.map((k, i) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ background: SERIES[i] }} /> {k}
          </span>
        ))}
      </div>
      <div ref={ref} className="relative w-full select-none" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={`${keys.join(' и ')} по месяцам`}>
            {[0, max / 2, max].map((t) => {
              const y = 8 + innerH - (t / max) * innerH
              return (
                <g key={t}>
                  <line x1={padL} x2={width} y1={y} y2={y} stroke="var(--color-line)" strokeDasharray={t ? '2 4' : undefined} />
                  <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="11" fill="var(--color-fg-subtle)" className="font-mono">
                    {compact(t)}
                  </text>
                </g>
              )
            })}
            {data.map((d, i) => {
              const x = padL + i * step + gap / 2
              const h0 = (d.values[0] / max) * innerH
              const h1 = (d.values[1] / max) * innerH
              const base = 8 + innerH
              return (
                <g key={d.t} opacity={hover == null || hover === i ? 1 : 0.45}>
                  <rect x={x} y={base - h0} width={bw} height={Math.max(0, h0)} fill={SERIES[0]} />
                  {/* 2px surface gap between stacked segments */}
                  <rect x={x} y={base - h0 - h1} width={bw} height={Math.max(0, h1 - (h1 > 2 ? 2 : 0))} rx={Math.min(3, bw / 2)} fill={SERIES[1]} />
                </g>
              )
            })}
            {data.map((d, i) =>
              i % labelEvery === 0 ? (
                <text key={d.t} x={padL + i * step + step / 2} y={height - 6} textAnchor="middle" fontSize="11" fill="var(--color-fg-subtle)">
                  {labels(d.t)}
                </text>
              ) : null,
            )}
            <rect
              x={padL}
              y={0}
              width={innerW}
              height={height - padB}
              fill="transparent"
              onMouseMove={(e) => {
                const bx = e.currentTarget.getBoundingClientRect()
                setHover(Math.min(data.length - 1, Math.max(0, Math.floor((e.clientX - bx.left) / step))))
              }}
              onMouseLeave={() => setHover(null)}
            />
          </svg>
        )}
        {hover != null && data[hover] && (
          <Tooltip x={padL + hover * step + step / 2} y={8 + innerH - ((data[hover].values[0] + data[hover].values[1]) / max) * innerH} width={width}>
            <div className="text-fg-muted">{labels(data[hover].t)}</div>
            {keys.map((k, i) => (
              <div key={k}>
                {k}: <span className="font-mono font-semibold">{num(data[hover].values[i])}</span>
              </div>
            ))}
          </Tooltip>
        )}
      </div>
    </div>
  )
}

/** Horizontal bar list with labels and values; the label column can hold any node. */
export function BarList({
  items,
  format = num,
  color = SERIES[0],
}: {
  items: { key: string | number; label: ReactNode; value: number; hint?: string }[]
  format?: (v: number) => string
  color?: string
}) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((it) => (
        <li key={it.key} title={it.hint} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
          <div className="min-w-0 truncate text-[13px]">{it.label}</div>
          <span className="text-right font-mono text-[13px] font-semibold tabular">{format(it.value)}</span>
          <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-muted">
            <span className="block h-full rounded-full" style={{ width: `${Math.max(2, (it.value / max) * 100)}%`, background: color }} />
          </span>
        </li>
      ))}
    </ul>
  )
}
