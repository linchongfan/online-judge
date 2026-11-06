import { describe, expect, it, vi } from 'vitest'
import { createIdempotencyKey, formatDateTime, parseServerDate } from '../../src/utils/format'

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
