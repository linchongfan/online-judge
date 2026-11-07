<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import DifficultyTag from '../../components/DifficultyTag.vue'
import {
  adminErrorMessage,
  archiveAdminStudyPlan,
  createAdminStudyPlan,
  getAdminStudyPlan,
  isAdminRequestCancelled,
  listAdminProblems,
  listAdminStudyPlans,
  publishAdminStudyPlan,
  updateAdminStudyPlan,
} from '../../api/admin'
import { formatDateTime, formatNumber } from '../../utils/format'
import { PLAN_ACCENTS, planAccent } from '../../utils/studyPlan'
import type {
  AdminProblem,
  AdminStudyPlanSummary,
  AdminStudyPlanWrite,
  Difficulty,
  ProblemStatus,
  StudyPlanAccent,
  StudyPlanStatus,
} from '../../types'

interface PlanProblemForm {
  problemId: number | null
  groupName: string
  position: number
}
interface PlanForm {
  title: string
  subtitle: string
  description: string
  accent: StudyPlanAccent
  problems: PlanProblemForm[]
}
interface ProblemOption {
  id: number
  title: string
  difficulty: Difficulty
  status: ProblemStatus
}

const statusMap: Record<StudyPlanStatus, { label: string; tone: string }> = {
  draft: { label: '未发布', tone: 'neutral' },
  published: { label: '已发布', tone: 'success' },
  archived: { label: '已归档', tone: 'warning' },
}
const ACCENT_OPTIONS = Object.entries(PLAN_ACCENTS) as Array<[StudyPlanAccent, { label: string; from: string; to: string }]>

const rows = ref<AdminStudyPlanSummary[]>([])
const keyword = ref('')
const statusFilter = ref<'all' | StudyPlanStatus>('all')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const editingLoadingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const saving = ref(false)
const pendingKeys = ref<Set<string>>(new Set())
const problemOptions = ref<ProblemOption[]>([])
const problemOptionsLoading = ref(false)
const problemOptionsError = ref('')
let listController: AbortController | null = null
let problemController: AbortController | null = null
let filterTimer: ReturnType<typeof setTimeout> | null = null
let problemTimer: ReturnType<typeof setTimeout> | null = null

function emptyForm(): PlanForm {
  return { title: '', subtitle: '', description: '', accent: 'blue', problems: [] }
}
const form = ref<PlanForm>(emptyForm())
const rules: FormRules<PlanForm> = {
  title: [{ required: true, message: '请输入学习计划名称', trigger: 'blur' }],
}

const hasFilters = computed(() => Boolean(keyword.value || statusFilter.value !== 'all'))
const publishedCount = computed(() => rows.value.filter(row => row.status === 'published').length)
const archivedCount = computed(() => rows.value.filter(row => row.status === 'archived').length)

function setPending(key: string, pending: boolean) {
  const next = new Set(pendingKeys.value)
  if (pending) next.add(key)
  else next.delete(key)
  pendingKeys.value = next
}
function actionKey(planId: number, action: string) { return `${planId}:${action}` }

