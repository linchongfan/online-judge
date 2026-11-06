<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import StatusTag from '../../components/StatusTag.vue'
import {
  adminErrorMessage,
  batchRejudgeAdminTasks,
  getAdminJudgeSettings,
  isAdminRequestCancelled,
  listAdminAbnormalJudgeTasks,
  listAdminJudgeWorkers,
  rejudgeAdminTask,
  updateAdminJudgeSettings,
  updateAdminJudgeWorker,
} from '../../api/admin'
import type { AdminAbnormalJudgeTask, AdminJudgeSettings, JudgeWorker, Language } from '../../types'
import { formatDateTime, formatNumber } from '../../utils/format'

const workers = ref<JudgeWorker[]>([])
const tasks = ref<AdminAbnormalJudgeTask[]>([])
const settings = ref<AdminJudgeSettings | null>(null)
const settingsDraft = ref<AdminJudgeSettings>({ submissionsEnabled: false, globalQueueLimit: 10 })
const lastUpdated = ref('—')
const loading = ref(false)
const errorMessage = ref('')
const pendingWorkers = ref<Set<string>>(new Set())
const settingsSaving = ref(false)
const selectedTasks = ref<AdminAbnormalJudgeTask[]>([])
const taskTableRef = ref()
const rejudgeVisible = ref(false)
const rejudgeTargets = ref<AdminAbnormalJudgeTask[]>([])
const rejudgeReason = ref('')
const rejudgePending = ref(false)
let loadController: AbortController | null = null

const onlineCount = computed(() => workers.value.filter(worker => worker.status !== 'offline').length)
const acceptingCount = computed(() => workers.value.filter(worker => worker.accepting).length)
const runningTasks = computed(() => workers.value.reduce((sum, worker) => sum + worker.activeTasks, 0))
const completedTotal = computed(() => workers.value.reduce((sum, worker) => sum + worker.completed, 0))
const metrics = computed(() => [
  { label: '活跃 Worker', value: `${onlineCount.value} / ${workers.value.length}`, icon: 'Cpu', detail: `${acceptingCount.value} 个节点接收新任务`, tone: 'primary' },
  { label: '运行中任务', value: String(runningTasks.value), icon: 'Loading', detail: settings.value ? `全局队列上限 ${formatNumber(settings.value.globalQueueLimit)}` : '等待队列设置', tone: 'blue' },
  { label: '待处理异常', value: String(tasks.value.length), icon: 'Warning', detail: '仅统计真实 SE 异常任务', tone: 'orange' },
  { label: 'Worker 累计完成', value: formatNumber(completedTotal.value), icon: 'CircleCheck', detail: '各节点累计完成数之和', tone: 'green' },
])
const workerStatus = {
  online: { label: '空闲', tone: 'success' },
  busy: { label: '忙碌', tone: 'warning' },
  offline: { label: '已下线', tone: 'neutral' },
}
const languageLabels: Record<Language, string> = { cpp: 'C++11', c: 'C99', java: 'JDK 8', python: 'Python 3.8.6' }

function resourceColor(value: number | null, offline = false) {
  if (value === null || offline) return '#b8c2ce'
  if (value <= 30) return '#22a06b'
  if (value <= 60) return '#e3a22f'
  return '#d95764'
}
function resourcePercent(value: number | null): number {
  return value === null ? 0 : Math.max(0, Math.min(100, value))
}
function setWorkerPending(workerId: string, pending: boolean) {
  const next = new Set(pendingWorkers.value)
  if (pending) next.add(workerId)
  else next.delete(workerId)
  pendingWorkers.value = next
}

