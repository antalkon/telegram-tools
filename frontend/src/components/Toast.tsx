import clsx from 'clsx'
import { CheckCircle2, AlertCircle, Info } from 'lucide-react'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type ToastTone = 'success' | 'error' | 'info'
interface ToastItem {
  id: number
  tone: ToastTone
  text: string
}

const Ctx = createContext<(text: string, tone?: ToastTone) => void>(() => {})
export const useToast = () => useContext(Ctx)

let seq = 0
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const push = useCallback((text: string, tone: ToastTone = 'info') => {
    const id = ++seq
    setItems((xs) => [...xs.slice(-3), { id, tone, text }])
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === 'error' ? 6000 : 3500)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 left-4 z-[60] flex flex-col items-center gap-2 sm:left-auto sm:items-end">
        {items.map((t) => {
          const Icon = t.tone === 'success' ? CheckCircle2 : t.tone === 'error' ? AlertCircle : Info
          return (
            <div
              key={t.id}
              role={t.tone === 'error' ? 'alert' : 'status'}
              className="animate-in pointer-events-auto flex max-w-sm items-start gap-2.5 rounded-xl border border-line-strong bg-elevated px-3.5 py-3 text-sm shadow-2xl"
            >
              <Icon
                className={clsx(
                  'mt-0.5 size-4 shrink-0',
                  t.tone === 'success' ? 'text-success' : t.tone === 'error' ? 'text-danger' : 'text-accent',
                )}
                aria-hidden
              />
              <span>{t.text}</span>
            </div>
          )
        })}
      </div>
    </Ctx.Provider>
  )
}
