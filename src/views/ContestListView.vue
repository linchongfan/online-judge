<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listContests, registerForContest } from '../api/contests'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { contestStatusMap, formatDateTime, formatDurationSeconds, formatNumber, parseServerDate } from '../utils/format'
import type { Contest, ContestStatus } from '../types'

const router = useRouter()
const status = ref<ContestStatus | ''>('')
const contests = ref<Contest[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const error = ref('')
const registeringId = ref<number | null>(null)
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | undefined

const ongoing = computed(() => contests.value.find((contest) => contest.status === 'ongoing'))
const ongoingCount = computed(() => contests.value.filter(contest => contest.status === 'ongoing').length)
const heroRemaining = computed(() => ongoing.value ? Math.max(0, parseServerDate(ongoing.value.endTime).getTime() - now.value) : 0)

function accentColor(value: string): string {
  return value.startsWith('#') ? value : ({ blue: '#1557d6', purple: '#7256c8', green: '#168a70' }[value] ?? '#1557d6')
}
function datePart(value: string, part: 'day' | 'month' | 'year'): string {
  const date = parseServerDate(value)
  if (part === 'day') return String(date.getDate()).padStart(2, '0')
  if (part === 'month') return `${date.getMonth() + 1} 月`
  return String(date.getFullYear())
}
async function loadContests() {
  loading.value = true
  error.value = ''
  try {
    const data = await listContests({ page: page.value, pageSize, status: status.value || undefined })
    contests.value = data.items
    total.value = data.total
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '竞赛加载失败'
    contests.value = []
  } finally { loading.value = false }
}
async function register(id: number) {
  if (!session.loggedIn) {
    await router.push({ path: '/login', query: { redirect: `/contests/${id}` } })
    return
  }
  registeringId.value = id
  try {
    await registerForContest(id)
    ElMessage.success('报名成功')
    await loadContests()
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : '报名失败')
  } finally { registeringId.value = null }
}
watch(status, () => { page.value = 1; void loadContests() })
watch(page, () => { void loadContests() })
onMounted(() => { void loadContests(); clock = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (clock) clearInterval(clock) })
</script>

<template>
  <div class="contest-page">
    <div class="page-heading"><div><span class="eyebrow">新保研赛事中心</span><h1>算法竞赛</h1><p>与同路人同场竞技，在有限的时间里突破自己的边界。</p></div><div class="contest-heading-stats"><div><strong>{{ total }}</strong><span>公开赛事</span></div><i /><div><strong>{{ ongoingCount }}</strong><span>当前进行中</span></div></div></div>

    <section v-if="ongoing" class="ongoing-hero">
      <div class="hero-grid" />
      <div class="hero-content"><span class="live-label"><i />正在进行</span><h2>{{ ongoing.title }}</h2><p>{{ ongoing.subtitle }}</p><div class="hero-meta"><span><el-icon><Clock /></el-icon>剩余 {{ formatDurationSeconds(heroRemaining / 1000) }}</span><span><el-icon><User /></el-icon>{{ formatNumber(ongoing.participants) }} 人参赛</span><span><el-icon><Tickets /></el-icon>{{ ongoing.problems.length }} 道赛题</span></div><div class="hero-actions"><el-button color="#ffffff" @click="router.push(`/contests/${ongoing.id}`)">进入比赛<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button><button @click="router.push(`/contests/${ongoing.id}?tab=ranking`)">查看实时榜单</button></div></div>
      <div class="hero-visual" aria-hidden="true"><div class="orbit orbit-one" /><div class="orbit orbit-two" /><div class="trophy-emblem"><img src="/images/xinbaoyan-mark.png" alt="" /><span>{{ ongoing.id }}<small>赛事</small></span></div><span class="floating-code code-one">{ AC }</span><span class="floating-code code-two">01:42</span></div>
    </section>

    <div class="contest-toolbar"><div class="status-tabs"><button :class="{ active: status === '' }" @click="status = ''">全部比赛<span>{{ contests.length }}</span></button><button :class="{ active: status === 'ongoing' }" @click="status = 'ongoing'">进行中</button><button :class="{ active: status === 'upcoming' }" @click="status = 'upcoming'">即将开始</button><button :class="{ active: status === 'ended' }" @click="status = 'ended'">已结束</button></div><span class="prototype-note">比赛时间以服务器时间为准</span></div>

    <section class="contest-list" v-loading="loading">
      <el-alert v-if="error" type="error" :title="error" show-icon :closable="false"><el-button text @click="loadContests">重试</el-button></el-alert>
      <article v-for="contest in contests" :key="contest.id" class="contest-card surface-card" :style="{ '--contest-accent': accentColor(contest.accent) }">
        <div class="contest-date"><strong>{{ datePart(contest.startTime, 'day') }}</strong><span>{{ datePart(contest.startTime, 'month') }}</span><small>{{ datePart(contest.startTime, 'year') }}</small></div>
        <div class="contest-info"><div class="contest-title-line"><span class="status-pill" :class="contestStatusMap[contest.status].tone"><i />{{ contestStatusMap[contest.status].label }}</span><h3 @click="router.push(`/contests/${contest.id}`)">{{ contest.title }}</h3><span v-if="contest.registered" class="registered-mark"><el-icon><CircleCheck /></el-icon>已报名</span></div><p>{{ contest.subtitle }}</p><div class="contest-detail-meta"><span><el-icon><Calendar /></el-icon>{{ formatDateTime(contest.startTime) }} 开始</span><span><el-icon><Timer /></el-icon>时长 {{ formatDurationSeconds(contest.durationSeconds) }}</span><span><el-icon><User /></el-icon>{{ formatNumber(contest.participants) }} 人报名</span><span><el-icon><Medal /></el-icon>ACM 赛制</span></div></div>
        <div class="contest-action"><el-button v-if="contest.status === 'ongoing'" type="primary" @click="router.push(`/contests/${contest.id}`)">{{ contest.registered ? '进入比赛' : '查看比赛' }}</el-button><el-button v-else-if="contest.status === 'upcoming' && !contest.registered" type="primary" plain :loading="registeringId === contest.id" @click="register(contest.id)">立即报名</el-button><el-button v-else-if="contest.status === 'upcoming'" disabled>已报名</el-button><el-button v-else plain @click="router.push(`/contests/${contest.id}`)">查看赛果</el-button><button class="detail-link" @click="router.push(`/contests/${contest.id}`)">比赛详情<el-icon><ArrowRight /></el-icon></button></div>
      </article>
      <div v-if="total > pageSize" class="pagination-row">
        <span>第 {{ page }} / {{ Math.ceil(total / pageSize) }} 页</span>
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" background />
      </div>
    </section>
    <div v-if="!loading && !error && !contests.length" class="empty-state surface-card"><div class="empty-icon"><el-icon :size="26"><Trophy /></el-icon></div><h3>当前没有该状态的比赛</h3><p>看看其他比赛，或稍后再来</p><el-button @click="status = ''">查看全部</el-button></div>
  </div>