async function refreshStatus(showMessage = false) {
  loadController?.abort()
  const current = new AbortController()
  loadController = current
  loading.value = true
  errorMessage.value = ''
  const results = await Promise.allSettled([
    listAdminJudgeWorkers({ signal: current.signal }),
    listAdminAbnormalJudgeTasks({ signal: current.signal }),
    getAdminJudgeSettings({ signal: current.signal }),
  ])
  if (current.signal.aborted) return
  if (results[0].status === 'fulfilled') workers.value = results[0].value
  if (results[1].status === 'fulfilled') {
    tasks.value = results[1].value
    selectedTasks.value = []
    taskTableRef.value?.clearSelection()
  }
  if (results[2].status === 'fulfilled') {
    settings.value = results[2].value
    settingsDraft.value = { ...results[2].value }
  }
  const failed = results.find(result => result.status === 'rejected')
  if (failed && !isAdminRequestCancelled(failed.reason)) {
    errorMessage.value = adminErrorMessage(failed.reason, '部分判题数据加载失败，请重试')
  } else if (!failed) {
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (showMessage) ElMessage.success('Worker、异常任务与设置已刷新')
  }
  if (loadController === current) {
    loading.value = false
    loadController = null
  }
}

async function toggleWorker(worker: JudgeWorker) {
  if (pendingWorkers.value.has(worker.id)) return
  const accepting = !worker.accepting
  try {
    await ElMessageBox.confirm(
      accepting ? `恢复 ${worker.id} 接收新任务后，该节点将通过心跳恢复消费判题队列。` : `停止 ${worker.id} 接收新任务后，该 Worker 会暂停领取新任务（进行中的任务仍会完成），直到再次恢复。`,
      accepting ? '确认恢复接收任务' : '确认停止接收任务',
      { confirmButtonText: accepting ? '恢复接收' : '停止接收', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  setWorkerPending(worker.id, true)
  try {
    const updated = await updateAdminJudgeWorker(worker.id, accepting)
    Object.assign(worker, updated)
    ElMessage.success(`${worker.id} 已${accepting ? '恢复' : '停止'}接收新任务`)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, 'Worker 接收状态更新失败'))
  } finally {
    setWorkerPending(worker.id, false)
  }
}

function openSingleRejudge(task: AdminAbnormalJudgeTask) {
  rejudgeTargets.value = [task]
  rejudgeReason.value = ''
  rejudgeVisible.value = true
}
function openBatchRejudge(targets: AdminAbnormalJudgeTask[]) {
  if (!targets.length) {
    ElMessage.info('请先勾选需要重判的异常任务')
    return
  }
  rejudgeTargets.value = [...targets]
  rejudgeReason.value = ''
  rejudgeVisible.value = true
}
async function submitRejudge() {
  const reason = rejudgeReason.value.trim()
  if (reason.length < 3 || reason.length > 300) {
    ElMessage.warning('重判原因需为 3–300 个字符')
    return
  }
  if (!rejudgeTargets.value.length || rejudgePending.value) return
  rejudgePending.value = true
  const single = rejudgeTargets.value.length === 1
  try {
    if (single) {
      const response = await rejudgeAdminTask(rejudgeTargets.value[0].taskId, reason)
      ElMessage.success(`重判任务 ${response.taskId} 已创建并进入调度`)
    } else {
      const response = await batchRejudgeAdminTasks(rejudgeTargets.value.map(task => task.taskId), reason)
      ElMessage.success(`已创建 ${response.count} 个重判任务`)
    }
    rejudgeVisible.value = false
    await refreshStatus()
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '重判任务创建失败'))
  } finally {
    rejudgePending.value = false
  }
}

async function saveSettings() {
  if (!settings.value || settingsSaving.value) return
  const queueLimit = settingsDraft.value.globalQueueLimit
  if (!Number.isInteger(queueLimit) || queueLimit < 10 || queueLimit > 100000) {
    ElMessage.warning('全局队列上限需为 10–100000 的整数')
    return
  }
  settingsSaving.value = true
  try {
    const updated = await updateAdminJudgeSettings({
      submissionsEnabled: settingsDraft.value.submissionsEnabled,
      globalQueueLimit: queueLimit,
    })
    settings.value = updated
    settingsDraft.value = { ...updated }
    ElMessage.success('判题全局设置已保存')
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '判题设置保存失败'))
  } finally {
    settingsSaving.value = false
  }
}

