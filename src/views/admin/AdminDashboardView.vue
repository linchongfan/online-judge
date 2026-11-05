<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  adminErrorMessage,
  getAdminDashboard,
  getAdminDashboardTrends,
  getAdminStatusDistribution,
  isAdminRequestCancelled,
  listAdminAbnormalJudgeTasks,
} from '../../api/admin'
import { session } from '../../stores/session'
import type {
  AdminAbnormalJudgeTask,
  AdminDashboard,
  AdminStatusDistribution,
  JudgeStatus,
} from '../../types'
import { formatDateTime, formatNumber, judgeStatusMap } from '../../utils/format'

const router = useRouter()
const trendRange = ref<'7d' | '30d'>('7d')
const lastUpdated = ref('—')
const dashboard = ref<AdminDashboard | null>(null)
const trends = ref<{ date: string; label: string; value: number }[]>([])
const statusDistribution = ref<AdminStatusDistribution[]>([])
const anomalies = ref<AdminAbnormalJudgeTask[]>([])
const loading = ref(false)
const trendLoading = ref(false)
const errorMessage = ref('')
const trendError = ref('')
let overviewController: AbortController | null = null
let trendController: AbortController | null = null

const greeting = computed(() => {
  const hour = new Date().getHours()
  return hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
})
const metrics = computed(() => {
  const data = dashboard.value
  return [
    { label: '注册用户', value: data ? formatNumber(data.userCount) : '—', icon: 'User', detail: '平台真实账号总数', tone: 'primary' },
    { label: '题目总数', value: data ? formatNumber(data.problemCount) : '—', icon: 'Document', detail: '包含草稿与归档题目', tone: 'blue' },
    { label: '累计提交', value: data ? formatNumber(data.submissionCount) : '—', icon: 'Upload', detail: data ? `${formatNumber(data.acceptedCount)} 次通过 · 通过率 ${data.acceptance}%` : '等待数据', tone: 'green' },
    { label: '竞赛总数', value: data ? formatNumber(data.contestCount) : '—', icon: 'Trophy', detail: data ? `${formatNumber(data.activeWorkerCount)} 个活跃 Worker · ${formatNumber(data.pendingCount)} 个待判` : '等待数据', tone: 'blue' },
  ]
})

function localDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

async function loadTrends() {
  trendController?.abort()
  const controller = new AbortController()
  trendController = controller
  trendLoading.value = true
  trendError.value = ''
  const days = trendRange.value === '7d' ? 7 : 30
  try {
    const rows = await getAdminDashboardTrends(days, { signal: controller.signal })
    if (controller.signal.aborted) return
    const counts = new Map(rows.map(item => [item.date.slice(0, 10), item.submissions]))
    const today = new Date()
    trends.value = Array.from({ length: days }, (_, index) => {
      const date = new Date(today)
      date.setHours(12, 0, 0, 0)
      date.setDate(today.getDate() - (days - 1 - index))
      const key = localDateKey(date)
      return {
        date: key,
        label: key.slice(5),
        value: counts.get(key) ?? 0,
      }
    })
  } catch (error) {
    if (!isAdminRequestCancelled(error)) trendError.value = adminErrorMessage(error, '提交趋势加载失败')
  } finally {
    if (trendController === controller) {
      trendLoading.value = false
      trendController = null
    }
  }
}

async function loadOverview(showMessage = false) {
  overviewController?.abort()
  const controller = new AbortController()
  overviewController = controller
  loading.value = true
  errorMessage.value = ''
  const results = await Promise.allSettled([
    getAdminDashboard({ signal: controller.signal }),
    getAdminStatusDistribution({ signal: controller.signal }),
    listAdminAbnormalJudgeTasks({ signal: controller.signal }),
  ])
  if (controller.signal.aborted) return
  if (results[0].status === 'fulfilled') dashboard.value = results[0].value
  if (results[1].status === 'fulfilled') statusDistribution.value = results[1].value
  if (results[2].status === 'fulfilled') anomalies.value = results[2].value.slice(0, 6)
  const failed = results.find(result => result.status === 'rejected')
  if (failed && !isAdminRequestCancelled(failed.reason)) {
    errorMessage.value = adminErrorMessage(failed.reason, '部分概览数据加载失败，请重试')
  } else if (!failed) {
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    if (showMessage) ElMessage.success('概览数据已刷新')
  }
  if (overviewController === controller) {
    loading.value = false
    overviewController = null
  }
}

function refreshDashboard() {
  void Promise.all([loadOverview(), loadTrends()])
}

