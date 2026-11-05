<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import DifficultyTag from '../components/DifficultyTag.vue'
import { cancelContestRegistration, getContest, getContestRanking, getMyContestResult, registerForContest } from '../api/contests'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { contestStatusMap, formatDateTime, formatDurationSeconds, formatNumber, parseServerDate } from '../utils/format'
import type { Contest, ContestResult, RankEntry } from '../types'

const route = useRoute()
const router = useRouter()
const contest = ref<Contest | null>(null)
const rankingEntries = ref<RankEntry[]>([])
const myResult = ref<ContestResult | null>(null)
const activeTab = ref(String(route.query.tab ?? 'problems'))
const loading = ref(true)
const rankingLoading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const now = ref(Date.now())
const serverOffset = ref(0)
const lastRankingUpdate = ref<Date | null>(null)
let clock: ReturnType<typeof setInterval> | undefined
let rankingClock: ReturnType<typeof setInterval> | undefined

const contestId = computed(() => Number(route.params.id))
const registered = computed(() => contest.value?.registered ?? false)
const remaining = computed(() => {
  if (!contest.value) return 0
  const target = contest.value.status === 'upcoming' ? contest.value.startTime : contest.value.endTime
  return Math.max(0, parseServerDate(target).getTime() - (now.value + serverOffset.value))
})
const countdown = computed(() => {
  const total = Math.floor(remaining.value / 1000)
  return {
    days: Math.floor(total / 86400),
    hours: String(Math.floor((total % 86400) / 3600)).padStart(2, '0'),
    minutes: String(Math.floor((total % 3600) / 60)).padStart(2, '0'),
    seconds: String(total % 60).padStart(2, '0'),
  }
})
const rankingAgo = computed(() => {
  if (!lastRankingUpdate.value) return '等待首次更新'
  const seconds = Math.max(0, Math.floor((now.value - lastRankingUpdate.value.getTime()) / 1000))
  if (seconds < 5) return '刚刚更新'
  if (seconds < 60) return `${seconds} 秒前更新`
  return `${Math.floor(seconds / 60)} 分钟前更新`
})
const avatarColors = ['#1557d6', '#168a70', '#c87620', '#7256c8', '#c45d68']
function avatarColor(username: string): string { return avatarColors[username.length % avatarColors.length] }

async function loadContest() {
  loading.value = true
  error.value = ''
  try {
    contest.value = await getContest(contestId.value)
    serverOffset.value = parseServerDate(contest.value.serverTime).getTime() - Date.now()
    await Promise.all([loadRanking(), loadMyResult()])
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '竞赛加载失败'
    contest.value = null
  } finally { loading.value = false }
}
async function loadRanking() {
  if (!contest.value || contest.value.status === 'upcoming') { rankingEntries.value = []; return }
  rankingLoading.value = true
  try {
    rankingEntries.value = (await getContestRanking(contest.value.id)).entries
    lastRankingUpdate.value = new Date()
  }
  catch (caught) { if (!(caught instanceof ApiError && caught.code === 'CONTEST_NOT_STARTED')) rankingEntries.value = [] }
  finally { rankingLoading.value = false }
}
async function loadMyResult() {
  if (!contest.value || !session.loggedIn || !contest.value.registered) { myResult.value = null; return }
  try { myResult.value = await getMyContestResult(contest.value.id) } catch { myResult.value = null }
}
async function register() {
  if (!contest.value) return
  if (!session.loggedIn) { await router.push({ path: '/login', query: { redirect: route.fullPath } }); return }
  if (contest.value.status === 'ongoing') {
    activeTab.value = 'problems'
    document.querySelector('.contest-tabs')?.scrollIntoView({ behavior: 'smooth' })
    return
  }
  actionLoading.value = true
  try {
    await registerForContest(contest.value.id)
    ElMessage.success('报名成功')
    await loadContest()
  } catch (caught) { ElMessage.error(caught instanceof ApiError ? caught.message : '报名失败') }
  finally { actionLoading.value = false }
}
async function cancelRegistration() {
  if (!contest.value) return
  try { await ElMessageBox.confirm('确定取消本场比赛的报名吗？', '取消报名', { confirmButtonText: '确定取消', cancelButtonText: '保留报名', type: 'warning' }) } catch { return }
  actionLoading.value = true
  try {
    await cancelContestRegistration(contest.value.id)
    ElMessage.success('已取消报名')
    await loadContest()
  } catch (caught) { ElMessage.error(caught instanceof ApiError ? caught.message : '取消报名失败') }
  finally { actionLoading.value = false }
}
function openProblem(problemId: number) {
  if (!contest.value || contest.value.status === 'upcoming') return
  void router.push({ path: `/problems/${problemId}`, query: contest.value.status === 'ongoing' ? { contest: contest.value.id } : {} })
}
watch(activeTab, value => { if (value === 'ranking') void loadRanking() })
// Reload server state when the countdown crosses the start/end boundary so
// the page switches between locked / ongoing / ended without a manual refresh.
watch(remaining, (value, previous) => { if (previous > 0 && value === 0) void loadContest() })
onMounted(() => {
  void loadContest()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
  rankingClock = setInterval(() => {
    if (contest.value?.status === 'ongoing' && activeTab.value === 'ranking') void loadRanking()
  }, 30_000)
})
onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
  if (rankingClock) clearInterval(rankingClock)
})
</script>

