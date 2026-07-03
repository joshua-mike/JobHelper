import { useCallback } from 'react'
import { useInvalidateMetrics, useRuns, useRunStatus } from '../api/hooks'
import { PendingReviewTile } from '../components/review/PendingReviewTile'
import { RunPanel } from '../components/run/RunPanel'
import { RunsTable } from '../components/run/RunsTable'
import { Card } from '../components/ui/card'

export default function RunsPage() {
  const { data: status, refetch } = useRunStatus()
  const runs = useRuns(20)
  const invalidateMetrics = useInvalidateMetrics()

  const onFinished = useCallback(() => {
    void refetch()
    invalidateMetrics()
  }, [refetch, invalidateMetrics])

  return (
    <div className="space-y-6">
      <RunPanel status={status} onFinished={onFinished} />
      {/* Surfaces automatically when a finished run left proposals to review. */}
      <PendingReviewTile />
      <Card title="Run history">
        <RunsTable data={runs.data ?? []} />
      </Card>
    </div>
  )
}
