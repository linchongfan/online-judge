import type {
  AdminAbnormalJudgeTask,
  AdminContest,
  AdminContestParticipant,
  AdminContestWrite,
  AdminDashboard,
  AdminDashboardTrend,
  AdminJudgeSettings,
  AdminProblem,
  AdminProblemDetail,
  AdminProblemWrite,
  AdminSolution,
  AdminStatusDistribution,
  AdminStudyPlanDetail,
  AdminStudyPlanSummary,
  AdminStudyPlanWrite,
  AdminTestDataUploadResult,
  AdminTestDataVersion,
  AdminUser,
  ContestPublicationStatus,
  ContestStatus,
  JudgeWorker,
  MessageResponse,
  Page,
  ProblemStatus,
  SolutionCode,
  StudyPlanStatus,
  UserRole,
  UserStatus,
} from '../types'
import {
  API_BASE_URL,
  ApiError,
  refreshAccessToken,
  request,
  type ApiRequestOptions,
} from './client'
import { getAccessToken } from './token'

type RequestControl = Pick<ApiRequestOptions, 'signal' | 'timeoutMs'>

export interface AdminUserListParams {
  page?: number
  pageSize?: number
  keyword?: string
  role?: UserRole
  status?: UserStatus
}

export interface AdminProblemListParams {
  page?: number
  pageSize?: number
  keyword?: string
  status?: ProblemStatus
}

export interface AdminContestListParams {
  page?: number
  pageSize?: number
  keyword?: string
  status?: ContestStatus
  publicationStatus?: ContestPublicationStatus
}

export interface AdminStudyPlanListParams {
  page?: number
  pageSize?: number
  keyword?: string
  status?: StudyPlanStatus
}

export function getAdminDashboard(options: RequestControl = {}): Promise<AdminDashboard> {
  return request<AdminDashboard>('/admin/dashboard', options)
}

export function getAdminDashboardTrends(days: 7 | 30, options: RequestControl = {}): Promise<AdminDashboardTrend[]> {
  return request<AdminDashboardTrend[]>('/admin/dashboard/trends', { ...options, query: { days } })
}

export function getAdminStatusDistribution(options: RequestControl = {}): Promise<AdminStatusDistribution[]> {
  return request<AdminStatusDistribution[]>('/admin/dashboard/status-distribution', options)
}

export function listAdminUsers(params: AdminUserListParams = {}, options: RequestControl = {}): Promise<Page<AdminUser>> {
  return request<Page<AdminUser>>('/admin/users', {
    ...options,
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      role: params.role,
      status: params.status,
    },
  })
}

export function updateAdminUser(userId: number, data: { role?: UserRole; status?: UserStatus }): Promise<AdminUser> {
  return request<AdminUser>(`/admin/users/${userId}`, { method: 'PATCH', json: data })
}

