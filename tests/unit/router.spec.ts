// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ getProfile: vi.fn() }))
vi.mock('../../src/api/me', () => ({ getProfile: mocks.getProfile }))

import { ApiError } from '../../src/api/client'
import { session } from '../../src/stores/session'
import router from '../../src/router'

function resetSession() {
  Object.assign(session, {
    loggedIn: false,
    initializing: false,
    initialized: false,
    degraded: false,
    profile: null,
    role: null,
  })
  mocks.getProfile.mockReset()
}

describe('router auth guard', () => {
  beforeEach(resetSession)

  it('redirects confirmed guests to login for protected pages', async () => {
    mocks.getProfile.mockRejectedValue(new ApiError('SESSION_EXPIRED', 'expired', 401))
    await router.push('/submissions')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(router.currentRoute.value.query.redirect).toBe('/submissions')
  })

  it('holds protected pages when the session is degraded instead of bouncing to login', async () => {
    mocks.getProfile.mockRejectedValue(new ApiError('NETWORK_ERROR', 'offline', 0))
    await router.push('/submissions')
    expect(router.currentRoute.value.path).toBe('/submissions')
    expect(session.degraded).toBe(true)
  })

  it('never lets a degraded session into admin pages', async () => {
    mocks.getProfile.mockRejectedValue(new ApiError('NETWORK_ERROR', 'offline', 0))
    await router.push('/admin/dashboard')
    expect(router.currentRoute.value.path).toBe('/problems')
  })
})
