<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import StatusTag from '../components/StatusTag.vue'
import { getSubmission, getSubmissionSource, listSubmissions } from '../api/submissions'
import { getUserStats } from '../api/me'
import { ApiError } from '../api/client'
import { formatDateTime, formatMemoryKb, formatRuntimeMs, judgeStatusMap } from '../utils/format'
import type { JudgeStatus, Language, Submission, UserStats } from '../types'

const router = useRouter()
const keyword = ref('')
const status = ref<JudgeStatus | ''>('')
const language = ref<Language | ''>('')
const currentPage = ref(1)
const pageSize = 6
const loading = ref(false)
const error = ref('')
const detailVisible = ref(false)
const selectedSubmission = ref<Submission>()
const selectedSource = ref('')
const sourceLoading = ref(false)
const records = ref<Submission[]>([])
const total = ref(0)
const stats = ref<UserStats | null>(null)
const sourceError = ref('')
const lastOpenedSubmission = ref<Submission | null>(null)
let generation = 0
let detailGeneration = 0
let poller: ReturnType<typeof setInterval> | undefined

const languageLabels: Record<Language, string> = { cpp: 'C++', c: 'C', java: 'Java', python: 'Python3' }
const statusOptions = (Object.keys(judgeStatusMap) as JudgeStatus[]).map((value) => ({ value, label: judgeStatusMap[value].label }))
const languageOptions = (Object.keys(languageLabels) as Language[]).map((value) => ({ value, label: languageLabels[value] }))
const acceptedCount = computed(() => records.value.filter((item) => item.status === 'AC').length)
const hasFilters = computed(() => Boolean(keyword.value || status.value || language.value))
const selectedDiagnostic = computed(() => {
  const current = selectedSubmission.value
  const advice: Record<JudgeStatus, { title: string; content: string; hint: string; tone: string }> = {
    PENDING: { title: '提交正在排队', content: '任务已进入真实判题队列。', hint: '无需重复提交，可稍后刷新。', tone: 'pending' },
    JUDGING: { title: '正在判题', content: '判题 Worker 正在处理本次任务。', hint: '结果产生后会自动更新。', tone: 'pending' },
    AC: { title: '所有测试点通过', content: '程序已通过本题测试数据。', hint: '可以回顾思路或继续挑战下一题。', tone: 'success' },
    WA: { title: '答案错误', content: '至少一个测试点输出不符合要求。', hint: '请检查边界条件与输出格式。', tone: 'danger' },
    TLE: { title: '超出时间限制', content: '程序未能在题目时间限制内完成。', hint: '建议检查算法复杂度。', tone: 'warning' },
    MLE: { title: '超出内存限制', content: '程序峰值内存超过题目限制。', hint: '检查大型数组与中间结果。', tone: 'warning' },
    RE: { title: '运行时错误', content: '程序执行期间异常退出。', hint: '检查下标、空指针和非法输入。', tone: 'danger' },
    CE: { title: '编译错误', content: '代码未能通过编译。', hint: '请核对语法和语言版本。', tone: 'danger' },
    SE: { title: '判题系统异常', content: '本次结果不代表代码正确性。', hint: '请稍后重试或联系管理员。', tone: 'neutral' },
  }
  return current ? advice[current.status] : advice.SE
})

async function loadRecords() {
  const current = ++generation
  loading.value = true
  error.value = ''
  try {
    const data = await listSubmissions({ page: currentPage.value, pageSize, keyword: keyword.value.trim() || undefined, status: status.value || undefined, language: language.value || undefined })
    if (current !== generation) return
    records.value = data.items
    total.value = data.total
  } catch (caught) {
    if (current !== generation) return
    error.value = caught instanceof ApiError ? caught.message : '提交记录加载失败'
  } finally {
    if (current === generation) loading.value = false
  }
}

async function refreshRecords(showMessage = false) {
  await loadRecords()
  if (showMessage && !error.value) ElMessage.success('提交记录已更新')
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  language.value = ''
  currentPage.value = 1
  void loadRecords()
}

