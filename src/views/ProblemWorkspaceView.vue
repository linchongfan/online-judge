<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import CodeEditor from '../components/CodeEditor.vue'
import DifficultyTag from '../components/DifficultyTag.vue'
import StatusTag from '../components/StatusTag.vue'
import { getProblem, getProblemSolution, listProblems, runProblemSample } from '../api/problems'
import { createSubmission, listSubmissions } from '../api/submissions'
import { getContest } from '../api/contests'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { useSubmissionPolling } from '../composables/useSubmissionPolling'
import { createIdempotencyKey, formatDateTime, formatMemoryKb, formatRuntimeMs, judgeStatusMap } from '../utils/format'
import type { Contest, JudgeStatus, Language, Problem, Solution, Submission } from '../types'

const route = useRoute()
const router = useRouter()
const language = ref<Language>('cpp')
const code = ref('')
const activeLeftTab = ref('description')
const solutionLanguage = ref<Language>('cpp')
const solutionLanguages: Language[] = ['cpp', 'c', 'java', 'python']
const storedPaneWidth = Number(storageGet('xinbaoyan-pane-width'))
const leftPaneWidth = ref(storedPaneWidth >= 28 && storedPaneWidth <= 70 ? storedPaneWidth : 45)
const workspaceBody = ref<HTMLElement>()
const resizing = ref(false)
const consoleTab = ref('run')
const consoleOpen = ref(true)
const running = ref(false)
const judging = ref<JudgeStatus | 'idle' | 'done'>('idle')
const saved = ref(true)
const storageReady = ref(true)
let warnedStorage = false
function storageGet(key: string): string | null {
  try { return localStorage.getItem(key) } catch { storageReady.value = false; return null }
}
function storageSet(key: string, value: string): boolean {
  try { localStorage.setItem(key, value); storageReady.value = true; return true } catch {
    storageReady.value = false
    if (!warnedStorage) { warnedStorage = true; ElMessage.warning('浏览器本地存储不可用，草稿仅保留在当前页面') }
    return false
  }
}
function storageRemove(key: string) { try { localStorage.removeItem(key) } catch { storageReady.value = false } }
const loading = ref(true)
const loadError = ref('')
const problem = ref<Problem>({ id: 0, title: '题目加载中', difficulty: '简单', tags: [], acceptance: 0, submissionCount: 0, solvedCount: 0, progress: 'untouched', description: [], inputDescription: '', outputDescription: '', constraints: [], samples: [], timeLimitMs: 0, memoryLimitMb: 0, updatedAt: '' })
const solution = ref<Solution | null>(null)
const solutionError = ref('')
const problemSubmissions = ref<Submission[]>([])
const contest = ref<Contest | null>(null)
const globalProblemIds = ref<number[]>([])
const problemIds = computed(() => contest.value ? contest.value.problems.map(item => item.problemId) : globalProblemIds.value)
const currentSubmission = ref<Submission | null>(null)
const activeSubmissionId = ref<string | null>(null)
const operation = ref<'sample' | 'submit'>('submit')
const languageLabels: Record<Language, string> = { cpp: 'C++11', c: 'C99', java: 'JDK 8', python: 'Python 3.8.6' }
let saveTimer: ReturnType<typeof setTimeout> | undefined
let loadGeneration = 0

const solutionCode = computed(() => solution.value?.codes.find(item => item.language === solutionLanguage.value)?.code ?? '')
const solutionMissing = computed(() => solution.value !== null && !solutionCode.value)
const problemIndex = computed(() => problemIds.value.indexOf(problem.value.id))
const finalStatus = computed<JudgeStatus>(() => currentSubmission.value?.status ?? 'AC')
function judgeStatusText(status: JudgeStatus): string { return judgeStatusMap[status].label }
const busy = computed(() => running.value || judging.value === 'PENDING' || judging.value === 'JUDGING')
const polling = useSubmissionPolling(activeSubmissionId, {
  immediate: false,
  pollIntervalMs: 800,
  onUpdate: item => {
    currentSubmission.value = item
    if (operation.value === 'sample') {
      running.value = item.status === 'PENDING' || item.status === 'JUDGING'
      judging.value = item.status
    } else {
      judging.value = ['PENDING', 'JUDGING'].includes(item.status) ? item.status : 'done'
    }
  },
  onTerminal: () => {
    running.value = false
    if (operation.value === 'submit') judging.value = 'done'
    void loadProblemSubmissions()
  },
})