onMounted(() => void refreshStatus())
onUnmounted(() => loadController?.abort())
</script>

<template>
  <div class="judge-page">
    <div class="page-heading"><div><h1>判题任务</h1><p>监控真实判题节点与异常任务，管理重判和全局队列设置。</p></div><div class="heading-actions"><span class="prototype-note">更新于 {{ lastUpdated }}</span><el-button :loading="loading" @click="refreshStatus(true)"><el-icon v-if="!loading"><Refresh /></el-icon>刷新状态</el-button></div></div>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert"><el-button size="small" @click="refreshStatus()">重新加载</el-button></el-alert>
    <section v-loading="loading && !workers.length" class="stat-grid judge-stats">
      <article v-for="metric in metrics" :key="metric.label" class="stat-card"><div class="stat-label">{{ metric.label }}<span class="stat-icon" :class="metric.tone"><el-icon :size="18"><component :is="metric.icon" /></el-icon></span></div><strong class="stat-value">{{ metric.value }}</strong><div class="stat-foot">{{ metric.detail }}</div></article>
    </section>

    <section class="workers-section">
      <div class="section-heading"><div><h2>Worker 节点</h2><p>接收开关与心跳状态分别来自服务端；空资源不会按 0% 伪造。</p></div><span class="cluster-health"><i />{{ onlineCount }} / {{ workers.length }} 节点活跃</span></div>
      <div v-if="!workers.length && !loading" class="surface-card worker-empty empty-state"><div class="empty-icon"><el-icon :size="26"><Cpu /></el-icon></div><h3>暂无 Worker</h3><p>判题节点注册并上报心跳后将在此显示。</p></div>
      <div v-else class="worker-grid">
        <article v-for="worker in workers" :key="worker.id" class="surface-card worker-card" :class="{ offline: worker.status === 'offline' }">
          <div class="worker-header"><div><span class="worker-icon"><el-icon :size="20"><Cpu /></el-icon></span><div><strong class="mono">{{ worker.id }}</strong><span class="mono">{{ worker.host }}</span></div></div><span class="status-pill" :class="workerStatus[worker.status].tone"><i />{{ workerStatus[worker.status].label }}</span></div>
          <div class="resource-list">
            <div><span>CPU 使用率</span><strong>{{ worker.cpu === null ? '未上报' : `${worker.cpu}%` }}</strong></div>
            <el-progress :percentage="resourcePercent(worker.cpu)" :stroke-width="5" :show-text="false" :color="resourceColor(worker.cpu, worker.status === 'offline')" />
            <div><span>内存使用率</span><strong>{{ worker.memory === null ? '未上报' : `${worker.memory}%` }}</strong></div>
            <el-progress :percentage="resourcePercent(worker.memory)" :stroke-width="5" :show-text="false" :color="resourceColor(worker.memory, worker.status === 'offline')" />
          </div>
          <div class="worker-meta"><span>当前任务<strong>{{ worker.activeTasks }}</strong></span><span>累计完成<strong>{{ formatNumber(worker.completed) }}</strong></span></div>
          <div class="worker-footer"><span><el-icon><Clock /></el-icon>心跳 {{ worker.heartbeat ? formatDateTime(worker.heartbeat) : '未上报' }}</span><el-button size="small" :type="worker.accepting ? 'default' : 'primary'" :plain="worker.accepting" :loading="pendingWorkers.has(worker.id)" @click="toggleWorker(worker)"><el-icon v-if="!pendingWorkers.has(worker.id)"><SwitchButton /></el-icon>{{ worker.accepting ? '停止接收' : '恢复接收' }}</el-button></div>
        </article>
      </div>
    </section>

    <section class="surface-card settings-card">
      <div class="section-heading"><div><h2>全局判题设置</h2><p>控制全站提交入口与调度队列容量，保存后由服务端持久化。</p></div><el-button type="primary" :loading="settingsSaving" :disabled="!settings || loading" @click="saveSettings">保存设置</el-button></div>
      <div v-loading="loading && !settings" class="settings-grid">
        <div class="setting-item"><div><strong>允许用户提交</strong><span>关闭后全局禁止创建新提交</span></div><el-switch v-model="settingsDraft.submissionsEnabled" :disabled="!settings || settingsSaving" active-text="开启" inactive-text="关闭" /></div>
        <div class="setting-item"><div><strong>全局队列上限</strong><span>允许 10–100000 的整数</span></div><el-input-number v-model="settingsDraft.globalQueueLimit" :min="10" :max="100000" :step="10" :disabled="!settings || settingsSaving" /></div>
      </div>
    </section>

    <section class="surface-card task-card">
      <div class="section-heading task-heading"><div><h2>异常任务</h2><p>勾选多个任务可批量重判；每次重判都必须填写真实原因。</p></div><div class="task-actions"><el-button :disabled="!tasks.length" @click="openBatchRejudge(tasks)">全部重判（{{ tasks.length }}）</el-button><el-button type="primary" plain :disabled="!selectedTasks.length" @click="openBatchRejudge(selectedTasks)"><el-icon><RefreshRight /></el-icon>重判已选<span v-if="selectedTasks.length">（{{ selectedTasks.length }}）</span></el-button></div></div>
      <div class="table-scroll">
        <el-table ref="taskTableRef" v-loading="loading" :data="tasks" row-key="taskId" class="admin-table" @selection-change="selectedTasks = $event">
          <el-table-column type="selection" width="45" reserve-selection />
          <el-table-column label="任务 / 提交" width="180"><template #default="{ row }"><div class="problem-cell"><span class="submission-id mono">任务 #{{ row.taskId }}</span><span class="mono">提交 #{{ row.submissionId }}</span></div></template></el-table-column>
          <el-table-column label="题目" min-width="190"><template #default="{ row }"><div class="problem-cell"><strong>{{ row.problemTitle }}</strong><span>#{{ row.problemId }} / {{ languageLabels[row.language as Language] }}</span></div></template></el-table-column>
          <el-table-column label="提交用户" width="125"><template #default="{ row }"><span class="mono username">@{{ row.username }}</span></template></el-table-column>
          <el-table-column label="Worker" width="125"><template #default="{ row }"><span class="mono" :class="{ muted: !row.workerId }">{{ row.workerId || '未分配' }}</span></template></el-table-column>
          <el-table-column label="异常原因" min-width="180"><template #default="{ row }">{{ row.reason || '未提供异常详情' }}</template></el-table-column>
          <el-table-column label="尝试" width="70" align="right"><template #default="{ row }">#{{ row.attempt }}</template></el-table-column>
          <el-table-column label="结果" width="110"><template #default="{ row }"><StatusTag :status="row.judgeStatus" compact /></template></el-table-column>
          <el-table-column label="发生时间" width="180"><template #default="{ row }"><span class="mono muted">{{ formatDateTime(row.finishedAt || row.createdAt) }}</span></template></el-table-column>
          <el-table-column label="操作" width="112" fixed="right"><template #default="{ row }"><el-button text type="primary" @click="openSingleRejudge(row)"><el-icon><RefreshRight /></el-icon>重判</el-button></template></el-table-column>
          <template #empty><div class="empty-state"><div class="empty-icon"><el-icon :size="26"><CircleCheck /></el-icon></div><h3>暂无异常任务</h3><p>当前没有 SE 状态的判题任务。</p></div></template>
        </el-table>
      </div>
      <div class="queue-footer"><span><el-icon><InfoFilled /></el-icon>重判会创建新 attempt，不修改原始代码与提交时间。</span><span>已选 {{ selectedTasks.length }} / 异常 {{ tasks.length }} 个任务</span></div>
    </section>

    <el-dialog v-model="rejudgeVisible" :title="rejudgeTargets.length > 1 ? `批量重判 ${rejudgeTargets.length} 个任务` : '确认重新判题'" width="min(540px, calc(100vw - 32px))" :close-on-click-modal="!rejudgePending">
      <div class="rejudge-summary"><el-icon><Warning /></el-icon><p>将基于原始提交代码与其绑定的测试数据版本创建新的判题任务。<template v-if="rejudgeTargets.length === 1">原任务 #{{ rejudgeTargets[0].taskId }}，提交 #{{ rejudgeTargets[0].submissionId }}。</template></p></div>
      <el-form label-position="top" @submit.prevent="submitRejudge"><el-form-item label="重判原因（必填，3–300 字）" required><el-input v-model="rejudgeReason" type="textarea" :rows="4" minlength="3" maxlength="300" show-word-limit placeholder="例如：Worker 沙箱异常退出，需在恢复后的节点重新验证" @keydown.ctrl.enter="submitRejudge" /></el-form-item></el-form>
      <template #footer><el-button :disabled="rejudgePending" @click="rejudgeVisible = false">取消</el-button><el-button type="primary" :loading="rejudgePending" @click="submitRejudge">确认重判</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.judge-page :deep(.page-heading) { margin-bottom: 22px; }
