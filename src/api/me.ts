import type {
  MessageResponse,
  PasswordChangeRequest,
  ProfileUpdateRequest,
  UserContestRecord,
  UserProfile,
  UserStats,
} from '../types'
import { request, type ApiRequestOptions } from './client'

export function getProfile(options: Pick<ApiRequestOptions, 'signal' | 'timeoutMs'> = {}): Promise<UserProfile> {
  return request<UserProfile>('/me', options)
}

export function updateProfile(data: ProfileUpdateRequest): Promise<UserProfile> {
  return request<UserProfile>('/me', { method: 'PATCH', json: data })
}

export function changePassword(data: PasswordChangeRequest): Promise<MessageResponse> {
  return request<MessageResponse>('/me/password', { method: 'PUT', json: data })
}

export function getUserStats(): Promise<UserStats> {
  return request<UserStats>('/me/stats')
}

export function getUserContestRecords(): Promise<UserContestRecord[]> {
  return request<UserContestRecord[]>('/me/contests')
}

export const meApi = {
  get: getProfile,
  update: updateProfile,
  changePassword,
  stats: getUserStats,
  contests: getUserContestRecords,
}
