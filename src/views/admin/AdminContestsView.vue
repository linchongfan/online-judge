<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import DifficultyTag from '../../components/DifficultyTag.vue'
import {
  adminErrorMessage,
  archiveAdminContest,
  cancelAdminContest,
  createAdminContest,
  isAdminRequestCancelled,
  listAdminContestParticipants,
  listAdminContests,
  listAdminProblems,
  publishAdminContest,
  recomputeAdminContest,
  updateAdminContest,
} from '../../api/admin'
import type {
  AdminContest,
  AdminContestParticipant,
  AdminProblem,
  ContestPublicationStatus,
  ContestStatus,
  Difficulty,
} from '../../types'
import { formatDateTime, formatDurationSeconds, formatNumber } from '../../utils/format'

interface ContestProblemForm {
  problemId: number | null
  label: string
  position: number
}
interface ContestForm {
  title: string
  subtitle: string
  description: string
  organizer: string
  timeRange: string[]
  expectedParticipants: number | null
  accent: string
  problems: ContestProblemForm[]
}
type ProblemOption = Pick<AdminProblem, 'id' | 'title' | 'difficulty'>

const lifecycleMap: Record<ContestStatus, { label: string; tone: string }> = {
  ongoing: { label: '进行中', tone: 'success' },
  upcoming: { label: '即将开始', tone: 'primary' },
  ended: { label: '已结束', tone: 'neutral' },
}
const publicationMap: Record<ContestPublicationStatus, { label: string; tone: string }> = {
  draft: { label: '未发布', tone: 'neutral' },
  published: { label: '已发布', tone: 'success' },
  cancelled: { label: '已取消', tone: 'danger' },
  archived: { label: '已归档', tone: 'warning' },
}

const rows = ref<AdminContest[]>([])
const keyword = ref('')
const statusFilter = ref<'all' | ContestStatus>('all')
const publicationFilter = ref<'all' | ContestPublicationStatus>('all')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const saving = ref(false)
const pendingKeys = ref<Set<string>>(new Set())
const problemOptions = ref<ProblemOption[]>([])
const problemOptionsLoading = ref(false)
const problemOptionsError = ref('')
const participantsVisible = ref(false)
const participantsLoading = ref(false)
const participantsError = ref('')
const participantContest = ref<AdminContest | null>(null)
const participants = ref<AdminContestParticipant[]>([])
let listController: AbortController | null = null
let problemController: AbortController | null = null
let filterTimer: ReturnType<typeof setTimeout> | null = null
let problemTimer: ReturnType<typeof setTimeout> | null = null

function emptyForm(): ContestForm {
  return {
    title: '', subtitle: '', description: '', organizer: '新保研官方', timeRange: [],
    expectedParticipants: null, accent: '#1557d6', problems: [],
  }
}
const form = ref<ContestForm>(emptyForm())
const rules: FormRules<ContestForm> = {
  title: [{ required: true, message: '请输入竞赛名称', trigger: 'blur' }],
  description: [{ required: true, message: '请输入竞赛说明', trigger: 'blur' }],
  organizer: [{ required: true, message: '请输入主办方', trigger: 'blur' }],
  timeRange: [{ required: true, type: 'array', len: 2, message: '请选择开始和结束时间', trigger: 'change' }],
}

const hasFilters = computed(() => Boolean(keyword.value || statusFilter.value !== 'all' || publicationFilter.value !== 'all'))
const ongoingCount = computed(() => rows.value.filter(contest => contest.status === 'ongoing').length)
const upcomingCount = computed(() => rows.value.filter(contest => contest.status === 'upcoming').length)
const draftCount = computed(() => rows.value.filter(contest => contest.publicationStatus === 'draft').length)
const durationPreview = computed(() => {
  const [start, end] = form.value.timeRange
  if (!start || !end) return '选择时间后自动计算'
  const seconds = Math.round((Date.parse(end) - Date.parse(start)) / 1000)
  if (!Number.isFinite(seconds) || seconds <= 0) return '结束时间需晚于开始时间'
  return formatDurationSeconds(seconds)
})

function setPending(key: string, pending: boolean) {
  const next = new Set(pendingKeys.value)
  if (pending) next.add(key)
  else next.delete(key)
  pendingKeys.value = next
}
function actionKey(contestId: number, action: string) { return `${contestId}:${action}` }