const currentTrend = computed(() => trends.value)
const chartMax = computed(() => {
  const maximum = Math.max(0, ...currentTrend.value.map(item => item.value))
  return maximum ? Math.ceil(maximum / 4) * 4 : 4
})
const chartPoints = computed(() => currentTrend.value.map((item, index) => ({
  ...item,
  x: 48 + index * (696 / Math.max(1, currentTrend.value.length - 1)),
  y: 200 - (item.value / chartMax.value) * 180,
})))
const linePath = computed(() => chartPoints.value.map((point, index) => `${index ? 'L' : 'M'} ${point.x} ${point.y}`).join(' '))
const areaPath = computed(() => chartPoints.value.length ? `${linePath.value} L 744 200 L 48 200 Z` : '')
const yTicks = computed(() => Array.from({ length: 5 }, (_, index) => ({
  y: 20 + index * 45,
  value: Math.round(chartMax.value * (4 - index) / 4),
})))
const totalSubmissions = computed(() => currentTrend.value.reduce((sum, item) => sum + item.value, 0))
const peak = computed(() => {
  if (!currentTrend.value.length || totalSubmissions.value === 0) return null
  return currentTrend.value.reduce((best, item) => item.value > best.value ? item : best)
})
function showTrendLabel(index: number): boolean {
  return trendRange.value === '7d' || index % 5 === 0 || index === currentTrend.value.length - 1
}

const statusColors: Record<JudgeStatus, string> = {
  AC: '#1557d6', WA: '#d95764', TLE: '#f29a38', MLE: '#a879c7', RE: '#e1795c',
  CE: '#7286a0', SE: '#9a5264', PENDING: '#9bb5d4', JUDGING: '#38a1b5',
}
const distributionTotal = computed(() => statusDistribution.value.reduce((sum, item) => sum + item.count, 0))
const distribution = computed(() => statusDistribution.value.map(item => ({
  status: item.status,
  label: `${judgeStatusMap[item.status]?.label ?? item.status}（${item.status}）`,
  value: distributionTotal.value ? Math.round(item.count / distributionTotal.value * 1000) / 10 : 0,
  count: item.count,
  color: statusColors[item.status] ?? '#c7d3e2',
})))
const donutStyle = computed(() => {
  if (!distributionTotal.value) return { background: '#e7edf5' }
  let position = 0
  const stops = distribution.value.map(item => {
    const start = position
    position += item.count / distributionTotal.value * 100
    return `${item.color} ${start}% ${position}%`
  })
  return { background: `conic-gradient(${stops.join(',')})` }
})

watch(trendRange, () => void loadTrends())
onMounted(() => {
  void loadOverview()
  void loadTrends()
})
onUnmounted(() => {
  overviewController?.abort()
  trendController?.abort()
})
</script>

