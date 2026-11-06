<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import DifficultyTag from '../../components/DifficultyTag.vue'
import {
  adminErrorMessage,
  archiveAdminProblem,
  createAdminProblem,
  downloadAdminTestDataTemplate,
  getAdminProblem,
  isAdminRequestCancelled,
  listAdminProblems,
  listAdminTestDataVersions,
  publishAdminProblem,
  unpublishAdminProblem,
  updateAdminProblem,
  uploadAdminTestData,
} from '../../api/admin'
import { listTags } from '../../api/problems'
import { ApiError } from '../../api/client'
import type {
  AdminProblem,
  AdminProblemWrite,
  AdminTestDataValidationError,
  AdminTestDataVersion,
  Difficulty,
  Language,
  ProblemStatus,
} from '../../types'
import { formatDateTime, formatNumber } from '../../utils/format'

interface SolutionForm {
  enabled: boolean
  title: string
  summary: string
  stepsText: string
  time: string
  space: string
  codeByLanguage: Record<Language, string>
}
interface ProblemForm {
  title: string
  difficulty: Difficulty
  tags: string[]
  description: string
  inputDescription: string
  outputDescription: string
  constraintsText: string
  timeLimitMs: number
  memoryLimitMb: number
  solution: SolutionForm
}

const statusMap: Record<ProblemStatus, { label: string; tone: string }> = {
  published: { label: '已发布', tone: 'success' },
  draft: { label: '草稿 / 已下架', tone: 'neutral' },
  archived: { label: '已归档', tone: 'warning' },
}
const versionStatusMap: Record<AdminTestDataVersion['status'], { label: string; type: 'success' | 'info' | 'warning' | 'danger' }> = {
  uploading: { label: '上传中', type: 'info' },
  uploaded: { label: '待校验', type: 'warning' },
  validating: { label: '校验中', type: 'warning' },
  valid: { label: '校验通过', type: 'success' },
  invalid: { label: '校验失败', type: 'danger' },
}
const solutionLanguages: Language[] = ['cpp', 'c', 'java', 'python']
const solutionLanguageLabels: Record<Language, string> = { cpp: 'C++11', c: 'C99', java: 'JDK 8', python: 'Python 3.12' }

const rows = ref<AdminProblem[]>([])
const keyword = ref('')
const statusFilter = ref<'all' | ProblemStatus>('all')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const pendingIds = ref<Set<number>>(new Set())
const drawerVisible = ref(false)
const editingId = ref<number | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const saving = ref(false)
const formRef = ref<FormInstance>()
const solutionLanguage = ref<Language>('cpp')
const hasPersistedSolution = ref(false)
const availableTags = ref<string[]>([])
const versions = ref<AdminTestDataVersion[]>([])
const versionsLoading = ref(false)
const versionsError = ref('')
const uploading = ref(false)
const templateDownloading = ref(false)
const uploadErrors = ref<AdminTestDataValidationError[]>([])
const uploadInput = ref<HTMLInputElement>()
let listController: AbortController | null = null
let searchTimer: ReturnType<typeof setTimeout> | null = null
let detailSequence = 0

function emptySolution(): SolutionForm {
  return {
    enabled: false, title: '', summary: '', stepsText: '', time: 'O(n)', space: 'O(n)',
    codeByLanguage: { cpp: '', c: '', java: '', python: '' },
  }
}
function emptyForm(): ProblemForm {
  return {
    title: '', difficulty: '简单', tags: [], description: '', inputDescription: '', outputDescription: '',
    constraintsText: '', timeLimitMs: 1000, memoryLimitMb: 256, solution: emptySolution(),
  }
}
const form = ref<ProblemForm>(emptyForm())
const rules: FormRules<ProblemForm> = {
  title: [{ required: true, message: '请输入题目标题', trigger: 'blur' }],
  difficulty: [{ required: true, message: '请选择难度', trigger: 'change' }],
  description: [{ required: true, message: '请输入题目描述', trigger: 'blur' }],
  inputDescription: [{ required: true, message: '请输入输入说明', trigger: 'blur' }],
  outputDescription: [{ required: true, message: '请输入输出说明', trigger: 'blur' }],
  timeLimitMs: [{ required: true, type: 'number', min: 100, max: 30000, message: '时间限制为 100–30000 ms', trigger: 'change' }],
  memoryLimitMb: [{ required: true, type: 'number', min: 16, max: 1024, message: '内存限制为 16–1024 MB', trigger: 'change' }],
}