async function loadContests() {
  listController?.abort()
  const current = new AbortController()
  listController = current
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listAdminContests({
      page: page.value,
      pageSize: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      publicationStatus: publicationFilter.value === 'all' ? undefined : publicationFilter.value,
    }, { signal: current.signal })
    if (current.signal.aborted) return
    rows.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (!result.items.length && result.total > 0 && result.pages > 0 && page.value > result.pages) {
      page.value = result.pages
      await loadContests()
    }
  } catch (error) {
    if (!isAdminRequestCancelled(error)) {
      rows.value = []
      errorMessage.value = adminErrorMessage(error, '竞赛列表加载失败')
    }
  } finally {
    if (listController === current) {
      loading.value = false
      listController = null
    }
  }
}
function scheduleFilterLoad() {
  if (filterTimer) clearTimeout(filterTimer)
  filterTimer = setTimeout(() => { page.value = 1; void loadContests() }, 350)
}
function resetFilters() {
  const hadFilters = hasFilters.value
  keyword.value = ''
  statusFilter.value = 'all'
  publicationFilter.value = 'all'
  if (!hadFilters) { page.value = 1; void loadContests() }
}
function changePage(value: number) { page.value = value; void loadContests() }
function changePageSize(value: number) { pageSize.value = value; page.value = 1; void loadContests() }

function mergeProblemOptions(items: ProblemOption[]) {
  const map = new Map(problemOptions.value.map(item => [item.id, item]))
  items.forEach(item => map.set(item.id, item))
  problemOptions.value = Array.from(map.values()).sort((a, b) => a.id - b.id)
}
async function searchProblems(query: string) {
  problemController?.abort()
  const current = new AbortController()
  problemController = current
  problemOptionsLoading.value = true
  problemOptionsError.value = ''
  try {
    const result = await listAdminProblems({ page: 1, pageSize: 100, keyword: query.trim() || undefined, status: 'published' }, { signal: current.signal })
    if (!current.signal.aborted) mergeProblemOptions(result.items)
  } catch (error) {
    if (!isAdminRequestCancelled(error)) problemOptionsError.value = adminErrorMessage(error, '可选题目加载失败')
  } finally {
    if (problemController === current) {
      problemOptionsLoading.value = false
      problemController = null
    }
  }
}
function scheduleProblemSearch(query: string) {
  if (problemTimer) clearTimeout(problemTimer)
  problemTimer = setTimeout(() => void searchProblems(query), 300)
}
function availableProblemsFor(entry: ContestProblemForm): ProblemOption[] {
  const selected = new Set(form.value.problems.filter(item => item !== entry && item.problemId !== null).map(item => item.problemId))
  return problemOptions.value.filter(item => !selected.has(item.id))
}
function nextProblemLabel(): string {
  const used = new Set(form.value.problems.map(item => item.label))
  for (let index = 0; index < 52; index += 1) {
    let value = index
    let label = ''
    do {
      label = String.fromCharCode(65 + value % 26) + label
      value = Math.floor(value / 26) - 1
    } while (value >= 0)
    if (!used.has(label)) return label
  }
  return ''
}
function addProblem() {
  if (form.value.problems.length >= 52) return
  form.value.problems.push({ problemId: null, label: nextProblemLabel(), position: form.value.problems.length + 1 })
}
function removeProblem(index: number) {
  form.value.problems.splice(index, 1)
  normalizePositions()
}
function moveProblem(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= form.value.problems.length) return
  const [item] = form.value.problems.splice(index, 1)
  form.value.problems.splice(target, 0, item)
  normalizePositions()
}
function normalizePositions() {
  form.value.problems.forEach((item, index) => { item.position = index + 1 })
}
function problemTitle(problemId: number | null): string {
  return problemOptions.value.find(item => item.id === problemId)?.title ?? '请选择题目'
}
function problemDifficulty(problemId: number | null): Difficulty | null {
  return problemOptions.value.find(item => item.id === problemId)?.difficulty ?? null
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  problemOptionsError.value = ''
  dialogVisible.value = true
  void searchProblems('')
}
function openEdit(contest: AdminContest) {
  if (contest.status !== 'upcoming') {
    ElMessage.info('已开始或结束的竞赛不能直接编辑，可使用成绩重算或归档')
    return
  }
  editingId.value = contest.id
  mergeProblemOptions(contest.problems.map(problem => ({ id: problem.problemId, title: problem.title, difficulty: problem.difficulty })))
  form.value = {
    title: contest.title,
    subtitle: contest.subtitle,
    description: contest.description,
    organizer: contest.organizer,
    timeRange: [contest.startTime, contest.endTime],
    expectedParticipants: contest.expectedParticipants,
    accent: contest.accent,
    problems: contest.problems.map((problem, index) => ({ problemId: problem.problemId, label: problem.label, position: index + 1 })),
  }
  problemOptionsError.value = ''
  dialogVisible.value = true
  void searchProblems('')
}
function validateProblems(): boolean {
  if (form.value.problems.some(item => item.problemId === null)) {
    ElMessage.warning('请为每一行赛题选择题目，或删除空行')
    return false
  }
  const ids = form.value.problems.map(item => item.problemId)
  if (new Set(ids).size !== ids.length) {
    ElMessage.warning('竞赛不能重复包含同一道题')
    return false
  }
  const labels = form.value.problems.map(item => item.label.trim().toUpperCase())
  if (labels.some(label => !/^[A-Z][A-Z0-9]{0,7}$/.test(label))) {
    ElMessage.warning('赛题标签需以字母开头，仅含字母或数字，最长 8 位')
    return false
  }
  if (new Set(labels).size !== labels.length) {
    ElMessage.warning('赛题标签不能重复')
    return false
  }
  return true
}
async function saveContest() {
  if (!formRef.value || saving.value) return
  try { await formRef.value.validate() } catch { ElMessage.warning('请完善必填信息后再保存'); return }
  const [startTime, endTime] = form.value.timeRange
  if (!startTime || !endTime || Date.parse(endTime) <= Date.parse(startTime)) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return
  }
  if (!validateProblems()) return
  saving.value = true
  const current = form.value
  const payload = {
    title: current.title.trim(), subtitle: current.subtitle.trim(), description: current.description.trim(),
    organizer: current.organizer.trim(), startTime, endTime, accent: current.accent,
    expectedParticipants: current.expectedParticipants,
    problems: current.problems.map(item => ({ problemId: item.problemId as number, label: item.label.trim().toUpperCase(), position: item.position })),
  }
  try {
    const result = editingId.value === null ? await createAdminContest(payload) : await updateAdminContest(editingId.value, payload)
    ElMessage.success(editingId.value === null ? `竞赛 #${result.id} 已创建为未发布草稿` : `竞赛「${result.title}」已保存`)
    dialogVisible.value = false
    await loadContests()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '竞赛保存失败'))
  } finally {
    saving.value = false
  }
}