<template>
  <div class="dashboard-page">
    <div class="page-heading dashboard-heading">
      <div>
        <h1>{{ greeting }}，{{ session.profile?.nickname ?? '管理员' }}</h1>
        <p>汇总题库、学习与判题运行情况，优先处理需要关注的异常。</p>
      </div>
      <div class="heading-actions">
        <span class="prototype-note">更新于 {{ lastUpdated }}</span>
        <el-button :loading="loading" @click="refreshDashboard"><el-icon v-if="!loading"><Refresh /></el-icon>刷新数据</el-button>
      </div>
    </div>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert">
      <el-button size="small" @click="loadOverview()">重新加载</el-button>
    </el-alert>

    <section v-loading="loading && !dashboard" class="stat-grid" aria-label="核心指标">
      <article v-for="metric in metrics" :key="metric.label" class="stat-card metric-card">
        <div class="stat-label">
          {{ metric.label }}
          <span class="stat-icon" :class="metric.tone"><el-icon :size="18"><component :is="metric.icon" /></el-icon></span>
        </div>
        <strong class="stat-value">{{ metric.value }}</strong>
        <div class="stat-foot">{{ metric.detail }}</div>
      </article>
    </section>

    <section class="analytics-grid">
      <article class="surface-card trend-card" v-loading="trendLoading && !trends.length">
        <div class="section-heading">
          <div><h2>提交趋势</h2><p>共 {{ formatNumber(totalSubmissions) }} 次提交，缺失日期按 0 次展示</p></div>
          <el-radio-group v-model="trendRange" size="small" :disabled="trendLoading">
            <el-radio-button label="7d">近 7 天</el-radio-button>
            <el-radio-button label="30d">近 30 天</el-radio-button>
          </el-radio-group>
        </div>
        <el-alert v-if="trendError" :title="trendError" type="error" :closable="false" show-icon role="alert" />
        <div v-else-if="totalSubmissions === 0 && !trendLoading" class="chart-empty empty-state">
          <div class="empty-icon"><el-icon :size="26"><TrendCharts /></el-icon></div>
          <h3>该时间范围内暂无提交</h3><p>趋势会在产生真实提交后更新。</p>
        </div>
        <div v-else class="chart-wrap">
          <svg viewBox="0 0 760 244" role="img" aria-label="提交数量趋势图" preserveAspectRatio="none">
            <g v-for="tick in yTicks" :key="tick.y">
              <line x1="48" x2="744" :y1="tick.y" :y2="tick.y" stroke="#e4ebf4" stroke-width="1" />
              <text x="38" :y="tick.y + 4" text-anchor="end" class="axis-label">{{ tick.value >= 1000 ? `${tick.value / 1000}k` : tick.value }}</text>
            </g>
            <path :d="areaPath" fill="#eaf2ff" />
            <path :d="linePath" fill="none" stroke="#1557d6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
            <g v-for="(point, index) in chartPoints" :key="point.date" class="chart-point">
              <circle :cx="point.x" :cy="point.y" r="4.5" fill="#fff" stroke="#1557d6" stroke-width="2.5" vector-effect="non-scaling-stroke"><title>{{ point.label }}：{{ formatNumber(point.value) }} 次提交</title></circle>
              <text v-if="showTrendLabel(index)" :x="point.x" y="229" text-anchor="middle" class="axis-label">{{ point.label }}</text>
            </g>
          </svg>
        </div>
        <div class="chart-summary"><span><i class="legend-dot" />提交数量</span><span v-if="peak"><el-icon><TrendCharts /></el-icon> 峰值 {{ peak.label }}，{{ formatNumber(peak.value) }} 次</span></div>
      </article>

      <article class="surface-card distribution-card" v-loading="loading && !dashboard">
        <div class="section-heading"><div><h2>提交状态分布</h2><p>全部真实提交结果</p></div><span class="status-pill" :class="dashboard?.abnormalTaskCount ? 'warning' : 'success'"><i />{{ dashboard?.abnormalTaskCount ? `${dashboard.abnormalTaskCount} 个异常` : '暂无异常' }}</span></div>
        <div v-if="!distributionTotal && !loading" class="distribution-empty empty-state"><h3>暂无提交状态数据</h3><p>产生提交后将在此展示分布。</p></div>
        <template v-else>
          <div class="donut-wrap"><div class="donut" :style="donutStyle"><div><strong>{{ formatNumber(distributionTotal) }}</strong><span>总提交数</span></div></div></div>
          <div class="distribution-list">
            <div v-for="item in distribution" :key="item.status">
              <span class="distribution-label"><i :style="{ background: item.color }" />{{ item.label }}</span>
              <strong>{{ item.value }}%</strong><span>{{ formatNumber(item.count) }}</span>
            </div>
          </div>
        </template>
      </article>
    </section>

    <section class="surface-card anomaly-card" v-loading="loading && !dashboard">
      <div class="section-heading">
        <div><h2>最近异常</h2><p>来自判题中心的真实系统异常任务</p></div>
        <el-button text type="primary" @click="router.push('/admin/judge')">前往判题中心<el-icon><ArrowRight /></el-icon></el-button>
      </div>
      <div v-if="!anomalies.length && !loading" class="empty-state"><div class="empty-icon"><el-icon :size="26"><CircleCheck /></el-icon></div><h3>暂无异常任务</h3><p>当前没有需要处理的判题系统异常。</p></div>
      <div v-else class="anomaly-list">
        <div v-for="item in anomalies" :key="item.taskId" class="anomaly-row">
          <span class="anomaly-icon danger"><el-icon :size="18"><Warning /></el-icon></span>
          <div class="anomaly-content"><strong>提交 #{{ item.submissionId }} 判题异常</strong><span>#{{ item.problemId }} {{ item.problemTitle }} · {{ item.reason || '未提供异常详情' }}</span></div>
          <time class="mono">{{ formatDateTime(item.finishedAt || item.createdAt) }}</time>
          <el-button size="small" @click="router.push('/admin/judge')">查看并重判</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-page :deep(.page-heading h1) { font-weight: 700; }
