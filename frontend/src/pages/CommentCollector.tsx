import { MessagesSquare } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { Card, EmptyState, Skeleton } from '../components/ui'
import { CollectorForm } from '../features/collector/CollectorForm'
import { JobPanel } from '../features/collector/JobPanel'
import { ParticipantsTable } from '../features/collector/ParticipantsTable'
import { isTerminal, useJob } from '../features/collector/useJob'
import { Page, PageHeader } from '../layout/AppLayout'
import { RecentJobs } from './Jobs'
import { Link } from 'react-router-dom'

export default function CommentCollector() {
  const params = useParams()
  const jobId = params.jobId ? Number(params.jobId) : null
  const job = useJob(jobId)

  return (
    <Page wide>
      <PageHeader
        icon={<MessagesSquare className="size-5" />}
        title="Сборщик комментаторов"
        description="Все, кто когда-либо комментировал посты канала: аватар, имя, @username и число комментариев"
      />
      <div className="flex flex-col gap-5">
        <CollectorForm compact={jobId != null} />
        {jobId == null && (
          <p className="-mt-2 text-[12.5px] text-fg-subtle">
            Нужны сообщения и участники группы или чата обсуждений? Это <Link to="/tools/chat-indexer" className="text-accent hover:underline">индексатор чатов</Link>.
          </p>
        )}

        {jobId == null ? (
          <RecentJobs tool="comment-collector" />
        ) : job.isLoading ? (
          <Skeleton className="h-64 rounded-[var(--radius-card)]" />
        ) : job.isError || !job.data ? (
          <Card>
            <EmptyState icon={<MessagesSquare className="size-5" />} title="Задача не найдена" description={job.error?.message} />
          </Card>
        ) : (
          <>
            <JobPanel job={job.data} />
            {isTerminal(job.data.status) && job.data.status !== 'failed' && (
              // a дозабор run appends into its base collection: show the full, updated list
              <ParticipantsTable key={jobId} jobId={job.data.result?.base_job_id ?? jobId} />
            )}
          </>
        )}
      </div>
    </Page>
  )
}
