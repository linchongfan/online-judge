export type Difficulty = '简单' | '中等' | '困难'
export type ProblemProgress = 'solved' | 'attempted' | 'untouched'
export type JudgeStatus = 'PENDING' | 'JUDGING' | 'AC' | 'WA' | 'TLE' | 'MLE' | 'RE' | 'CE' | 'SE'
export type ContestStatus = 'ongoing' | 'upcoming' | 'ended'
export type ContestPublicationStatus = 'draft' | 'published' | 'cancelled' | 'archived'
export type ProblemStatus = 'draft' | 'published' | 'archived'
export type Language = 'cpp' | 'c' | 'java' | 'python'
export type UserRole = 'user' | 'admin'
export type UserStatus = 'active' | 'disabled'
export type WorkerStatus = 'online' | 'busy' | 'offline'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
  pages: number
}

export interface MessageResponse {
  message: string
}

export interface UserProfile {
  id: number
  username: string
  nickname: string
  email: string
  school: string
  bio: string
  role: UserRole
  joinedAt: string
}

export interface RegisterRequest {
  username: string
  nickname: string
  email: string
  password: string
}

export interface LoginRequest {
  account: string
  password: string
  remember?: boolean
}

export interface TokenResponse {
  accessToken: string
  tokenType: string
  expiresIn: number
  user: UserProfile
}

export interface ForgotCodeRequest {
  email: string
}

export interface ForgotResetRequest {
  email: string
  code: string
  newPassword: string
}

export interface ProfileUpdateRequest {
  nickname: string
  school: string
  bio: string
}

export interface PasswordChangeRequest {
  oldPassword: string
  newPassword: string
}

export interface Sample {
  input: string
  output: string
  explanation: string | null
}

export interface ProblemListItem {
  id: number
  title: string
  difficulty: Difficulty
  tags: string[]
  acceptance: number
  submissionCount: number
  solvedCount: number
  progress: ProblemProgress
}

export interface ProblemDetail extends ProblemListItem {
  description: string[]
  inputDescription: string
  outputDescription: string
  constraints: string[]
  samples: Sample[]
  timeLimitMs: number
  memoryLimitMb: number
  updatedAt: string
}

export type Problem = ProblemDetail

export interface SolutionCode {
  language: Language
  code: string
}

export interface Solution {
  title: string
  summary: string
  steps: string[]
  time: string
  space: string
  codes: SolutionCode[]
}

export interface Tag {
  id: number
  name: string
  problemCount: number
}

export interface SubmissionCreate {
  problemId: number
  contestId?: number | null
  language: Language
  source: string
  idempotencyKey: string
}

export interface SampleRunCreate {
  language: Language
  source: string
  sampleId?: number | null
  contestId?: number | null
  idempotencyKey: string
}

export interface Submission {
  id: string
  problemId: number
  problemTitle: string
  contestId: number | null
  contestTitle: string | null
  language: Language
  status: JudgeStatus
  runtimeMs: number | null
  memoryKb: number | null
  diagnostic: string | null
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  isSampleRun: boolean
}

export interface SubmissionAccepted {
  id: string
  status: JudgeStatus
  pollAfterMs: number
}

export interface SubmissionSource {
  id: string
  language: Language
  source: string
}

export interface ContestProblem {
  label: string
  problemId: number
  title: string
  difficulty: Difficulty
  solved: number
  attempts: number
  userStatus: 'AC' | 'WA' | 'untouched'
}

export interface Contest {
  id: number
  title: string
  subtitle: string
  description: string
  organizer: string
  startTime: string
  endTime: string
  durationSeconds: number
  status: ContestStatus
  publicationStatus: ContestPublicationStatus
  participants: number
  expectedParticipants: number | null
  registered: boolean
  accent: string
  serverTime: string
  problems: ContestProblem[]
}

export interface ContestProblems {
  serverTime: string
  items: ContestProblem[]
}

export interface RankProblemResult {
  status: 'AC' | 'WA' | 'none'
  timeSeconds: number | null
  attempts: number
  wrongAttempts: number
}

export interface RankEntry {
  rank: number
  username: string
  nickname: string
  solved: number
  penaltySeconds: number
  results: Record<string, RankProblemResult>
}