async function contestAction(contest: AdminContest, action: 'publish' | 'cancel' | 'archive') {
  const key = actionKey(contest.id, action)
  if (pendingKeys.value.has(key)) return
  const messages = {
    publish: [`发布后，「${contest.title}」将显示在用户端竞赛列表中。`, '确认发布竞赛', '确认发布'],
    cancel: [`取消后，用户将无法继续报名或参加「${contest.title}」。`, '确认取消竞赛', '确认取消'],
    archive: [`归档后，「${contest.title}」将保留历史数据并退出正常赛事流程。`, '确认归档竞赛', '确认归档'],
  } as const
  try {
    await ElMessageBox.confirm(messages[action][0], messages[action][1], { confirmButtonText: messages[action][2], cancelButtonText: '返回', type: 'warning' })
  } catch { return }
  setPending(key, true)
  const title = contest.title
  try {
    if (action === 'publish') await publishAdminContest(contest.id)
    else if (action === 'cancel') await cancelAdminContest(contest.id)
    else await archiveAdminContest(contest.id)
    ElMessage.success(action === 'publish' ? `「${title}」发布成功` : action === 'cancel' ? `「${title}」已取消` : `「${title}」已归档`)
    await loadContests()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '竞赛状态更新失败'))
  } finally {
    setPending(key, false)
  }
}

