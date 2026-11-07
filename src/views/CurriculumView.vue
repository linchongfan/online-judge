<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleCheckFilled, Clock, Reading } from '@element-plus/icons-vue'
import DifficultyTag from '../components/DifficultyTag.vue'
import { listProblems } from '../api/problems'
import { session } from '../stores/session'
import { formatNumber } from '../utils/format'
import type { ProblemListItem } from '../types'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const problems = ref<ProblemListItem[]>([])

// 题号区间与模块一一对应：2000-2009 为第一个模块，依此每 10 题一个模块。
const MODULES = [
  { name: '程序设计入门', goal: '算法、程序结构、编译运行与注释', start: 2000 },
  { name: '数据与表达式', goal: '变量、常量、数据类型、运算符与类型转换', start: 2010 },
  { name: '输入与输出', goal: 'printf、scanf 与格式控制', start: 2020 },
  { name: '选择结构', goal: 'if、if-else、嵌套判断与 switch', start: 2030 },
  { name: '循环结构', goal: 'while、do-while、for 与循环嵌套', start: 2040 },
  { name: '数组与字符串', goal: '一维数组、二维数组、字符数组与字符串', start: 2050 },
  { name: '函数', goal: '函数定义调用、参数、返回值与递归', start: 2060 },
  { name: '指针', goal: '地址、指针变量、数组与指针、指针参数', start: 2070 },
  { name: '构造类型', goal: '结构体、结构体数组与枚举', start: 2080 },
  { name: '文件与综合应用', goal: '文件读写、数据组织与综合练习', start: 2090 },
]

const byModule = computed(() => {
  const groups = MODULES.map(module => ({ ...module, items: [] as ProblemListItem[] }))
  for (const problem of problems.value) {
    const index = Math.floor((problem.id - 2000) / 10)
    if (index >= 0 && index < groups.length) groups[index].items.push(problem)
  }
  for (const group of groups) group.items.sort((a, b) => a.id - b.id)
  return groups
})

const totalSolved = computed(() => problems.value.filter(item => item.progress === 'solved').length)
const totalPlanned = computed(() => byModule.value.reduce((sum, group) => sum + group.items.length, 0))
const totalPercent = computed(() => (totalPlanned.value ? Math.round((totalSolved.value / totalPlanned.value) * 100) : 0))

function moduleSolved(items: ProblemListItem[]): number {
  return items.filter(item => item.progress === 'solved').length
}