.dashboard-heading { align-items: center; margin-bottom: 22px; }
.heading-actions { display: flex; align-items: center; gap: 14px; }
.heading-actions :deep(.el-button), .anomaly-row :deep(.el-button) { border-radius: 6px; }
.prototype-note::before { background: #9bb5d4; }
.request-alert { margin-bottom: 16px; }
.stat-grid { gap: 0; overflow: hidden; background: #fff; border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-sm); min-height: 130px; }
.metric-card { padding: 20px 22px; border: 0; border-radius: 0; box-shadow: none; }
.metric-card + .metric-card { border-left: 1px solid var(--border); }
.metric-card .stat-label { color: var(--text-secondary); font-weight: 500; }
.metric-card .stat-value { margin-top: 12px; font-size: 29px; font-weight: 700; line-height: 1.2; }
.metric-card .stat-foot { display: flex; align-items: center; flex-wrap: wrap; margin-top: 10px; color: var(--text-secondary); }
.stat-icon { border-radius: 7px; }
.stat-icon.primary, .stat-icon.blue { color: var(--primary); background: var(--primary-soft); }
.stat-icon.green { color: var(--success); background: #eaf7f1; }
.analytics-grid { display: grid; grid-template-columns: minmax(0, 1.9fr) minmax(290px, .8fr); gap: 16px; margin-top: 16px; }
.trend-card, .distribution-card, .anomaly-card { padding: 22px; border-radius: 8px; box-shadow: none; }
.section-heading { margin-bottom: 20px; }
.section-heading h2 { font-size: 16px; font-weight: 700; }
.section-heading p { color: var(--text-secondary); }
.section-heading :deep(.el-radio-button__inner) { border-radius: 0; color: var(--text-secondary); }
.chart-wrap { width: 100%; height: 260px; margin-top: 4px; }
.chart-wrap svg { width: 100%; height: 100%; overflow: visible; }
.chart-empty { min-height: 260px; display: flex; justify-content: center; }
.axis-label { fill: #71859f; font-size: 10px; font-family: 'Manrope', 'Noto Sans SC', sans-serif; }
.chart-point circle { transition: r .18s; }
.chart-point:hover circle { r: 6.5px; }
.chart-summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--border); color: var(--text-secondary); font-size: 11px; }
.chart-summary span { display: inline-flex; align-items: center; gap: 6px; }
.legend-dot { width: 14px; height: 3px; border-radius: 1px; background: var(--primary); }
.status-pill.success { color: var(--success); background: #eaf7f1; }
.status-pill.warning { color: #a86218; background: var(--accent-soft); }
.donut-wrap { display: grid; place-items: center; padding: 12px 0 24px; }
.donut { width: 164px; height: 164px; border-radius: 50%; display: grid; place-items: center; transform: rotate(-35deg); }
.donut::before { content: ''; width: 106px; height: 106px; border-radius: 50%; background: #fff; grid-area: 1 / 1; }
.donut div { grid-area: 1 / 1; z-index: 1; transform: rotate(35deg); display: flex; flex-direction: column; align-items: center; }
.donut strong { font-size: 24px; letter-spacing: -.8px; color: var(--text-strong); }
.donut span { color: var(--text-secondary); font-size: 11px; margin-top: 5px; }
.distribution-list { display: flex; flex-direction: column; gap: 10px; }
.distribution-list > div { display: grid; grid-template-columns: 1fr 48px 58px; align-items: center; gap: 8px; font-size: 12px; }
.distribution-label { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.distribution-label i { width: 8px; height: 8px; border-radius: 2px; flex: none; }
.distribution-list strong { text-align: right; color: var(--text-strong); font-weight: 600; }
.distribution-list > div > span:last-child { color: var(--text-secondary); text-align: right; font-size: 11px; }
.distribution-empty { min-height: 245px; }
.anomaly-card { margin-top: 16px; }
.anomaly-list { margin: -4px -6px -6px; }
.anomaly-row { display: flex; align-items: center; gap: 14px; min-height: 70px; padding: 11px 8px; border-top: 1px solid var(--border); }
.anomaly-row:first-child { border-top: 0; }
.anomaly-icon { width: 36px; height: 36px; border-radius: 7px; display: grid; place-items: center; flex: none; }
.anomaly-icon.danger { color: var(--danger); background: #fff0f1; }
.anomaly-content { display: flex; flex-direction: column; gap: 5px; min-width: 0; flex: 1; }
.anomaly-content strong { color: var(--text-strong); font-size: 13px; font-weight: 600; }
.anomaly-content span { color: var(--text-secondary); font-size: 11px; }
.anomaly-row time { color: var(--text-secondary); font-size: 11px; }
.anomaly-row .el-button { min-width: 90px; justify-content: center; }
@media (max-width: 1100px) {
  .analytics-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-card:nth-child(3) { border-left: 0; }
  .metric-card:nth-child(n+3) { border-top: 1px solid var(--border); }
}
@media (max-width: 760px) {
  .heading-actions { width: 100%; justify-content: space-between; }
  .anomaly-row { flex-wrap: wrap; }
  .anomaly-content { min-width: calc(100% - 54px); }
  .anomaly-row time { margin-left: 50px; }
  .anomaly-row .el-button { margin-left: auto; }
}
@media (max-width: 600px) {
  .metric-card { padding: 16px 14px; }
  .metric-card .stat-value { font-size: 24px; }
  .trend-card, .distribution-card, .anomaly-card { padding: 16px; }
  .chart-wrap { height: 220px; overflow-x: auto; }
  .chart-wrap svg { min-width: 570px; }
  .chart-summary { align-items: flex-start; flex-direction: column; }
  .prototype-note { display: none; }
}
</style>