function persistPaneWidth() { storageSet('xinbaoyan-pane-width', String(leftPaneWidth.value)) }
function startResize(event: PointerEvent) {
  if (window.innerWidth <= 760) return
  resizing.value = true
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function resizePane(event: PointerEvent) {
  if (!resizing.value || !workspaceBody.value) return
  const rect = workspaceBody.value.getBoundingClientRect()
  leftPaneWidth.value = Math.min(70, Math.max(28, (event.clientX - rect.left) / rect.width * 100))
}
function stopResize() { if (resizing.value) { resizing.value = false; persistPaneWidth() } }
function adjustPaneWidth(delta: number) { leftPaneWidth.value = Math.min(70, Math.max(28, leftPaneWidth.value + delta)); persistPaneWidth() }
function resetPaneWidth() { leftPaneWidth.value = 45; persistPaneWidth() }

function templateFor(item: Problem, lang: Language) {
  const templates: Record<Language, string> = {
    cpp: `#include <iostream>\nusing namespace std;\n\n// ${item.title}\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n\n    // 在这里编写你的解法\n    \n    return 0;\n}`,
    c: `#include <stdio.h>\n\n// ${item.title}\nint main(void) {\n    // 在这里编写你的解法\n    \n    return 0;\n}`,
    java: `import java.util.*;\n\npublic class Main {\n    // ${item.title}\n    public static void main(String[] args) {\n        Scanner scanner = new Scanner(System.in);\n        // 在这里编写你的解法\n        \n    }\n}`,
    python: `import sys\n\n# ${item.title}\ndef solution():\n    # 在这里编写你的解法\n    pass\n\nif __name__ == "__main__":\n    solution()`,
  }
  return templates[lang]
}
function draftKey(id = problem.value.id, lang = language.value) {
  return `cloudcode-draft-${session.profile?.id ?? 'guest'}-${id}-${lang}`
}
function loadDraft() {
  code.value = storageGet(draftKey()) ?? templateFor(problem.value, language.value)
  judging.value = 'idle'
  currentSubmission.value = null
  running.value = false
  solutionLanguage.value = 'cpp'
  consoleTab.value = 'run'
}
function changeLanguage(value: Language) {
  storageSet(draftKey(), code.value)
  language.value = value
  code.value = storageGet(draftKey()) ?? templateFor(problem.value, value)
}
async function resetCode() {
  try { await ElMessageBox.confirm('将恢复当前语言的初始代码，已编辑的内容会被清除。', '重置代码', { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'warning' }) } catch { return }
  code.value = templateFor(problem.value, language.value)
  storageRemove(draftKey())
  ElMessage.success('已恢复初始代码')
}
function requireLogin(): boolean {
  if (session.loggedIn) return true
  void router.push({ path: '/login', query: { redirect: route.fullPath } })
  return false
}
function newSubmission(operationName: 'sample' | 'submit', accepted: { id: string; status: JudgeStatus }) {
  operation.value = operationName
  activeSubmissionId.value = accepted.id
  judging.value = accepted.status
  polling.start()
}
async function runSample() {
  if (busy.value || !requireLogin()) return
  if (!code.value.trim()) { ElMessage.warning('请先编写代码'); return }
  consoleOpen.value = true
  consoleTab.value = 'run'
  running.value = true
  try {
    const accepted = await runProblemSample(problem.value.id, { language: language.value, source: code.value, contestId: contest.value?.id, idempotencyKey: createIdempotencyKey() })
    newSubmission('sample', accepted)
  } catch (error) {
    running.value = false
    judging.value = 'idle'
    ElMessage.error(error instanceof ApiError ? error.message : '样例运行失败')
  }
}
async function submitCode() {
  if (busy.value || !requireLogin()) return
  if (!code.value.trim()) { ElMessage.warning('请先编写代码'); return }
  consoleOpen.value = true
  consoleTab.value = 'result'
  judging.value = 'PENDING'
  try {
    const accepted = await createSubmission({ problemId: problem.value.id, contestId: contest.value?.id, language: language.value, source: code.value, idempotencyKey: createIdempotencyKey() })
    newSubmission('submit', accepted)
  } catch (error) {
    judging.value = 'idle'
    ElMessage.error(error instanceof ApiError ? error.message : '提交失败')
  }
}
async function copyText(text: string, successMessage = '样例输入已复制') {
  try { await navigator.clipboard.writeText(text); ElMessage.success(successMessage) } catch { ElMessage.info('请手动选择并复制内容') }
}
async function useSolution() {
  if (!solutionCode.value || !solution.value) return
  try { await ElMessageBox.confirm('参考代码会替换编辑器中的当前内容，建议先保存自己的解法。', '使用参考代码', { confirmButtonText: '放入编辑器', cancelButtonText: '保留我的代码', type: 'warning' }) } catch { return }
  language.value = solutionLanguage.value
  code.value = solutionCode.value
  storageSet(draftKey(problem.value.id, solutionLanguage.value), code.value)
  ElMessage.success(`${languageLabels[solutionLanguage.value]} 参考代码已放入编辑器`)
}
function changeLeftTab(tab: string) {
  activeLeftTab.value = tab
  if (tab === 'solution') void loadSolution()
  if (tab === 'submissions') void loadProblemSubmissions()
  nextTick(() => document.querySelector('.problem-pane .description-scroll')?.scrollTo({ top: 0 }))
}
function goToProblem(offset: number) {
  if (!problemIds.value.length || problemIndex.value < 0) return
  const next = problemIds.value[(problemIndex.value + offset + problemIds.value.length) % problemIds.value.length]
  void router.push({ path: `/problems/${next}`, query: contest.value ? { contest: contest.value.id } : {} })
}
function showHistoryResult(item: Submission) {
  currentSubmission.value = item
  operation.value = 'submit'
  judging.value = 'done'
  consoleTab.value = 'result'
  consoleOpen.value = true
}
async function loadSolution() {
  // Retry must be allowed: this same function backs the "重新加载" button
  // shown when solutionError is set.
  if (solution.value) return
  const generation = loadGeneration
  solutionError.value = ''
  try {
    const result = await getProblemSolution(problem.value.id)
    if (generation !== loadGeneration) return
    solution.value = result
  } catch (error) {
    if (generation === loadGeneration) solutionError.value = error instanceof ApiError ? error.message : '题解加载失败'
  }
}
async function loadProblemSubmissions() {
  if (!session.loggedIn || !problem.value.id) { problemSubmissions.value = []; return }
  try { problemSubmissions.value = (await listSubmissions({ problemId: problem.value.id, page: 1, pageSize: 6 })).items } catch { problemSubmissions.value = [] }
}
async function loadWorkspace() {
  const generation = ++loadGeneration
  polling.stop()
  activeSubmissionId.value = null
  loading.value = true
  loadError.value = ''
  solution.value = null
  solutionError.value = ''
  try {
    const contestId = route.query.contest ? Number(route.query.contest) : undefined
    // Contest context is best-effort: cancelled/archived contests fall back to
    // practice mode, and only ongoing contests keep submission context.
    let contestData: Contest | null = null
    if (contestId) {
      try { contestData = await getContest(contestId) } catch { contestData = null }
    }
    const problemData = await getProblem(Number(route.params.id), contestData ? contestId : undefined)
    if (generation !== loadGeneration) return
    problem.value = problemData
    contest.value = contestData && contestData.status === 'ongoing' ? contestData : null
    loadDraft()
    void loadProblemSubmissions()
    if (activeLeftTab.value === 'solution') void loadSolution()
  } catch (error) {
    if (generation === loadGeneration) loadError.value = error instanceof ApiError ? error.message : '题目加载失败'
  } finally {
    if (generation === loadGeneration) loading.value = false
  }
}

watch(code, () => {
  saved.value = false
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => { if (storageSet(draftKey(), code.value)) saved.value = true }, 500)
})
watch(() => [route.params.id, route.query.contest], loadWorkspace)
watch(() => polling.error.value, (error) => {
  if (!error) return
  // Permanent polling failure (network/auth/not-found): release the UI so the
  // user can retry or navigate away instead of waiting forever.
  running.value = false
  judging.value = 'idle'
  polling.stop()
  ElMessage.error(error instanceof ApiError ? error.message : '判题状态获取失败，请稍后重试')
})
onMounted(() => {
  void loadWorkspace()
  void listProblems({ page: 1, pageSize: 100 }).then(data => { globalProblemIds.value = data.items.map(item => item.id) }).catch(() => {})
})
onBeforeUnmount(() => {
  polling.stop()
  if (saveTimer) clearTimeout(saveTimer)
  if (problem.value.id) storageSet(draftKey(), code.value)
})
</script>

