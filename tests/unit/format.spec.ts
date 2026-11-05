import { describe, expect, it } from 'vitest'
import { formatDateTime, parseServerDate } from '../../src/utils/format'

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
