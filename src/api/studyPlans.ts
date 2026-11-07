import { request } from './client'
import type { MessageResponse, StudyPlanDetail, StudyPlanSummary } from '../types'

export function listStudyPlans(): Promise<StudyPlanSummary[]> {
  return request<StudyPlanSummary[]>('/study-plans')
}

export function getStudyPlan(planId: number): Promise<StudyPlanDetail> {
  return request<StudyPlanDetail>(`/study-plans/${planId}`)
}

export function joinStudyPlan(planId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/study-plans/${planId}/enrollment`, { method: 'PUT' })
}

export function leaveStudyPlan(planId: number): Promise<MessageResponse> {
  return request<MessageResponse>(`/study-plans/${planId}/enrollment`, { method: 'DELETE' })
}

export const studyPlansApi = { listStudyPlans, getStudyPlan, joinStudyPlan, leaveStudyPlan }