<template>
  <div class="contest-detail-page" v-loading="loading">
    <button class="back-link" @click="router.push('/contests')"><el-icon><ArrowLeft /></el-icon>返回竞赛列表</button>
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button text @click="loadContest">重新加载</el-button></el-alert>
    <template v-if="contest">
    <section class="contest-banner" :style="{ '--accent': contest.accent }">
      <div class="banner-content"><div class="banner-labels"><span class="status-pill" :class="contestStatusMap[contest.status].tone"><i />{{ contestStatusMap[contest.status].label }}</span><span>ACM 个人赛</span><span>公开报名</span></div><h1>{{ contest.title }}</h1><p>{{ contest.subtitle }}</p><div class="banner-meta"><span><el-icon><Calendar /></el-icon>{{ formatDateTime(contest.startTime) }} — {{ formatDateTime(contest.endTime) }}</span><span><el-icon><User /></el-icon>{{ formatNumber(contest.participants) }} 人已报名</span><span><el-icon><OfficeBuilding /></el-icon>{{ contest.organizer }}</span></div></div>
      <div class="banner-action">
        <template v-if="contest.status !== 'ended'"><span class="countdown-label">{{ contest.status === 'ongoing' ? '距离比赛结束' : '距离比赛开始' }}</span><div class="countdown"><span v-if="countdown.days"><strong>{{ countdown.days }}</strong><small>天</small><i>:</i></span><span><strong>{{ countdown.hours }}</strong><small>时</small></span><i>:</i><span><strong>{{ countdown.minutes }}</strong><small>分</small></span><i>:</i><span><strong>{{ countdown.seconds }}</strong><small>秒</small></span></div><el-button v-if="!registered || contest.status === 'ongoing'" type="primary" size="large" :loading="actionLoading" :disabled="contest.status === 'ongoing' && !registered" @click="register">{{ contest.status === 'ongoing' ? (registered ? '进入比赛' : '报名已截止') : '立即报名' }}</el-button><div v-else class="registered-actions"><el-button size="large" disabled><el-icon><CircleCheck /></el-icon>已报名</el-button><button @click="cancelRegistration">取消报名</button></div></template>
        <template v-else><span class="ended-mark"><el-icon><Medal /></el-icon>本场比赛已结束</span><el-button size="large" @click="activeTab = 'ranking'">查看最终榜单</el-button></template>
      </div>
    </section>

    <nav class="contest-tabs surface-card"><button :class="{ active: activeTab === 'problems' }" @click="activeTab = 'problems'"><el-icon><Tickets /></el-icon>比赛题目<span v-if="contest.status !== 'upcoming'">{{ contest.problems.length }}</span></button><button :class="{ active: activeTab === 'ranking' }" @click="activeTab = 'ranking'"><el-icon><Histogram /></el-icon>排行榜</button><button :class="{ active: activeTab === 'rules' }" @click="activeTab = 'rules'"><el-icon><Document /></el-icon>比赛说明</button><span class="server-time"><i />服务器时间已校准</span></nav>

    <div class="contest-content-grid">
      <section class="contest-main surface-card">
        <template v-if="activeTab === 'problems'">
          <div class="section-heading"><div><h2>赛题列表</h2><p v-if="contest.status === 'ongoing'">点击题目进入竞赛编程环境</p><p v-else-if="contest.status === 'ended'">赛后练习提交不影响本场比赛排名</p></div><span v-if="contest.status === 'ongoing'" class="refresh-hint"><el-icon><Refresh /></el-icon>提交数据实时更新</span></div>
          <div v-if="contest.status === 'upcoming'" class="locked-problems"><div class="lock-emblem"><el-icon><Lock /></el-icon></div><h3>赛题尚未开放</h3><p>比赛开始后，已报名的参赛者可以查看题目并提交代码。</p><el-button type="primary" :disabled="registered" @click="register">{{ registered ? '你已完成报名' : '先报名比赛' }}</el-button></div>
          <div v-if="contest.status === 'ongoing' && !registered" class="empty-state"><h3>本场报名已截止</h3><p>比赛开始后不能再报名，你仍可查看赛题说明与公开排行榜。</p></div>
          <el-table v-else :data="contest.problems" @row-click="(row: any) => openProblem(row.problemId)">
            <el-table-column label="#" width="60" align="center"><template #default="{ row }"><span class="problem-letter">{{ row.label }}</span></template></el-table-column>
            <el-table-column label="题目" min-width="220"><template #default="{ row }"><div class="contest-problem-title"><strong>{{ row.title }}</strong><span v-if="row.userStatus === 'AC'" class="solved-check"><el-icon><CircleCheckFilled /></el-icon></span></div></template></el-table-column>
            <el-table-column label="难度" width="90"><template #default="{ row }"><DifficultyTag :difficulty="row.difficulty" /></template></el-table-column>
            <el-table-column label="通过 / 提交" width="150" align="center"><template #default="{ row }"><span class="attempt-stats"><strong>{{ row.solved }}</strong> / {{ row.attempts }}</span></template></el-table-column>
            <el-table-column label="通过率" width="100"><template #default="{ row }"><span class="problem-rate">{{ row.attempts ? Math.round(row.solved / row.attempts * 100) : 0 }}%</span></template></el-table-column>
            <el-table-column width="70" align="right"><template #default="{ row }"><el-button text size="small">{{ row.userStatus === 'AC' ? '再做一次' : '去解答' }}<el-icon><ArrowRight /></el-icon></el-button></template></el-table-column>
          </el-table>
          <div v-if="contest.status === 'ongoing'" class="contest-tip"><el-icon><InfoFilled /></el-icon>竞赛期间的提交将计入排行榜。错误提交会在首次通过前产生 20 分钟罚时。</div>
        </template>

        <template v-else-if="activeTab === 'ranking'">
          <div class="section-heading"><div><h2>{{ contest.status === 'ended' ? '最终排行榜' : '实时排行榜' }}</h2><p>按解题数降序、总用时（分钟）升序排列</p></div><span class="refresh-hint"><i class="live-dot" />{{ contest.status === 'ended' ? '成绩已核验' : rankingAgo }}</span></div>
          <div class="ranking-table-wrap" v-loading="rankingLoading"><table class="ranking-table"><thead><tr><th>排名</th><th>参赛者</th><th>解题</th><th>总用时（分钟）</th><th v-for="item in contest.problems" :key="item.label">{{ item.label }}</th></tr></thead><tbody><tr v-for="entry in rankingEntries" :key="entry.username" :class="{ 'current-user': entry.username === session.profile?.username }"><td><span class="rank-number" :class="`rank-${entry.rank}`"><el-icon v-if="entry.rank <= 3"><Trophy /></el-icon><template v-else>{{ entry.rank }}</template></span></td><td><div class="rank-user"><span class="avatar" :style="{ background: avatarColor(entry.username) + '20', color: avatarColor(entry.username) }">{{ entry.username.slice(0, 1).toUpperCase() }}</span><div><strong>{{ entry.username }}</strong><span v-if="entry.username === session.profile?.username">这是我</span></div></div></td><td><strong class="solved-count">{{ entry.solved }}</strong></td><td><span class="penalty mono">{{ Math.floor(entry.penaltySeconds / 60) }}</span></td><td v-for="item in contest.problems" :key="item.label"><template v-if="entry.results[item.label]"><div v-if="entry.results[item.label].status === 'AC'" class="rank-cell ac"><strong>+{{ entry.results[item.label].wrongAttempts || '' }}</strong><span>{{ Math.floor((entry.results[item.label].timeSeconds ?? 0) / 60) }}'</span></div><div v-else-if="entry.results[item.label].status === 'WA'" class="rank-cell wa"><strong>-{{ entry.results[item.label].wrongAttempts }}</strong><span>未通过</span></div><span v-else class="rank-empty">—</span></template></td></tr></tbody></table></div>
          <div class="ranking-legend"><span><i class="ac" />已通过（时间为首次 AC 分钟数）</span><span><i class="wa" />尚未通过（数字为错误次数）</span></div>
        </template>

        <template v-else>
          <div class="section-heading"><div><h2>比赛说明</h2><p>请在参赛前仔细阅读以下规则</p></div></div><div class="contest-description"><p>{{ contest.description }}</p></div><div class="rules-grid"><article><span><el-icon><Medal /></el-icon></span><div><h3>排名规则</h3><p>按成功解题数量降序排名；解题数相同时，总用时（分钟）更少者排名靠前。</p></div></article><article><span><el-icon><Timer /></el-icon></span><div><h3>罚时计算</h3><p>已 AC 题目的罚时为开始至首次 AC 的时间，加首次 AC 前每次错误提交 20 分钟。</p></div></article><article><span><el-icon><Lock /></el-icon></span><div><h3>提交权限</h3><p>仅已报名参赛者的有效提交计入排名。比赛结束后不能进行竞赛提交。</p></div></article><article><span><el-icon><Warning /></el-icon></span><div><h3>公平竞赛</h3><p>请独立完成比赛，不得共享代码、使用他人账号或干扰判题服务。</p></div></article></div><div class="rule-note"><h3>结果与数据说明</h3><ul><li>支持 C、C++、Java、Python，具体资源限制以每道题目为准。</li><li>WA、TLE、MLE、RE 会产生罚时，CE 与系统异常 SE 不计罚时。</li><li>隐藏测试点、标准答案和内部路径不会在判题结果中展示。</li><li>首版不提供封榜、滚榜、虚拟参赛与团队赛功能。</li></ul></div>
        </template>
      </section>

      <aside class="contest-aside">
        <section class="surface-card my-contest-card"><div class="my-card-top"><span class="avatar">{{ session.profile?.nickname.slice(0, 1) ?? '客' }}</span><div><strong>{{ session.loggedIn ? session.profile?.nickname : '尚未登录' }}</strong><span>{{ registered ? '本场已报名' : '查看我的比赛状态' }}</span></div></div><template v-if="registered"><div class="my-score"><div><strong>{{ contest.status === 'upcoming' ? '—' : myResult?.solvedCount ?? 0 }}</strong><span>已解题</span></div><div><strong>{{ contest.status === 'upcoming' ? '—' : Math.floor((myResult?.penaltySeconds ?? 0) / 60) }}</strong><span>当前用时（分钟）</span></div><div><strong>{{ contest.status === 'upcoming' ? '—' : myResult?.rank ?? '—' }}</strong><span>当前排名</span></div></div><button v-if="contest.status !== 'upcoming'" class="rank-link" @click="activeTab = 'ranking'">查看我的排名<el-icon><ArrowRight /></el-icon></button></template><el-button v-else-if="contest.status === 'upcoming'" type="primary" plain style="width:100%;margin-top:15px" @click="register">报名本场比赛</el-button></section>
        <section class="surface-card info-card"><h3>比赛信息</h3><dl><div><dt>开始时间</dt><dd>{{ formatDateTime(contest.startTime) }}</dd></div><div><dt>结束时间</dt><dd>{{ formatDateTime(contest.endTime) }}</dd></div><div><dt>比赛时长</dt><dd>{{ formatDurationSeconds(contest.durationSeconds) }}</dd></div><div><dt>计分方式</dt><dd>ACM 计分</dd></div><div><dt>比赛语言</dt><dd>C / C++ / Java / Python</dd></div><div><dt>主办方</dt><dd>{{ contest.organizer }}</dd></div></dl></section>
        <section class="fair-play"><el-icon><CircleCheck /></el-icon><div><strong>公平竞赛，从每一次独立提交开始</strong><p>异常提交与越权操作将被记录并审计。</p></div></section>
      </aside>
    </div>
    </template>
  </div>