async function openParticipants(contest: AdminContest) {
  participantContest.value = contest
  participants.value = []
  participantsError.value = ''
  participantsVisible.value = true
  participantsLoading.value = true
  try {
    participants.value = await listAdminContestParticipants(contest.id)
  } catch (error) {
    participantsError.value = adminErrorMessage(error, '参赛名单加载失败')
  } finally {
    participantsLoading.value = false
  }
}
async function recomputeResults(contest: AdminContest) {
  const key = actionKey(contest.id, 'recompute')
  if (pendingKeys.value.has(key)) return
  try {
    await ElMessageBox.confirm(`将从真实提交明细重新计算「${contest.title}」的解题数、罚时和排名。`, '确认重算成绩', { confirmButtonText: '开始重算', cancelButtonText: '取消', type: 'warning' })
  } catch { return }
  setPending(key, true)
  try {
    const response = await recomputeAdminContest(contest.id)
    ElMessage.success(response.message)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '竞赛成绩重算失败'))
  } finally {
    setPending(key, false)
  }
}

watch([keyword, statusFilter, publicationFilter], scheduleFilterLoad)
onMounted(() => void loadContests())
onUnmounted(() => {
  if (filterTimer) clearTimeout(filterTimer)
  if (problemTimer) clearTimeout(problemTimer)
  listController?.abort()
  problemController?.abort()
})
</script>

