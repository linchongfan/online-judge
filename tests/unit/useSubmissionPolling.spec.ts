import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useSubmissionPolling } from '../../src/composables/useSubmissionPolling'
import { ApiError } from '../../src/api/client'
import type { Submission } from '../../src/types'

function submission(status: Submission['status']): Submission {
  return { id: 's-1', status } as Submission
}

describe('useSubmissionPolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('stops after a terminal status and calls onTerminal', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(submission('JUDGING'))
      .mockResolvedValueOnce(submission('AC'))
    const onTerminal = vi.fn()
    const scope = effectScope()
    const id = ref('s-1')
    const polling = scope.run(() =>
      useSubmissionPolling(id, { fetcher, pollIntervalMs: 100, onTerminal }),
    )!
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(100)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(onTerminal).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(fetcher).toHaveBeenCalledTimes(2)
    scope.stop()
  })

  it('keeps polling after transient errors but backs off', async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new ApiError('NETWORK_ERROR', 'offline', 0))
      .mockRejectedValueOnce(new ApiError('NETWORK_ERROR', 'offline', 0))
      .mockResolvedValueOnce(submission('WA'))
    const onTerminal = vi.fn()
    const scope = effectScope()
    const polling = scope.run(() =>
      useSubmissionPolling(ref('s-1'), { fetcher, pollIntervalMs: 100, onTerminal }),
    )!
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(200) // first retry after 2x backoff
    expect(fetcher).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(400) // second retry after 4x backoff
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(onTerminal).toHaveBeenCalledTimes(1)
    expect(polling.error.value).toBeNull()
    scope.stop()
  })

  it('stops on permanent errors (404) and exposes the error', async () => {
    const fetcher = vi.fn().mockRejectedValue(new ApiError('NOT_FOUND', 'missing', 404))
    const scope = effectScope()
    const polling = scope.run(() =>
      useSubmissionPolling(ref('s-1'), { fetcher, pollIntervalMs: 100 }),
    )!
    await vi.advanceTimersByTimeAsync(0)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(polling.error.value?.message).toBe('missing')
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetcher).toHaveBeenCalledTimes(1)
    scope.stop()
  })
})