export function sendAdminPasswordReset(userId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/admin/users/${userId}/password-reset`, { method: 'POST' })
}

export function listAdminProblems(params: AdminProblemListParams = {}, options: RequestControl = {}): Promise<Page<AdminProblem>> {
  return request<Page<AdminProblem>>('/admin/problems', {
    ...options,
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      status: params.status,
    },
  })
}

export function createAdminProblem(data: AdminProblemWrite): Promise<AdminProblem> {
  return request<AdminProblem>('/admin/problems', { method: 'POST', json: data })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function normalizeAdminSolution(value: unknown): AdminSolution | null {
  if (!isRecord(value)) return null
  const rawCodes = value.codes ?? value.codeVariants ?? value.code_variants
  const codes: SolutionCode[] = Array.isArray(rawCodes)
    ? rawCodes.flatMap((item) => {
        if (!isRecord(item) || typeof item.language !== 'string' || typeof item.code !== 'string') return []
        return [{ language: item.language as SolutionCode['language'], code: item.code }]
      })
    : []
  return {
    title: String(value.title ?? ''),
    summary: String(value.summary ?? ''),
    steps: Array.isArray(value.steps) ? value.steps.map(String) : [],
    time: String(value.time ?? value.timeComplexity ?? value.time_complexity ?? ''),
    space: String(value.space ?? value.spaceComplexity ?? value.space_complexity ?? ''),
    enabled: value.enabled !== false,
    codes,
  }
}

export async function getAdminProblem(problemId: number): Promise<AdminProblemDetail> {
  // This route intentionally has no response_model. Normalize its snake_case detail fields
  // and ORM solution relationship instead of exposing backend persistence names to the view.
  const response = await request<unknown>(`/admin/problems/${problemId}`)
  if (!isRecord(response)) throw new ApiError('INVALID_RESPONSE', '题目详情响应格式无效')
  const value = (camel: string, snake: string): unknown => response[camel] ?? response[snake]
  return {
    id: Number(response.id),
    title: String(response.title ?? ''),
    difficulty: response.difficulty as AdminProblemDetail['difficulty'],
    tags: Array.isArray(response.tags) ? response.tags.map(String) : [],
    status: response.status as AdminProblemDetail['status'],
    timeLimitMs: Number(value('timeLimitMs', 'time_limit_ms') ?? 1000),
    memoryLimitMb: Number(value('memoryLimitMb', 'memory_limit_mb') ?? 256),
    testDataVersion: (value('testDataVersion', 'test_data_version') as string | null | undefined) ?? null,
    testCaseCount: Number(value('testCaseCount', 'test_case_count') ?? 0),
    testDataSize: Number(value('testDataSize', 'test_data_size') ?? 0),
    acceptance: Number(response.acceptance ?? 0),
    submissionCount: Number(value('submissionCount', 'submission_count') ?? 0),
    solutionLanguageCount: Number(value('solutionLanguageCount', 'solution_language_count') ?? 0),
    updatedAt: String(value('updatedAt', 'updated_at') ?? ''),
    description: Array.isArray(response.description) ? response.description.map(String) : [],
    inputDescription: String(value('inputDescription', 'input_description') ?? ''),
    outputDescription: String(value('outputDescription', 'output_description') ?? ''),
    constraints: Array.isArray(response.constraints) ? response.constraints.map(String) : [],
    samples: (Array.isArray(response.samples) ? response.samples : []) as AdminProblemDetail['samples'],
    solvedCount: Number(value('solvedCount', 'solved_count') ?? 0),
    progress: (response.progress ?? 'untouched') as AdminProblemDetail['progress'],
    solution: normalizeAdminSolution(response.solution),
  }
}

export function updateAdminProblem(problemId: number, data: AdminProblemWrite): Promise<AdminProblem> {
  return request<AdminProblem>(`/admin/problems/${problemId}`, { method: 'PUT', json: data })
}

function changeAdminProblemStatus(problemId: number, action: 'publish' | 'unpublish' | 'archive'): Promise<AdminProblem> {
  return request<AdminProblem>(`/admin/problems/${problemId}/${action}`, { method: 'POST' })
}

export function publishAdminProblem(problemId: number): Promise<AdminProblem> {
  return changeAdminProblemStatus(problemId, 'publish')
}

export function unpublishAdminProblem(problemId: number): Promise<AdminProblem> {
  return changeAdminProblemStatus(problemId, 'unpublish')
}

export function archiveAdminProblem(problemId: number): Promise<AdminProblem> {
  return changeAdminProblemStatus(problemId, 'archive')
}

export function listAdminTestDataVersions(problemId: number): Promise<AdminTestDataVersion[]> {
  return request<AdminTestDataVersion[]>(`/admin/problems/${problemId}/test-data`)
}

export function uploadAdminTestData(problemId: number, file: File): Promise<AdminTestDataUploadResult> {
  const body = new FormData()
  body.append('upload', file)
  return request<AdminTestDataUploadResult>(`/admin/problems/${problemId}/test-data`, {
    method: 'POST',
    body,
    timeoutMs: 120_000,
  })
}

async function templateResponseError(response: Response): Promise<ApiError> {
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    // The fallback below still preserves the HTTP status for non-JSON failures.
  }
  const error = isRecord(payload) && isRecord(payload.error) ? payload.error : null
  return new ApiError(
    typeof error?.code === 'string' ? error.code : `HTTP_${response.status}`,
    typeof error?.message === 'string' ? error.message : `模板下载失败（${response.status}）`,
    response.status,
    error?.details ?? null,
    response.headers.get('X-Request-ID'),
  )
}

export async function downloadAdminTestDataTemplate(): Promise<Blob> {
  const execute = () => fetch(`${API_BASE_URL}/admin/test-data/template`, {
    credentials: 'include',
    headers: {
      Accept: 'application/zip',
      ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
    },
  })
  let response: Response
  try {
    response = await execute()
    if (response.status === 401) {
      await refreshAccessToken()
      response = await execute()
    }
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError('NETWORK_ERROR', '无法连接服务器，请稍后重试', 0, error)
  }
  if (!response.ok) throw await templateResponseError(response)
  return response.blob()
}

export function listAdminContests(params: AdminContestListParams = {}, options: RequestControl = {}): Promise<Page<AdminContest>> {
  return request<Page<AdminContest>>('/admin/contests', {
    ...options,
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      status: params.status,
      publicationStatus: params.publicationStatus,
    },
  })
}

export function createAdminContest(data: AdminContestWrite): Promise<AdminContest> {
  return request<AdminContest>('/admin/contests', { method: 'POST', json: data })
}

export function updateAdminContest(contestId: number, data: AdminContestWrite): Promise<AdminContest> {
  return request<AdminContest>(`/admin/contests/${contestId}`, { method: 'PUT', json: data })
}

function changeAdminContestStatus(contestId: number, action: 'publish' | 'cancel' | 'archive'): Promise<AdminContest> {
  return request<AdminContest>(`/admin/contests/${contestId}/${action}`, { method: 'POST' })
}

export function publishAdminContest(contestId: number): Promise<AdminContest> {
  return changeAdminContestStatus(contestId, 'publish')
}

export function cancelAdminContest(contestId: number): Promise<AdminContest> {
  return changeAdminContestStatus(contestId, 'cancel')
}

export function archiveAdminContest(contestId: number): Promise<AdminContest> {
  return changeAdminContestStatus(contestId, 'archive')
}

export function listAdminContestParticipants(contestId: number): Promise<AdminContestParticipant[]> {
  return request<AdminContestParticipant[]>(`/admin/contests/${contestId}/participants`)
}

export function recomputeAdminContest(contestId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/admin/contests/${contestId}/recompute`, { method: 'POST', timeoutMs: 120_000 })
}

