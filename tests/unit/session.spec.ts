import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ getProfile: vi.fn() }))
vi.mock('../../src/api/me', () => ({ getProfile: mocks.getProfile }))

import { ApiError } from '../../src/api/client'
import { initializeSession, session } from '../../src/stores/session'

function resetSession() {
  Object.assign(session, { loggedIn: false, initializing: false, initialized: false, profile: null, role: null })
  mocks.getProfile.mockReset()
}

describe('session initialization', () => {
  beforeEach(resetSession)

  it('applies the profile on success', async () => {
    mocks.getProfile.mockResolvedValue({ username: 'u', role: 'user' })
    const profile = await initializeSession()
    expect(profile?.username).toBe('u')
    expect(session.loggedIn).toBe(true)
    expect(session.initialized).toBe(true)
  })

  it('stays uninitialized on transient network errors so the next navigation retries', async () => {
    mocks.getProfile.mockRejectedValue(new ApiError('NETWORK_ERROR', 'offline', 0))
    const profile = await initializeSession()
    expect(profile).toBeNull()
    expect(session.loggedIn).toBe(false)
    expect(session.initialized).toBe(false)

    mocks.getProfile.mockResolvedValue({ username: 'u', role: 'user' })
    await initializeSession()
    expect(session.loggedIn).toBe(true)
    expect(mocks.getProfile).toHaveBeenCalledTimes(2)
  })

  it('clears the session for good when credentials are rejected (401)', async () => {
    mocks.getProfile.mockRejectedValue(new ApiError('SESSION_EXPIRED', 'expired', 401))
    await initializeSession()
    expect(session.loggedIn).toBe(false)
    expect(session.initialized).toBe(true)
  })
})
