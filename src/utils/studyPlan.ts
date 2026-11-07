import type { StudyPlanAccent, StudyPlanProblemEntry, StudyPlanSummary } from '../types'

export const DEFAULT_PLAN_SECTION = '计划题目'

export interface StudyPlanSection {
  title: string
  problems: StudyPlanProblemEntry[]
}

export const PLAN_ACCENTS: Record<StudyPlanAccent, { label: string; from: string; to: string }> = {
  blue: { label: '科技蓝', from: '#1f5fd6', to: '#0b3c96' },
  green: { label: '成长绿', from: '#1f9d74', to: '#0d5b49' },
  purple: { label: '灵感紫', from: '#7b5bd6', to: '#43308f' },
  orange: { label: '活力橙', from: '#e58a2f', to: '#a04c16' },
  rose: { label: '进阶玫', from: '#d85678', to: '#8d2443' },
  teal: { label: '沉稳青', from: '#17a2b8', to: '#0b6174' },
}

export function planAccent(value: string): { label: string; from: string; to: string } {
  return PLAN_ACCENTS[value as StudyPlanAccent] ?? PLAN_ACCENTS.blue
}

export function groupPlanProblems(problems: StudyPlanProblemEntry[]): StudyPlanSection[] {
  const sections: StudyPlanSection[] = []
  for (const problem of [...problems].sort((a, b) => a.position - b.position)) {
    const title = problem.groupName?.trim() || DEFAULT_PLAN_SECTION
    const last = sections[sections.length - 1]
    if (last && last.title === title) last.problems.push(problem)
    else sections.push({ title, problems: [problem] })
  }
  return sections
}

export function planProgress(problems: StudyPlanProblemEntry[]): { solved: number; total: number; percent: number } {
  const total = problems.length
  const solved = problems.filter(item => item.progress === 'solved').length
  return { solved, total, percent: total ? Math.round(solved / total * 100) : 0 }
}

export function summaryProgress(plan: Pick<StudyPlanSummary, 'problemCount' | 'solvedCount'>): number {
  return plan.problemCount ? Math.round(plan.solvedCount / plan.problemCount * 100) : 0
}

export function normalizePositions<T extends { position: number }>(rows: T[]): T[] {
  rows.forEach((row, index) => { row.position = index + 1 })
  return rows
}