async function openDetail(submission: Submission) {
  const current = ++detailGeneration
  lastOpenedSubmission.value = submission
  detailVisible.value = true
  selectedSubmission.value = undefined
  selectedSource.value = ''
  sourceLoading.value = true
  sourceError.value = ''
  try {
    const [detail, source] = await Promise.all([getSubmission(submission.id), getSubmissionSource(submission.id)])
    if (current !== detailGeneration) return
    selectedSubmission.value = detail
    selectedSource.value = source.source
  } catch (caught) {
    if (current !== detailGeneration) return
    sourceError.value = caught instanceof ApiError ? caught.message : '提交详情加载失败'
    ElMessage.error(sourceError.value)
  } finally {
    if (current === detailGeneration) sourceLoading.value = false
  }
}

function problemQuery(submission: Pick<Submission, 'contestId'>) {
  // The workspace drops the contest context itself when the contest is not
  // ongoing, so carrying the id here is always safe.
  return submission.contestId ? { contest: submission.contestId } : {}
}

function goToProblem(submission: Pick<Submission, 'problemId' | 'contestId'>) {
  detailVisible.value = false
  void router.push({ path: `/problems/${submission.problemId}`, query: problemQuery(submission) })
}

watch([keyword, status, language], () => { currentPage.value = 1; void loadRecords() })
watch(currentPage, () => { void loadRecords() })
watch(detailVisible, (visible) => {
  if (!visible) selectedSubmission.value = undefined
})

void loadRecords()
void getUserStats().then(value => { stats.value = value }).catch(() => {})
poller = setInterval(() => {
  if (records.value.some(item => item.status === 'PENDING' || item.status === 'JUDGING')) void loadRecords()
  if (selectedSubmission.value && ['PENDING', 'JUDGING'].includes(selectedSubmission.value.status)) {
    void getSubmission(selectedSubmission.value.id).then(item => { selectedSubmission.value = item }).catch(() => {})
  }
}, 4000)
onBeforeUnmount(() => { if (poller) clearInterval(poller); generation += 1 })
</script>

