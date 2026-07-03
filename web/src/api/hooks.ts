import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { ConfigName, ReviewAction, VerifySourceRequest } from './types'

const METRIC_KEYS = [
  'summary',
  'funnel',
  'timeline',
  'sources',
  'runs',
  'recentJobs',
  'reviewJobs',
]

export function useSummary() {
  return useQuery({ queryKey: ['summary'], queryFn: () => api.summary() })
}

export function useFunnel() {
  return useQuery({ queryKey: ['funnel'], queryFn: () => api.funnel() })
}

export function useTimeline(days = 30) {
  return useQuery({ queryKey: ['timeline', days], queryFn: () => api.timeline(days) })
}

export function useSources() {
  return useQuery({ queryKey: ['sources'], queryFn: () => api.sources() })
}

export function useRuns(limit = 20) {
  return useQuery({ queryKey: ['runs', limit], queryFn: () => api.runs(limit) })
}

export function useRecentJobs(limit = 15) {
  return useQuery({ queryKey: ['recentJobs', limit], queryFn: () => api.recentJobs(limit) })
}

export function useRunStatus() {
  return useQuery({
    queryKey: ['runStatus'],
    queryFn: () => api.runStatus(),
    // Tight poll while a run is live so the pill/panel react quickly.
    refetchInterval: (query) => (query.state.data?.state === 'running' ? 2000 : 15000),
  })
}

export function useStartRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (useCache: boolean) => api.startRun(useCache),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['runStatus'] })
      void qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })
}

export function useReviewJobs() {
  return useQuery({ queryKey: ['reviewJobs'], queryFn: () => api.reviewJobs() })
}

/** Apply a review action; refreshes the board and every metric it feeds. */
export function useReviewAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: ReviewAction }) =>
      api.reviewAction(id, action),
    onSuccess: () => {
      for (const key of METRIC_KEYS) void qc.invalidateQueries({ queryKey: [key] })
    },
  })
}

/** Refresh every metric query — called when a run completes. */
export function useInvalidateMetrics() {
  const qc = useQueryClient()
  return useCallback(() => {
    for (const key of METRIC_KEYS) void qc.invalidateQueries({ queryKey: [key] })
  }, [qc])
}

// ---- Settings ---------------------------------------------------------------
export function useSettingsStatus() {
  return useQuery({
    queryKey: ['settingsStatus'],
    queryFn: () => api.settingsStatus(),
    refetchInterval: 15000, // run_active flips when a run starts/ends
  })
}

export function useConfig<T>(name: ConfigName) {
  return useQuery({
    queryKey: ['config', name],
    queryFn: () => api.getConfig<T>(name),
    staleTime: 60_000,
  })
}

export function useSaveConfig<T>(name: ConfigName) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: T) => api.saveConfig(name, data),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['config', name] })
      void qc.invalidateQueries({ queryKey: ['settingsStatus'] })
    },
  })
}

export function useVerifySource() {
  return useMutation({
    mutationFn: (req: VerifySourceRequest) => api.verifySource(req),
  })
}

export function useImportResume() {
  return useMutation({ mutationFn: (file: File) => api.importResume(file) })
}