async function loadPlans() {
  listController?.abort()
  const current = new AbortController()
  listController = current
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listAdminStudyPlans({
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
      await loadPlans()
    }
  } catch (error) {
    if (!isAdminRequestCancelled(error)) {
      rows.value = []
      errorMessage.value = adminErrorMessage(error, '学习计划列表加载失败')
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
  filterTimer = setTimeout(() => { page.value = 1; void loadPlans() }, 350)
}
function resetFilters() {
  const hadFilters = hasFilters.value
  keyword.value = ''
  statusFilter.value = 'all'
  if (!hadFilters) { page.value = 1; void loadPlans() }
}
function changePage(value: number) { page.value = value; void loadPlans() }
function changePageSize(value: number) { pageSize.value = value; page.value = 1; void loadPlans() }

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
    if (!current.signal.aborted) {
      mergeProblemOptions(result.items.map((item: AdminProblem) => ({
        id: item.id,
        title: item.title,
        difficulty: item.difficulty,
        status: item.status,
      })))
    }
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
function availableProblemsFor(entry: PlanProblemForm): ProblemOption[] {
  const selected = new Set(form.value.problems.filter(item => item !== entry && item.problemId !== null).map(item => item.problemId))
  return problemOptions.value.filter(item => !selected.has(item.id))
}
function addProblem() {
  if (form.value.problems.length >= 300) return
  form.value.problems.push({ problemId: null, groupName: '', position: form.value.problems.length + 1 })
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
function problemOption(problemId: number | null): ProblemOption | undefined {
  return problemOptions.value.find(item => item.id === problemId)
}
function problemStatusLabel(problemId: number | null): string {
  const status = problemOption(problemId)?.status
  if (status === 'archived') return '已归档'
  if (status === 'draft') return '未发布'
  return ''
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  problemOptionsError.value = ''
  dialogVisible.value = true
  void searchProblems('')
}
async function openEdit(row: AdminStudyPlanSummary) {
  if (row.status === 'archived') {
    ElMessage.info('已归档的学习计划不可编辑')
    return
  }
  editingLoadingId.value = row.id
  try {
    const detail = await getAdminStudyPlan(row.id)
    mergeProblemOptions(detail.problems.map(item => ({
      id: item.problemId,
      title: item.title,
      difficulty: item.difficulty,
      status: item.problemStatus,
    })))
    editingId.value = detail.id
    form.value = {
      title: detail.title,
      subtitle: detail.subtitle,
      description: detail.description,
      accent: (detail.accent in PLAN_ACCENTS ? detail.accent : 'blue') as StudyPlanAccent,
      problems: detail.problems.map((item, index) => ({
        problemId: item.problemId,
        groupName: item.groupName ?? '',
        position: index + 1,
      })),
    }
    problemOptionsError.value = ''
    dialogVisible.value = true
    void searchProblems('')
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '学习计划详情加载失败'))
  } finally {
    editingLoadingId.value = null
  }
}

function validateProblems(): boolean {
  if (form.value.problems.some(item => item.problemId === null)) {
    ElMessage.warning('请为每一行选择题目，或删除空行')
    return false
  }
  const ids = form.value.problems.map(item => item.problemId as number)
  if (new Set(ids).size !== ids.length) {
    ElMessage.warning('学习计划不能重复包含同一道题')
    return false
  }
  if (form.value.problems.some(item => item.groupName.trim().length > 50)) {
    ElMessage.warning('分组名称不能超过 50 个字符')
    return false
  }
  return true
}
async function savePlan() {
  if (!formRef.value || saving.value) return
  try { await formRef.value.validate() } catch { ElMessage.warning('请完善计划名称后再保存'); return }
  if (!validateProblems()) return
  saving.value = true
  const current = form.value
  const payload: AdminStudyPlanWrite = {
    title: current.title.trim(),
    subtitle: current.subtitle.trim(),
    description: current.description.trim(),
    accent: current.accent,
    problems: current.problems.map((item, index) => ({
      problemId: item.problemId as number,
      position: index + 1,
      groupName: item.groupName.trim() || null,
    })),
  }
  try {
    const result = editingId.value === null
      ? await createAdminStudyPlan(payload)
      : await updateAdminStudyPlan(editingId.value, payload)
    ElMessage.success(editingId.value === null ? `学习计划 #${result.id} 已创建为未发布草稿` : `学习计划「${result.title}」已保存`)
    dialogVisible.value = false
    await loadPlans()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '学习计划保存失败'))
  } finally {
    saving.value = false
  }
}

