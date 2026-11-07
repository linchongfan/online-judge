<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listStudyPlans } from '../api/studyPlans'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { planAccent, summaryProgress } from '../utils/studyPlan'
import type { StudyPlanSummary } from '../types'

const router = useRouter()
const plans = ref<StudyPlanSummary[]>([])
const loading = ref(true)
const error = ref('')
const activeTab = ref<'all' | 'mine'>('all')

const myPlans = computed(() => plans.value.filter(plan => plan.enrolled))
const completedCount = computed(() => plans.value.filter(plan => plan.completed).length)
const visiblePlans = computed(() => activeTab.value === 'mine' ? myPlans.value : plans.value)

async function loadPlans() {
  loading.value = true
  error.value = ''
  try {
    plans.value = await listStudyPlans()
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught.message : '学习计划加载失败'
    plans.value = []
  } finally {
    loading.value = false
  }
}

function openPlan(planId: number) {
  void router.push(`/plans/${planId}`)
}
function openLogin() {
  void router.push({ path: '/login', query: { redirect: '/plans' } })
}

watch(() => session.loggedIn, () => {
  if (!session.loggedIn) activeTab.value = 'all'
  void loadPlans()
})
onMounted(() => { void loadPlans() })
</script>

<template>
  <div class="plans-page">
    <div class="page-heading plans-heading">
      <div>
        <span class="eyebrow">学习计划</span>
        <h1>按计划学，把知识点连成线。</h1>
        <p>跟着精心编排的题目路径逐章练习，完成状态由站内提交自动更新。</p>
      </div>
      <div class="plan-heading-stats">
        <div><strong>{{ plans.length }}</strong><span>公开计划</span></div>
        <i />
        <div><strong>{{ myPlans.length }}</strong><span>我的计划</span></div>
        <i />
        <div><strong>{{ completedCount }}</strong><span>已完成</span></div>
      </div>
    </div>

    <div class="plan-toolbar">
      <div class="status-tabs">
        <button :class="{ active: activeTab === 'all' }" @click="activeTab = 'all'">全部计划<span>{{ plans.length }}</span></button>
        <button :class="{ active: activeTab === 'mine' }" @click="activeTab = 'mine'">我的计划<span>{{ myPlans.length }}</span></button>
      </div>
      <span class="plan-toolbar-note">加入计划后可在这里快速继续学习</span>
    </div>

    <div v-if="error" class="empty-state surface-card">
      <h3>学习计划加载失败</h3>
      <p>{{ error }}</p>
      <el-button type="primary" @click="loadPlans">重新加载</el-button>
    </div>

    <div v-else v-loading="loading" class="plan-grid-wrap">
      <div v-if="visiblePlans.length" class="plan-grid">
        <article
          v-for="plan in visiblePlans"
          :key="plan.id"
          class="plan-card surface-card"
          role="link"
          tabindex="0"
          :style="{ '--plan-from': planAccent(plan.accent).from, '--plan-to': planAccent(plan.accent).to }"
          @click="openPlan(plan.id)"
          @keydown.enter="openPlan(plan.id)"
        >
          <div class="plan-cover">
            <span class="plan-watermark" aria-hidden="true">{{ plan.title.slice(0, 1) }}</span>
            <div class="cover-ring ring-one" aria-hidden="true" />
            <div class="cover-ring ring-two" aria-hidden="true" />
            <div class="plan-cover-top">
              <span>计划 #{{ plan.id }}</span>
              <span v-if="plan.completed" class="cover-badge">已完成</span>
              <span v-else-if="plan.enrolled" class="cover-badge joined">学习中</span>
            </div>
            <div class="plan-cover-copy">
              <h2>{{ plan.title }}</h2>
              <p>{{ plan.subtitle || '系统化的题目练习路径' }}</p>
            </div>
          </div>
          <div class="plan-body">
            <div class="plan-meta">
              <span><el-icon><Document /></el-icon>{{ plan.problemCount }} 道题</span>
              <span v-if="plan.enrolled" class="meta-joined"><el-icon><CircleCheck /></el-icon>已加入</span>
              <span v-else>可随时加入</span>
            </div>
            <div v-if="session.loggedIn" class="plan-progress">
              <div class="plan-progress-label"><span>完成进度</span><strong>{{ plan.solvedCount }} / {{ plan.problemCount }}</strong></div>
              <div class="bar"><i :style="{ width: `${summaryProgress(plan)}%` }" /></div>
            </div>
            <div v-else class="plan-login-hint">登录后记录计划进度</div>
            <div class="plan-action">
              <span>{{ plan.enrolled ? (plan.completed ? '再练一遍' : '继续学习') : '查看计划' }}</span>
              <el-icon><ArrowRight /></el-icon>
            </div>
          </div>
        </article>
      </div>

      <div v-else-if="!loading" class="empty-state surface-card plan-empty">
        <div class="empty-icon"><el-icon :size="28"><Reading /></el-icon></div>
        <template v-if="activeTab === 'mine' && !session.loggedIn">
          <h3>登录后查看我的学习计划</h3>
          <p>加入计划可以集中跟踪每一章的学习进度。</p>
          <el-button type="primary" @click="openLogin">登录 / 注册</el-button>
        </template>
        <template v-else-if="activeTab === 'mine'">
          <h3>还没有加入学习计划</h3>
          <p>从公开计划里选一条适合你的路径开始吧。</p>
          <el-button type="primary" plain @click="activeTab = 'all'">浏览全部计划</el-button>
        </template>
        <template v-else>
          <h3>暂时还没有公开的学习计划</h3>
          <p>管理员发布计划后会显示在这里。</p>
        </template>
      </div>
    </div>

    <div class="study-note"><el-icon><InfoFilled /></el-icon><span>题目通过后会自动计入计划进度；加入计划只是收藏学习路径，不影响题库原有进度。</span></div>
  </div>
