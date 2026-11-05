import type {
  Difficulty,
  Page,
  ProblemDetail,
  ProblemListItem,
  ProblemProgress,
  SampleRunCreate,
  Solution,
  SubmissionAccepted,
  Tag,
} from '../types'
import { request, type ApiRequestOptions } from './client'

export interface ProblemListParams {
  page?: number
  pageSize?: number
  keyword?: string
  difficulty?: Difficulty
  tag?: string
  progress?: ProblemProgress
}

export function listProblems(params: ProblemListParams = {}): Promise<Page<ProblemListItem>> {
  return request<Page<ProblemListItem>>('/problems', {
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      difficulty: params.difficulty,
      tag: params.tag,
      progress: params.progress,
    },
  })
}

export function getProblem(problemId: number, contestId?: number): Promise<ProblemDetail> {
  return request<ProblemDetail>(`/problems/${problemId}`, { query: { contest_id: contestId } })
}

export function getRandomProblem(): Promise<ProblemDetail> {
  return request<ProblemDetail>('/problems/random')
}

export function getProblemSolution(problemId: number): Promise<Solution> {
  return request<Solution>(`/problems/${problemId}/solution`)
}

export function runProblemSample(
  problemId: number,
  data: SampleRunCreate,
  options: Pick<ApiRequestOptions, 'signal' | 'timeoutMs'> = {},
): Promise<SubmissionAccepted> {
  return request<SubmissionAccepted>(`/problems/${problemId}/sample-runs`, {
    ...options,
    method: 'POST',
    json: data,
  })
}

export function listTags(): Promise<Tag[]> {
  return request<Tag[]>('/tags')
}

export const problemsApi = {
  list: listProblems,
  get: getProblem,
  random: getRandomProblem,
  solution: getProblemSolution,
  runSample: runProblemSample,
  tags: listTags,
}