async function planAction(row: AdminStudyPlanSummary, action: 'publish' | 'archive') {
  const key = actionKey(row.id, action)
  if (pendingKeys.value.has(key)) return
  const messages = {
    publish: [`发布后，「${row.title}」会出现在用户端学习计划列表中。`, '确认发布学习计划', '确认发布'],
    archive: [`归档后，「${row.title}」会从用户端隐藏，已有加入记录保留。`, '确认归档学习计划', '确认归档'],
  } as const
  try {
    await ElMessageBox.confirm(messages[action][0], messages[action][1], {
      confirmButtonText: messages[action][2],
      cancelButtonText: '返回',
      type: 'warning',
    })
  } catch { return }
  setPending(key, true)
  const title = row.title
  try {
    if (action === 'publish') await publishAdminStudyPlan(row.id)
    else await archiveAdminStudyPlan(row.id)
    ElMessage.success(action === 'publish' ? `学习计划「${title}」已发布` : `学习计划「${title}」已归档`)
    await loadPlans()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, action === 'publish' ? '学习计划发布失败' : '学习计划归档失败'))
  } finally {
    setPending(key, false)
  }
}

function previewPlan(row: AdminStudyPlanSummary) {
  if (row.status !== 'published') {
    ElMessage.info('发布后才能预览用户端页面')
    return
  }
  window.open(`/plans/${row.id}`, '_blank', 'noopener')
}

watch([keyword, statusFilter], scheduleFilterLoad)
onMounted(() => { void loadPlans() })
onUnmounted(() => {
  if (filterTimer) clearTimeout(filterTimer)
  if (problemTimer) clearTimeout(problemTimer)
  listController?.abort()
  problemController?.abort()
})
</script>

