import clsx from 'clsx'
import { Loader2, X } from 'lucide-react'
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'

// ---------- Button ----------

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const variants: Record<Variant, string> = {
  primary: 'bg-accent text-accent-fg hover:bg-accent-hover shadow-[0_6px_20px_-8px_rgb(42_171_238/0.6)]',
  secondary: 'bg-elevated text-fg border border-line-strong/70 hover:bg-muted hover:border-line-strong',
  ghost: 'text-fg-muted hover:text-fg hover:bg-elevated',
  danger: 'bg-danger-soft text-danger border border-danger/30 hover:bg-danger/20',
}
const sizes: Record<Size, string> = {
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-[10px]',
  lg: 'h-12 px-5 text-[15px] gap-2 rounded-xl',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, icon, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        'inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
})

export function IconButton({ label, className, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={clsx(
        'inline-flex size-9 items-center justify-center rounded-lg text-fg-muted transition-colors duration-150 hover:bg-elevated hover:text-fg',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

// ---------- Card ----------

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx('rounded-[var(--radius-card)] border border-line bg-card shadow-[var(--shadow-card)]', className)}
      {...props}
    />
  )
}

export function CardHeader({ title, description, actions, icon }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 text-accent">{icon}</div>}
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-fg">{title}</h2>
          {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

// ---------- Form ----------

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: ReactNode
  error?: string | null
  htmlFor: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-fg">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="text-[13px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-[12.5px] text-fg-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean
  leading?: ReactNode
  trailing?: ReactNode
  inputSize?: 'md' | 'lg'
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, leading, trailing, className, inputSize = 'md', ...props },
  ref,
) {
  return (
    <div
      className={clsx(
        'flex items-center gap-2 rounded-[10px] border bg-surface px-3 transition-[border-color,box-shadow] duration-150',
        'focus-within:border-accent focus-within:shadow-[0_0_0_3px_rgb(42_171_238/0.18)]',
        invalid ? 'border-danger/70' : 'border-line-strong/70 hover:border-line-strong',
        inputSize === 'lg' ? 'h-12' : 'h-10',
        className,
      )}
    >
      {leading && <span className="flex shrink-0 text-fg-subtle">{leading}</span>}
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className="h-full min-w-0 flex-1 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg-subtle focus-visible:outline-none"
        {...props}
      />
      {trailing && <span className="flex shrink-0">{trailing}</span>}
    </div>
  )
})

export function Switch({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
        </label>
        {description && <p className="text-[12.5px] text-fg-subtle">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors duration-200',
          checked ? 'border-accent bg-accent' : 'border-line-strong bg-muted',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 left-0.5 size-[18px] rounded-full bg-white shadow transition-transform duration-200',
            checked && 'translate-x-5',
          )}
        />
      </button>
    </div>
  )
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; hint?: string }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] border border-line bg-surface p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          title={o.hint}
          onClick={() => onChange(o.value)}
          className={clsx(
            'h-8 rounded-[7px] px-3 text-[13px] font-medium transition-colors duration-150',
            value === o.value ? 'bg-elevated text-fg shadow-sm' : 'text-fg-muted hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------- Misc ----------

type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'
const tones: Record<Tone, string> = {
  neutral: 'bg-muted text-fg-muted',
  accent: 'bg-accent-soft text-accent',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
}

export function Badge({ tone = 'neutral', className, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={clsx('inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11.5px] font-medium whitespace-nowrap', tones[tone], className)}
      {...props}
    />
  )
}

export function ProgressBar({ value, indeterminate, label }: { value?: number; indeterminate?: boolean; label: string }) {
  const pct = Math.max(0, Math.min(100, value ?? 0))
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      className="h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      <div
        className={clsx(
          'h-full rounded-full bg-gradient-to-r from-accent to-[#5ec8ff] transition-[width] duration-500 ease-out',
          indeterminate && 'progress-indeterminate',
        )}
        style={{ width: indeterminate ? '100%' : `${pct}%` }}
      />
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded-md bg-muted', className)} />
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-xl border border-line bg-elevated text-fg-muted">{icon}</div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-fg-muted">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line-strong bg-elevated px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">{children}</kbd>
  )
}

// ---------- Dialog / Drawer ----------

function useEscape(open: boolean, onClose: () => void) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const prevFocus = document.activeElement as HTMLElement | null
    // Move focus into the panel unless a child already grabbed it (autoFocus inputs).
    requestAnimationFrame(() => {
      if (panel.current && !panel.current.contains(document.activeElement)) panel.current.focus()
    })
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
      prevFocus?.focus?.()
    }
  }, [open, onClose])
  return panel
}

export function Dialog({ open, onClose, title, description, children, width = 'max-w-md' }: {
  open: boolean
  onClose: () => void
  title: string
  description?: ReactNode
  children: ReactNode
  width?: string
}) {
  const panel = useEscape(open, onClose)
  const id = useId()
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        className={clsx('animate-in relative w-full rounded-t-2xl outline-none border border-line bg-card shadow-2xl sm:rounded-2xl', width)}
      >
        <div className="flex items-start justify-between gap-4 px-5 pt-5">
          <div>
            <h2 id={id} className="text-base font-semibold">{title}</h2>
            {description && <p className="mt-1 text-[13px] text-fg-muted">{description}</p>}
          </div>
          <IconButton label="Закрыть" onClick={onClose} className="-mt-1 -mr-2">
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="max-h-[calc(90dvh-5rem)] overflow-y-auto px-5 pt-4 pb-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  const panel = useEscape(open, onClose)
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <aside
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        className="absolute inset-y-0 right-0 flex w-full max-w-md outline-none flex-col border-l border-line bg-card shadow-2xl"
        style={{ animation: 'fade-up 200ms ease-out both' }}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0 flex-1">{title}</div>
          <IconButton label="Закрыть" onClick={onClose}>
            <X className="size-4" />
          </IconButton>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto">{children}</div>
      </aside>
    </div>,
    document.body,
  )
}