.heading-actions { display: flex; align-items: center; gap: 14px; }
.heading-actions :deep(.el-button) { border-radius: 6px; }
.prototype-note::before { background: #9bb5d4; }
.request-alert { margin-bottom: 16px; }
.judge-stats { gap: 0; overflow: hidden; background: #fff; border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-sm); min-height: 130px; }
.judge-stats .stat-card { padding: 20px 22px; border: 0; border-radius: 0; box-shadow: none; }
.judge-stats .stat-card + .stat-card { border-left: 1px solid var(--border); }
.judge-stats .stat-value { margin-top: 12px; font-size: 27px; line-height: 1.2; }
.judge-stats .stat-foot { margin-top: 10px; color: var(--text-secondary); }
.stat-icon { border-radius: 7px; }
.stat-icon.primary, .stat-icon.blue { color: var(--primary); background: var(--primary-soft); }
.stat-icon.green { color: var(--success); background: #eaf7f1; }
.stat-icon.orange { color: #b56c19; background: var(--accent-soft); }
.workers-section { margin-top: 24px; }
.workers-section > .section-heading h2, .task-heading h2, .settings-card h2 { font-size: 16px; font-weight: 700; }
.workers-section > .section-heading p, .task-heading p, .settings-card .section-heading p { color: var(--text-secondary); }
.cluster-health { display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 11px; }
.cluster-health i { width: 6px; height: 6px; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 3px #e8f6f0; }
.worker-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.worker-empty { border-radius: 8px; }
.worker-card { padding: 18px; min-width: 0; border-radius: 8px; box-shadow: none; transition: border-color .18s, background-color .18s; }
.worker-card:hover { border-color: #b9d0f5; }
.worker-card.offline { background: #f6f8fb; }
.worker-card.offline .resource-list, .worker-card.offline .worker-meta { opacity: .58; }
.worker-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.worker-header > div { display: flex; align-items: center; gap: 9px; min-width: 0; }
.worker-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px; color: var(--primary); background: var(--primary-soft); flex: none; }
.offline .worker-icon { color: #71849a; background: #e8edf3; }
.worker-header > div > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.worker-header strong { color: var(--text-strong); font-size: 12px; }
.worker-header .mono + .mono { color: var(--text-secondary); font-size: 9px; }
.status-pill { border-radius: 5px; padding: 4px 8px; }
.status-pill.success { color: var(--success); background: #eaf7f1; }
.status-pill.warning { color: #a86218; background: var(--accent-soft); }
.status-pill.neutral { color: #687b91; background: #e8edf3; }
.resource-list { margin-top: 18px; }
.resource-list > div { display: flex; align-items: center; justify-content: space-between; margin: 11px 0 7px; color: var(--text-secondary); font-size: 10px; }
.resource-list > div strong { color: var(--text-strong); font-size: 11px; }
.resource-list :deep(.el-progress-bar__outer) { background: #e7edf5; border-radius: 2px; }
.resource-list :deep(.el-progress-bar__inner) { border-radius: 2px; }
.worker-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 17px; padding: 12px 0; border-block: 1px solid var(--border); }
.worker-meta > span { display: flex; flex-direction: column; gap: 4px; color: var(--text-secondary); font-size: 10px; }
.worker-meta > span + span { padding-left: 14px; border-left: 1px solid var(--border); }
.worker-meta strong { color: var(--text-strong); font-size: 15px; font-weight: 600; }
.worker-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 13px; }
.worker-footer > span { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); font-size: 9px; }
.worker-footer :deep(.el-button) { border-radius: 5px; flex: none; }
.settings-card { margin-top: 24px; padding: 20px; border-radius: 8px; box-shadow: none; }
.settings-card .section-heading { margin-bottom: 16px; }
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; min-height: 68px; }
.setting-item { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-soft); }
.setting-item > div { display: flex; flex-direction: column; gap: 5px; }
.setting-item strong { color: var(--text-strong); font-size: 12px; }
.setting-item span { color: var(--text-secondary); font-size: 10px; }
.task-card { margin-top: 24px; overflow: hidden; border-radius: 8px; box-shadow: none; }
.task-heading { margin: 0; padding: 20px; }
.task-heading :deep(.el-button) { border-radius: 6px; }
.task-actions { display: flex; gap: 8px; }
.table-scroll { width: 100%; overflow-x: auto; border-top: 1px solid var(--border); }
.admin-table { width: 100%; min-width: 1390px; --el-table-header-bg-color: #f4f8fd; --el-table-row-hover-bg-color: #f5f8ff; --el-table-header-text-color: var(--text-secondary); }
.admin-table :deep(th.el-table__cell) { height: 44px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.admin-table :deep(td.el-table__cell) { padding: 14px 0; }
.submission-id { color: var(--primary); font-size: 11px; font-weight: 500; }
.problem-cell { display: flex; flex-direction: column; gap: 5px; }
.problem-cell strong { color: var(--text-strong); font-size: 12px; font-weight: 600; }
.problem-cell span { color: var(--text-secondary); font-size: 10px; }
.username { font-size: 10px; color: var(--text-secondary); }
.admin-table :deep(.el-button) { border-radius: 5px; }
.queue-footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 13px 20px; border-top: 1px solid var(--border); background: #fbfdff; color: var(--text-secondary); font-size: 10px; }
.queue-footer span { display: flex; align-items: center; gap: 5px; }
.queue-footer span:first-child :deep(.el-icon) { color: var(--primary); }
.rejudge-summary { display: flex; align-items: flex-start; gap: 9px; padding: 12px; margin-bottom: 18px; border-radius: 6px; background: var(--accent-soft); color: #8b5a1d; }
.rejudge-summary .el-icon { margin-top: 3px; flex: none; }
.rejudge-summary p { margin: 0; font-size: 11px; line-height: 1.7; }
@media (max-width: 1200px) { .worker-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) {
  .judge-stats .stat-card:nth-child(3) { border-left: 0; }
  .judge-stats .stat-card:nth-child(n+3) { border-top: 1px solid var(--border); }
}
@media (max-width: 760px) {
  .heading-actions { width: 100%; justify-content: space-between; }
  .cluster-health { display: none; }
  .settings-grid { grid-template-columns: 1fr; }
  .task-heading { align-items: flex-start; }
  .task-actions { flex-wrap: wrap; justify-content: flex-end; }
}
@media (max-width: 600px) {
  .judge-stats .stat-card { padding: 16px 14px; }
  .judge-stats .stat-value { font-size: 23px; }
  .worker-grid { grid-template-columns: 1fr; }
  .task-heading { align-items: flex-start; padding: 16px; }
  .queue-footer { align-items: flex-start; flex-direction: column; gap: 8px; }
  .prototype-note { display: none; }
}
</style>