const publishedCount = computed(() => rows.value.filter(problem => problem.status === 'published').length)
const draftCount = computed(() => rows.value.filter(problem => problem.status === 'draft').length)
const hasFilters = computed(() => Boolean(keyword.value || statusFilter.value !== 'all'))
const tagOptions = computed(() => Array.from(new Set([...availableTags.value, ...form.value.tags])).sort())
const editingRow = computed(() => rows.value.find(item => item.id === editingId.value) ?? null)
const currentVersion = computed(() => versions.value.find(item => item.isCurrent) ?? null)
const currentTestCaseCount = computed(() => currentVersion.value?.testCaseCount ?? editingRow.value?.testCaseCount ?? 0)
const currentTestDataSize = computed(() => currentVersion.value?.uncompressedSize ?? editingRow.value?.testDataSize ?? 0)
const pageTestCases = computed(() => rows.value.reduce((sum, item) => sum + item.testCaseCount, 0))

function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

function setPending(problemId: number, pending: boolean) {
  const next = new Set(pendingIds.value)
  if (pending) next.add(problemId)
  else next.delete(problemId)
  pendingIds.value = next
}

async function loadProblems() {
  listController?.abort()
  const current = new AbortController()
  listController = current
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listAdminProblems({
      page: page.value,
      pageSize: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    }, { signal: current.signal })
    if (current.signal.aborted) return
    rows.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (!result.items.length && result.total > 0 && result.pages > 0 && page.value > result.pages) {
      page.value = result.pages
      await loadProblems()
    }
  } catch (error) {
    if (!isAdminRequestCancelled(error)) {
      rows.value = []
      errorMessage.value = adminErrorMessage(error, '题目列表加载失败')
    }
  } finally {
    if (listController === current) {
      loading.value = false
      listController = null
    }
  }
}

function scheduleFilterLoad() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    void loadProblems()
  }, 350)
}
function resetFilters() {
  const hadFilters = hasFilters.value
  keyword.value = ''
  statusFilter.value = 'all'
  if (!hadFilters) {
    page.value = 1
    void loadProblems()
  }
}
function changePage(value: number) { page.value = value; void loadProblems() }
function changePageSize(value: number) { pageSize.value = value; page.value = 1; void loadProblems() }

function openCreate() {
  detailSequence += 1
  editingId.value = null
  form.value = emptyForm()
  hasPersistedSolution.value = false
  versions.value = []
  uploadErrors.value = []
  detailLoading.value = false
  versionsLoading.value = false
  detailError.value = ''
  versionsError.value = ''
  solutionLanguage.value = 'cpp'
  drawerVisible.value = true
}

async function loadVersions(problemId: number) {
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const result = await listAdminTestDataVersions(problemId)
    if (editingId.value === problemId) versions.value = result
  } catch (error) {
    if (editingId.value === problemId) versionsError.value = adminErrorMessage(error, '测试数据版本加载失败')
  } finally {
    if (editingId.value === problemId) versionsLoading.value = false
  }
}

async function openEdit(problem: AdminProblem) {
  const sequence = ++detailSequence
  editingId.value = problem.id
  form.value = emptyForm()
  versions.value = []
  uploadErrors.value = []
  detailError.value = ''
  versionsError.value = ''
  solutionLanguage.value = 'cpp'
  drawerVisible.value = true
  detailLoading.value = true
  try {
    const detail = await getAdminProblem(problem.id)
    if (sequence !== detailSequence) return
    hasPersistedSolution.value = detail.solution !== null
    const codeByLanguage: Record<Language, string> = { cpp: '', c: '', java: '', python: '' }
    detail.solution?.codes.forEach(item => { codeByLanguage[item.language] = item.code })
    form.value = {
      title: detail.title,
      difficulty: detail.difficulty,
      tags: [...detail.tags],
      description: detail.description.join('\n'),
      inputDescription: detail.inputDescription,
      outputDescription: detail.outputDescription,
      constraintsText: detail.constraints.join('\n'),
      timeLimitMs: detail.timeLimitMs,
      memoryLimitMb: detail.memoryLimitMb,
      solution: detail.solution ? {
        enabled: detail.solution.enabled,
        title: detail.solution.title,
        summary: detail.solution.summary,
        stepsText: detail.solution.steps.join('\n'),
        time: detail.solution.time,
        space: detail.solution.space,
        codeByLanguage,
      } : emptySolution(),
    }
  } catch (error) {
    if (sequence === detailSequence) detailError.value = adminErrorMessage(error, '题目详情加载失败')
  } finally {
    if (sequence === detailSequence) detailLoading.value = false
  }
  void loadVersions(problem.id)
}

function validateSolution(solution: SolutionForm): boolean {
  if (!solution.enabled) return true
  if (!solution.title.trim() || !solution.summary.trim() || !solution.stepsText.trim() || !solution.time.trim() || !solution.space.trim()) {
    ElMessage.warning('请完善题解标题、思路、步骤与复杂度')
    return false
  }
  if (!solutionLanguages.some(language => solution.codeByLanguage[language].trim())) {
    ElMessage.warning('提供题解时请至少填写一种语言的参考代码')
    return false
  }
  return true
}