export function listAdminStudyPlans(
  params: AdminStudyPlanListParams = {},
  options: RequestControl = {},
): Promise<Page<AdminStudyPlanSummary>> {
  return request<Page<AdminStudyPlanSummary>>('/admin/study-plans', {
    ...options,
    query: {
      page: params.page,
      page_size: params.pageSize,
      keyword: params.keyword,
      status: params.status,
    },
  })
}

export function getAdminStudyPlan(planId: number): Promise<AdminStudyPlanDetail> {
  return request<AdminStudyPlanDetail>(`/admin/study-plans/${planId}`)
}

export function createAdminStudyPlan(data: AdminStudyPlanWrite): Promise<AdminStudyPlanDetail> {
  return request<AdminStudyPlanDetail>('/admin/study-plans', { method: 'POST', json: data })
}

export function updateAdminStudyPlan(planId: number, data: AdminStudyPlanWrite): Promise<AdminStudyPlanDetail> {
  return request<AdminStudyPlanDetail>(`/admin/study-plans/${planId}`, { method: 'PUT', json: data })
}

function changeAdminStudyPlanStatus(planId: number, action: 'publish' | 'archive'): Promise<AdminStudyPlanDetail> {
  return request<AdminStudyPlanDetail>(`/admin/study-plans/${planId}/${action}`, { method: 'POST' })
}

export function publishAdminStudyPlan(planId: number): Promise<AdminStudyPlanDetail> {
  return changeAdminStudyPlanStatus(planId, 'publish')
}

export function archiveAdminStudyPlan(planId: number): Promise<AdminStudyPlanDetail> {
  return changeAdminStudyPlanStatus(planId, 'archive')
}

export function listAdminJudgeWorkers(options: RequestControl = {}): Promise<JudgeWorker[]> {
  return request<JudgeWorker[]>('/admin/judge/workers', options)
}

export function updateAdminJudgeWorker(workerId: string, accepting: boolean): Promise<JudgeWorker> {
  return request<JudgeWorker>(`/admin/judge/workers/${encodeURIComponent(workerId)}`, {
    method: 'PATCH',
    json: { accepting },
  })
}

export function listAdminAbnormalJudgeTasks(options: RequestControl = {}): Promise<AdminAbnormalJudgeTask[]> {
  return request<AdminAbnormalJudgeTask[]>('/admin/judge/abnormal', options)
}

export function rejudgeAdminTask(taskId: string, reason: string): Promise<{ taskId: string }> {
  return request<{ taskId: string }>(`/admin/judge/tasks/${encodeURIComponent(taskId)}/rejudge`, {
    method: 'POST',
    json: { reason },
  })
}

export function batchRejudgeAdminTasks(taskIds: string[], reason: string): Promise<{ taskIds: string[]; count: number }> {
  return request<{ taskIds: string[]; count: number }>('/admin/judge/tasks/batch-rejudge', {
    method: 'POST',
    json: { taskIds, reason },
    timeoutMs: 120_000,
  })
}

export function getAdminJudgeSettings(options: RequestControl = {}): Promise<AdminJudgeSettings> {
  return request<AdminJudgeSettings>('/admin/judge/settings', options)
}

export function updateAdminJudgeSettings(data: AdminJudgeSettings): Promise<AdminJudgeSettings> {
  return request<AdminJudgeSettings>('/admin/judge/settings', { method: 'PUT', json: data })
}

export function isAdminRequestCancelled(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'ABORTED'
}

export function adminErrorMessage(error: unknown, fallback = '操作失败，请稍后重试'): string {
  return error instanceof ApiError && error.code !== 'ABORTED' ? error.message : fallback
}