</template>

<style scoped>
.contest-heading-stats { display: flex; align-items: center; gap: 24px; padding: 10px 0; }.contest-heading-stats div { display: flex; flex-direction: column; gap: 4px; }.contest-heading-stats strong { font-size: 22px; letter-spacing: -.5px; }.contest-heading-stats span { color: var(--text-tertiary); font-size: 10px; }.contest-heading-stats i { width: 1px; height: 35px; background: var(--border); }
.ongoing-hero { min-height: 280px; position: relative; overflow: hidden; border-radius: 17px; padding: 38px 42px; color: #fff; background: #164a9e; box-shadow: 0 16px 38px rgba(25, 74, 150, .18); }.hero-grid { position: absolute; inset: 0; opacity: .07; background-image: linear-gradient(rgba(255,255,255,.7) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.7) 1px, transparent 1px); background-size: 35px 35px; mask-image: linear-gradient(90deg, #000, transparent 80%); }.hero-content { position: relative; z-index: 2; max-width: 670px; }.live-label { display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px; border: 1px solid rgba(242,154,56,.45); border-radius: 20px; background: rgba(242,154,56,.13); color: #ffe3bf; font-size: 10px; font-weight: 600; }.live-label i { width: 6px; height: 6px; background: #75e5b6; border-radius: 50%; box-shadow: 0 0 0 4px rgba(117,229,182,.12); animation: live-pulse 1.6s infinite; }.hero-content h2 { margin: 17px 0 9px; font-size: 29px; letter-spacing: -.8px; }.hero-content > p { margin: 0; color: rgba(255,255,255,.63); font-size: 12px; line-height: 1.7; }.hero-meta { display: flex; flex-wrap: wrap; gap: 22px; margin-top: 21px; }.hero-meta span { display: flex; align-items: center; gap: 6px; color: rgba(255,255,255,.75); font-size: 11px; }.hero-actions { display: flex; align-items: center; gap: 20px; margin-top: 25px; }.hero-actions .el-button { color: #164a9e; border: 0; font-weight: 600; padding: 10px 20px; }.hero-actions > button:not(.el-button) { border: 0; background: none; color: rgba(255,255,255,.7); text-decoration: underline; text-underline-offset: 4px; cursor: pointer; font-size: 11px; }.hero-visual { position: absolute; width: 300px; height: 300px; right: 30px; top: -10px; display: grid; place-items: center; }.trophy-emblem { width: 148px; height: 148px; border-radius: 18px; background: #fff; border: 1px solid rgba(255,255,255,.7); display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 0 20px 50px rgba(9,42,97,.24); transform: rotate(4deg); }.trophy-emblem img { width: 112px; height: 104px; object-fit: contain; }.trophy-emblem > span { display: flex; align-items: center; gap: 6px; color: #164a9e; font-size: 19px; font-weight: 800; margin-top: -4px; }.trophy-emblem small { color: #7d93b0; font-size: 9px; font-weight: 500; }.orbit { position: absolute; border: 1px solid rgba(255,255,255,.12); border-radius: 50%; }.orbit-one { width: 210px; height: 210px; }.orbit-two { width: 275px; height: 275px; border-style: dashed; }.floating-code { position: absolute; font: 10px 'JetBrains Mono', monospace; padding: 7px 10px; border-radius: 7px; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.13); color: rgba(255,255,255,.7); }.code-one { left: 5px; top: 60px; transform: rotate(-8deg); }.code-two { right: 0; bottom: 62px; transform: rotate(6deg); }
.contest-toolbar { display: flex; align-items: center; justify-content: space-between; margin: 27px 0 16px; }.status-tabs { display: flex; gap: 25px; }.status-tabs button { border: 0; background: none; color: var(--text-tertiary); padding: 0 0 8px; font-size: 12px; cursor: pointer; position: relative; }.status-tabs button.active { color: var(--primary); font-weight: 600; }.status-tabs button.active::after { content: ''; position: absolute; bottom: 0; left: 0; width: 20px; height: 2px; background: var(--primary); }.status-tabs button span { margin-left: 5px; font-size: 9px; padding: 1px 5px; background: #eeeef3; border-radius: 7px; }
.contest-list { display: flex; flex-direction: column; gap: 12px; }.contest-card { display: flex; align-items: center; padding: 20px 23px; position: relative; overflow: hidden; transition: transform .2s, box-shadow .2s; }.contest-card::before { content: ''; position: absolute; left: 0; top: 18px; bottom: 18px; width: 3px; border-radius: 0 3px 3px 0; background: var(--contest-accent); opacity: .8; }.contest-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }.contest-date { width: 72px; flex: none; display: flex; flex-direction: column; align-items: center; padding-right: 19px; border-right: 1px solid var(--border); }.contest-date strong { font-size: 29px; line-height: 1; letter-spacing: -1px; }.contest-date span { font-size: 10px; color: var(--text-secondary); margin-top: 5px; }.contest-date small { color: var(--text-tertiary); font-size: 9px; margin-top: 3px; }.contest-info { flex: 1; min-width: 0; padding-left: 22px; }.contest-title-line { display: flex; align-items: center; gap: 10px; }.contest-title-line h3 { margin: 0; font-size: 15px; cursor: pointer; }.contest-title-line h3:hover { color: var(--primary); }.registered-mark { display: flex; align-items: center; gap: 3px; color: var(--success); font-size: 10px; }.contest-info > p { margin: 7px 0 12px; color: var(--text-tertiary); font-size: 11px; }.contest-detail-meta { display: flex; flex-wrap: wrap; gap: 18px; }.contest-detail-meta span { display: flex; align-items: center; gap: 4px; color: var(--text-tertiary); font-size: 10px; }.contest-action { margin-left: 20px; display: flex; flex-direction: column; align-items: center; gap: 8px; min-width: 94px; }.detail-link { display: flex; align-items: center; gap: 3px; border: 0; background: none; color: var(--text-tertiary); font-size: 9px; cursor: pointer; }.detail-link:hover { color: var(--primary); }
.pagination-row { display: flex; align-items: center; justify-content: center; gap: 18px; margin-top: 20px; color: var(--text-tertiary); font-size: 11px; }
@keyframes live-pulse { 50% { opacity: .45; } }
@media (max-width: 900px) { .hero-visual { right: -70px; opacity: .6; }.hero-content { max-width: 75%; }.contest-detail-meta { gap: 10px; }.contest-heading-stats { display: none; } }
@media (max-width: 650px) { .ongoing-hero { padding: 27px 23px; min-height: 320px; }.hero-content { max-width: 100%; }.hero-content h2 { font-size: 24px; }.hero-visual { display: none; }.hero-meta { gap: 12px; }.contest-toolbar > .prototype-note { display: none; }.status-tabs { gap: 18px; }.contest-card { padding: 17px 14px; align-items: flex-start; }.contest-date { width: 51px; padding-right: 11px; }.contest-date strong { font-size: 24px; }.contest-info { padding-left: 13px; }.contest-title-line { flex-wrap: wrap; gap: 6px; }.contest-title-line h3 { width: 100%; order: -1; font-size: 14px; }.contest-detail-meta span:nth-child(n+3) { display: none; }.contest-action { margin-left: 7px; min-width: 72px; }.contest-action .el-button { padding: 8px 11px; font-size: 11px; }.detail-link { display: none; }.registered-mark { display: none; } }
</style>