<template>
  <div class="study-plans-admin">
    <div class="page-heading"><div><h1>学习计划管理</h1><p>编排章节与题目，发布后用户可加入并按 AC 自动记录进度。</p></div><el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建学习计划</el-button></div>

    <section class="plan-overview">
      <div class="overview-item"><span class="overview-icon total"><el-icon><Reading /></el-icon></span><div><strong>{{ formatNumber(total) }}</strong><span>计划总数</span></div></div>
      <div class="overview-item"><span class="overview-icon live"><el-icon><VideoPlay /></el-icon></span><div><strong>{{ publishedCount }}</strong><span>本页已发布</span></div></div>
      <div class="overview-item"><span class="overview-icon draft"><el-icon><Document /></el-icon></span><div><strong>{{ rows.length - publishedCount - archivedCount }}</strong><span>本页草稿</span></div></div>
      <div class="overview-note"><el-icon><InfoFilled /></el-icon><span>用户进度按站内 AC 自动计算，无需手动维护</span></div>
    </section>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert"><el-button size="small" @click="loadPlans">重新加载</el-button></el-alert>

    <section class="surface-card table-card">
      <div class="section-heading table-heading"><div><h2>全部学习计划</h2><p>共 {{ formatNumber(total) }} 个计划，按更新时间倒序展示</p></div><span class="prototype-note">真实发布状态</span></div>
      <div class="filter-bar">
        <el-input v-model="keyword" class="search-input" clearable placeholder="搜索计划名称或副标题"><template #prefix><el-icon><Search /></el-icon></template></el-input>
        <el-select v-model="statusFilter" class="status-select" aria-label="筛选发布状态"><el-option label="全部发布状态" value="all" /><el-option label="未发布" value="draft" /><el-option label="已发布" value="published" /><el-option label="已归档" value="archived" /></el-select>
        <el-button v-if="hasFilters" text @click="resetFilters"><el-icon><RefreshLeft /></el-icon>重置</el-button>
        <span class="filter-result">{{ formatNumber(total) }} 个服务端计划</span>
      </div>

      <div class="table-scroll">
        <el-table v-loading="loading" :data="rows" row-key="id" class="admin-table">
          <el-table-column label="学习计划" min-width="280">
            <template #default="{ row }">
              <div class="plan-cell">
                <span class="plan-mark" :style="{ background: `linear-gradient(135deg, ${planAccent(row.accent).from}, ${planAccent(row.accent).to})` }">{{ row.title.slice(0, 1) }}</span>
                <div><strong>{{ row.title }}</strong><span>#{{ row.id }} · {{ row.subtitle || '暂无副标题' }}</span></div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="发布状态" width="105"><template #default="{ row }"><span class="status-pill" :class="statusMap[row.status as StudyPlanStatus].tone"><i />{{ statusMap[row.status as StudyPlanStatus].label }}</span></template></el-table-column>
          <el-table-column label="题目数" width="90" align="right"><template #default="{ row }">{{ row.problemCount }}</template></el-table-column>
          <el-table-column label="加入人数" width="100" align="right"><template #default="{ row }">{{ formatNumber(row.enrolledCount) }}</template></el-table-column>
          <el-table-column label="更新时间" width="190"><template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template></el-table-column>
          <el-table-column label="操作" width="330" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-tooltip :disabled="row.status !== 'archived'" content="已归档的学习计划不可编辑" placement="top">
                  <span><el-button text type="primary" :disabled="row.status === 'archived'" :loading="editingLoadingId === row.id" @click="openEdit(row)">编辑</el-button></span>
                </el-tooltip>
                <el-button v-if="row.status !== 'published'" text type="success" :loading="pendingKeys.has(actionKey(row.id, 'publish'))" @click="planAction(row, 'publish')">发布</el-button>
                <el-button v-if="row.status === 'published'" text type="primary" @click="previewPlan(row)">预览</el-button>
                <el-button v-if="row.status !== 'archived'" text type="warning" :loading="pendingKeys.has(actionKey(row.id, 'archive'))" @click="planAction(row, 'archive')">归档</el-button>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty-state"><div class="empty-icon"><el-icon :size="26"><Reading /></el-icon></div><h3>{{ hasFilters ? '没有匹配的学习计划' : '暂无学习计划' }}</h3><p>{{ hasFilters ? '尝试更换关键词或重置筛选。' : '新建计划、配置章节和题目后即可发布。' }}</p><el-button v-if="hasFilters" type="primary" plain @click="resetFilters">清除筛选</el-button></div>
          </template>
        </el-table>
      </div>
      <div class="pagination-bar"><el-pagination background :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" :disabled="loading" @current-change="changePage" @size-change="changePageSize" /><span v-if="pages">共 {{ pages }} 页</span></div>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingId === null ? '新建学习计划' : `编辑学习计划 #${editingId}`" width="min(940px, calc(100vw - 32px))" top="4vh" @closed="formRef?.clearValidate()">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="plan-form" :disabled="saving">
        <div class="form-grid">
          <el-form-item label="计划名称" prop="title"><el-input v-model="form.title" maxlength="120" show-word-limit placeholder="例如：C 语言入门 100 题" /></el-form-item>
          <el-form-item label="副标题"><el-input v-model="form.subtitle" maxlength="255" placeholder="一句简短的计划介绍" /></el-form-item>
        </div>
        <el-form-item label="封面主题色">
          <div class="accent-field">
            <button
              v-for="[key, accent] in ACCENT_OPTIONS"
              :key="key"
              type="button"
              class="accent-swatch"
              :class="{ active: form.accent === key }"
              :style="{ background: `linear-gradient(135deg, ${accent.from}, ${accent.to})` }"
              :title="accent.label"
              :aria-label="accent.label"
              @click="form.accent = key"
            ><el-icon v-if="form.accent === key"><Check /></el-icon></button>
          </div>
        </el-form-item>
        <el-form-item label="计划介绍"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="50000" placeholder="介绍计划目标、适合人群和学习建议。支持换行。" /></el-form-item>

        <div class="plan-problems-editor">
          <div class="problem-editor-heading"><div><h3>章节与题目</h3><p>按顺序排列；连续相同的分组名会合并成一个章节。</p></div><el-button type="primary" plain :disabled="form.problems.length >= 300" @click="addProblem"><el-icon><Plus /></el-icon>添加题目</el-button></div>
          <el-alert v-if="problemOptionsError" :title="problemOptionsError" type="error" :closable="false" show-icon role="alert" />
          <div v-if="!form.problems.length" class="problem-editor-empty"><el-icon><DocumentAdd /></el-icon><span>尚未配置题目，发布前至少添加一道。</span></div>
          <div v-for="(problem, index) in form.problems" :key="`${index}-${problem.position}`" class="problem-editor-row">
            <span class="position-number mono">{{ index + 1 }}</span>
            <el-select v-model="problem.problemId" class="problem-selector" filterable remote clearable :remote-method="scheduleProblemSearch" :loading="problemOptionsLoading" placeholder="搜索并选择题目">
              <el-option v-for="option in availableProblemsFor(problem)" :key="option.id" :label="`#${option.id} ${option.title}`" :value="option.id"><span>#{{ option.id }} {{ option.title }}</span><DifficultyTag :difficulty="option.difficulty" /></el-option>
            </el-select>
            <el-input v-model="problem.groupName" class="group-input" maxlength="50" placeholder="分组，如：动态规划" />
            <div class="selected-problem-meta">
              <DifficultyTag v-if="problemOption(problem.problemId)" :difficulty="problemOption(problem.problemId)!.difficulty" />
              <span v-else class="muted">未选择</span>
              <span v-if="problemStatusLabel(problem.problemId)" class="problem-status-warning">{{ problemStatusLabel(problem.problemId) }}</span>
            </div>
            <div class="sort-actions"><el-button circle size="small" aria-label="上移题目" :disabled="index === 0" @click="moveProblem(index, -1)"><el-icon><ArrowUp /></el-icon></el-button><el-button circle size="small" aria-label="下移题目" :disabled="index === form.problems.length - 1" @click="moveProblem(index, 1)"><el-icon><ArrowDown /></el-icon></el-button><el-button circle size="small" type="danger" plain aria-label="删除题目" @click="removeProblem(index)"><el-icon><Delete /></el-icon></el-button></div>
          </div>
        </div>
        <div class="publish-tip"><el-icon><InfoFilled /></el-icon><span>保存仅更新计划内容；新建计划需在列表确认发布。发布要求所有题目处于已发布状态。</span></div>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="savePlan"><el-icon v-if="!saving"><Check /></el-icon>{{ editingId === null ? '创建草稿' : '保存修改' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.study-plans-admin :deep(.page-heading) { margin-bottom: 22px; }
.study-plans-admin :deep(.page-heading .el-button) { min-height: 36px; border-radius: 6px; padding-inline: 16px; }
.request-alert { margin-bottom: 16px; }
.plan-overview { display: flex; align-items: center; gap: 0; padding: 19px 22px; margin-bottom: 16px; border: 1px solid var(--border); border-radius: 8px; background: #fff; box-shadow: var(--shadow-sm); }
.overview-item { display: flex; align-items: center; gap: 12px; min-width: 150px; padding-right: 26px; margin-right: 26px; border-right: 1px solid var(--border); }
.overview-icon { width: 38px; height: 38px; border-radius: 7px; display: grid; place-items: center; font-size: 18px; }
.overview-icon.total { color: var(--primary); background: var(--primary-soft); }
.overview-icon.live { color: var(--success); background: #eaf7f1; }
.overview-icon.draft { color: #5d7693; background: #edf2f7; }
.overview-item > div { display: flex; flex-direction: column; }
.overview-item strong { color: var(--text-strong); font-size: 23px; line-height: 1.2; }
.overview-item span:not(.overview-icon) { color: var(--text-secondary); font-size: 11px; margin-top: 4px; }
.overview-note { margin-left: auto; display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 11px; }
.overview-note :deep(.el-icon) { color: var(--primary); }
.table-card { overflow: hidden; border-radius: 8px; box-shadow: none; }
.table-heading { margin: 0; padding: 19px 20px; }
.table-heading h2 { font-size: 16px; font-weight: 700; }
.table-heading p { color: var(--text-secondary); }
.filter-bar { display: flex; align-items: center; gap: 10px; padding: 0 20px 16px; }
.search-input { max-width: 360px; }
.status-select { width: 155px; }
.filter-result { margin-left: auto; color: var(--text-tertiary); font-size: 10px; }
.table-scroll { overflow-x: auto; }
.plan-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.plan-mark { width: 34px; height: 34px; flex: none; display: grid; place-items: center; border-radius: 8px; color: #fff; font-size: 15px; font-weight: 700; }
.plan-cell > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.plan-cell strong { overflow: hidden; color: var(--text-strong); font-size: 12px; white-space: nowrap; text-overflow: ellipsis; }
.plan-cell span { overflow: hidden; color: var(--text-tertiary); font-size: 9px; white-space: nowrap; text-overflow: ellipsis; }
.row-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; }
.pagination-bar { display: flex; align-items: center; justify-content: flex-end; gap: 14px; padding: 14px 20px; border-top: 1px solid var(--border); }
.pagination-bar span { color: var(--text-tertiary); font-size: 10px; }
.plan-form :deep(.el-form-item) { margin-bottom: 17px; }
.form-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 16px; }
.accent-field { display: flex; align-items: center; gap: 10px; }
.accent-swatch { width: 30px; height: 30px; display: grid; place-items: center; border: 2px solid transparent; border-radius: 8px; color: #fff; cursor: pointer; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .24); }
.accent-swatch.active { border-color: var(--text-strong); box-shadow: 0 0 0 2px #fff, 0 0 0 4px var(--primary); }
.plan-problems-editor { margin-top: 4px; padding: 15px; border: 1px solid var(--border); border-radius: 9px; background: #fbfdff; }
.problem-editor-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.problem-editor-heading h3 { margin: 0; color: var(--text-strong); font-size: 13px; }
.problem-editor-heading p { margin: 4px 0 0; color: var(--text-tertiary); font-size: 10px; }
.problem-editor-empty { display: flex; align-items: center; justify-content: center; gap: 7px; padding: 26px 10px; color: var(--text-tertiary); font-size: 11px; }
.problem-editor-row { display: grid; grid-template-columns: 26px minmax(210px, 1.5fr) minmax(130px, .8fr) 100px 108px; gap: 10px; align-items: center; padding: 8px 0; border-top: 1px dashed #e4ebf3; }
.position-number { color: var(--text-tertiary); font-size: 10px; text-align: center; }
.problem-selector { width: 100%; }
.group-input { width: 100%; }
.selected-problem-meta { display: flex; align-items: center; gap: 6px; min-width: 0; }
.selected-problem-meta .muted { font-size: 10px; }
.problem-status-warning { flex: none; padding: 2px 5px; border-radius: 4px; background: #fff4e4; color: #b57629; font-size: 8px; }
.sort-actions { display: flex; align-items: center; gap: 3px; justify-content: flex-end; }
.publish-tip { display: flex; align-items: center; gap: 6px; margin-top: 14px; color: var(--text-tertiary); font-size: 10px; }
@media (max-width: 1100px) {
  .plan-overview { flex-wrap: wrap; gap: 14px; }
  .overview-item { border-right: 0; padding-right: 0; margin-right: 18px; }
  .overview-note { width: 100%; margin-left: 0; }
}
@media (max-width: 900px) {
  .form-grid { grid-template-columns: 1fr; gap: 0; }
  .problem-editor-row { grid-template-columns: 24px minmax(0, 1fr) 100px; }
  .problem-editor-row .group-input { grid-column: 2 / 3; }
  .problem-editor-row .selected-problem-meta { grid-column: 3 / 4; justify-content: flex-end; }
  .problem-editor-row .sort-actions { grid-column: 2 / -1; justify-content: flex-end; }
}
@media (max-width: 640px) {
  .filter-bar { flex-wrap: wrap; padding: 0 14px 14px; }
  .search-input { max-width: none; flex: 1 1 100%; }
  .filter-result { display: none; }
  .plan-overview { display: none; }
  .problem-editor-heading { align-items: flex-start; flex-direction: column; }
  .problem-editor-row { grid-template-columns: 20px minmax(0, 1fr); gap: 8px; }
  .problem-editor-row .selected-problem-meta { grid-column: 2 / 3; justify-content: flex-start; }
  .problem-editor-row .sort-actions { grid-column: 2 / 3; justify-content: flex-start; }
}
</style>
