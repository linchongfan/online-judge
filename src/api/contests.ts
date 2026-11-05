import type {
  Contest,
  ContestProblems,
  ContestResult,
  ContestStatus,
  MessageResponse,
  Page,
  Ranking,
} from '../types'
import { request } from './client'

export interface ContestListParams {
  page?: number
  pageSize?: number
  status?: ContestStatus
}

export function listContests(params: ContestListParams = {}): Promise<Page<Contest>> {
  return request<Page<Contest>>('/contests', {
    query: { page: params.page, page_size: params.pageSize, status: params.status },
  })
}

export function getContest(contestId: number): Promise<Contest> {
  return request<Contest>(`/contests/${contestId}`)
}

export function getContestProblems(contestId: number): Promise<ContestProblems> {
  return request<ContestProblems>(`/contests/${contestId}/problems`)
}

export function registerForContest(contestId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/contests/${contestId}/registration`, { method: 'PUT' })
}

export function cancelContestRegistration(contestId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/contests/${contestId}/registration`, { method: 'DELETE' })
}

export function getContestRanking(contestId: number): Promise<Ranking> {
  return request<Ranking>(`/contests/${contestId}/ranking`)
}

export function getMyContestResult(contestId: number): Promise<ContestResult> {
  return request<ContestResult>(`/contests/${contestId}/my-result`)
}

export const contestsApi = {
  list: listContests,
  get: getContest,
  problems: getContestProblems,
  register: registerForContest,
  unregister: cancelContestRegistration,
  ranking: getContestRanking,
  myResult: getMyContestResult,
}
