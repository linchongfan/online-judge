import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../src/api/client'
import { createIdempotencyKey, formatDateTime, isSubmissionResponseUnknown, parseServerDate } from '../../src/utils/format'

describe('server time parsing', () => {
  it('treats naive SQLAlchemy timestamps as UTC, not browser-local time', () => {
    const naive = parseServerDate('2026-11-04T10:49:46.404013')
    const aware = parseServerDate('2026-11-04T10:49:46.404013Z')
    expect(naive.getTime()).toBe(aware.getTime())
  })

  it('keeps explicit timezone offsets intact', () => {
    expect(parseServerDate('2026-11-04T10:49:46+08:00').toISOString()).toBe('2026-11-04T02:49:46.000Z')
  })

  it('formats invalid dates with a placeholder', () => {
    expect(formatDateTime('not-a-date')).toBe('—')
  })
})

describe('idempotency keys', () => {
  it('falls back when crypto.randomUUID is unavailable (plain HTTP)', () => {
    const original = globalThis.crypto
    vi.stubGlobal('crypto', {})
    try {
      const key = createIdempotencyKey()
      expect(key).toMatch(/^[0-9a-z]+-[0-9a-z]+$/)
    } finally {
      vi.stubGlobal('crypto', original)
    }
  })

  it('produces unique values on every call', () => {
    const first = createIdempotencyKey()
    const second = createIdempotencyKey()
    expect(first).not.toBe(second)
  })
})

describe('isSubmissionResponseUnknown', () => {
  it('treats network errors, timeouts and 5xx as unknown', async () => {
    const { isSubmissionResponseUnknown } = await import('../../src/utils/format')
    const { ApiError } = await import('../../src/api/client')
    expect(isSubmissionResponseUnknown(new ApiError('NETWORK_ERROR', 'offline', 0))).toBe(true)
    expect(isSubmissionResponseUnknown(new ApiError('TIMEOUT', 'timeout', 408))).toBe(true)
    expect(isSubmissionResponseUnknown(new ApiError('SERVER', 'boom', 503))).toBe(true)
    expect(isSubmissionResponseUnknown(new Error('weird'))).toBe(true)
  })

  it('treats definitive 4xx rejections as known outcomes', async () => {
    const { isSubmissionResponseUnknown } = await import('../../src/utils/format')
    const { ApiError } = await import('../../src/api/client')
    expect(isSubmissionResponseUnknown(new ApiError('VALIDATION_ERROR', 'bad', 422))).toBe(false)
    expect(isSubmissionResponseUnknown(new ApiError('SOURCE_TOO_LARGE', 'big', 413))).toBe(false)
    expect(isSubmissionResponseUnknown(new ApiError('AUTH_REQUIRED', 'no', 401))).toBe(false)
  })
})
