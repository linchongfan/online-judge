import type {
  ForgotCodeRequest,
  ForgotResetRequest,
  LoginRequest,
  MessageResponse,
  RegisterRequest,
  TokenResponse,
} from '../types'
import { refreshAccessToken, request } from './client'
import { clearAccessToken, setAccessToken } from './token'

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const response = await request<TokenResponse>('/auth/login', {
    method: 'POST',
    json: data,
    skipAuthRefresh: true,
  })
  setAccessToken(response.accessToken)
  return response
}

export async function register(data: RegisterRequest): Promise<TokenResponse> {
  const response = await request<TokenResponse>('/auth/register', {
    method: 'POST',
    json: data,
    skipAuthRefresh: true,
  })
  setAccessToken(response.accessToken)
  return response
}

export function refresh(): Promise<TokenResponse> {
  return refreshAccessToken()
}

export async function logout(): Promise<MessageResponse> {
  try {
    return await request<MessageResponse>('/auth/logout', {
      method: 'POST',
      csrf: true,
      skipAuthRefresh: true,
    })
  } finally {
    clearAccessToken()
  }
}

export function requestPasswordResetCode(data: ForgotCodeRequest): Promise<MessageResponse> {
  return request<MessageResponse>('/auth/forgot/code', {
    method: 'POST',
    json: data,
    skipAuthRefresh: true,
  })
}

export function resetPassword(data: ForgotResetRequest): Promise<MessageResponse> {
  return request<MessageResponse>('/auth/forgot/reset', {
    method: 'POST',
    json: data,
    skipAuthRefresh: true,
  })
}

export const authApi = {
  login,
  register,
  refresh,
  logout,
  requestPasswordResetCode,
  resetPassword,
}