function modulePercent(items: ProblemListItem[]): number {
  return items.length ? Math.round((moduleSolved(items) / items.length) * 100) : 0
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const first = await listProblems({ page: 1, pageSize: 100 })
    const pages = [first]
    for (let page = 2; page <= first.pages; page += 1) {
      pages.push(await listProblems({ page, pageSize: 100 }))
    }
    problems.value = pages
      .flatMap(page => page.items)
      .filter(item => item.id >= 2000 && item.id <= 2099)
  } catch {
    error.value = '题单加载失败，请稍后重试'
    problems.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="curriculum-page">
    <div class="curriculum-hero">
      <div>
        <span class="hero-kicker"><el-icon><Reading /></el-icon> C 语言培养方案</span>
        <h1>按知识模块，从第一行代码练到综合应用</h1>
        <p>10 个模块、{{ totalPlanned }} 道题，由易到难排列。每模块建议按顺序完成，遇到卡点回到对应章节复习。</p>
      </div>
      <div class="hero-progress">
        <span>我的进度</span>
        <strong>{{ totalSolved }} <small>/ {{ totalPlanned }}</small></strong>
        <div class="bar"><i :style="{ width: `${totalPercent}%` }" /></div>
        <em>{{ session.loggedIn ? `已完成 ${totalPercent}%` : '登录后记录完成情况' }}</em>
      </div>
    </div>

    <div v-if="error" class="empty-state"><h3>{{ error }}</h3><el-button type="primary" @click="load">重新加载</el-button></div>
    <div v-else v-loading="loading" class="module-list">
      <section v-for="(group, index) in byModule" :key="group.start" class="module-card">
        <header class="module-head">
          <span class="module-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="module-title">
            <h2>{{ group.name }}</h2>
            <p>{{ group.goal }}</p>
          </div>
          <div class="module-progress">
            <span>{{ moduleSolved(group.items) }} / {{ group.items.length }}</span>
            <div class="bar"><i :style="{ width: `${modulePercent(group.items)}%` }" /></div>
          </div>
        </header>
        <div class="module-grid module-grid-head">
          <span>状态</span><span>题目</span><span>难度</span><span>通过率</span><span>提交数</span><span />
        </div>
        <button
          v-for="problem in group.items"
          :key="problem.id"
          class="module-grid module-row"
          @click="router.push(`/problems/${problem.id}`)"
        >
          <span class="row-status">
            <el-icon v-if="problem.progress === 'solved'" class="solved"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="problem.progress === 'attempted'" class="attempted"><Clock /></el-icon>
            <i v-else />
          </span>
          <span class="row-name"><small>{{ problem.id }}</small><strong>{{ problem.title }}</strong></span>
          <span><DifficultyTag :difficulty="problem.difficulty" /></span>
          <span class="row-acceptance">{{ problem.acceptance }}%</span>
          <span class="row-count">{{ formatNumber(problem.submissionCount) }}</span>
          <span class="row-arrow">›</span>
        </button>
        <div v-if="!group.items.length" class="module-empty">该模块题目暂未上线</div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.curriculum-page { padding-bottom: 40px; }
.curriculum-hero { display: flex; align-items: center; justify-content: space-between; gap: 32px; padding: 24px 0; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
.hero-kicker { display: inline-flex; align-items: center; gap: 6px; color: var(--primary); font-size: 12px; font-weight: 600; }
.hero-kicker .el-icon { font-size: 15px; }
.curriculum-hero h1 { margin: 9px 0 10px; color: #123668; font-size: 29px; letter-spacing: -.8px; }
.curriculum-hero p { margin: 0; max-width: 720px; color: #5f7695; font-size: 13px; line-height: 1.7; }
.hero-progress { flex: none; min-width: 220px; padding: 16px 20px; border: 1px solid var(--border); border-radius: 10px; background: #fff; }
.hero-progress span { color: var(--text-tertiary); font-size: 11px; }
.hero-progress strong { display: block; margin: 6px 0 10px; color: var(--primary); font-size: 27px; line-height: 1; }
.hero-progress strong small { color: var(--text-tertiary); font-size: 13px; font-weight: 500; }
.hero-progress em { display: block; margin-top: 8px; color: var(--text-tertiary); font-size: 10px; font-style: normal; }
.bar { height: 5px; border-radius: 5px; background: #e5edf6; overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 5px; background: var(--primary); }
.module-list { display: flex; flex-direction: column; gap: 18px; }
.module-card { border: 1px solid var(--border); border-radius: 10px; background: #fff; overflow: hidden; box-shadow: var(--shadow-sm); }
.module-head { display: flex; align-items: center; gap: 16px; padding: 16px 20px; background: #fbfdff; border-bottom: 1px solid var(--border); }
.module-index { flex: none; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; background: var(--primary-soft); color: var(--primary); font-size: 13px; font-weight: 700; }
.module-title { flex: 1; min-width: 0; }
.module-title h2 { margin: 0; color: var(--text-strong); font-size: 15px; }
.module-title p { margin: 5px 0 0; color: var(--text-tertiary); font-size: 11px; }
.module-progress { flex: none; width: 150px; }
.module-progress span { display: block; margin-bottom: 7px; color: var(--text-secondary); font-size: 11px; text-align: right; }
.module-grid { display: grid; grid-template-columns: 56px minmax(0, 1fr) 90px 110px 90px 28px; align-items: center; gap: 12px; padding: 0 20px; }
.module-grid-head { height: 38px; color: var(--text-tertiary); font-size: 10px; border-bottom: 1px solid #edf2f7; }
.module-row { width: 100%; min-height: 54px; border: 0; border-bottom: 1px solid #edf2f7; background: #fff; color: var(--text); text-align: left; cursor: pointer; transition: background .15s; }
.module-row:last-of-type { border-bottom: 0; }
.module-row:hover { background: #f6faff; }
.module-row:hover .row-name strong { color: var(--primary); }
.row-status { display: flex; justify-content: center; color: #c2cdd9; font-size: 17px; }
.row-status .solved { color: var(--success); }
.row-status .attempted { color: var(--warning); }
.row-status > i { width: 13px; height: 13px; border: 1.5px solid #d0dbe7; border-radius: 50%; }
.row-name { display: flex; align-items: center; gap: 10px; min-width: 0; }
.row-name small { flex: none; color: var(--text-tertiary); font-size: 11px; font-variant-numeric: tabular-nums; }
.row-name strong { overflow: hidden; color: var(--text); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.row-acceptance, .row-count { color: var(--text-secondary); font-size: 12px; font-variant-numeric: tabular-nums; }
.row-arrow { color: #c2cdd9; font-size: 16px; text-align: right; }
.module-empty { padding: 22px 20px; color: var(--text-tertiary); font-size: 12px; }
@media (max-width: 900px) {
  .curriculum-hero { align-items: flex-start; flex-direction: column; gap: 18px; }
  .hero-progress { width: 100%; }
  .module-grid { grid-template-columns: 44px minmax(0, 1fr) 80px 70px 24px; }
  .module-grid > :nth-child(5) { display: none; }
  .module-progress { width: 110px; }
}
@media (max-width: 600px) {
  .module-grid { grid-template-columns: 36px minmax(0, 1fr) 70px 22px; padding: 0 14px; }
  .module-grid > :nth-child(4) { display: none; }
  .module-head { padding: 14px; }
  .module-title p { display: none; }
  .module-progress { width: 84px; }
}
</style>