function problemPayload(): AdminProblemWrite {
  const current = form.value
  const includeSolution = current.solution.enabled || hasPersistedSolution.value
  return {
    title: current.title.trim(),
    difficulty: current.difficulty,
    tags: current.tags.map(tag => tag.trim()).filter(Boolean),
    description: current.description.split('\n').map(line => line.trim()).filter(Boolean),
    inputDescription: current.inputDescription.trim(),
    outputDescription: current.outputDescription.trim(),
    constraints: current.constraintsText.split('\n').map(line => line.trim()).filter(Boolean),
    timeLimitMs: current.timeLimitMs,
    memoryLimitMb: current.memoryLimitMb,
    solution: includeSolution ? {
      title: current.solution.title.trim(),
      summary: current.solution.summary.trim(),
      steps: current.solution.stepsText.split('\n').map(line => line.trim()).filter(Boolean),
      timeComplexity: current.solution.time.trim(),
      spaceComplexity: current.solution.space.trim(),
      enabled: current.solution.enabled,
      codes: solutionLanguages.filter(language => current.solution.codeByLanguage[language].trim()).map(language => ({
        language,
        code: current.solution.codeByLanguage[language],
      })),
    } : null,
  }
}

async function saveProblem() {
  if (!formRef.value || saving.value || detailLoading.value || detailError.value) return
  try {
    await formRef.value.validate()
  } catch {
    ElMessage.warning('请完善必填信息后再保存')
    return
  }
  if (!validateSolution(form.value.solution)) return
  if (form.value.tags.length > 12 || form.value.tags.some(tag => tag.trim().length > 40)) {
    ElMessage.warning('最多配置 12 个标签，且单个标签不能超过 40 个字符')
    return
  }
  saving.value = true
  try {
    const id = editingId.value
    const result = id === null
      ? await createAdminProblem(problemPayload())
      : await updateAdminProblem(id, problemPayload())
    ElMessage.success(id === null ? `题目 ${result.id} 已创建为草稿，可继续编辑并上传测试数据` : `题目 ${result.id} 已保存`)
    drawerVisible.value = false
    await loadProblems()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '题目保存失败'))
  } finally {
    saving.value = false
  }
}

async function changeStatus(problem: AdminProblem, action: 'publish' | 'unpublish' | 'archive') {
  if (pendingIds.value.has(problem.id)) return
  if (action !== 'publish') {
    const archiving = action === 'archive'
    try {
      await ElMessageBox.confirm(
        archiving ? `归档后「${problem.title}」将退出正常题库管理流程，历史提交会保留。` : `下架后「${problem.title}」将回到草稿状态，不再出现在用户端题库。`,
        archiving ? '确认归档题目' : '确认下架题目',
        { confirmButtonText: archiving ? '确认归档' : '确认下架', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  setPending(problem.id, true)
  try {
    const updated = action === 'publish'
      ? await publishAdminProblem(problem.id)
      : action === 'unpublish' ? await unpublishAdminProblem(problem.id) : await archiveAdminProblem(problem.id)
    Object.assign(problem, updated)
    ElMessage.success(action === 'publish' ? `「${problem.title}」已发布` : action === 'unpublish' ? `「${problem.title}」已下架` : `「${problem.title}」已归档`)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '题目状态更新失败'))
  } finally {
    setPending(problem.id, false)
  }
}

async function downloadTemplate() {
  if (templateDownloading.value) return
  templateDownloading.value = true
  try {
    const blob = await downloadAdminTestDataTemplate()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'test-data-template.zip'
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('ZIP 模板已下载')
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '模板下载失败'))
  } finally {
    templateDownloading.value = false
  }
}

function readUploadErrors(error: unknown): AdminTestDataValidationError[] {
  if (!(error instanceof ApiError) || error.status !== 422 || typeof error.details !== 'object' || error.details === null) return []
  const details = error.details as { errors?: unknown }
  if (!Array.isArray(details.errors)) return []
  return details.errors.flatMap((item) => {
    if (typeof item !== 'object' || item === null) return []
    const value = item as Record<string, unknown>
    return [{
      code: String(value.code ?? 'VALIDATION_ERROR'),
      path: String(value.path ?? '压缩包'),
      message: String(value.message ?? '测试数据校验失败'),
    }]
  })
}

function chooseUpload() {
  uploadErrors.value = []
  uploadInput.value?.click()
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const problemId = editingId.value
  if (!file || problemId === null || uploading.value) return
  if (!file.name.toLowerCase().endsWith('.zip') || file.size === 0) {
    ElMessage.warning('请选择非空的 ZIP 测试数据压缩包')
    return
  }
  uploading.value = true
  uploadErrors.value = []
  try {
    const result = await uploadAdminTestData(problemId, file)
    ElMessage.success(`测试数据版本已上传并校验通过：${result.testCaseCount} 个测试点，${result.sampleCount} 个样例`)
    await Promise.all([loadVersions(problemId), loadProblems()])
  } catch (error) {
    uploadErrors.value = readUploadErrors(error)
    ElMessage.error(adminErrorMessage(error, '测试数据上传失败'))
    await loadVersions(problemId)
  } finally {
    uploading.value = false
  }
}