</template>

<style scoped>
.plans-heading { align-items: flex-end; }
.plan-heading-stats { display: flex; align-items: center; gap: 24px; padding: 8px 0; }
.plan-heading-stats div { display: flex; flex-direction: column; gap: 4px; }
.plan-heading-stats strong { color: var(--text-strong); font-size: 23px; letter-spacing: -.5px; }
.plan-heading-stats span { color: var(--text-tertiary); font-size: 10px; }
.plan-heading-stats i { width: 1px; height: 35px; background: var(--border); }
.plan-toolbar { display: flex; align-items: center; justify-content: space-between; margin: 26px 0 16px; }
.plan-toolbar-note { color: var(--text-tertiary); font-size: 10px; }
.status-tabs { display: flex; gap: 25px; }
.status-tabs button { border: 0; background: none; color: var(--text-tertiary); padding: 0 0 8px; font-size: 12px; cursor: pointer; position: relative; }
.status-tabs button.active { color: var(--primary); font-weight: 600; }
.status-tabs button.active::after { content: ''; position: absolute; bottom: 0; left: 0; width: 20px; height: 2px; background: var(--primary); }
.status-tabs button span { margin-left: 5px; padding: 1px 5px; border-radius: 7px; background: #eeeef3; font-size: 9px; }
.plan-grid-wrap { min-height: 220px; }
.plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(262px, 1fr)); gap: 18px; }
.plan-card { padding: 0; overflow: hidden; border: 0; cursor: pointer; transition: transform .2s, box-shadow .2s; outline: none; }
.plan-card:hover, .plan-card:focus-visible { transform: translateY(-3px); box-shadow: var(--shadow-md); }
.plan-cover { position: relative; height: 158px; padding: 16px 18px; overflow: hidden; color: #fff; background: linear-gradient(135deg, var(--plan-from), var(--plan-to)); }
.plan-cover-copy { position: absolute; left: 18px; right: 18px; bottom: 17px; z-index: 2; }
.plan-cover-copy h2 { margin: 0 0 6px; font-size: 19px; letter-spacing: -.4px; text-shadow: 0 1px 10px rgba(0, 0, 0, .16); }
.plan-cover-copy p { margin: 0; color: rgba(255, 255, 255, .72); font-size: 11px; line-height: 1.5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.plan-cover-top { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; color: rgba(255, 255, 255, .62); font-size: 9px; }
.cover-badge { padding: 3px 7px; border-radius: 10px; background: rgba(255, 255, 255, .2); color: #fff; }
.cover-badge.joined { background: rgba(255, 255, 255, .18); }
.plan-watermark { position: absolute; right: -4px; top: -32px; z-index: 1; color: rgba(255, 255, 255, .12); font-size: 150px; font-weight: 800; line-height: 1; user-select: none; }
.cover-ring { position: absolute; border: 1px solid rgba(255, 255, 255, .16); border-radius: 50%; }
.ring-one { width: 190px; height: 190px; right: -58px; bottom: -95px; }
.ring-two { width: 118px; height: 118px; right: 12px; bottom: -68px; border-style: dashed; }
.plan-body { padding: 15px 18px 16px; }
.plan-meta { display: flex; align-items: center; gap: 14px; color: var(--text-tertiary); font-size: 10px; }
.plan-meta span { display: flex; align-items: center; gap: 4px; }
.plan-meta .meta-joined { color: var(--success); }
.plan-progress { margin-top: 14px; }
.plan-progress-label { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; color: var(--text-tertiary); font-size: 10px; }
.plan-progress-label strong { color: var(--text-secondary); font-weight: 600; }
.bar { height: 5px; border-radius: 5px; background: #e5edf6; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 5px; background: var(--primary); transition: width .3s; }
.plan-login-hint { margin-top: 14px; color: var(--text-tertiary); font-size: 10px; }
.plan-action { display: flex; align-items: center; justify-content: space-between; margin-top: 15px; padding-top: 12px; border-top: 1px solid #edf2f7; color: var(--primary); font-size: 11px; font-weight: 600; }
.plan-empty { padding: 52px 20px; border: 0; box-shadow: none; }
.study-note { display: flex; align-items: center; gap: 6px; margin-top: 18px; color: var(--text-tertiary); font-size: 10px; }
@media (max-width: 900px) {
  .plan-heading-stats { display: none; }
  .plan-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .plan-toolbar-note { display: none; }
  .plan-grid { grid-template-columns: 1fr; }
  .plan-cover { height: 146px; }
  .study-note { align-items: flex-start; line-height: 1.7; }
}
</style>