<template>
  <div class="contests-page">
    <div class="page-heading"><div><h1>竞赛管理</h1><p>安排赛程、赛题与赛事信息，统一管理发布、名单和成绩。</p></div><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建竞赛</el-button></div>

    <section class="contest-overview">
      <div class="overview-item"><span class="overview-icon live"><el-icon><VideoPlay /></el-icon></span><div><strong>{{ ongoingCount }}</strong><span>本页正在进行</span></div></div>
      <div class="overview-item"><span class="overview-icon upcoming"><el-icon><Calendar /></el-icon></span><div><strong>{{ upcomingCount }}</strong><span>本页等待开赛</span></div></div>
      <div class="overview-item"><span class="overview-icon draft"><el-icon><EditPen /></el-icon></span><div><strong>{{ draftCount }}</strong><span>本页未发布草稿</span></div></div>
      <div class="schedule-note"><el-icon><Clock /></el-icon><span>赛事时间以服务端返回为准</span></div>
    </section>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert"><el-button size="small" @click="loadContests">重新加载</el-button></el-alert>
    <section class="surface-card table-card">
      <div class="section-heading table-heading"><div><h2>全部竞赛</h2><p>共 {{ formatNumber(total) }} 场赛事，按开始时间倒序展示</p></div><span class="prototype-note">真实发布与赛程状态</span></div>
      <div class="filter-bar">
        <el-input v-model="keyword" class="search-input" clearable placeholder="搜索名称、副标题或主办方"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="statusFilter" class="status-select" aria-label="筛选赛程状态"><el-option label="全部赛程" value="all" /><el-option label="进行中" value="ongoing" /><el-option label="即将开始" value="upcoming" /><el-option label="已结束" value="ended" /></el-select>
        <el-select v-model="publicationFilter" class="status-select" aria-label="筛选发布状态"><el-option label="全部发布状态" value="all" /><el-option label="未发布" value="draft" /><el-option label="已发布" value="published" /><el-option label="已取消" value="cancelled" /><el-option label="已归档" value="archived" /></el-select>
        <el-button v-if="hasFilters" text @click="resetFilters"><el-icon><RefreshLeft /></el-icon>重置</el-button><span class="filter-result">{{ formatNumber(total) }} 场服务端竞赛</span>
      </div>
      <div class="table-scroll">
        <el-table v-loading="loading" :data="rows" row-key="id" class="admin-table">
          <el-table-column label="竞赛" min-width="250"><template #default="{ row }"><div class="contest-cell"><span class="contest-mark" :class="row.status" :style="{ color: row.accent }"><el-icon><Trophy /></el-icon></span><div><strong>{{ row.title }}</strong><span>#{{ row.id }} / {{ row.organizer }}</span></div></div></template></el-table-column>
          <el-table-column label="赛程状态" width="105"><template #default="{ row }"><span class="status-pill" :class="lifecycleMap[row.status as ContestStatus].tone"><i />{{ lifecycleMap[row.status as ContestStatus].label }}</span></template></el-table-column>
          <el-table-column label="发布状态" width="100"><template #default="{ row }"><span class="status-pill" :class="publicationMap[row.publicationStatus as ContestPublicationStatus].tone"><i />{{ publicationMap[row.publicationStatus as ContestPublicationStatus].label }}</span></template></el-table-column>
          <el-table-column label="赛程时间" width="190"><template #default="{ row }"><div class="time-cell"><span>{{ formatDateTime(row.startTime) }}</span><span>至 {{ formatDateTime(row.endTime) }}</span></div></template></el-table-column>
          <el-table-column label="时长" width="130"><template #default="{ row }">{{ formatDurationSeconds(row.durationSeconds) }}</template></el-table-column>
          <el-table-column label="赛题" min-width="150"><template #default="{ row }"><div class="problem-cell"><span>{{ row.problems.length }} 道题</span><div><el-tooltip v-for="problem in row.problems.slice(0, 4)" :key="problem.label" :content="`${problem.label} · ${problem.title}`" placement="top"><span class="problem-label">{{ problem.label }}</span></el-tooltip><span v-if="!row.problems.length" class="muted">尚未配置</span></div></div></template></el-table-column>
          <el-table-column label="实际 / 预计" width="125" align="right"><template #default="{ row }"><strong>{{ formatNumber(row.participants) }}</strong><span class="muted"> / {{ row.expectedParticipants === null ? '未设置' : formatNumber(row.expectedParticipants) }}</span></template></el-table-column>
          <el-table-column label="操作" width="370" fixed="right">
            <template #default="{ row }"><div class="row-actions"><el-tooltip :disabled="row.status === 'upcoming'" content="已开始或结束的竞赛不可直接编辑" placement="top"><span><el-button text type="primary" :disabled="row.status !== 'upcoming'" @click="openEdit(row)">编辑</el-button></span></el-tooltip><el-button v-if="row.publicationStatus !== 'published'" text type="success" :loading="pendingKeys.has(actionKey(row.id, 'publish'))" @click="contestAction(row, 'publish')">发布</el-button><el-button text type="primary" @click="openParticipants(row)">名单</el-button><el-button text type="primary" :loading="pendingKeys.has(actionKey(row.id, 'recompute'))" @click="recomputeResults(row)">重算</el-button><el-button v-if="row.publicationStatus === 'published'" text type="danger" :loading="pendingKeys.has(actionKey(row.id, 'cancel'))" @click="contestAction(row, 'cancel')">取消</el-button><el-button v-if="row.publicationStatus !== 'archived'" text type="warning" :loading="pendingKeys.has(actionKey(row.id, 'archive'))" @click="contestAction(row, 'archive')">归档</el-button></div></template>
          </el-table-column>
          <template #empty><div class="empty-state"><div class="empty-icon"><el-icon :size="26"><Trophy /></el-icon></div><h3>{{ hasFilters ? '没有匹配的竞赛' : '暂无竞赛' }}</h3><p>{{ hasFilters ? '尝试更换关键词或重置筛选。' : '新建竞赛、配置赛题后即可发布。' }}</p><el-button v-if="hasFilters" type="primary" plain @click="resetFilters">清除筛选</el-button></div></template>
        </el-table>
      </div>
      <div class="pagination-bar"><el-pagination background :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" :disabled="loading" @current-change="changePage" @size-change="changePageSize" /><span v-if="pages">共 {{ pages }} 页</span></div>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新建竞赛' : `编辑竞赛 #${editingId}`" width="min(860px, calc(100vw - 32px))" top="4vh" @closed="formRef?.clearValidate()">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="contest-form" :disabled="saving">
        <el-form-item label="竞赛名称" prop="title"><el-input v-model="form.title" maxlength="200" show-word-limit placeholder="例如：新保研周赛 · 第 43 场" /></el-form-item>
        <el-form-item label="赛事副标题"><el-input v-model="form.subtitle" maxlength="255" placeholder="一句简短的赛事介绍" /></el-form-item>
        <el-form-item label="开始与结束时间" prop="timeRange"><el-date-picker v-model="form.timeRange" type="datetimerange" range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
        <div class="duration-preview"><el-icon><Timer /></el-icon><span>竞赛时长</span><strong>{{ durationPreview }}</strong></div>
        <div class="form-grid"><el-form-item label="主办方" prop="organizer"><el-input v-model="form.organizer" maxlength="100" /></el-form-item><el-form-item label="预计参赛人数"><el-input-number v-model="form.expectedParticipants" :min="0" :max="100000000" :step="100" placeholder="不设置" /></el-form-item></div>
        <el-form-item label="主题色（accent）"><div class="accent-field"><el-color-picker v-model="form.accent" /><el-input v-model="form.accent" maxlength="20" placeholder="#1557d6" /></div></el-form-item>
        <el-form-item label="竞赛说明" prop="description"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="50000" placeholder="介绍竞赛规则、面向人群和注意事项" /></el-form-item>
        <div class="contest-problems-editor">
          <div class="problem-editor-heading"><div><h3>赛题配置</h3><p>从已发布题库选择题，设置标签并调整出场顺序。</p></div><el-button type="primary" plain :disabled="form.problems.length >= 52" @click="addProblem"><el-icon><Plus /></el-icon>新增题目</el-button></div>
          <el-alert v-if="problemOptionsError" :title="problemOptionsError" type="error" :closable="false" show-icon role="alert" />
          <div v-if="!form.problems.length" class="problem-editor-empty"><el-icon><DocumentAdd /></el-icon><span>尚未配置赛题，发布前至少添加一道。</span></div>
          <div v-for="(problem, index) in form.problems" :key="`${index}-${problem.position}`" class="problem-editor-row">
            <span class="position-number mono">{{ index + 1 }}</span>
            <el-select v-model="problem.problemId" class="problem-selector" filterable remote clearable :remote-method="scheduleProblemSearch" :loading="problemOptionsLoading" placeholder="搜索并选择题目">
              <el-option v-for="option in availableProblemsFor(problem)" :key="option.id" :label="`#${option.id} ${option.title}`" :value="option.id"><span>#{{ option.id }} {{ option.title }}</span><DifficultyTag :difficulty="option.difficulty" /></el-option>
            </el-select>
            <el-input v-model="problem.label" class="label-input" maxlength="8" placeholder="标签 A" @input="problem.label = problem.label.toUpperCase()" />
            <div class="selected-problem-meta"><DifficultyTag v-if="problemDifficulty(problem.problemId)" :difficulty="problemDifficulty(problem.problemId)!" /><span v-else>未选择</span></div>
            <div class="sort-actions"><el-button circle size="small" aria-label="上移赛题" :disabled="index === 0" @click="moveProblem(index, -1)"><el-icon><ArrowUp /></el-icon></el-button><el-button circle size="small" aria-label="下移赛题" :disabled="index === form.problems.length - 1" @click="moveProblem(index, 1)"><el-icon><ArrowDown /></el-icon></el-button><el-button circle size="small" type="danger" plain aria-label="删除赛题" @click="removeProblem(index)"><el-icon><Delete /></el-icon></el-button></div>
            <div class="mobile-problem-title">{{ problemTitle(problem.problemId) }}</div>
          </div>
        </div>
        <div class="publish-tip"><el-icon><InfoFilled /></el-icon><span>保存仅更新赛事与赛题；新建赛事需在列表确认发布。开始后的赛事不可直接编辑。</span></div>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveContest"><el-icon v-if="!saving"><Check /></el-icon>{{ editingId === null ? '创建草稿' : '保存修改' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="participantsVisible" :title="`参赛名单${participantContest ? ` · ${participantContest.title}` : ''}`" width="min(680px, calc(100vw - 32px))">
      <el-alert v-if="participantsError" :title="participantsError" type="error" :closable="false" show-icon role="alert"><el-button size="small" @click="participantContest && openParticipants(participantContest)">重新加载</el-button></el-alert>
      <el-table v-loading="participantsLoading" :data="participants" row-key="id" max-height="440">
        <el-table-column label="用户" min-width="220"><template #default="{ row }"><div class="participant-cell"><strong>{{ row.nickname }}</strong><span class="mono">@{{ row.username }}</span></div></template></el-table-column>
        <el-table-column label="用户 ID" prop="id" width="100" align="right" />
        <el-table-column label="报名时间" width="210"><template #default="{ row }">{{ formatDateTime(row.registeredAt) }}</template></el-table-column>
        <template #empty><div class="empty-state"><h3>暂无有效报名</h3><p>真实报名用户将在此显示。</p></div></template>
      </el-table>
      <template #footer><span class="participant-total">共 {{ participants.length }} 名有效参赛用户</span><el-button @click="participantsVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.contests-page :deep(.page-heading) { margin-bottom: 22px; }