watch([keyword, statusFilter], scheduleFilterLoad)
onMounted(() => {
  void loadProblems()
  void listTags().then(tags => { availableTags.value = tags.map(tag => tag.name) }).catch(() => {
    // Tags remain manually creatable even if the auxiliary suggestion list is unavailable.
  })
})
onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
  listController?.abort()
  detailSequence += 1
})
</script>

<template>
  <div class="problems-page">
    <div class="page-heading">
      <div><h1>题目管理</h1><p>维护题面、题解与测试数据，发布后题目将同步到用户端题库。</p></div>
      <div class="heading-actions"><el-button :loading="templateDownloading" @click="downloadTemplate"><el-icon><Download /></el-icon>ZIP 模板</el-button><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新增题目</el-button></div>
    </div>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert"><el-button size="small" @click="loadProblems">重新加载</el-button></el-alert>
    <section class="surface-card table-card">
      <div class="library-toolbar">
        <div class="library-meta"><strong>题库列表</strong><span><i class="published" />本页 {{ publishedCount }} 已发布</span><span><i class="draft" />本页 {{ draftCount }} 草稿 / 下架</span></div>
        <span class="prototype-note">测试点与大小来自有效版本</span>
      </div>
      <div class="filter-bar">
        <el-input v-model="keyword" class="search-input" clearable placeholder="按题目标题搜索"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="statusFilter" class="filter-select" aria-label="筛选发布状态">
          <el-option label="全部状态" value="all" /><el-option label="已发布" value="published" /><el-option label="草稿 / 已下架" value="draft" /><el-option label="已归档" value="archived" />
        </el-select>
        <el-button v-if="hasFilters" text @click="resetFilters"><el-icon><RefreshLeft /></el-icon>重置</el-button>
        <span class="filter-result">{{ formatNumber(total) }} 道服务端题目</span>
      </div>

      <div class="table-scroll">
        <el-table v-loading="loading" :data="rows" row-key="id" class="admin-table">
          <el-table-column label="题号" width="82"><template #default="{ row }"><span class="problem-id mono">{{ row.id }}</span></template></el-table-column>
          <el-table-column label="题目" min-width="250"><template #default="{ row }"><div class="problem-title"><strong>{{ row.title }}</strong><div><el-tag v-for="tag in row.tags.slice(0, 3)" :key="tag" size="small" effect="plain">{{ tag }}</el-tag><span v-if="!row.tags.length" class="muted">无标签</span></div></div></template></el-table-column>
          <el-table-column label="难度" width="90"><template #default="{ row }"><DifficultyTag :difficulty="row.difficulty" /></template></el-table-column>
          <el-table-column label="题解代码" width="120"><template #default="{ row }"><div v-if="row.solutionLanguageCount" class="solution-cell"><strong><el-icon><Reading /></el-icon>已配置</strong><span>{{ row.solutionLanguageCount }} 种语言代码</span></div><span v-else class="no-solution">无参考代码</span></template></el-table-column>
          <el-table-column label="测试点" width="140"><template #default="{ row }"><div class="testpoint-cell"><strong><el-icon><Files /></el-icon>{{ row.testCaseCount }} 个</strong><span>{{ formatBytes(row.testDataSize) }}</span></div></template></el-table-column>
          <el-table-column label="通过率" width="115"><template #default="{ row }"><div class="acceptance-cell"><span>{{ row.acceptance }}%</span><div><i :style="{ width: `${row.acceptance}%` }" /></div></div></template></el-table-column>
          <el-table-column label="提交数" width="110" align="right"><template #default="{ row }">{{ formatNumber(row.submissionCount) }}</template></el-table-column>
          <el-table-column label="状态" width="130"><template #default="{ row }"><span class="status-pill" :class="statusMap[row.status as ProblemStatus].tone"><i />{{ statusMap[row.status as ProblemStatus].label }}</span></template></el-table-column>
          <el-table-column label="最近更新" width="180"><template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template></el-table-column>
          <el-table-column label="操作" width="230" fixed="right">
            <template #default="{ row }"><div class="row-actions"><el-button text type="primary" :disabled="pendingIds.has(row.id)" @click="openEdit(row)">编辑</el-button><el-button v-if="row.status === 'published'" text type="danger" :loading="pendingIds.has(row.id)" @click="changeStatus(row, 'unpublish')">下架</el-button><el-button v-else text type="success" :loading="pendingIds.has(row.id)" @click="changeStatus(row, 'publish')">发布</el-button><el-button v-if="row.status !== 'archived'" text type="warning" :disabled="pendingIds.has(row.id)" @click="changeStatus(row, 'archive')">归档</el-button></div></template>
          </el-table-column>
          <template #empty><div class="empty-state"><div class="empty-icon"><el-icon :size="26"><Document /></el-icon></div><h3>{{ hasFilters ? '没有匹配的题目' : '题库暂无题目' }}</h3><p>{{ hasFilters ? '调整关键词或状态筛选。' : '创建题目并上传有效测试数据后即可发布。' }}</p><el-button v-if="hasFilters" type="primary" plain @click="resetFilters">清除筛选</el-button></div></template>
        </el-table>
      </div>
      <div class="table-footer"><span>当前页 {{ rows.length }} / 共 {{ formatNumber(total) }} 道题目</span><span>本页测试点总计 {{ formatNumber(pageTestCases) }} 个</span></div>
      <div class="pagination-bar"><el-pagination background :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" :disabled="loading" @current-change="changePage" @size-change="changePageSize" /><span v-if="pages">共 {{ pages }} 页</span></div>
    </section>

    <el-drawer v-model="drawerVisible" :title="editingId === null ? '新增题目' : `编辑题目 #${editingId}`" size="min(820px, 100vw)" @closed="formRef?.clearValidate()">
      <el-alert v-if="detailError" :title="detailError" type="error" show-icon :closable="false" role="alert"><el-button size="small" @click="editingRow && openEdit(editingRow)">重试详情</el-button></el-alert>
      <el-form v-loading="detailLoading" ref="formRef" :model="form" :rules="rules" label-position="top" class="problem-form" :disabled="saving || detailLoading">
        <div class="form-section"><h3>基本信息</h3><p>清晰的标题和标签能帮助用户快速检索题目。</p>
          <el-form-item label="题目标题" prop="title"><el-input v-model="form.title" maxlength="200" show-word-limit placeholder="例如：两数之和" /></el-form-item>
          <div class="form-grid"><el-form-item label="难度" prop="difficulty"><el-select v-model="form.difficulty"><el-option label="简单" value="简单" /><el-option label="中等" value="中等" /><el-option label="困难" value="困难" /></el-select></el-form-item><el-form-item label="题目编号"><el-input :model-value="editingId ?? '保存后自动生成'" disabled /></el-form-item></div>
          <el-form-item label="算法标签"><el-select v-model="form.tags" multiple filterable allow-create default-first-option :max-collapse-tags="6" placeholder="选择或输入标签，最多 12 个"><el-option v-for="tag in tagOptions" :key="tag" :label="tag" :value="tag" /></el-select></el-form-item>
        </div>
        <div class="form-section"><h3>题面内容</h3><p>题目描述与约束每行将作为一个条目。</p>
          <el-form-item label="题目描述" prop="description"><el-input v-model="form.description" type="textarea" :rows="5" placeholder="输入题目背景、目标与要求" /></el-form-item>
          <el-form-item label="输入说明" prop="inputDescription"><el-input v-model="form.inputDescription" type="textarea" :rows="3" placeholder="描述输入格式" /></el-form-item>
          <el-form-item label="输出说明" prop="outputDescription"><el-input v-model="form.outputDescription" type="textarea" :rows="3" placeholder="描述输出格式" /></el-form-item>
          <el-form-item label="约束条件"><el-input v-model="form.constraintsText" type="textarea" :rows="3" placeholder="每行一个约束，例如：1 ≤ n ≤ 100000" /></el-form-item>
        </div>
        <div class="form-section solution-config">
          <div class="solution-config-heading"><div><h3>题解配置</h3><p>题解字段与多语言参考代码将映射到真实题解数据。</p></div><el-switch v-model="form.solution.enabled" active-text="提供题解" /></div>
          <template v-if="form.solution.enabled">
            <el-form-item label="题解标题" required><el-input v-model="form.solution.title" maxlength="200" placeholder="例如：哈希表：一次遍历寻找互补数" /></el-form-item>
            <el-form-item label="思路说明" required><el-input v-model="form.solution.summary" type="textarea" :rows="4" placeholder="说明核心思路" /></el-form-item>
            <el-form-item label="解题步骤" required><el-input v-model="form.solution.stepsText" type="textarea" :rows="4" placeholder="每行一个步骤" /></el-form-item>
            <div class="form-grid"><el-form-item label="时间复杂度" required><el-input v-model="form.solution.time" placeholder="例如：O(n)" /></el-form-item><el-form-item label="空间复杂度" required><el-input v-model="form.solution.space" placeholder="例如：O(n)" /></el-form-item></div>
            <div class="code-config">
              <div class="config-label"><span>多语言参考代码</span><small>至少填写一种，仅提交非空语言代码</small></div>
              <div class="code-language-tabs" role="tablist" aria-label="编辑参考代码语言"><button v-for="language in solutionLanguages" :key="language" type="button" :class="{ active: solutionLanguage === language, filled: form.solution.codeByLanguage[language].trim() }" @click="solutionLanguage = language">{{ solutionLanguageLabels[language] }}<el-icon v-if="form.solution.codeByLanguage[language].trim()"><CircleCheckFilled /></el-icon></button></div>
              <el-input v-model="form.solution.codeByLanguage[solutionLanguage]" class="solution-code-input" type="textarea" :rows="12" :placeholder="`输入 ${solutionLanguageLabels[solutionLanguage]} 参考实现`" />
            </div>
          </template>
          <div v-else class="solution-disabled"><el-icon><Reading /></el-icon><div><strong>{{ hasPersistedSolution ? '已保存题解将对用户隐藏' : '暂未为此题提供题解' }}</strong><p>开启后可编辑思路与多语言代码。</p></div></div>
        </div>
        <div class="form-section"><h3>判题配置</h3><p>资源限制可编辑；测试点数量与大小由有效 ZIP 版本自动统计，不可手填。</p>
          <div class="form-grid"><el-form-item label="时间限制（ms）" prop="timeLimitMs"><el-input-number v-model="form.timeLimitMs" :min="100" :max="30000" :step="100" /></el-form-item><el-form-item label="内存限制（MB）" prop="memoryLimitMb"><el-input-number v-model="form.memoryLimitMb" :min="16" :max="1024" :step="16" /></el-form-item></div>
          <div class="test-data-summary"><div><span>当前版本</span><strong>{{ currentVersion ? `v${currentVersion.version}` : (editingRow?.testDataVersion ? '有效版本' : '—') }}</strong></div><div><span>测试点</span><strong>{{ currentTestCaseCount }}</strong></div><div><span>解压大小</span><strong>{{ formatBytes(currentTestDataSize) }}</strong></div></div>
        </div>
        <div class="form-section test-data-section">
          <div class="solution-config-heading"><div><h3>测试数据版本</h3><p>ZIP 内按 sample / hidden 目录组织成对 .in 与 .out 文件。</p></div><el-button size="small" :loading="templateDownloading" @click="downloadTemplate"><el-icon><Download /></el-icon>下载模板</el-button></div>
          <template v-if="editingId !== null">
            <input ref="uploadInput" class="visually-hidden" type="file" accept=".zip,application/zip" @change="handleUpload" />
            <div class="upload-actions"><el-button type="primary" plain :loading="uploading" :disabled="detailLoading || saving" @click="chooseUpload"><el-icon><Upload /></el-icon>{{ uploading ? '上传并校验中' : '选择 ZIP 并上传' }}</el-button><span>新有效版本会自动成为当前版本</span></div>
            <div v-if="uploadErrors.length" class="validation-errors" role="alert"><strong>服务端返回 {{ uploadErrors.length }} 条校验错误</strong><div v-for="(item, index) in uploadErrors" :key="`${item.code}-${item.path}-${index}`"><span class="mono">{{ item.path }}</span><p>{{ item.message }}</p><code>{{ item.code }}</code></div></div>
            <el-alert v-if="versionsError" :title="versionsError" type="error" :closable="false" show-icon role="alert"><el-button size="small" @click="editingId !== null && loadVersions(editingId)">重试版本列表</el-button></el-alert>
            <el-table v-loading="versionsLoading" :data="versions" row-key="id" class="version-table" size="small">
              <el-table-column type="expand"><template #default="{ row }"><div class="version-errors"><template v-if="row.validationErrors?.length"><div v-for="(item, index) in row.validationErrors" :key="index"><strong class="mono">{{ item.path }}</strong><span>{{ item.message }}（{{ item.code }}）</span></div></template><span v-else>该版本没有校验错误。</span></div></template></el-table-column>
              <el-table-column label="版本" width="80"><template #default="{ row }"><strong>v{{ row.version }}</strong><el-tag v-if="row.isCurrent" size="small" type="success" class="current-tag">当前</el-tag></template></el-table-column>
              <el-table-column label="文件" prop="filename" min-width="160" show-overflow-tooltip />
              <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="versionStatusMap[row.status as AdminTestDataVersion['status']].type" size="small">{{ versionStatusMap[row.status as AdminTestDataVersion['status']].label }}</el-tag></template></el-table-column>
              <el-table-column label="测试点" width="75" align="right"><template #default="{ row }">{{ row.testCaseCount }}</template></el-table-column>
              <el-table-column label="大小" width="100" align="right"><template #default="{ row }">{{ formatBytes(row.uncompressedSize) }}</template></el-table-column>
              <el-table-column label="上传时间" width="165"><template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template></el-table-column>
              <template #empty><div class="version-empty">暂无测试数据版本，请上传 ZIP。</div></template>
            </el-table>
          </template>
          <div v-else class="testpoint-tip"><el-icon><InfoFilled /></el-icon><span>请先创建题目，再打开编辑页上传测试数据。测试点与大小由服务端校验后生成。</span></div>
        </div>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button :disabled="saving" @click="drawerVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="detailLoading || Boolean(detailError) || uploading" @click="saveProblem"><el-icon v-if="!saving"><Check /></el-icon>{{ editingId === null ? '创建题目' : '保存修改' }}</el-button></div></template>
    </el-drawer>
  </div>
