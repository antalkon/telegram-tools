import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, History, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { useToast } from '../components/Toast'
import { Badge, Card, CardHeader, EmptyState, IconButton, Skeleton } from '../components/ui'
import { jobPath, TypeBadge } from '../components/SourceBits'
import { StatusBadge } from '../features/collector/JobPanel'
import { isTerminal } from '../features/collector/useJob'
import { Page, PageHeader } from '../layout/AppLayout'
import { api, type Job } from '../lib/api'
import { duration, num, relative } from '../lib/format'
import { TOOLS } from '../lib/tools'

function JobRow({ job }: { job: Job }) {
  const qc = useQueryClient()
  const toast = useToast()
  const tool = TOOLS.find((t) => t.id === job.tool)
  const ch = job.result?.channel ?? job.progress?.channel
  const users = job.result?.unique_users ?? job.progress?.unique_users
  const remove = useMutation({
    mutationFn: () => api(`/jobs/${job.id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['jobs'] }),
    onError: (e) => toast(e.message, 'error'),
  })
  return (
    <li className="group relative flex items-center gap-3 px-5 py-3.5 transition-colors hover:bg-elevated/60">
      {ch ? (
        <Avatar id={ch.id} name={ch.title} photoId={ch.photo_id} size={38} />
      ) : (
        <span className="flex size-[38px] shrink-0 items-center justify-center rounded-full bg-muted text-fg-subtle">{tool && <tool.icon className="size-4" />}</span>
      )}
      <div className="min-w-0 flex-1">
        <Link to={jobPath(job)} className="flex items-center gap-2 after:absolute after:inset-0">
          <span className="truncate text-[14px] font-medium">{ch?.title ?? job.input.channel}</span>
          {ch?.type && ch.type !== 'channel' && <TypeBadge type={ch.type} className="hidden sm:inline-flex" />}
          <StatusBadge status={job.status} />
          {job.input.mode === 'incremental' && job.result?.mode !== 'full' && <Badge tone="accent">дозабор</Badge>}
          {job.input.monitor_id && <Badge>мониторинг</Badge>}
        </Link>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12.5px] text-fg-muted">
          <span>#{job.id}</span>
          {job.result?.mode === 'incremental' ? (
            <>
              <span>+{num(job.result.new_comments)} {job.tool === 'chat-indexer' ? 'сообщ.' : 'комм.'}</span>
              <span className={job.result.new_users ? 'text-success' : ''}>+{num(job.result.new_users ?? 0)} новых</span>
            </>
          ) : (
            <>
              {users != null && <span>{num(users)} {job.tool === 'chat-indexer' ? 'авторов' : 'польз.'}</span>}
              {job.result?.comments != null && <span>{num(job.result.comments)} {job.tool === 'chat-indexer' ? 'сообщ.' : 'комм.'}</span>}
              {!!job.result?.members && <span>{num(job.result.members)} участн.</span>}
            </>
          )}
          {job.result?.duration_sec != null && <span>{duration(job.result.duration_sec)}</span>}
          <span className="text-fg-subtle">{relative(job.created_at)}</span>
        </div>
      </div>
      {isTerminal(job.status) && (
        <IconButton label="Удалить задачу" onClick={() => remove.mutate()} className="relative z-10 opacity-100 hover:text-danger sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
          <Trash2 className="size-4" />
        </IconButton>
      )}
      <ChevronRight className="size-4 text-fg-subtle" aria-hidden />
    </li>
  )
}

function JobList({ tool, limit }: { tool?: string; limit: number }) {
  const jobs = useQuery({
    queryKey: ['jobs', tool, limit],
    queryFn: () => api<Job[]>(`/jobs?limit=${limit}${tool ? `&tool=${tool}` : ''}`),
    refetchInterval: (q) => (q.state.data?.some((j) => !isTerminal(j.status)) ? 3000 : false),
  })
  if (jobs.isLoading)
    return (
      <div className="flex flex-col gap-2 p-5">
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    )
  if (!jobs.data?.length)
    return <EmptyState icon={<History className="size-5" />} title="Задач пока нет" description="Запустите сбор — результаты сохранятся здесь." />
  return <ul className="divide-y divide-line">{jobs.data.map((j) => <JobRow key={j.id} job={j} />)}</ul>
}

export function RecentJobs({ tool }: { tool: string }) {
  return (
    <Card>
      <CardHeader title="Последние сборы" />
      <JobList tool={tool} limit={10} />
    </Card>
  )
}

export default function Jobs() {
  return (
    <Page>
      <PageHeader icon={<History className="size-5" />} title="История задач" description="Все запуски инструментов" />
      <Card>
        <JobList limit={100} />
      </Card>
    </Page>
  )
}