.contests-page :deep(.page-heading .el-button) { min-height: 36px; border-radius: 6px; padding-inline: 16px; }
.request-alert { margin-bottom: 16px; }
.contest-overview { display: flex; align-items: center; gap: 0; padding: 19px 22px; margin-bottom: 16px; border: 1px solid var(--border); border-radius: 8px; background: #fff; box-shadow: var(--shadow-sm); }
.overview-item { display: flex; align-items: center; gap: 12px; min-width: 175px; padding-right: 28px; margin-right: 28px; border-right: 1px solid var(--border); }
.overview-icon { width: 38px; height: 38px; border-radius: 7px; display: grid; place-items: center; font-size: 18px; }
.overview-icon.live { color: var(--success); background: #eaf7f1; }
.overview-icon.upcoming { color: var(--primary); background: var(--primary-soft); }
.overview-icon.draft { color: #5d7693; background: #edf2f7; }
.overview-item > div { display: flex; flex-direction: column; }
.overview-item strong { color: var(--text-strong); font-size: 23px; line-height: 1.2; }
.overview-item span:not(.overview-icon) { color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
.schedule-note { margin-left: auto; display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 11px; }
.schedule-note :deep(.el-icon) { color: var(--success); }
.table-card { overflow: hidden; border-radius: 8px; box-shadow: none; }
.table-heading { margin: 0; padding: 19px 20px; }
.table-heading h2 { font-size: 16px; font-weight: 700; }
.table-heading p { color: var(--text-secondary); }
.prototype-note::before { background: var(--success); }
.filter-bar { display: flex; align-items: center; gap: 10px; padding: 16px 20px; background: #f8fbff; border-block: 1px solid var(--border); }
.filter-bar :deep(.el-input__wrapper), .filter-bar :deep(.el-select__wrapper) { border-radius: 6px; background: #fff; }
.filter-bar :deep(.el-button) { border-radius: 6px; }
.search-input { width: 300px; }
.status-select { width: 145px; }
.filter-result { margin-left: auto; color: var(--text-secondary); font-size: 11px; }
.table-scroll { width: 100%; overflow-x: auto; }
.admin-table { width: 100%; min-width: 1620px; --el-table-header-bg-color: #f4f8fd; --el-table-row-hover-bg-color: #f5f8ff; --el-table-header-text-color: var(--text-secondary); }
.admin-table :deep(th.el-table__cell) { height: 44px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.admin-table :deep(td.el-table__cell) { padding: 13px 0; }
.contest-cell { display: flex; align-items: center; gap: 12px; }
.contest-mark { width: 36px; height: 40px; display: grid; place-items: center; color: var(--primary); background: var(--primary-soft); border: 1px solid #d8e6f8; border-radius: 6px; flex: none; }
.contest-cell > div { display: flex; flex-direction: column; gap: 5px; }
.contest-cell strong { color: var(--text-strong); font-size: 13px; font-weight: 600; }
.contest-cell span:not(.contest-mark) { color: var(--text-secondary); font-size: 10px; }
.status-pill { border-radius: 5px; padding: 4px 8px; }
.status-pill.success { color: var(--success); background: #eaf7f1; }
.status-pill.primary { color: var(--primary); background: var(--primary-soft); }
.status-pill.neutral { color: #687b91; background: #eef2f6; }
.status-pill.danger { color: var(--danger); background: #fff0f1; }
.status-pill.warning { color: #a86218; background: var(--accent-soft); }
.time-cell { display: flex; flex-direction: column; gap: 5px; color: var(--text-secondary); font-size: 10px; }
.problem-cell { display: flex; flex-direction: column; gap: 7px; }
.problem-cell > span { color: var(--text-secondary); font-size: 10px; }
.problem-cell > div { display: flex; align-items: center; gap: 5px; }
.problem-label { width: 22px; height: 22px; display: inline-grid; place-items: center; border: 1px solid #d8e6f8; border-radius: 4px; color: var(--primary); background: var(--primary-soft); font-size: 10px; font-weight: 600; cursor: default; }
.row-actions { display: flex; gap: 0; }
.row-actions :deep(.el-button) { border-radius: 5px; }
.pagination-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; border-top: 1px solid var(--border); overflow-x: auto; }
.pagination-bar > span { color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.contest-form :deep(.el-form-item) { margin-bottom: 20px; }
.contest-form :deep(.el-form-item__label) { color: var(--text-secondary); font-size: 12px; font-weight: 500; margin-bottom: 7px; }
.contest-form :deep(.el-date-editor) { width: 100%; }
.contest-form :deep(.el-input__wrapper), .contest-form :deep(.el-textarea__inner) { border-radius: 6px; }
.form-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; }
.form-grid :deep(.el-input-number) { width: 100%; }
.accent-field { display: flex; align-items: center; gap: 10px; width: 100%; }
.accent-field :deep(.el-input) { max-width: 180px; }
.duration-preview { display: flex; align-items: center; gap: 7px; padding: 11px 12px; margin: -4px 0 20px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-soft); color: var(--text-secondary); font-size: 11px; }
.duration-preview :deep(.el-icon) { color: var(--primary); }
.duration-preview strong { margin-left: auto; color: var(--primary); font-weight: 600; }
.contest-problems-editor { margin: 24px 0; padding-top: 20px; border-top: 1px solid var(--border); }
.problem-editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.problem-editor-heading h3 { margin: 0; color: var(--text-strong); font-size: 14px; }
.problem-editor-heading p { margin: 6px 0 0; color: var(--text-secondary); font-size: 11px; }
.problem-editor-empty { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 84px; border: 1px dashed var(--border); border-radius: 6px; color: var(--text-secondary); font-size: 11px; }
.problem-editor-row { display: grid; grid-template-columns: 28px minmax(220px, 1fr) 90px 90px 116px; align-items: center; gap: 8px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.position-number { color: var(--text-secondary); text-align: center; }
.label-input { width: 90px; }
.selected-problem-meta { color: var(--text-secondary); font-size: 10px; }
.sort-actions { display: flex; gap: 3px; }
.sort-actions :deep(.el-button + .el-button) { margin-left: 0; }
.problem-selector :deep(.difficulty) { float: right; }
.mobile-problem-title { display: none; }
.publish-tip { display: flex; align-items: flex-start; gap: 8px; padding: 12px; border: 1px solid #d8e6f8; border-radius: 6px; background: var(--primary-soft); color: #46688f; font-size: 11px; line-height: 1.6; }
.publish-tip .el-icon { flex: none; margin-top: 2px; color: var(--primary); }
.contests-page :deep(.el-dialog__footer .el-button) { border-radius: 6px; }
.empty-state .empty-icon { border-radius: 10px; color: #8da5c1; background: var(--primary-soft); }
.participant-cell { display: flex; flex-direction: column; gap: 5px; }
.participant-cell strong { color: var(--text-strong); }
.participant-cell span { color: var(--text-secondary); font-size: 10px; }
.participant-total { float: left; color: var(--text-secondary); font-size: 11px; line-height: 32px; }
@media (max-width: 1100px) {
  .schedule-note { display: none; }
  .overview-item:last-of-type { border-right: 0; margin-right: 0; }
  .filter-bar { flex-wrap: wrap; }
  .filter-result { margin-left: 0; }
}
@media (max-width: 760px) {
  .contest-overview { justify-content: space-between; padding: 16px; }
  .overview-item { min-width: 0; margin-right: 15px; padding-right: 15px; gap: 8px; }
  .overview-icon { width: 32px; height: 32px; }
  .search-input { width: 100%; }
  .problem-editor-row { grid-template-columns: 24px minmax(150px, 1fr) 80px 108px; }
  .selected-problem-meta { display: none; }
}
@media (max-width: 600px) {
  .overview-icon { display: none; }
  .overview-item { margin-right: 10px; padding-right: 10px; }
  .table-heading, .filter-bar { padding: 14px; }
  .table-heading .prototype-note { display: none; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
  .problem-editor-row { grid-template-columns: 24px 1fr 72px; }
  .problem-selector { grid-column: 2 / 4; }
  .label-input { grid-column: 2; width: 100%; }
  .sort-actions { grid-column: 3; }
  .sort-actions :deep(.el-button) { width: 30px; height: 30px; }
}
</style>