<template>
  <div class="submissions-page">
    <div class="page-heading">
      <div>
        <span class="eyebrow">练习档案</span>
        <h1>提交记录</h1>
        <p>回看每一次判题结果，从反馈中找到下一步优化方向。</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="loading" @click="refreshRecords(true)"><el-icon><Refresh /></el-icon>刷新记录</el-button>
        <el-button type="primary" @click="router.push('/problems')"><el-icon><EditPen /></el-icon>继续刷题</el-button>
      </div>
    </div>

    <section class="summary-strip surface-card" aria-label="提交概况">
      <div><span class="summary-icon blue"><el-icon><Tickets /></el-icon></span><p>累计提交<strong>{{ stats?.submissionCount ?? total }}</strong></p></div>
      <i />
      <div><span class="summary-icon green"><el-icon><CircleCheck /></el-icon></span><p>通过提交<strong>{{ stats?.acceptedCount ?? acceptedCount }}</strong></p></div>
      <i />
      <div><span class="summary-icon orange"><el-icon><DataLine /></el-icon></span><p>真实通过率<strong>{{ stats?.acceptance ?? 0 }}%</strong></p></div>
      <span class="prototype-note">数据来自真实判题服务</span>
    </section>

    <section class="records-card surface-card">
      <div class="filter-bar">
        <el-input v-model="keyword" class="keyword-input" placeholder="搜索提交 ID 或题目" clearable :prefix-icon="Search" />
        <el-select v-model="status" class="status-select" placeholder="全部判题状态" clearable>
          <el-option v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-select v-model="language" class="language-select" placeholder="全部语言" clearable>
          <el-option v-for="option in languageOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
        <el-button class="reset-button" text :disabled="!hasFilters" @click="resetFilters"><el-icon><RefreshLeft /></el-icon>重置</el-button>
      </div>

      <div class="table-meta">
        <span>共找到 <strong>{{ total }}</strong> 条记录</span>
        <span v-if="hasFilters" class="filter-hint">已应用筛选条件</span>
        <span v-else>按提交时间倒序排列</span>
      </div>

      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button text @click="loadRecords">重试</el-button></el-alert>

      <el-table v-loading="loading" :data="records" class="submission-table" row-key="id">
        <el-table-column label="提交 ID" width="112">
          <template #default="{ row }"><span class="mono submission-id">#{{ row.id }}</span></template>
        </el-table-column>
        <el-table-column label="题目" min-width="245">
          <template #default="{ row }">
            <button class="problem-link" @click="goToProblem(row)">
              <span class="problem-number mono">{{ row.problemId }}</span>
              <span>{{ row.problemTitle }}</span>
            </button>
            <div class="problem-extra">
              <span v-if="row.contestTitle"><el-icon><Trophy /></el-icon>{{ row.contestTitle }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="判题状态" width="128">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="语言" width="105">
          <template #default="{ row }"><span class="language-label mono">{{ languageLabels[row.language as Language] }}</span></template>
        </el-table-column>
        <el-table-column label="运行时间" width="105">
          <template #default="{ row }"><span class="mono metric">{{ formatRuntimeMs(row.runtimeMs) }}</span></template>
        </el-table-column>
        <el-table-column label="内存" width="95">
          <template #default="{ row }"><span class="mono metric">{{ formatMemoryKb(row.memoryKb) }}</span></template>
        </el-table-column>
        <el-table-column label="提交时间" width="135">
          <template #default="{ row }"><span class="time-label">{{ formatDateTime(row.createdAt) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="82" fixed="right" align="center">
          <template #default="{ row }"><el-button text type="primary" @click="openDetail(row)">详情</el-button></template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <div class="empty-icon"><el-icon :size="27"><DocumentRemove /></el-icon></div>
            <h3>{{ hasFilters ? '没有符合条件的提交' : '还没有提交记录' }}</h3>
            <p>{{ hasFilters ? '试试调整关键词或清除筛选条件。' : '选择一道题目，写下你的第一份解法吧。' }}</p>
            <el-button v-if="hasFilters" @click="resetFilters">清除筛选</el-button>
            <el-button v-else type="primary" @click="router.push('/problems')">去题库看看</el-button>
          </div>
        </template>
      </el-table>

      <div v-if="total > pageSize" class="pagination-row">
        <span>第 {{ currentPage }} / {{ Math.ceil(total / pageSize) }} 页</span>
        <el-pagination v-model:current-page="currentPage" :page-size="pageSize" :total="total" layout="prev, pager, next" background />
      </div>
    </section>

    <el-dialog v-model="detailVisible" class="submission-dialog" width="570px" destroy-on-close>
      <template #header>
        <div v-if="selectedSubmission" class="dialog-heading">
          <span class="eyebrow">判题反馈</span>
          <h2>提交详情 <span class="mono">#{{ selectedSubmission.id }}</span></h2>
          <StatusTag :status="selectedSubmission.status" />
        </div>
      </template>
      <template v-if="selectedSubmission">
        <div class="detail-problem">
          <span class="detail-problem-icon"><el-icon><Document /></el-icon></span>
          <div><small>提交题目</small><strong>{{ selectedSubmission.problemId }} · {{ selectedSubmission.problemTitle }}</strong></div>
          <el-button text type="primary" @click="goToProblem(selectedSubmission)">前往题目<el-icon><ArrowRight /></el-icon></el-button>
        </div>
        <el-descriptions :column="2" border class="detail-descriptions">
          <el-descriptions-item label="提交时间">{{ formatDateTime(selectedSubmission.createdAt) }}</el-descriptions-item>
          <el-descriptions-item label="编程语言"><span class="mono">{{ languageLabels[selectedSubmission.language] }}</span></el-descriptions-item>
          <el-descriptions-item label="运行时间"><span class="mono">{{ formatRuntimeMs(selectedSubmission.runtimeMs) }}</span></el-descriptions-item>
          <el-descriptions-item label="内存消耗"><span class="mono">{{ formatMemoryKb(selectedSubmission.memoryKb) }}</span></el-descriptions-item>
          <el-descriptions-item v-if="selectedSubmission.contestTitle" label="所属竞赛" :span="2">{{ selectedSubmission.contestTitle }}</el-descriptions-item>
        </el-descriptions>
        <div class="diagnostic" :class="`is-${selectedDiagnostic.tone}`">
          <div class="diagnostic-title"><el-icon><InfoFilled /></el-icon><strong>{{ selectedDiagnostic.title }}</strong><span>信息已脱敏</span></div>
          <pre class="mono">{{ selectedSubmission.diagnostic || selectedDiagnostic.content }}</pre>
          <details v-if="selectedSource" class="source-details"><summary>查看本次提交源码</summary><pre class="mono">{{ selectedSource }}</pre></details>
          <p>{{ selectedDiagnostic.hint }}</p>
        </div>
        <div class="security-note"><el-icon><Lock /></el-icon>评测输入、标准答案及服务器路径均不会公开展示</div>
      </template>
      <div v-else-if="sourceLoading" class="detail-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在加载提交详情…</span></div>
      <div v-else-if="sourceError" class="detail-error"><el-icon><Warning /></el-icon><p>{{ sourceError }}</p><el-button text type="primary" :disabled="!lastOpenedSubmission" @click="lastOpenedSubmission && openDetail(lastOpenedSubmission)">重试</el-button></div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="selectedSubmission" type="primary" @click="goToProblem(selectedSubmission)">再次挑战</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.submissions-page { color: var(--text); }
.submissions-page > .page-heading { position: relative; }
.submissions-page > .page-heading .eyebrow { margin-bottom: 6px; }
.heading-actions { display: flex; gap: 10px; }
.summary-strip { min-height: 92px; display: flex; align-items: center; gap: 28px; padding: 18px 24px; margin-bottom: 20px; border: 0; border-radius: 10px; box-shadow: none; }
.summary-strip > div { display: flex; align-items: center; gap: 13px; }
.summary-strip > i { width: 1px; height: 35px; background: var(--border); }
.summary-icon { width: 39px; height: 39px; border-radius: 8px; display: grid; place-items: center; font-size: 18px; }
.summary-icon.blue { color: var(--primary); background: var(--primary-soft); }.summary-icon.green { color: var(--success); background: #eaf7f1; }.summary-icon.orange { color: #c87620; background: var(--accent-soft); }
.summary-strip p { margin: 0; display: flex; flex-direction: column; color: var(--text-secondary); font-size: 10px; gap: 3px; }
.summary-strip strong { color: var(--text-strong); font-size: 22px; letter-spacing: -.5px; }
.summary-strip strong small { color: var(--text-tertiary); font-size: 12px; font-weight: 400; }
.summary-strip .prototype-note { margin-left: auto; }
.summary-strip .prototype-note::before { background: var(--accent); }
.records-card { overflow: hidden; border-radius: 10px; box-shadow: none; }
.filter-bar { padding: 20px 22px; display: flex; align-items: center; gap: 11px; border-bottom: 1px solid var(--border); background: #f8fbff; }
.keyword-input { width: min(340px, 100%); }.status-select { width: 158px; }.language-select { width: 137px; }
.filter-bar :deep(.el-input__wrapper), .filter-bar :deep(.el-select__wrapper) { background: #fff; }
.reset-button { margin-left: auto; }
.table-meta { display: flex; justify-content: space-between; padding: 15px 22px 3px; color: var(--text-tertiary); font-size: 11px; }
.table-meta strong { color: var(--text-secondary); }.filter-hint { color: var(--primary); }
.submission-table { width: 100%; --el-table-header-bg-color: #f7faff; --el-table-row-hover-bg-color: #f5f9ff; }
.submission-table :deep(.el-table__header th) { color: var(--text-secondary); font-size: 11px; }
.submission-id { color: var(--text-tertiary); font-size: 11px; }
.problem-link { display: flex; align-items: center; gap: 8px; max-width: 100%; padding: 0; border: 0; background: transparent; color: var(--text-strong); font-weight: 500; cursor: pointer; text-align: left; }
.problem-link:hover { color: var(--primary); }
.problem-number { color: var(--primary); background: var(--primary-soft); border-radius: 4px; padding: 2px 5px; font-size: 10px; font-weight: 500; }
.problem-extra { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.problem-extra > span:last-child:not(.difficulty) { display: inline-flex; align-items: center; gap: 4px; color: var(--text-tertiary); font-size: 9px; max-width: 185px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.language-label { color: var(--text); font-size: 11px; padding: 4px 7px; border-radius: 5px; background: #f0f5fb; }
.metric { font-size: 11px; color: var(--text-secondary); }.time-label { color: var(--text-secondary); font-size: 11px; }
.submission-table :deep(.el-table__inner-wrapper::before) { display: none; }
.submission-table :deep(.el-table__body td) { border-bottom-color: #e9eff7; }
.submission-table :deep(.el-table__empty-block) { min-height: 310px; }
.submission-table :deep(.empty-icon) { color: var(--primary); background: var(--primary-soft); }
.pagination-row { padding: 18px 22px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: #fbfdff; }
.pagination-row > span { color: var(--text-tertiary); font-size: 11px; }
.dialog-heading { position: relative; padding-right: 28px; }
.dialog-heading .eyebrow { margin-bottom: 5px; }
.dialog-heading h2 { color: var(--text-strong); font-size: 20px; margin: 0 0 12px; }
.dialog-heading h2 span { color: var(--text-tertiary); font-size: 13px; font-weight: 400; }
.detail-problem { display: flex; align-items: center; gap: 12px; padding: 13px 14px; border: 1px solid #d7e5f7; border-radius: 8px; background: #f5f9ff; margin-bottom: 17px; }
.detail-problem-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; background: #fff; color: var(--primary); }
.detail-problem div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.detail-problem small { color: var(--text-tertiary); font-size: 9px; }.detail-problem strong { color: var(--text-strong); font-size: 12px; }
.detail-problem .el-button { margin-left: auto; flex: none; font-size: 11px; }
.detail-descriptions { margin-bottom: 17px; }
.detail-descriptions :deep(.el-descriptions__label) { color: var(--text-secondary); background: #f7faff; font-size: 11px; width: 78px; }
.detail-descriptions :deep(.el-descriptions__content) { color: var(--text); font-size: 11px; }
.diagnostic { border-radius: 8px; padding: 15px 16px; background: #f5f8fc; border: 1px solid var(--border); }
.diagnostic-title { display: flex; align-items: center; gap: 7px; color: var(--text-secondary); }
.diagnostic-title strong { font-size: 12px; }.diagnostic-title span { margin-left: auto; color: var(--text-tertiary); font-size: 9px; }
.diagnostic pre { white-space: pre-wrap; word-break: break-word; margin: 12px 0 8px; color: var(--text-secondary); font-size: 10px; line-height: 1.8; font-family: 'JetBrains Mono', Consolas, monospace; }
.diagnostic p { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.7; }
.diagnostic.is-success { background: #f2faf6; border-color: #dbeee5; }.diagnostic.is-success .diagnostic-title { color: var(--success); }
.diagnostic.is-danger { background: #fff7f7; border-color: #f6e2e4; }.diagnostic.is-danger .diagnostic-title { color: var(--danger); }
.diagnostic.is-warning { background: #fffaf2; border-color: #f2dfc3; }.diagnostic.is-warning .diagnostic-title { color: #b86c1c; }
.diagnostic.is-pending { background: #f3f7ff; border-color: #d7e5f8; }.diagnostic.is-pending .diagnostic-title { color: var(--primary); }
.security-note { display: flex; justify-content: center; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 9px; margin-top: 15px; }
.detail-loading { display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-secondary); font-size: 12px; padding: 42px 0; }
.detail-error { display: flex; flex-direction: column; align-items: center; gap: 9px; color: var(--text-secondary); font-size: 12px; padding: 34px 0; text-align: center; }
:global(.submission-dialog) { max-width: calc(100vw - 30px); border-radius: 10px; }
@media (max-width: 1000px) {
  .summary-strip .prototype-note { display: none; }
  .filter-bar { flex-wrap: wrap; }
  .keyword-input { flex: 1; min-width: 250px; }
  .reset-button { margin-left: 0; }
}
@media (max-width: 760px) {
  .summary-strip { gap: 16px; padding: 15px; justify-content: space-between; }
  .summary-strip > i { display: none; }
  .summary-strip > div { gap: 8px; }
  .summary-icon { width: 32px; height: 32px; font-size: 15px; }
  .summary-strip strong { font-size: 18px; }
  .filter-bar { padding: 15px; gap: 9px; }
  .keyword-input { width: 100%; min-width: 100%; }
  .status-select, .language-select { flex: 1; min-width: 130px; }
  .table-meta { padding-left: 15px; padding-right: 15px; }
  .pagination-row { padding: 15px; }
  .pagination-row > span { display: none; }
  .pagination-row .el-pagination { margin: auto; }
}
@media (max-width: 480px) {
  .heading-actions { width: 100%; }
  .heading-actions .el-button { flex: 1; }
  .summary-strip { display: grid; grid-template-columns: repeat(3, 1fr); }
  .summary-strip > div { flex-direction: column; text-align: center; }
  .summary-strip p { font-size: 9px; }
  .filter-bar .el-select { width: calc(50% - 5px); min-width: 0; }
  .reset-button { width: 100%; }
  .table-meta > span:last-child { display: none; }
  .detail-problem { flex-wrap: wrap; }
  .detail-problem .el-button { margin-left: 46px; }
}
</style>
