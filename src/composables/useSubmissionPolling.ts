import {
  getCurrentScope,
  onScopeDispose,
  ref,
  toValue,
  watch,
  type MaybeRefOrGetter,
} from 'vue'
import { getSubmission } from '../api/submissions'
import { ApiError } from '../api/client'
import type { JudgeStatus, Submission } from '../types'

const terminalStatuses: ReadonlySet<JudgeStatus> = new Set(['AC', 'WA', 'TLE', 'MLE', 'RE', 'CE', 'SE'])

export function isTerminalSubmissionStatus(status: JudgeStatus): boolean {
  return terminalStatuses.has(status)
}

export interface SubmissionPollingOptions {
  pollIntervalMs?: number
  immediate?: boolean
  fetcher?: (submissionId: string, options: { signal: AbortSignal }) => Promise<Submission>
  onUpdate?: (submission: Submission) => void
  onTerminal?: (submission: Submission) => void
}

export function useSubmissionPolling(
  submissionId: MaybeRefOrGetter<string | null | undefined>,
  options: SubmissionPollingOptions = {},
) {
  const submission = ref<Submission | null>(null)
  const error = ref<Error | null>(null)
  const isLoading = ref(false)
  const isPolling = ref(false)
  const pollIntervalMs = options.pollIntervalMs ?? 1_000
  const fetcher = options.fetcher ?? getSubmission

  let active = false
  let inFlight = false
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null
  let consecutiveFailures = 0

  function clearTimer(): void {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  function stop(): void {
    active = false
    generation += 1
    consecutiveFailures = 0
    clearTimer()
    controller?.abort()
    controller = null
    isPolling.value = false
    isLoading.value = false
  }

  function schedule(run: number): void {
    if (!active || run !== generation) return
    clearTimer()
    // Transient network failures back off exponentially instead of hammering.
    const backoff = consecutiveFailures ? Math.min(8, 2 ** consecutiveFailures) : 1
    timer = setTimeout(() => {
      timer = undefined
      void poll(run)
    }, pollIntervalMs * backoff)
  }

  async function poll(run: number): Promise<void> {
    const id = toValue(submissionId)
    if (!active || run !== generation || inFlight || !id) return

    inFlight = true
    isLoading.value = true
    const requestController = new AbortController()
    controller = requestController
    let shouldSchedule = true

    try {
      const result = await fetcher(id, { signal: requestController.signal })
      if (!active || run !== generation) return
      submission.value = result
      error.value = null
      consecutiveFailures = 0
      options.onUpdate?.(result)
      if (isTerminalSubmissionStatus(result.status)) {
        shouldSchedule = false
        stop()
        options.onTerminal?.(result)
      }
    } catch (caught) {
      if (!active || run !== generation || requestController.signal.aborted) {
        shouldSchedule = false
      } else {
        consecutiveFailures += 1
        error.value = caught instanceof Error ? caught : new Error(String(caught))
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403 || caught.status === 404)) {
          // Permanent failure: polling forever would pin the UI in "judging".
          shouldSchedule = false
        }
      }
    } finally {
      inFlight = false
      if (controller === requestController) controller = null
      if (run === generation) isLoading.value = false

      if (active && run === generation && shouldSchedule) schedule(run)
      else if (active && run !== generation) {
        isLoading.value = false
        void poll(generation)
      }
    }
  }

  function start(): void {
    stop()
    const id = toValue(submissionId)
    if (!id) {
      submission.value = null
      return
    }
    active = true
    isPolling.value = true
    error.value = null
    if (!inFlight) void poll(generation)
  }

  async function refresh(): Promise<void> {
    if (!active) {
      start()
      return
    }
    clearTimer()
    await poll(generation)
  }

  watch(
    () => toValue(submissionId),
    () => {
      submission.value = null
      start()
    },
    { immediate: options.immediate !== false },
  )

  if (getCurrentScope()) onScopeDispose(stop)

  return {
    submission,
    error,
    isLoading,
    isPolling,
    start,
    stop,
    refresh,
  }
}
