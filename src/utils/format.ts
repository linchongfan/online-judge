import type { ContestStatus, Difficulty, JudgeStatus } from '../types'

export const judgeStatusMap: Record<JudgeStatus, { label: string; tone: string }> = {
  PENDING: { label: '等待判题', tone: 'pending' },
  JUDGING: { label: '正在判题', tone: 'judging' },
  AC: { label: '通过', tone: 'success' },
  WA: { label: '答案错误', tone: 'danger' },
  TLE: { label: '超出时间限制', tone: 'warning' },
  MLE: { label: '超出内存限制', tone: 'warning' },
  RE: { label: '运行时错误', tone: 'danger' },
  CE: { label: '编译错误', tone: 'danger' },
  SE: { label: '系统异常', tone: 'neutral' },
}

export const contestStatusMap: Record<ContestStatus, { label: string; tone: string }> = {
  ongoing: { label: '进行中', tone: 'success' },
  upcoming: { label: '即将开始', tone: 'primary' },
  ended: { label: '已结束', tone: 'neutral' },
}

export const difficultyTone: Record<Difficulty, string> = {
  简单: 'easy',
  中等: 'medium',
  困难: 'hard',
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function parseServerDate(value: string | number | Date): Date {
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value)
  // SQLAlchemy columns are stored as UTC but serialized without a timezone.
  // Without this suffix, browsers interpret them as local time and countdowns
  // can differ from serverTime by the host's UTC offset.
  const normalized = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value)
    ? `${value}Z`
    : value
  return new Date(normalized)
}

function validDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null
  const date = parseServerDate(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDate(value: string | number | Date | null | undefined): string {
  const date = validDate(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = validDate(value)
  if (!date) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function formatRuntimeMs(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value < 1_000) return `${Math.max(0, Math.round(value))} ms`
  return `${(value / 1_000).toFixed(value < 10_000 ? 2 : 1)} s`
}

export function formatMemoryKb(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const kb = Math.max(0, value)
  if (kb < 1_024) return `${Math.round(kb)} KB`
  if (kb < 1_048_576) return `${(kb / 1_024).toFixed(1)} MB`
  return `${(kb / 1_048_576).toFixed(2)} GB`
}

export function formatDurationSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const total = Math.max(0, Math.floor(value))
  const days = Math.floor(total / 86_400)
  const hours = Math.floor((total % 86_400) / 3_600)
  const minutes = Math.floor((total % 3_600) / 60)
  const seconds = total % 60
  if (days) return `${days}天 ${hours}小时 ${minutes}分`
  if (hours) return `${hours}小时 ${minutes}分${seconds ? ` ${seconds}秒` : ''}`
  if (minutes) return `${minutes}分${seconds ? ` ${seconds}秒` : ''}`
  return `${seconds}秒`
}

export function formatPenaltySeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${formatNumber(Math.floor(Math.max(0, value) / 60))} 分钟`
}
