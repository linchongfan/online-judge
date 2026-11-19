// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { initializeSession, session } from '../../src/stores/session'

function resetSession() {
  Object.assign(session, {
    loggedIn: false,
    initializing: false,
    initialized: false,
    degraded: false,
    profile: null,
    role: null,
  })
}

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }))
}

describe('auth refresh chain', () => {
  beforeEach(resetSession)
  afterEach(() => vi.unstubAllGlobals())

  it('marks the session degraded when the refresh request hits a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/auth/refresh')) return Promise.reject(new TypeError('offline'))
      return jsonResponse(401, { error: { code: 'SESSION_EXPIRED', message: 'expired' } })
    }))
    await initializeSession()
    expect(session.degraded).toBe(true)
    expect(session.initialized).toBe(false)
    expect(session.loggedIn).toBe(false)
  })

  it('clears degraded for good once the refresh credential is rejected', async () => {
    let meCalls = 0
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/refresh')) return jsonResponse(401, { error: { code: 'SESSION_REVOKED', message: 'revoked' } })
      meCalls += 1
      if (meCalls === 1) return Promise.reject(new TypeError('offline'))
      return jsonResponse(401, { error: { code: 'SESSION_EXPIRED', message: 'expired' } })
    }))
    await initializeSession()
    expect(session.degraded).toBe(true)
    await initializeSession()
    expect(session.degraded).toBe(false)
    expect(session.initialized).toBe(true)
    expect(session.loggedIn).toBe(false)
  })

  it('treats a refresh 403 as a permanent logout', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/auth/refresh')) return jsonResponse(403, { error: { code: 'SESSION_REVOKED', message: 'revoked' } })
      return jsonResponse(401, { error: { code: 'SESSION_EXPIRED', message: 'expired' } })
    }))
    await initializeSession()
    expect(session.degraded).toBe(false)
    expect(session.initialized).toBe(true)
    expect(session.loggedIn).toBe(false)
  })
})
