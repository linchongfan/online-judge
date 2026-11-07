<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import DifficultyTag from '../components/DifficultyTag.vue'
import { getStudyPlan, joinStudyPlan, leaveStudyPlan } from '../api/studyPlans'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { groupPlanProblems, planAccent, planProgress } from '../utils/studyPlan'
import type { StudyPlanDetail, StudyPlanProblemEntry } from '../types'

const route = useRoute()
const router = useRouter()
const plan = ref<StudyPlanDetail | null>(null)
const loading = ref(true)
const error = ref('')
const joining = ref(false)
const leaving = ref(false)

const sections = computed(() => plan.value ? groupPlanProblems(plan.value.problems) : [])
const progress = computed(() => plan.value ? planProgress(plan.value.problems) : { solved: 0, total: 0, percent: 0 })
const nextProblem = computed<StudyPlanProblemEntry | null>(() => {
  if (!plan.value?.problems.length) return null
  return plan.value.problems.find(item => item.progress !== 'solved') ?? plan.value.problems[0]
})
const heroStyle = computed(() => {
  const accent = planAccent(plan.value?.accent ?? 'blue')
  return { '--plan-from': accent.from, '--plan-to': accent.to }
})

function sectionProgress(items: StudyPlanProblemEntry[]) {
  return planProgress(items)
}

async function loadPlan() {
  const planId = Number(route.params.id)
  if (!Number.isInteger(planId) || planId <= 0) {
    error.value = '学习计划不存在'
    plan.value = null
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    plan.value = await getStudyPlan(planId)
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '学习计划加载失败'
    plan.value = null
  } finally {
    loading.value = false
  }
}

async function joinPlan() {
  if (!plan.value) return
  if (!session.loggedIn) {
    await router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  joining.value = true
  try {
    await joinStudyPlan(plan.value.id)
    plan.value = { ...plan.value, enrolled: true }
    ElMessage.success('已加入学习计划')
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : '加入学习计划失败')
  } finally {
    joining.value = false
  }
}

async function leavePlan() {
  if (!plan.value) return
  try {
    await ElMessageBox.confirm(`退出后「${plan.value.title}」将从“我的计划”中移除，做题进度不会丢失。`, '退出学习计划', {
      confirmButtonText: '确认退出',
      cancelButtonText: '继续学习',
      type: 'warning',
    })
  } catch { return }
  leaving.value = true
  try {
    await leaveStudyPlan(plan.value.id)
    plan.value = { ...plan.value, enrolled: false }
    ElMessage.success('已退出学习计划')
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : '退出学习计划失败')
  } finally {
    leaving.value = false
  }
}

function startLearning() {
  if (!plan.value || !nextProblem.value) return
  if (nextProblem.value.progress === 'solved') {
    ElMessage.success('这个计划已经全部完成，可以再练一遍巩固一下')
  }
  openProblem(nextProblem.value)
}
function openProblem(problem: StudyPlanProblemEntry) {
  if (!plan.value) return
  void router.push(`/problems/${problem.problemId}?plan=${plan.value.id}`)
}

watch(() => route.params.id, () => { void loadPlan() })
onMounted(() => { void loadPlan() })
</script>

