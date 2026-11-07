import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PLAN_SECTION,
  groupPlanProblems,
  normalizePositions,
  planAccent,
  planProgress,
  summaryProgress,
} from '../../src/utils/studyPlan'
import type { StudyPlanProblemEntry } from '../../src/types'

function entry(problemId: number, position: number, groupName: string | null, progress: StudyPlanProblemEntry['progress'] = 'untouched'): StudyPlanProblemEntry {
  return {
    problemId,
    position,
    groupName,
    progress,
    title: `题目 ${problemId}`,
    difficulty: '简单',
    tags: [],
  }
}

describe('study plan grouping', () => {
  it('groups consecutive rows by group name and keeps position order', () => {
    const sections = groupPlanProblems([
      entry(3, 3, '数组'),
      entry(1, 1, '基础'),
      entry(2, 2, '基础'),
    ])
    expect(sections.map(section => section.title)).toEqual(['基础', '数组'])
    expect(sections[0].problems.map(item => item.problemId)).toEqual([1, 2])
    expect(sections[1].problems.map(item => item.problemId)).toEqual([3])
  })

  it('puts ungrouped problems into the default section', () => {
    const sections = groupPlanProblems([entry(1, 1, null)])
    expect(sections).toHaveLength(1)
    expect(sections[0].title).toBe(DEFAULT_PLAN_SECTION)
  })

  it('splits non-consecutive rows with the same group name', () => {
    const sections = groupPlanProblems([
      entry(1, 1, 'A'),
      entry(2, 2, 'B'),
      entry(3, 3, 'A'),
    ])
    expect(sections.map(section => section.title)).toEqual(['A', 'B', 'A'])
  })
})

describe('study plan progress', () => {
  it('counts solved problems and rounds the percentage', () => {
    const progress = planProgress([
      entry(1, 1, null, 'solved'),
      entry(2, 2, null, 'attempted'),
      entry(3, 3, null, 'solved'),
    ])
    expect(progress).toEqual({ solved: 2, total: 3, percent: 67 })
  })

  it('handles an empty plan', () => {
    expect(planProgress([])).toEqual({ solved: 0, total: 0, percent: 0 })
  })

  it('derives summary progress from server counts', () => {
    expect(summaryProgress({ problemCount: 4, solvedCount: 1 })).toBe(25)
    expect(summaryProgress({ problemCount: 0, solvedCount: 0 })).toBe(0)
  })
})

describe('study plan editor helpers', () => {
  it('renumbers positions after reordering', () => {
    const rows = [{ position: 3 }, { position: 1 }, { position: 8 }]
    expect(normalizePositions(rows).map(row => row.position)).toEqual([1, 2, 3])
  })

  it('falls back to the blue accent for unknown values', () => {
    expect(planAccent('unknown').label).toBe('科技蓝')
  })
})
