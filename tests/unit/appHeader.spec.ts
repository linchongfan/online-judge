// @vitest-environment happy-dom
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  logoutRequest: vi.fn(),
  push: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
}))
vi.mock('../../src/api/auth', () => ({ logout: mocks.logoutRequest }))
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.messageSuccess, warning: mocks.messageWarning, info: vi.fn() },
  ElIcon: { template: '<i />' },
  ElButton: { template: '<button />' },
  ElDropdown: { template: '<div><slot /></div>' },
  ElDropdownMenu: { template: '<div><slot /></div>' },
  ElDropdownItem: { template: '<div><slot /></div>' },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/problems' }), useRouter: () => ({ push: mocks.push }) }))

import { ApiError } from '../../src/api/client'
import { session } from '../../src/stores/session'
import AppHeader from '../../src/components/AppHeader.vue'

function mountHeader() {
  return mount(AppHeader, {
    global: {
      stubs: {
        AppLogo: { template: '<div />' },
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('AppHeader sign-out', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(session, {
      loggedIn: true,
      initializing: false,
      initialized: true,
      degraded: false,
      profile: { username: 'u', nickname: '用户' },
      role: 'user',
    })
  })

  it('reports a plain success when the server revokes the session', async () => {
    mocks.logoutRequest.mockResolvedValue({ message: 'ok' })
    const wrapper = mountHeader()
    await (wrapper.vm as unknown as { signOut: () => Promise<void> }).signOut()
    expect(mocks.messageSuccess).toHaveBeenCalledWith('已退出登录')
    expect(mocks.messageWarning).not.toHaveBeenCalled()
  })

  it('warns that only the local session was cleared when the request fails', async () => {
    mocks.logoutRequest.mockRejectedValue(new ApiError('NETWORK_ERROR', 'offline', 0))
    const wrapper = mountHeader()
    await (wrapper.vm as unknown as { signOut: () => Promise<void> }).signOut()
    expect(mocks.messageWarning).toHaveBeenCalledWith('网络异常：已在本机退出，服务端会话可能仍有效')
    expect(mocks.messageSuccess).not.toHaveBeenCalled()
    expect(session.loggedIn).toBe(false)
  })
})
