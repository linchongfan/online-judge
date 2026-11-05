import type {
  JudgeStatus,
  Language,
  Page,
  Submission,
  SubmissionAccepted,
  SubmissionCreate,
  SubmissionSource,
} from '../types'
import { request, type ApiRequestOptions } from './client'

export interface SubmissionListParams {
  page?: number
  pageSize?: number
  keyword?: string
  status?: JudgeStatus
  language?: Language
  problemId?: number
}

export function createSubmission(
  data: SubmissionCreate,
  options: Pick<ApiRequestOptions, 'signal' | 'timeoutMs'> = {},
): Promise<SubmissionAccepted> {
  return request<SubmissionAccepted>('/submissions', { ...options, method: 'POST', json: data })
}

export function listSubmissions(params: SubmissionListParams = {}): Promise<Page<Submission>> {
  return request<Page<Submission>>('/submissions', {
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      status: params.status,
      language: params.language,
      problemId: params.problemId,
    },
  })
}

export function getSubmission(
  submissionId: string,
  options: Pick<ApiRequestOptions, 'signal' | 'timeoutMs'> = {},
): Promise<Submission> {
  return request<Submission>(`/submissions/${encodeURIComponent(submissionId)}`, options)
}

export function getSubmissionSource(
  submissionId: string,
  options: Pick<ApiRequestOptions, 'signal' | 'timeoutMs'> = {},
): Promise<SubmissionSource> {
  return request<SubmissionSource>(`/submissions/${encodeURIComponent(submissionId)}/source`, options)
}

export const submissionsApi = {
  create: createSubmission,
  list: listSubmissions,
  get: getSubmission,
  source: getSubmissionSource,
}
