import { Users } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { AddSourceForm } from '../components/AddSource'
import { Card, EmptyState, Skeleton } from '../components/ui'
import { JobPanel } from '../features/collector/JobPanel'
import { ParticipantsTable } from '../features/collector/ParticipantsTable'
import { isTerminal, useJob } from '../features/collector/useJob'
import { Page, PageHeader } from '../layout/AppLayout'
import { RecentJobs } from './Jobs'

export default function ChatIndexer() {
  const params = useParams()
  const jobId = params.jobId ? Number(params.jobId) : null
  const job = useJob(jobId)

  return (
    <Page wide>
      <PageHeader
        icon={<Users className="size-5" />}
        title="Индексатор чатов"
        description="Группы, супергруппы и форумы: вся история сообщений для поиска и список участников, если он открыт"
      />
      <div className="flex flex-col gap-5">
        {jobId == null && (
          <Card className="p-5">
            <AddSourceForm />
          </Card>
        )}
        {jobId == null ? (
          <RecentJobs tool="chat-indexer" />
        ) : job.isLoading ? (
          <Skeleton className="h-64 rounded-[var(--radius-card)]" />
        ) : job.isError || !job.data ? (
          <Card>
            <EmptyState icon={<Users className="size-5" />} title="Задача не найдена" description={job.error?.message} />
          </Card>
        ) : (
          <>
            <JobPanel job={job.data} />
            {isTerminal(job.data.status) && job.data.status !== 'failed' && (
              <ParticipantsTable key={jobId} jobId={job.data.result?.base_job_id ?? jobId} chat />
            )}
          </>
        )}
      </div>
    </Page>
  )
}