<template>
  <div class="plan-detail-page">
    <button class="back-link" @click="router.push('/plans')"><el-icon><ArrowLeft /></el-icon>全部学习计划</button>

    <div v-if="error" class="empty-state surface-card">
      <div class="empty-icon"><el-icon :size="28"><Reading /></el-icon></div>
      <h3>学习计划不可用</h3>
      <p>{{ error }}</p>
      <el-button type="primary" plain @click="router.push('/plans')">返回学习计划</el-button>
    </div>

    <div v-else v-loading="loading" class="plan-detail-body">
      <section v-if="plan" class="plan-hero" :style="heroStyle">
        <div class="hero-grid" aria-hidden="true" />
        <div class="hero-watermark" aria-hidden="true">{{ plan.title.slice(0, 1) }}</div>
        <div class="hero-copy">
          <span class="hero-kicker">学习计划 · #{{ plan.id }}</span>
          <h1>{{ plan.title }}</h1>
          <p>{{ plan.subtitle || '按章节循序练习，把零散知识点连成完整的解题路径。' }}</p>
          <div class="hero-meta">
            <span><el-icon><Document /></el-icon>{{ plan.problemCount }} 道题</span>
            <span><el-icon><Collection /></el-icon>{{ sections.length }} 个章节</span>
            <span><el-icon><CircleCheck /></el-icon>{{ plan.solvedCount }} 题已完成</span>
          </div>
          <div class="hero-actions">
            <template v-if="!session.loggedIn">
              <el-button color="#ffffff" @click="joinPlan">登录后加入计划<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
            </template>
            <template v-else-if="plan.enrolled">
              <el-button color="#ffffff" @click="startLearning"><el-icon class="el-icon--left"><VideoPlay /></el-icon>{{ progress.percent >= 100 ? '再练一遍' : '继续学习' }}</el-button>
              <button class="ghost-action" :disabled="leaving" @click="leavePlan">退出计划</button>
            </template>
            <template v-else>
              <el-button color="#ffffff" :loading="joining" @click="joinPlan"><el-icon class="el-icon--left"><Plus /></el-icon>加入学习计划</el-button>
              <span class="guest-note">加入后可同步到“我的计划”</span>
            </template>
          </div>
        </div>
        <div class="hero-progress">
          <div class="progress-ring">
            <strong>{{ progress.percent }}<small>%</small></strong>
            <span>整体完成</span>
          </div>
          <div class="hero-progress-bar"><i :style="{ width: `${progress.percent}%` }" /></div>
          <p>{{ progress.solved }} / {{ progress.total }} 道题已完成</p>
          <span v-if="plan.completed" class="complete-pill"><el-icon><CircleCheckFilled /></el-icon>计划已完成</span>
        </div>
      </section>

      <div v-if="plan" class="plan-content">
        <div class="plan-sections">
          <section v-for="(section, index) in sections" :key="`${section.title}-${index}`" class="plan-section surface-card">
            <header class="section-heading">
              <div class="section-title">
                <span class="section-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <div>
                  <h2>{{ section.title }}</h2>
                  <p>{{ section.problems.length }} 道题</p>
                </div>
              </div>
              <div class="section-progress">
                <span>{{ sectionProgress(section.problems).solved }} / {{ section.problems.length }}</span>
                <div class="bar"><i :style="{ width: `${sectionProgress(section.problems).percent}%` }" /></div>
              </div>
            </header>
            <button
              v-for="problem in section.problems"
              :key="problem.problemId"
              class="plan-problem-row"
              :class="{ done: problem.progress === 'solved' }"
              @click="openProblem(problem)"
            >
              <span class="row-status">
                <el-icon v-if="problem.progress === 'solved'" class="solved"><CircleCheckFilled /></el-icon>
                <el-icon v-else-if="problem.progress === 'attempted'" class="attempted"><Clock /></el-icon>
                <i v-else />
              </span>
              <span class="row-name"><small>{{ problem.problemId }}</small><strong>{{ problem.title }}</strong></span>
              <span class="row-difficulty"><DifficultyTag :difficulty="problem.difficulty" /></span>
              <span class="row-tags"><i v-for="tag in problem.tags.slice(0, 3)" :key="tag">{{ tag }}</i></span>
              <span class="row-arrow"><el-icon><ArrowRight /></el-icon></span>
            </button>
          </section>

          <div v-if="!sections.length" class="empty-state surface-card">
            <h3>这个计划还没有题目</h3>
            <p>管理员配置题目后即可开始学习。</p>
          </div>
        </div>

        <aside class="plan-side">
          <section class="side-card surface-card">
            <h2>计划介绍</h2>
            <p class="plan-description">{{ plan.description || '按顺序完成本计划的题目，逐步建立完整的知识体系。' }}</p>
          </section>
          <section class="side-card surface-card">
            <h2>我的进度</h2>
            <div class="side-progress">
              <strong>{{ progress.solved }}<small> / {{ progress.total }}</small></strong>
              <span>{{ plan.enrolled ? '已加入计划' : '尚未加入' }}</span>
            </div>
            <div class="bar"><i :style="{ width: `${progress.percent}%` }" /></div>
            <p class="side-hint">{{ plan.enrolled ? '进度会根据站内 AC 自动更新。' : '加入计划后可在“我的计划”中快速找到它。' }}</p>
          </section>
          <section class="side-card surface-card">
            <h2>学习提示</h2>
            <ul class="study-tips">
              <li>建议按章节顺序完成，每题先独立尝试。</li>
              <li>通过题目后自动点亮，无需手动勾选。</li>
              <li>遇到卡点可以回到题库复习对应知识点。</li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plan-detail-page .empty-state.surface-card { border: 0; box-shadow: none; }