</template>

<style scoped>
.problems-page :deep(.page-heading) { margin-bottom: 22px; }
.problems-page :deep(.page-heading .el-button) { min-height: 36px; border-radius: 6px; padding-inline: 16px; }
.heading-actions { display: flex; gap: 10px; }
.request-alert { margin-bottom: 16px; }
.table-card { overflow: hidden; border-radius: 8px; box-shadow: none; }
.library-toolbar { padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.library-meta { display: flex; align-items: center; gap: 18px; }
.library-meta > strong { color: var(--text-strong); font-size: 16px; margin-right: 4px; }
.library-meta > span { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 11px; }
.library-meta i { width: 6px; height: 6px; border-radius: 2px; }
.library-meta i.published { background: var(--success); }
.library-meta i.draft { background: #91a3b8; }
.prototype-note::before { background: var(--success); }
.filter-bar { display: flex; align-items: center; gap: 10px; padding: 16px 20px; background: #f8fbff; border-block: 1px solid var(--border); }
.filter-bar :deep(.el-input__wrapper), .filter-bar :deep(.el-select__wrapper) { border-radius: 6px; background: #fff; }
.filter-bar :deep(.el-button) { border-radius: 6px; }
.search-input { width: 310px; }
.filter-select { width: 160px; }
.filter-result { margin-left: auto; color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.table-scroll { width: 100%; overflow-x: auto; }
.admin-table { width: 100%; min-width: 1410px; --el-table-header-bg-color: #f4f8fd; --el-table-row-hover-bg-color: #f5f8ff; --el-table-header-text-color: var(--text-secondary); }
.admin-table :deep(th.el-table__cell) { height: 44px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.admin-table :deep(td.el-table__cell) { padding: 13px 0; }
.problem-id { color: #4c6787; font-size: 11px; }
.problem-title { display: flex; flex-direction: column; gap: 8px; }
.problem-title strong { color: var(--text-strong); font-weight: 600; font-size: 13px; }
.problem-title > div { display: flex; gap: 5px; }
.problem-title :deep(.el-tag) { --el-tag-bg-color: #f3f7fc; --el-tag-border-color: #dfe8f3; --el-tag-text-color: #607592; height: 20px; padding: 0 6px; border-radius: 3px; font-size: 9px; }
.admin-table :deep(.difficulty) { border-radius: 4px; padding: 3px 7px; font-size: 11px; }
.testpoint-cell { display: flex; flex-direction: column; gap: 5px; }
.testpoint-cell strong { display: flex; align-items: center; gap: 5px; font-weight: 500; color: var(--text-secondary); }
.testpoint-cell span { color: var(--text-secondary); font-size: 10px; padding-left: 19px; }
.acceptance-cell > span { font-size: 12px; color: var(--text-strong); font-weight: 600; }
.acceptance-cell > div { margin-top: 7px; width: 72px; height: 4px; border-radius: 2px; background: #e7edf5; overflow: hidden; }
.acceptance-cell i { display: block; height: 100%; background: var(--primary); border-radius: 2px; }
.status-pill { border-radius: 5px; padding: 4px 8px; }
.status-pill.success { color: var(--success); background: #eaf7f1; }
.status-pill.neutral { color: #687b91; background: #eef2f6; }
.status-pill.warning { color: #a86218; background: var(--accent-soft); }
.row-actions { display: flex; gap: 3px; }
.row-actions :deep(.el-button) { border-radius: 5px; }
.table-footer { display: flex; justify-content: space-between; padding: 13px 20px; border-top: 1px solid var(--border); background: #fbfdff; color: var(--text-secondary); font-size: 11px; }
.pagination-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; border-top: 1px solid var(--border); overflow-x: auto; }
.pagination-bar > span { color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.empty-state .empty-icon { border-radius: 10px; color: #8da5c1; background: var(--primary-soft); }
.problem-form { padding-bottom: 10px; min-height: 120px; }
.form-section { padding-bottom: 10px; margin-bottom: 22px; border-bottom: 1px solid var(--border); }
.form-section:last-child { border-bottom: 0; margin-bottom: 0; }
.form-section h3 { margin: 0; color: var(--text-strong); font-size: 15px; font-weight: 700; }
.form-section > p { margin: 6px 0 20px; color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.form-grid :deep(.el-select), .form-grid :deep(.el-input-number) { width: 100%; }
.problem-form :deep(.el-form-item) { margin-bottom: 20px; }
.problem-form :deep(.el-form-item__label) { color: var(--text-secondary); font-size: 12px; font-weight: 500; margin-bottom: 7px; }
.problem-form :deep(.el-input__wrapper), .problem-form :deep(.el-select__wrapper), .problem-form :deep(.el-textarea__inner) { border-radius: 6px; }
.testpoint-tip { display: flex; align-items: flex-start; gap: 8px; border: 1px solid #d8e6f8; border-radius: 6px; padding: 12px; background: var(--primary-soft); color: #46688f; font-size: 11px; line-height: 1.6; }
.testpoint-tip .el-icon { margin-top: 2px; flex: none; color: var(--primary); }
.solution-cell { display: flex; flex-direction: column; gap: 5px; }
.solution-cell strong { display: flex; align-items: center; gap: 4px; color: var(--primary); font-size: 11px; font-weight: 600; }
.solution-cell span, .no-solution { color: var(--text-tertiary); font-size: 10px; white-space: nowrap; }
.solution-config-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.solution-config-heading h3 { margin: 0; }
.solution-config-heading p { margin: 6px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.solution-disabled { display: flex; align-items: flex-start; gap: 12px; padding: 18px; border: 1px dashed #cbd9e9; border-radius: 7px; background: #f7faff; color: #7890ab; }
.solution-disabled > .el-icon { margin-top: 2px; font-size: 20px; }
.solution-disabled strong { color: var(--text-secondary); font-size: 12px; }
.solution-disabled p { margin: 5px 0 0; font-size: 10px; line-height: 1.7; }
.code-config { margin: 24px 0; }
.config-label { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 9px; }
.config-label > span { color: var(--text-secondary); font-size: 12px; font-weight: 500; }
.config-label small { color: var(--text-tertiary); font-size: 9px; }
.code-language-tabs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 9px; }
.code-language-tabs button { display: flex; align-items: center; justify-content: center; gap: 4px; border: 1px solid var(--border); border-radius: 5px; background: #fff; color: var(--text-secondary); padding: 7px 5px; font-size: 10px; cursor: pointer; }
.code-language-tabs button.filled .el-icon { color: var(--success); }
.code-language-tabs button.active { border-color: var(--primary); background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.solution-code-input :deep(.el-textarea__inner) { padding: 15px; background: #101d30; color: #d5e1f0; box-shadow: 0 0 0 1px #29415e inset; font: 11px/1.75 'JetBrains Mono', monospace; caret-color: #f2a44e; }
.test-data-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }
.test-data-summary > div { padding: 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-soft); display: flex; flex-direction: column; gap: 6px; }
.test-data-summary span { color: var(--text-secondary); font-size: 10px; }
.test-data-summary strong { color: var(--text-strong); font-size: 14px; }
.upload-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.upload-actions > span { color: var(--text-secondary); font-size: 10px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
.validation-errors { margin-bottom: 14px; padding: 12px; border: 1px solid #f1c5ca; border-radius: 6px; background: #fff5f5; color: var(--danger); }
.validation-errors > strong { display: block; margin-bottom: 8px; font-size: 12px; }
.validation-errors > div { display: grid; grid-template-columns: minmax(120px, .8fr) 1.5fr auto; align-items: start; gap: 8px; padding: 8px 0; border-top: 1px solid #f3d9dc; font-size: 11px; }
.validation-errors p { margin: 0; color: #8e3d47; }
.validation-errors code { font-size: 9px; }
.version-table { width: 100%; margin-top: 12px; }
.current-tag { margin-left: 4px; }
.version-empty { padding: 22px; color: var(--text-secondary); font-size: 11px; }
.version-errors { padding: 4px 12px; color: var(--text-secondary); font-size: 11px; }
.version-errors > div { display: flex; flex-direction: column; gap: 4px; padding: 6px 0; }
.drawer-footer { display: flex; justify-content: flex-end; gap: 8px; }
.drawer-footer :deep(.el-button) { border-radius: 6px; }
@media (max-width: 1000px) {
  .filter-bar { flex-wrap: wrap; }
  .filter-result { margin-left: 0; }
}
@media (max-width: 700px) {
  .search-input { width: 100%; }
  .filter-select { flex: 1; min-width: 120px; }
  .library-meta { gap: 10px; flex-wrap: wrap; }
  .library-toolbar .prototype-note { display: none; }
  .validation-errors > div { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .library-toolbar, .filter-bar { padding: 14px; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
  .code-language-tabs { grid-template-columns: repeat(2, 1fr); }
  .config-label { align-items: flex-start; flex-direction: column; }
  .table-footer { flex-direction: column; gap: 7px; }
  .test-data-summary { grid-template-columns: 1fr; }
  .upload-actions { align-items: flex-start; flex-direction: column; }
}
</style>