</template>

<style scoped>
.back-link { display: flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--text-tertiary); font-size: 11px; cursor: pointer; padding: 0; margin-bottom: 17px; }.back-link:hover { color: var(--primary); }
.contest-banner { position: relative; overflow: hidden; border-radius: 16px; background: #fff; border: 1px solid var(--border); padding: 30px 33px; display: flex; align-items: center; gap: 30px; }.contest-banner::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--accent); }.contest-banner::after { content: '</>'; position: absolute; right: 35%; bottom: -25px; color: var(--accent); opacity: .035; font: 700 120px 'JetBrains Mono', monospace; transform: rotate(-10deg); pointer-events: none; }.banner-content { flex: 1; position: relative; z-index: 1; }.banner-labels { display: flex; align-items: center; gap: 10px; }.banner-labels > span:not(.status-pill) { color: var(--text-tertiary); font-size: 10px; border-left: 1px solid var(--border); padding-left: 10px; }.banner-content h1 { font-size: 26px; margin: 14px 0 7px; letter-spacing: -.6px; }.banner-content > p { margin: 0; color: var(--text-secondary); font-size: 12px; }.banner-meta { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 19px; }.banner-meta span { display: flex; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 10px; }.banner-action { flex: none; min-width: 275px; text-align: center; border-left: 1px solid var(--border); padding-left: 30px; position: relative; z-index: 1; }.countdown-label { color: var(--text-tertiary); font-size: 10px; }.countdown { display: flex; justify-content: center; align-items: center; gap: 7px; margin: 9px 0 15px; }.countdown > span { display: flex; align-items: baseline; gap: 3px; }.countdown strong { font: 600 25px 'Manrope', sans-serif; letter-spacing: -.5px; }.countdown small { color: var(--text-tertiary); font-size: 9px; }.countdown i { color: #c5c4cf; font-style: normal; margin-top: -5px; }.banner-action .el-button { min-width: 140px; }.registered-actions { display: flex; flex-direction: column; align-items: center; gap: 6px; }.registered-actions > button:not(.el-button) { border: 0; background: none; color: var(--text-tertiary); font-size: 9px; cursor: pointer; }.ended-mark { display: flex; align-items: center; justify-content: center; gap: 7px; color: var(--text-secondary); font-size: 12px; margin-bottom: 15px; }
.contest-tabs { height: 56px; margin: 16px 0; display: flex; align-items: stretch; padding: 0 20px; gap: 28px; }.contest-tabs button { border: 0; background: none; position: relative; display: flex; align-items: center; gap: 6px; color: var(--text-tertiary); font-size: 12px; cursor: pointer; }.contest-tabs button.active { color: var(--primary); font-weight: 600; }.contest-tabs button.active::after { content: ''; position: absolute; height: 2px; bottom: -1px; left: 0; right: 0; background: var(--primary); }.contest-tabs button span { background: var(--primary-soft); color: var(--primary); border-radius: 8px; font-size: 9px; padding: 1px 5px; }.server-time { margin-left: auto; display: flex; align-items: center; gap: 6px; color: var(--text-tertiary); font-size: 9px; }.server-time i { width: 5px; height: 5px; border-radius: 50%; background: var(--success); }
.contest-content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 16px; }.contest-main { padding: 22px; min-width: 0; min-height: 420px; }.refresh-hint { display: flex; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 9px; }.contest-main :deep(.el-table__row) { cursor: pointer; }.problem-letter { display: inline-grid; place-items: center; width: 26px; height: 26px; background: var(--primary-soft); color: var(--primary); border-radius: 7px; font-weight: 700; font-size: 11px; }.contest-problem-title { display: flex; align-items: center; gap: 8px; }.contest-problem-title strong { font-size: 12px; }.solved-check { color: var(--success); }.attempt-stats { color: var(--text-tertiary); font-size: 11px; }.attempt-stats strong { color: var(--success); }.problem-rate { font-size: 11px; color: var(--text-secondary); }.contest-tip { display: flex; align-items: center; gap: 6px; background: #f8f7fe; color: #8880aa; border-radius: 7px; padding: 10px 12px; font-size: 9px; margin-top: 12px; }.locked-problems { text-align: center; padding: 65px 20px; }.lock-emblem { width: 58px; height: 58px; display: grid; place-items: center; margin: auto; border-radius: 17px; background: var(--primary-soft); color: var(--primary); font-size: 24px; }.locked-problems h3 { margin: 15px 0 7px; font-size: 16px; }.locked-problems p { color: var(--text-tertiary); font-size: 11px; margin: 0 0 20px; }
.ranking-table-wrap { overflow-x: auto; }.ranking-table { width: 100%; border-collapse: collapse; min-width: 630px; }.ranking-table th { text-align: center; background: #fafafd; color: var(--text-tertiary); font-size: 10px; font-weight: 600; padding: 10px; border-bottom: 1px solid var(--border); }.ranking-table th:nth-child(2) { text-align: left; }.ranking-table td { text-align: center; padding: 10px; border-bottom: 1px solid #f0f0f4; font-size: 11px; }.ranking-table tr.current-user { background: #f2f7ff; }.rank-number { display: inline-grid; place-items: center; width: 25px; height: 25px; color: var(--text-tertiary); }.rank-number .el-icon { font-size: 19px; }.rank-1 { color: #e0a33e; }.rank-2 { color: #98a2b6; }.rank-3 { color: #ba815a; }.rank-user { display: flex; align-items: center; gap: 8px; text-align: left; }.rank-user .avatar { width: 30px; height: 30px; border-radius: 8px; font-size: 11px; }.rank-user > div { display: flex; flex-direction: column; gap: 3px; }.rank-user strong { font-size: 11px; }.rank-user span:not(.avatar) { color: var(--primary); font-size: 8px; }.solved-count { color: var(--text-strong); }.penalty { color: var(--text-secondary); font-size: 10px; }.rank-cell { display: inline-flex; flex-direction: column; min-width: 38px; gap: 3px; padding: 4px 5px; border-radius: 5px; }.rank-cell strong { font-size: 10px; }.rank-cell span { font-size: 8px; }.rank-cell.ac { color: #278360; background: #eaf7f1; }.rank-cell.wa { color: #c9666e; background: #fff1f2; }.rank-empty { color: #d1d2da; }.ranking-legend { display: flex; gap: 20px; margin-top: 15px; }.ranking-legend span { display: flex; align-items: center; gap: 5px; color: var(--text-tertiary); font-size: 8px; }.ranking-legend i { width: 6px; height: 6px; border-radius: 2px; }.ranking-legend i.ac { background: #8bcfb4; }.ranking-legend i.wa { background: #e5a5ab; }.live-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--success); }
.contest-description { color: var(--text-secondary); font-size: 12px; line-height: 1.9; }.rules-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 20px; }.rules-grid article { display: flex; gap: 11px; padding: 15px; background: var(--surface-soft); border-radius: 9px; }.rules-grid article > span { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 8px; background: #ebe8fc; color: var(--primary); flex: none; }.rules-grid h3 { margin: 1px 0 5px; font-size: 12px; }.rules-grid p { margin: 0; color: var(--text-tertiary); font-size: 10px; line-height: 1.7; }.rule-note { margin-top: 22px; }.rule-note h3 { font-size: 13px; }.rule-note ul { padding-left: 18px; color: var(--text-secondary); font-size: 11px; line-height: 2; }
.contest-aside { display: flex; flex-direction: column; gap: 14px; }.my-contest-card, .info-card { padding: 18px; }.my-card-top { display: flex; align-items: center; gap: 10px; }.my-card-top > div { display: flex; flex-direction: column; gap: 4px; }.my-card-top strong { font-size: 12px; }.my-card-top span:not(.avatar) { color: var(--text-tertiary); font-size: 9px; }.my-score { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 18px; padding-top: 15px; border-top: 1px solid var(--border); }.my-score div { display: flex; flex-direction: column; align-items: center; gap: 4px; }.my-score strong { font-size: 18px; }.my-score span { color: var(--text-tertiary); font-size: 9px; }.rank-link { width: 100%; display: flex; align-items: center; justify-content: center; gap: 3px; border: 0; background: var(--primary-soft); color: var(--primary); border-radius: 7px; padding: 8px; margin-top: 15px; font-size: 10px; cursor: pointer; }.info-card h3 { margin: 0 0 13px; font-size: 13px; }.info-card dl { margin: 0; }.info-card dl > div { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-bottom: 1px dashed var(--border); font-size: 9px; }.info-card dl > div:last-child { border: 0; }.info-card dt { color: var(--text-tertiary); flex: none; }.info-card dd { margin: 0; color: var(--text-secondary); text-align: right; }.fair-play { display: flex; gap: 8px; padding: 12px; color: #7f799d; background: #efedf8; border-radius: 10px; }.fair-play > .el-icon { margin-top: 2px; }.fair-play strong { font-size: 9px; }.fair-play p { margin: 4px 0 0; font-size: 8px; color: #a09aaf; line-height: 1.6; }
@media (max-width: 1000px) { .contest-content-grid { grid-template-columns: minmax(0, 1fr) 225px; }.contest-banner { padding: 25px; }.banner-action { min-width: 235px; padding-left: 20px; }.banner-meta { gap: 10px; }.rules-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .contest-banner { flex-direction: column; align-items: stretch; padding: 23px; }.banner-action { border-left: 0; border-top: 1px solid var(--border); padding: 18px 0 0; min-width: 0; }.banner-content h1 { font-size: 23px; }.contest-content-grid { grid-template-columns: 1fr; }.contest-aside { display: grid; grid-template-columns: 1fr 1fr; }.fair-play { display: none; }.server-time { display: none; }.contest-tabs { gap: 15px; padding: 0 12px; }.contest-main { padding: 16px; }.ranking-table-wrap { margin: 0 -5px; } }
@media (max-width: 480px) { .contest-aside { grid-template-columns: 1fr; }.info-card { display: none; }.banner-meta span:nth-child(3) { display: none; }.contest-tabs button { font-size: 11px; }.contest-tabs { gap: 10px; }.rules-grid { gap: 8px; } }
</style>