.plan-detail-page { padding-bottom: 40px; }
.back-link { display: inline-flex; align-items: center; gap: 5px; margin-bottom: 16px; border: 0; background: none; color: var(--text-secondary); padding: 0; font-size: 11px; cursor: pointer; }
.back-link:hover { color: var(--primary); }
.plan-detail-body { min-height: 280px; }
.plan-hero { position: relative; overflow: hidden; display: flex; align-items: center; justify-content: space-between; gap: 36px; padding: 42px 46px; border-radius: 17px; color: #fff; background: linear-gradient(125deg, var(--plan-from), var(--plan-to)); box-shadow: 0 16px 38px rgba(25, 74, 150, .18); }
.hero-grid { position: absolute; inset: 0; opacity: .07; background-image: linear-gradient(rgba(255,255,255,.7) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.7) 1px, transparent 1px); background-size: 35px 35px; mask-image: linear-gradient(90deg, #000, transparent 82%); }
.hero-watermark { position: absolute; right: 26%; top: -60px; color: rgba(255, 255, 255, .1); font-size: 260px; font-weight: 800; line-height: 1; user-select: none; }
.hero-copy { position: relative; z-index: 2; max-width: 720px; }
.hero-kicker { color: rgba(255, 255, 255, .64); font-size: 10px; letter-spacing: .8px; }
.hero-copy h1 { margin: 10px 0 9px; font-size: 32px; letter-spacing: -.9px; }
.hero-copy > p { margin: 0; max-width: 620px; color: rgba(255, 255, 255, .72); font-size: 12px; line-height: 1.7; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 19px; }
.hero-meta span { display: flex; align-items: center; gap: 5px; color: rgba(255, 255, 255, .75); font-size: 11px; }
.hero-actions { display: flex; align-items: center; gap: 16px; margin-top: 25px; }
.hero-actions .el-button { color: var(--plan-to); border: 0; font-weight: 600; padding: 10px 18px; }
.ghost-action { border: 0; background: none; color: rgba(255, 255, 255, .72); text-decoration: underline; text-underline-offset: 4px; font-size: 11px; cursor: pointer; }
.ghost-action:disabled { opacity: .5; cursor: default; }
.guest-note { color: rgba(255, 255, 255, .6); font-size: 10px; }
.hero-progress { position: relative; z-index: 2; flex: none; width: 200px; padding: 20px 20px 18px; border: 1px solid rgba(255, 255, 255, .22); border-radius: 13px; background: rgba(9, 22, 34, .24); backdrop-filter: blur(10px); text-align: center; }
.progress-ring strong { display: block; font-size: 38px; letter-spacing: -1.5px; line-height: 1; }
.progress-ring strong small { font-size: 16px; font-weight: 600; }
.progress-ring span { display: block; margin-top: 5px; color: rgba(255, 255, 255, .68); font-size: 10px; }
.hero-progress-bar { height: 5px; margin: 16px 0 9px; border-radius: 5px; background: rgba(255, 255, 255, .2); overflow: hidden; }
.hero-progress-bar i { display: block; height: 100%; border-radius: 5px; background: #fff; transition: width .3s; }
.hero-progress p { margin: 0; color: rgba(255, 255, 255, .72); font-size: 10px; }
.complete-pill { display: inline-flex; align-items: center; gap: 4px; margin-top: 11px; padding: 4px 8px; border-radius: 10px; background: rgba(255, 255, 255, .18); color: #fff; font-size: 9px; }
.plan-content { display: grid; grid-template-columns: minmax(0, 1fr) 276px; gap: 22px; align-items: start; margin-top: 24px; }
.plan-sections { display: flex; flex-direction: column; gap: 16px; }
.plan-section { overflow: hidden; border: 0; border-radius: 10px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 20px; border-bottom: 1px solid var(--border); background: #fbfdff; }
.section-title { display: flex; align-items: center; gap: 11px; min-width: 0; }
.section-index { width: 30px; height: 30px; flex: none; display: grid; place-items: center; border-radius: 8px; background: var(--primary-soft); color: var(--primary); font-size: 11px; font-weight: 700; }
.section-title h2 { margin: 0; color: var(--text-strong); font-size: 14px; }
.section-title p { margin: 3px 0 0; color: var(--text-tertiary); font-size: 9px; }
.section-progress { width: 126px; flex: none; }
.section-progress > span { display: block; margin-bottom: 5px; color: var(--text-tertiary); font-size: 9px; text-align: right; }
.bar { height: 5px; border-radius: 5px; background: #e5edf6; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 5px; background: var(--primary); transition: width .3s; }
.plan-problem-row { width: 100%; display: grid; grid-template-columns: 40px minmax(0, 1fr) 78px minmax(130px, .7fr) 20px; gap: 12px; align-items: center; min-height: 56px; padding: 9px 20px; border: 0; border-bottom: 1px solid #edf2f7; background: #fff; color: var(--text); text-align: left; cursor: pointer; }
.plan-problem-row:last-child { border-bottom: 0; }
.plan-problem-row:hover { background: #f6faff; }
.plan-problem-row:hover .row-name strong { color: var(--primary); }
.plan-problem-row.done .row-name strong { color: var(--text-secondary); }
.row-status { display: flex; justify-content: center; color: #c2cdd9; font-size: 17px; }
.row-status .solved { color: var(--success); }
.row-status .attempted { color: var(--warning); }
.row-status > i { width: 13px; height: 13px; border: 1.5px solid #d0dbe7; border-radius: 50%; }
.row-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
.row-name small { color: var(--text-tertiary); font-size: 10px; }
.row-name strong { overflow: hidden; color: var(--text-strong); font-size: 12px; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; }
.row-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.row-tags i { padding: 3px 6px; border-radius: 4px; background: #f0f4f8; color: var(--text-secondary); font-size: 9px; font-style: normal; white-space: nowrap; }
.row-arrow { color: #a8b6c5; }
.plan-side { display: flex; flex-direction: column; gap: 14px; }
.side-card { padding: 18px 19px; border: 0; border-radius: 10px; }
.side-card h2 { margin: 0 0 11px; color: var(--text-strong); font-size: 13px; }
.plan-description { margin: 0; color: var(--text-secondary); font-size: 11px; line-height: 1.8; white-space: pre-line; }
.side-progress { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 9px; }
.side-progress strong { color: var(--primary); font-size: 25px; letter-spacing: -.5px; }
.side-progress strong small { color: var(--text-tertiary); font-size: 11px; font-weight: 500; }
.side-progress span { color: var(--text-tertiary); font-size: 10px; }
.side-hint { margin: 10px 0 0; color: var(--text-tertiary); font-size: 9px; line-height: 1.7; }
.study-tips { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 9px; }
.study-tips li { position: relative; padding-left: 13px; color: var(--text-secondary); font-size: 10px; line-height: 1.65; }
.study-tips li::before { content: ''; position: absolute; left: 0; top: 6px; width: 5px; height: 5px; border-radius: 50%; background: var(--accent); }
@media (max-width: 1080px) {
  .plan-content { grid-template-columns: 1fr; }
  .plan-side { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .plan-hero { padding: 30px 28px; }
  .hero-progress { width: 170px; }
  .hero-copy h1 { font-size: 27px; }
  .plan-side { grid-template-columns: 1fr 1fr; }
  .plan-side .side-card:last-child { grid-column: 1 / -1; }
  .plan-problem-row { grid-template-columns: 34px minmax(0, 1fr) 70px 18px; }
  .plan-problem-row .row-tags { display: none; }
}
@media (max-width: 700px) {
  .plan-hero { flex-direction: column; align-items: flex-start; padding: 26px 22px; }
  .hero-progress { width: 100%; display: flex; align-items: center; gap: 18px; text-align: left; }
  .progress-ring { flex: none; }
  .hero-progress-bar { flex: 1; margin: 0; }
  .hero-progress p { display: none; }
  .complete-pill { margin-top: 0; }
  .hero-watermark { right: -20px; font-size: 200px; }
  .hero-copy h1 { font-size: 23px; }
  .plan-side { display: flex; }
  .section-heading { flex-direction: column; align-items: flex-start; gap: 10px; }
  .section-progress { width: 100%; }
  .section-progress > span { text-align: left; }
  .plan-problem-row { grid-template-columns: 30px minmax(0, 1fr) 16px; padding: 10px 14px; }
  .plan-problem-row .row-difficulty { display: none; }
  .hero-actions { flex-wrap: wrap; }
}
</style>