<template>
  <div class="workspace-shell" v-loading="loading">
    <div class="workspace-topbar">
      <div class="workspace-breadcrumb">
        <button class="back-button" aria-label="返回" @click="contest ? router.push(`/contests/${contest.id}`) : router.push('/problems')"><el-icon><ArrowLeft /></el-icon></button>
        <span v-if="contest" class="contest-label">{{ contest.title }}<i>/</i></span>
        <strong>{{ problem.id }}. {{ problem.title }}</strong><DifficultyTag :difficulty="problem.difficulty" />
      </div>
      <div class="problem-switcher"><el-button text :icon="'ArrowLeft'" aria-label="上一题" @click="goToProblem(-1)" /><span>{{ problemIndex + 1 }} / {{ problemIds.length }}</span><el-button text :icon="'ArrowRight'" aria-label="下一题" @click="goToProblem(1)" /></div>
      <span class="prototype-note">真实判题服务</span>
    </div>

    <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false"><el-button text @click="loadWorkspace">重新加载</el-button></el-alert>

    <div ref="workspaceBody" class="workspace-body" :class="{ resizing }" :style="{ '--left-pane-width': `${leftPaneWidth}%` }">
      <section class="problem-pane">
        <div class="pane-tabs">
          <button :class="{ active: activeLeftTab === 'description' }" @click="changeLeftTab('description')"><el-icon><Document /></el-icon>题目描述</button>
          <button :class="{ active: activeLeftTab === 'solution' }" @click="changeLeftTab('solution')"><el-icon><Reading /></el-icon>题解</button>
          <button :class="{ active: activeLeftTab === 'submissions' }" @click="changeLeftTab('submissions')"><el-icon><List /></el-icon>我的提交</button>
        </div>
        <div v-if="activeLeftTab === 'description'" class="description-scroll">
          <div class="problem-heading"><span class="problem-number">{{ problem.id }}</span><h1>{{ problem.title }}</h1><div class="problem-meta"><DifficultyTag :difficulty="problem.difficulty" /><span><el-icon><Clock /></el-icon>{{ formatRuntimeMs(problem.timeLimitMs) }}</span><span><el-icon><Coin /></el-icon>{{ problem.memoryLimitMb }} MB</span></div><div class="problem-tags"><span v-for="item in problem.tags" :key="item">{{ item }}</span></div></div>
          <div class="problem-description"><p v-for="paragraph in problem.description" :key="paragraph">{{ paragraph }}</p></div>
          <div class="io-description"><h3>输入描述</h3><p>{{ problem.inputDescription }}</p><h3>输出描述</h3><p>{{ problem.outputDescription }}</p></div>
          <div v-for="(sample, index) in problem.samples" :key="index" class="sample-block">
            <div class="sample-title"><h3>样例 {{ index + 1 }}</h3><button @click="copyText(sample.input)"><el-icon><CopyDocument /></el-icon>复制输入</button></div>
            <div class="sample-row"><span>输入</span><pre>{{ sample.input }}</pre></div><div class="sample-row"><span>输出</span><pre>{{ sample.output }}</pre></div><p v-if="sample.explanation" class="sample-explanation"><strong>解释：</strong>{{ sample.explanation }}</p>
          </div>
          <div class="constraints"><h3>数据范围与提示</h3><ul><li v-for="item in problem.constraints" :key="item">{{ item }}</li></ul></div>
          <div class="problem-stats"><div><strong>{{ problem.acceptance }}%</strong><span>通过率</span></div><div><strong>{{ problem.solvedCount.toLocaleString() }}</strong><span>通过人数</span></div><div><strong>{{ problem.submissionCount.toLocaleString() }}</strong><span>总提交</span></div></div>
        </div>
        <div v-else-if="activeLeftTab === 'solution' && solution" class="description-scroll solution-pane">
          <div class="solution-intro">
            <div class="solution-brand"><span><el-icon><Reading /></el-icon>精选题解</span><small>新保研教研组</small></div>
            <h1>{{ solution.title }}</h1>
            <div class="solution-tags"><DifficultyTag :difficulty="problem.difficulty" /><span v-for="item in problem.tags" :key="item">{{ item }}</span></div>
            <p>{{ solution.summary }}</p>
          </div>

          <section class="solution-section">
            <h2><span>01</span>解题思路</h2>
            <ol class="solution-steps"><li v-for="(step, index) in solution.steps" :key="step"><span>{{ index + 1 }}</span><p>{{ step }}</p></li></ol>
          </section>

          <section class="solution-section">
            <h2><span>02</span>复杂度分析</h2>
            <div class="complexity-grid"><div><span>时间复杂度</span><strong>{{ solution.time }}</strong><small>输入规模决定主要计算量</small></div><div><span>空间复杂度</span><strong>{{ solution.space }}</strong><small>不计输入与返回值本身</small></div></div>
          </section>

          <section class="solution-section reference-section">
            <div class="reference-heading"><h2><span>03</span>参考实现</h2><button :disabled="solutionMissing" @click="copyText(solutionCode, `${languageLabels[solutionLanguage]} 代码已复制`)"><el-icon><CopyDocument /></el-icon>复制</button></div>
            <div class="solution-language-tabs" role="tablist" aria-label="参考代码语言"><button v-for="lang in solutionLanguages" :key="lang" role="tab" :aria-selected="solutionLanguage === lang" :class="{ active: solutionLanguage === lang }" @click="solutionLanguage = lang">{{ languageLabels[lang] }}</button></div>
            <div class="reference-code"><div class="code-caption"><span><i /><i /><i /></span><small>solution.{{ solutionLanguage === 'python' ? 'py' : solutionLanguage === 'java' ? 'java' : solutionLanguage === 'cpp' ? 'cpp' : 'c' }}</small></div><pre v-if="solutionMissing" class="solution-missing">该语言暂未提供参考实现，请切换其他语言。</pre><pre v-else><code>{{ solutionCode }}</code></pre></div>
            <el-button type="primary" class="use-solution" :disabled="solutionMissing" @click="useSolution"><el-icon><EditPen /></el-icon>将 {{ languageLabels[solutionLanguage] }} 代码放入编辑器</el-button>
          </section>
          <div class="solution-note"><el-icon><InfoFilled /></el-icon><p>参考实现用于理解算法思路。提交前请结合题目输入输出格式补齐代码，并尝试自己说明每一步的原因。</p></div>
        </div>
        <div v-else-if="activeLeftTab === 'solution'" class="description-scroll"><div class="empty-state"><h3>题解暂不可用</h3><p>{{ solutionError || '本题暂未提供官方题解' }}</p><el-button v-if="solutionError" @click="loadSolution">重新加载</el-button></div></div>
        <div v-else class="description-scroll submission-history">
          <div class="section-heading"><div><h3>本题提交记录</h3><p>只展示当前账号的最近提交</p></div><el-button text @click="router.push('/submissions')">全部记录<el-icon><ArrowRight /></el-icon></el-button></div>
          <button v-for="item in problemSubmissions" :key="item.id" class="history-item" @click="showHistoryResult(item)">
            <StatusTag :status="item.status" /><div><strong>#{{ item.id }}</strong><span>{{ formatDateTime(item.createdAt) }} · {{ languageLabels[item.language] }}</span></div><div class="history-metrics"><span>{{ formatRuntimeMs(item.runtimeMs) }}</span><small>{{ formatMemoryKb(item.memoryKb) }}</small></div>
          </button>
          <div v-if="!problemSubmissions.length" class="empty-state"><div class="empty-icon"><el-icon :size="25"><Document /></el-icon></div><h3>还没有提交记录</h3><p>完成代码后，点击右下角提交</p></div>
        </div>
      </section>

      <div class="pane-resizer" role="separator" aria-label="调整题面与编辑器宽度" aria-orientation="vertical" :aria-valuenow="Math.round(leftPaneWidth)" aria-valuemin="28" aria-valuemax="70" tabindex="0" title="拖动调整宽度，双击恢复默认" @pointerdown="startResize" @pointermove="resizePane" @pointerup="stopResize" @pointercancel="stopResize" @keydown.left.prevent="adjustPaneWidth(-2)" @keydown.right.prevent="adjustPaneWidth(2)" @dblclick="resetPaneWidth"><span /></div>
      <section class="editor-pane">
        <div class="editor-toolbar">
          <el-select :model-value="language" size="small" @change="changeLanguage">
            <el-option v-for="(label, key) in languageLabels" :key="key" :label="label" :value="key" />
          </el-select>
          <span class="editor-file mono">main.{{ language === 'python' ? 'py' : language === 'java' ? 'java' : language === 'cpp' ? 'cpp' : 'c' }}</span>
          <div class="editor-actions"><span class="save-state"><el-icon><CircleCheck /></el-icon>{{ !storageReady ? '本地存储不可用' : saved ? '已保存到本机' : '正在保存…' }}</span><el-button text size="small" @click="resetCode"><el-icon><RefreshLeft /></el-icon>重置</el-button></div>
        </div>
        <div class="monaco-wrap"><CodeEditor v-model="code" :language="language" /></div>
        <div class="console-panel" :class="{ collapsed: !consoleOpen }">
          <div class="console-header">
            <div><button :class="{ active: consoleTab === 'run' }" @click="consoleTab = 'run'; consoleOpen = true">运行结果</button><button :class="{ active: consoleTab === 'result' }" @click="consoleTab = 'result'; consoleOpen = true">判题结果<span v-if="judging === 'done'" class="result-dot" :class="finalStatus.toLowerCase()" /></button></div>
            <button class="console-toggle" :aria-expanded="consoleOpen" aria-label="折叠或展开结果面板" @click="consoleOpen = !consoleOpen"><el-icon><ArrowDown v-if="consoleOpen" /><ArrowUp v-else /></el-icon></button>
          </div>
          <div v-show="consoleOpen" class="console-content">
            <template v-if="consoleTab === 'run'">
              <div v-if="running" class="console-loading"><el-icon class="is-loading"><Loading /></el-icon><span>正在运行公开样例…</span></div>
              <div v-else-if="currentSubmission && operation === 'sample'" class="run-result" :class="{ failed: currentSubmission.status !== 'AC' }"><div class="run-success"><StatusTag :status="currentSubmission.status" /><strong>{{ problem.samples.length }} 个公开样例运行完成</strong><span>仅验证样例，不代表通过全部测试点</span></div><div class="testcase-row"><span><i />整体结果</span><pre>{{ currentSubmission.diagnostic || judgeStatusText(currentSubmission.status) }}</pre><strong>{{ formatRuntimeMs(currentSubmission.runtimeMs) }}</strong><small>{{ formatMemoryKb(currentSubmission.memoryKb) }}</small></div></div>
              <div v-else class="console-placeholder"><el-icon><VideoPlay /></el-icon><span>登录后运行公开样例，结果将显示在这里</span></div>
            </template>
            <template v-else>
              <div v-if="judging === 'idle'" class="console-placeholder"><el-icon><Upload /></el-icon><span>提交代码后，在这里查看判题状态与资源消耗</span></div>
              <div v-else-if="judging === 'PENDING' || judging === 'JUDGING'" class="judging-progress"><div class="judging-line"><el-icon class="is-loading"><Loading /></el-icon><div><strong>{{ judging === 'PENDING' ? '提交已进入判题队列' : '正在运行测试点…' }}</strong><span>{{ judging === 'PENDING' ? '正在等待可用的判题 Worker' : '隐藏测试数据已安全隔离' }}</span></div><StatusTag :status="judging" /></div><p class="queue-note">结果由独立判题服务返回，请勿重复提交</p></div>
              <div v-else class="final-result" :class="finalStatus === 'AC' ? 'accepted' : 'wrong'"><div class="result-summary"><span class="result-icon"><el-icon><CircleCheckFilled v-if="finalStatus === 'AC'" /><CircleCloseFilled v-else /></el-icon></span><div><StatusTag :status="finalStatus" /><span>{{ currentSubmission?.diagnostic || judgeStatusText(finalStatus) }}</span></div><div class="result-metrics"><span><small>执行用时</small><strong>{{ formatRuntimeMs(currentSubmission?.runtimeMs) }}</strong></span><span><small>消耗内存</small><strong>{{ formatMemoryKb(currentSubmission?.memoryKb) }}</strong></span></div></div><p v-if="finalStatus !== 'AC'"><el-icon><InfoFilled /></el-icon>隐藏测试输入、标准答案和内部路径不会展示。</p></div>
            </template>
          </div>
        </div>
        <div class="editor-footer"><span><el-icon><InfoFilled /></el-icon>支持公开样例运行 · 正式提交将测试隐藏数据</span><div><el-button :disabled="busy" @click="runSample"><el-icon><VideoPlay /></el-icon>运行样例</el-button><el-button type="primary" :loading="busy" @click="submitCode"><el-icon v-if="!busy"><Upload /></el-icon>{{ busy ? '判题中…' : '提交代码' }}</el-button></div></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.workspace-shell { height: 100%; min-height: 0; overflow: hidden; display: flex; flex-direction: column; background: #fff; }
.workspace-topbar { height: 53px; flex: none; border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 max(var(--content-gutter), calc((100vw - var(--content-max)) / 2 + var(--content-gutter))); gap: 16px; background: #fff; }
.workspace-breadcrumb { display: flex; align-items: center; gap: 10px; min-width: 0; }.workspace-breadcrumb strong { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.back-button { width: 28px; height: 28px; border: 0; border-radius: 6px; background: var(--surface-soft); color: var(--text-secondary); cursor: pointer; display: grid; place-items: center; }.back-button:hover { color: var(--primary); background: var(--primary-soft); }.contest-label { font-size: 11px; color: var(--text-tertiary); }.contest-label i { font-style: normal; margin-left: 8px; }
.problem-switcher { display: flex; align-items: center; gap: 2px; margin-left: auto; color: var(--text-tertiary); font-size: 10px; }.problem-switcher .el-button { padding: 5px; }.workspace-topbar > .prototype-note { margin-left: 8px; }
.workspace-body { display: flex; flex: 1; min-height: 0; }
.workspace-body.resizing { cursor: col-resize; user-select: none; }
.pane-resizer { width: 7px; flex: none; display: grid; place-items: center; cursor: col-resize; touch-action: none; background: #edf2f8; border-inline: 1px solid #dfe8f3; }
.pane-resizer > span { width: 2px; height: 34px; border-left: 2px dotted #a6b7ca; }
.pane-resizer:hover, .workspace-body.resizing .pane-resizer, .pane-resizer:focus-visible { background: var(--primary-soft); }
.pane-resizer:hover > span, .workspace-body.resizing .pane-resizer > span { border-color: var(--primary); }
.workspace-body.resizing .problem-pane, .workspace-body.resizing .editor-pane { pointer-events: none; }
.problem-pane { width: var(--left-pane-width, 45%); min-width: 0; flex: none; border-right: 0; display: flex; flex-direction: column; min-height: 0; background: #fff; }
.pane-tabs { height: 48px; flex: none; display: flex; align-items: stretch; gap: 24px; padding: 0 23px; border-bottom: 1px solid var(--border); }.pane-tabs button { border: 0; background: none; position: relative; display: flex; align-items: center; gap: 6px; color: var(--text-tertiary); font-size: 12px; cursor: pointer; }.pane-tabs button.active { color: var(--primary); font-weight: 600; }.pane-tabs button.active::after { content: ''; position: absolute; height: 2px; background: var(--primary); bottom: -1px; left: 0; right: 0; }
.description-scroll { overflow-y: auto; padding: 25px 28px 40px; flex: 1; }.problem-number { color: var(--text-tertiary); font-size: 11px; font-weight: 600; }.problem-heading h1 { font-size: 23px; letter-spacing: -.5px; margin: 5px 0 13px; color: var(--text-strong); }.problem-meta { display: flex; align-items: center; gap: 15px; }.problem-meta > span { display: flex; align-items: center; gap: 4px; color: var(--text-tertiary); font-size: 10px; }.problem-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 13px; }.problem-tags span { padding: 4px 8px; border-radius: 5px; background: #f4f4f8; color: var(--text-secondary); font-size: 10px; }
.problem-description { margin-top: 24px; }.problem-description p, .io-description p { color: #525563; font-size: 13px; line-height: 1.9; margin: 0 0 12px; }.description-scroll h3 { color: var(--text-strong); font-size: 13px; margin: 22px 0 9px; }.io-description { margin-top: 20px; }
.sample-block { margin-top: 20px; border: 1px solid var(--border); border-radius: 9px; overflow: hidden; background: #fafafd; }.sample-title { display: flex; align-items: center; justify-content: space-between; padding: 0 13px; border-bottom: 1px solid var(--border); background: #fff; }.sample-title h3 { margin: 11px 0; }.sample-title button { display: flex; gap: 4px; align-items: center; border: 0; background: transparent; color: var(--text-tertiary); font-size: 10px; cursor: pointer; }.sample-title button:hover { color: var(--primary); }.sample-row { display: grid; grid-template-columns: 40px 1fr; gap: 10px; padding: 10px 13px; }.sample-row > span { color: var(--text-tertiary); font-size: 10px; padding-top: 2px; }.sample-row pre { margin: 0; white-space: pre-wrap; color: #424454; font: 11px/1.7 'JetBrains Mono', monospace; }.sample-explanation { margin: 0; padding: 10px 13px; border-top: 1px dashed var(--border); color: var(--text-secondary); font-size: 11px; line-height: 1.7; }
.constraints ul { margin: 0; padding-left: 18px; }.constraints li { color: var(--text-secondary); font: 11px/2 'JetBrains Mono', 'Microsoft YaHei', monospace; }.problem-stats { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 28px; background: var(--surface-soft); border-radius: 9px; padding: 14px; }.problem-stats div { display: flex; flex-direction: column; align-items: center; gap: 4px; border-right: 1px solid var(--border); }.problem-stats div:last-child { border: 0; }.problem-stats strong { font-size: 14px; }.problem-stats span { color: var(--text-tertiary); font-size: 10px; }
.submission-history { padding-top: 20px; }.history-item { display: flex; align-items: center; width: 100%; border: 1px solid var(--border); background: #fff; border-radius: 9px; padding: 13px; margin-bottom: 9px; text-align: left; cursor: pointer; }.history-item:hover { border-color: #cfc9f6; background: #fbfaff; }.history-item > .judge-status { width: 108px; }.history-item > div:nth-child(2) { display: flex; flex-direction: column; gap: 4px; }.history-item strong { font-size: 11px; }.history-item span { font-size: 10px; color: var(--text-tertiary); }.history-metrics { margin-left: auto; text-align: right; display: flex; flex-direction: column; gap: 4px; }.history-metrics small { color: var(--text-tertiary); font-size: 9px; }
.solution-pane { background: #fbfdff; }
.solution-intro { padding: 3px 0 22px; border-bottom: 1px solid var(--border); }
.solution-brand { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.solution-brand > span { display: inline-flex; align-items: center; gap: 5px; color: var(--primary); font-size: 11px; font-weight: 600; }
.solution-brand small { color: var(--text-tertiary); font-size: 9px; }
.solution-intro h1 { margin: 15px 0 12px; color: var(--text-strong); font-size: 22px; line-height: 1.55; letter-spacing: -.5px; }
.solution-tags { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.solution-tags > span { padding: 3px 7px; border-radius: 4px; background: #edf3fa; color: var(--text-secondary); font-size: 9px; }
.solution-intro > p { margin: 17px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.95; }
.solution-section { padding: 24px 0 0; }
.solution-section h2, .reference-heading h2 { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; color: var(--text-strong); font-size: 14px; }
.solution-section h2 > span { color: var(--primary); font: 600 10px 'Manrope', sans-serif; }
.solution-steps { display: flex; flex-direction: column; gap: 12px; margin: 0; padding: 0; list-style: none; }
.solution-steps li { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid #e3ecf6; border-radius: 7px; background: #fff; }
.solution-steps li > span { width: 21px; height: 21px; display: grid; place-items: center; flex: none; border-radius: 50%; background: var(--primary-soft); color: var(--primary); font-size: 9px; font-weight: 700; }
.solution-steps p { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.8; }
.complexity-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.complexity-grid > div { display: flex; flex-direction: column; gap: 6px; padding: 14px; border-left: 3px solid var(--primary); background: #edf4ff; }
.complexity-grid span { color: var(--text-secondary); font-size: 10px; }
.complexity-grid strong { color: #123f87; font: 700 17px 'JetBrains Mono', monospace; }
.complexity-grid small { color: var(--text-tertiary); font-size: 8px; line-height: 1.5; }
.reference-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.reference-heading h2 { margin: 0; }
.reference-heading > button { display: flex; align-items: center; gap: 4px; border: 0; background: none; color: var(--text-tertiary); font-size: 10px; cursor: pointer; }
.reference-heading > button:hover { color: var(--primary); }
.solution-language-tabs { display: flex; gap: 3px; margin-bottom: 10px; padding: 4px; border-radius: 7px; background: #e9f0f8; }
.solution-language-tabs button { flex: 1; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); padding: 7px 6px; font-size: 10px; white-space: nowrap; cursor: pointer; }
.solution-language-tabs button:hover { color: var(--primary); }
.solution-language-tabs button.active { background: #fff; color: var(--primary); font-weight: 600; box-shadow: 0 1px 5px rgba(32, 72, 128, .09); }
.reference-code { overflow: hidden; border-radius: 8px; background: #101d30; }
.code-caption { height: 34px; display: flex; align-items: center; justify-content: space-between; padding: 0 13px; background: #162a43; border-bottom: 1px solid #29415e; }
.code-caption > span { display: flex; gap: 5px; }
.code-caption i { width: 6px; height: 6px; border-radius: 50%; background: #526b88; }
.code-caption i:first-child { background: #df7b72; }.code-caption i:nth-child(2) { background: #e1aa55; }.code-caption i:last-child { background: #61ad8d; }
.code-caption small { color: #7289a5; font: 9px 'JetBrains Mono', monospace; }
.reference-code pre { max-height: 360px; margin: 0; overflow: auto; padding: 16px; color: #cfdaea; font: 11px/1.85 'JetBrains Mono', monospace; white-space: pre; }
.use-solution { width: 100%; margin-top: 12px; }
.solution-note { display: flex; align-items: flex-start; gap: 7px; margin: 22px 0 4px; padding: 12px; border-radius: 7px; background: #fff5e8; color: #9b7a51; }
.solution-note .el-icon { flex: none; margin-top: 3px; }
.solution-note p { margin: 0; font-size: 10px; line-height: 1.75; }
.editor-pane { flex: 1; min-width: 0; display: flex; flex-direction: column; background: #101d30; min-height: 0; }
.editor-toolbar { height: 48px; flex: none; display: flex; align-items: center; gap: 12px; padding: 0 14px; background: #162a43; border-bottom: 1px solid #29415e; }.editor-toolbar .el-select { width: 115px; }.editor-toolbar :deep(.el-select__wrapper) { background: #2b2e3c; box-shadow: 0 0 0 1px #3a3d4c inset; color: #d8dbea; }.editor-toolbar :deep(.el-select__selected-item), .editor-toolbar :deep(.el-select__placeholder) { color: #d8dbea; font-size: 11px; }.editor-file { color: #797f98; font-size: 10px; }.editor-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }.save-state { display: flex; align-items: center; gap: 4px; color: #6f768e; font-size: 9px; }.editor-actions .el-button { color: #9399b0; }
.monaco-wrap { flex: 1; min-height: 180px; }
.console-panel { flex: none; height: clamp(200px, 24vh, 270px); background: #12243b; border-top: 1px solid #29415e; transition: height .2s; }.console-panel.collapsed { height: 39px; }.console-header { height: 39px; display: flex; align-items: center; justify-content: space-between; padding: 0 14px; }.console-header > div { display: flex; height: 100%; gap: 20px; }.console-header button { border: 0; background: none; color: #7f859c; font-size: 10px; cursor: pointer; position: relative; }.console-header button.active { color: #d9dced; }.console-header button.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: #9184ef; }.console-toggle { display: grid; place-items: center; width: 25px; height: 25px; }.result-dot { display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: var(--success); margin-left: 5px; }.result-dot.wa { background: var(--danger); }
.console-content { height: calc(100% - 39px); overflow-y: auto; padding: 8px 17px 12px; color: #c7cbda; }.console-loading, .console-placeholder { height: 100%; display: flex; align-items: center; justify-content: center; gap: 9px; color: #858ba2; font-size: 11px; }.console-loading .el-icon { color: #a597ff; font-size: 18px; }.run-success { display: flex; align-items: center; gap: 7px; margin: 3px 0 9px; }.run-success .el-icon { color: #60c49f; }.run-success strong { font-size: 11px; color: #a7dbc8; }.run-success span { margin-left: auto; color: #6f758b; font-size: 9px; }.testcase-row { display: grid; grid-template-columns: 80px 1fr 35px 45px; gap: 8px; align-items: center; padding: 7px 10px; border-radius: 5px; background: #1b304b; margin-top: 5px; font-size: 10px; }.testcase-row > span { display: flex; align-items: center; gap: 6px; color: #a9aec0; }.testcase-row i { width: 4px; height: 4px; border-radius: 50%; background: #57bd98; }.testcase-row pre { margin: 0; color: #8e95ab; font: 9px 'JetBrains Mono', monospace; white-space: pre-wrap; }.testcase-row strong { color: #61c29e; font-size: 9px; }.testcase-row small { color: #6f7589; text-align: right; font-size: 9px; }
.run-result.failed .run-success strong, .run-result.failed .testcase-row strong { color: #ef9aa3; }
.run-result.failed .testcase-row i { background: #e87982; }
.judging-progress { padding-top: 20px; }.judging-line { display: flex; align-items: center; gap: 12px; }.judging-line > .el-icon { font-size: 25px; color: #a99cf8; }.judging-line > div { display: flex; flex-direction: column; gap: 6px; }.judging-line strong { font-size: 12px; }.judging-line span { color: #7f8599; font-size: 9px; }.judging-line > .judge-status { margin-left: auto; }.judging-progress .el-progress { margin-top: 20px; }
.result-summary { display: flex; align-items: center; gap: 10px; }.result-icon { font-size: 29px; color: #5cc39c; }.wrong .result-icon { color: #e87982; }.result-summary > div:nth-child(2) { display: flex; flex-direction: column; gap: 5px; }.result-summary > div:nth-child(2) > span { color: #81879b; font-size: 9px; }.result-metrics { display: flex; gap: 25px; margin-left: auto; }.result-metrics > span { display: flex; flex-direction: column; gap: 5px; }.result-metrics small { color: #777e93; font-size: 9px; }.result-metrics strong { font-size: 12px; }.final-result > p { display: flex; align-items: center; gap: 5px; background: #342a35; color: #c3939a; font-size: 9px; padding: 8px 10px; border-radius: 5px; margin: 12px 0 0; }
.editor-footer { min-height: 55px; flex: none; background: #162a43; border-top: 1px solid #29415e; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 15px; }.editor-footer > span { display: flex; align-items: center; gap: 5px; color: #70768c; font-size: 9px; }.editor-footer > div { display: flex; gap: 8px; }.editor-footer .el-button { font-size: 11px; }.editor-footer .el-button:not(.el-button--primary) { background: #303341; color: #c2c6d5; border-color: #3d4050; }
@media (max-width: 1000px) { .workspace-topbar > .prototype-note { display: none; }.problem-pane { min-width: 0; }.description-scroll { padding: 20px; }.run-success span { display: none; }.save-state { display: none; }.editor-footer > span { display: none; }.editor-footer { justify-content: flex-end; } }
@media (max-width: 760px) { .workspace-shell { height: auto; min-height: calc(100vh - 120px); }.workspace-topbar { padding: 0 12px; }.workspace-breadcrumb :deep(.difficulty), .contest-label, .problem-switcher { display: none; }.workspace-body { flex-direction: column; }.pane-resizer { display: none; }.problem-pane { width: 100%; min-width: 0; border-right: 0; max-height: none; }.description-scroll { overflow: visible; padding: 22px 18px; }.editor-pane { min-height: 690px; }.monaco-wrap { min-height: 400px; }.console-panel { height: 230px; }.editor-footer { position: sticky; bottom: 0; z-index: 10; }.problem-heading h1 { font-size: 22px; } }
</style>
