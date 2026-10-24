import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, type Job } from '../../lib/api'

const TERMINAL = new Set(['done', 'failed', 'cancelled'])
export const isTerminal = (s: string | undefined) => !!s && TERMINAL.has(s)

/** Job state from REST, kept live through the SSE progress stream while the job runs. */
export function useJob(jobId: number | null) {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api<Job>(`/jobs/${jobId}`),
    enabled: jobId != null,
  })
  const status = query.data?.status

  useEffect(() => {
    if (jobId == null || !status || isTerminal(status)) return
    const es = new EventSource(`/api/jobs/${jobId}/events`)
    const merge = (patch: Partial<Job>) =>
      qc.setQueryData<Job>(['job', jobId], (old) => (old ? { ...old, ...patch, progress: { ...old.progress, ...patch.progress } } : old))

    es.addEventListener('state', (e) => qc.setQueryData(['job', jobId], JSON.parse((e as MessageEvent).data)))
    es.addEventListener('progress', (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as Partial<Job>
      const patch: Partial<Job> = { status: ev.status, progress: ev.progress ?? {} }
      if (ev.error !== undefined) patch.error = ev.error
      if (ev.result) patch.result = ev.result
      merge(patch)
      if (ev.status && isTerminal(ev.status)) {
        es.close()
        qc.invalidateQueries({ queryKey: ['job', jobId] })
        qc.invalidateQueries({ queryKey: ['participants', jobId] })
        qc.invalidateQueries({ queryKey: ['jobs'] })
        for (const key of ['sources', 'overview', 'users', 'graph', 'overlap', 'source', 'user'])
          qc.invalidateQueries({ queryKey: [key] })
      }
    })
    // EventSource reconnects on its own; nothing else to do on transient errors.
    return () => es.close()
  }, [jobId, status, qc])

  return query
}
