import { useWindowVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  /** grid track, e.g. 'minmax(0,1fr)' or '90px' */
  width: string
  sortKey?: string
  /** hide below this breakpoint */
  hideBelow?: 'sm' | 'lg'
  align?: 'right'
  render: (row: T, index: number) => ReactNode
}

const hideCls = { sm: 'hidden sm:flex', lg: 'hidden lg:flex' }

/** Window-scrolled virtualized table with sortable headers; loads more as you approach the end. */
export function VirtualTable<T>({
  rows,
  columns,
  rowKey,
  sort,
  onSort,
  onRowClick,
  onEndReached,
  rowHeight = 60,
  stickyTop = 'top-14 lg:top-0',
}: {
  rows: T[]
  columns: Column<T>[]
  rowKey: (r: T) => string | number
  sort?: { key: string; desc: boolean }
  onSort?: (key: string) => void
  onRowClick?: (r: T) => void
  onEndReached?: () => void
  rowHeight?: number
  stickyTop?: string
}) {
  const listRef = useRef<HTMLDivElement>(null)
  const [margin, setMargin] = useState(0)
  const hasRows = rows.length > 0
  useLayoutEffect(() => {
    if (listRef.current) setMargin(listRef.current.getBoundingClientRect().top + window.scrollY)
  }, [hasRows])
  const v = useWindowVirtualizer({ count: rows.length, estimateSize: () => rowHeight, overscan: 10, scrollMargin: margin })
  const items = v.getVirtualItems()
  const last = items.at(-1)?.index ?? 0
  useEffect(() => {
    if (onEndReached && last >= rows.length - 25) onEndReached()
  }, [last, rows.length, onEndReached])

  // tracks per breakpoint: hidden columns drop out of the grid
  const tracks = (bp: 'base' | 'sm' | 'lg') =>
    columns.filter((c) => !c.hideBelow || (bp === 'lg') || (bp === 'sm' && c.hideBelow === 'sm')).map((c) => c.width).join(' ')
  const style = {
    '--cols-base': tracks('base'),
    '--cols-sm': tracks('sm'),
    '--cols-lg': tracks('lg'),
  } as React.CSSProperties
  const grid = 'grid items-center gap-x-3 [grid-template-columns:var(--cols-base)] sm:[grid-template-columns:var(--cols-sm)] lg:[grid-template-columns:var(--cols-lg)]'

  return (
    <div style={style}>
      <div role="row" className={clsx(grid, 'sticky z-10 border-b border-line bg-card/95 px-4 py-2.5 text-[12px] font-medium text-fg-muted backdrop-blur sm:px-5', stickyTop)}>
        {columns.map((c) => {
          const active = sort?.key === c.sortKey
          const cls = clsx(c.hideBelow ? hideCls[c.hideBelow] : 'flex', c.align === 'right' && 'justify-end')
          return c.sortKey && onSort ? (
            <button
              key={c.key}
              onClick={() => onSort(c.sortKey!)}
              aria-sort={active ? (sort!.desc ? 'descending' : 'ascending') : 'none'}
              className={clsx(cls, 'items-center gap-1 transition-colors hover:text-fg', active && 'text-fg')}
            >
              {c.header}
              {active && (sort!.desc ? <ArrowDown className="size-3" aria-hidden /> : <ArrowUp className="size-3" aria-hidden />)}
            </button>
          ) : (
            <span key={c.key} className={cls}>
              {c.header}
            </span>
          )
        })}
      </div>
      <div ref={listRef} role="table" aria-rowcount={rows.length} className="relative" style={{ height: v.getTotalSize() }}>
        {items.map((vi) => {
          const r = rows[vi.index]
          return (
            <div
              key={rowKey(r)}
              role="row"
              tabIndex={onRowClick ? 0 : undefined}
              onClick={() => onRowClick?.(r)}
              onKeyDown={(e) => onRowClick && (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onRowClick(r))}
              className={clsx(grid, 'absolute inset-x-0 border-b border-line/60 px-4 transition-colors duration-100 sm:px-5', onRowClick && 'cursor-pointer hover:bg-elevated/70 focus-visible:bg-elevated')}
              style={{ height: vi.size, transform: `translateY(${vi.start - v.options.scrollMargin}px)` }}
            >
              {columns.map((c) => (
                <div key={c.key} className={clsx('min-w-0 items-center', c.hideBelow ? hideCls[c.hideBelow] : 'flex', c.align === 'right' && 'justify-end')}>
                  {c.render(r, vi.index)}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