export interface Ranking {
  contestId: number
  serverTime: string
  entries: RankEntry[]
}

export interface ContestResult {
  contestId: number
  solvedCount: number
  penaltySeconds: number
  rank: number | null
}

export interface DifficultyProgress {
  difficulty: Difficulty
  total: number
  solved: number
}

export interface UserStats {
  submissionCount: number
  acceptedCount: number
  solvedCount: number
  acceptance: number
  streak: number
  ranking: number
  difficultyProgress: DifficultyProgress[]
}

export interface UserContestRecord {
  contestId: number
  registeredAt: string
  solvedCount: number
  penaltySeconds: number
  rank: number | null
}

export interface AdminUser {
  id: number
  username: string
  nickname: string
  email: string
  role: UserRole
  status: UserStatus
  solved: number
  lastActive: string | null
}

export interface JudgeWorker {
  id: string
  host: string
  status: WorkerStatus
  accepting: boolean
  activeTasks: number
  completed: number
  cpu: number | null
  memory: number | null
  heartbeat: string | null
}

export interface AdminDashboard {
  userCount: number
  problemCount: number
  submissionCount: number
  contestCount: number
  pendingCount: number
  acceptedCount: number
  acceptance: number
  activeWorkerCount: number
  abnormalTaskCount: number
}

export interface AdminDashboardTrend {
  date: string
  submissions: number
}

export interface AdminStatusDistribution {
  status: JudgeStatus
  count: number
}

export interface AdminSolution {
  title: string
  summary: string
  steps: string[]
  time: string
  space: string
  enabled: boolean
  codes: SolutionCode[]
}

export interface AdminProblem {
  id: number
  title: string
  difficulty: Difficulty
  tags: string[]
  status: ProblemStatus
  timeLimitMs: number
  memoryLimitMb: number
  testDataVersion: string | null
  testCaseCount: number
  testDataSize: number
  acceptance: number
  submissionCount: number
  solutionLanguageCount: number
  updatedAt: string
}

export interface AdminProblemDetail extends AdminProblem {
  description: string[]
  inputDescription: string
  outputDescription: string
  constraints: string[]
  samples: Sample[]
  solvedCount: number
  progress: ProblemProgress
  solution: AdminSolution | null
}

export interface AdminProblemWrite {
  id?: number
  title: string
  difficulty: Difficulty
  tags: string[]
  description: string[]
  inputDescription: string
  outputDescription: string
  constraints: string[]
  timeLimitMs: number
  memoryLimitMb: number
  solution: {
    title: string
    summary: string
    steps: string[]
    timeComplexity: string
    spaceComplexity: string
    enabled: boolean
    codes: SolutionCode[]
  } | null
}

export interface AdminTestDataValidationError {
  code: string
  path: string
  message: string
}

export interface AdminTestDataVersion {
  id: string
  version: number
  status: 'uploading' | 'uploaded' | 'validating' | 'valid' | 'invalid'
  isCurrent: boolean
  filename: string
  compressedSize: number
  uncompressedSize: number
  testCaseCount: number
  sampleCount: number
  validationErrors: AdminTestDataValidationError[]
  createdAt: string
}

export interface AdminTestDataUploadResult {
  id: string
  status: 'valid'
  testCaseCount: number
  sampleCount: number
}

export interface AdminContest extends Contest {
  expectedParticipants: number | null
}

export interface AdminContestProblemInput {
  problemId: number
  label: string
  position: number
}

export interface AdminContestWrite {
  title: string
  subtitle: string
  description: string
  organizer: string
  startTime: string
  endTime: string
  accent: string
  expectedParticipants: number | null
  problems: AdminContestProblemInput[]
}

export interface AdminContestParticipant {
  id: number
  username: string
  nickname: string
  registeredAt: string
}

export interface AdminAbnormalJudgeTask {
  taskId: string
  submissionId: string
  problemId: number
  problemTitle: string
  username: string
  language: Language
  workerId: string | null
  judgeStatus: JudgeStatus
  createdAt: string
  finishedAt: string | null
  reason: string | null
  attempt: number
}

export interface AdminJudgeSettings {
  submissionsEnabled: boolean
  globalQueueLimit: number
}
