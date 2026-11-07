<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DifficultyTag from '../components/DifficultyTag.vue'
import { getRandomProblem, listProblems, listTags } from '../api/problems'
import { getUserStats } from '../api/me'
import { ApiError } from '../api/client'
import { session } from '../stores/session'
import { formatNumber } from '../utils/format'
import type { Difficulty, ProblemListItem, ProblemProgress, Tag, UserStats } from '../types'

const router = useRouter()
const keyword = ref('')
const difficulty = ref<Difficulty | ''>('')
const tag = ref('')
const progress = ref<ProblemProgress | ''>('')
const currentPage = ref(1)
const filtersOpen = ref(false)
const pageSize = 8
const pageItems = ref<ProblemListItem[]>([])
const allTags = ref<Tag[]>([])
const tagsExpanded = ref(false)
const stats = ref<UserStats | null>(null)
const total = ref(0)
const loading = ref(false)
const error = ref('')
let requestGeneration = 0

const CORE_TAG_THRESHOLD = 5
// 培养方案模块按学习顺序排在前面，其余知识点按覆盖题目数排序。
const MODULE_TAG_ORDER = ['C语言入门', '数据与表达式', '输入与输出', '选择结构', '循环结构', '数组与字符串', '函数', '指针', '构造类型', '文件']
const moduleTagIndex = new Map(MODULE_TAG_ORDER.map((name, index) => [name, index]))
const sortedTags = computed(() => [...allTags.value].sort((a, b) => {
  const aIndex = moduleTagIndex.get(a.name)
  const bIndex = moduleTagIndex.get(b.name)
  if (aIndex !== undefined || bIndex !== undefined) {
    if (aIndex === undefined) return 1
    if (bIndex === undefined) return -1
    return aIndex - bIndex
  }
  return b.problemCount - a.problemCount
}))
const coreTags = computed(() => {
  const core = sortedTags.value.filter(item => item.problemCount >= CORE_TAG_THRESHOLD)
  return core.length ? core : sortedTags.value.slice(0, 12)
})
const hiddenTagCount = computed(() => Math.max(0, sortedTags.value.length - coreTags.value.length))
const visibleTags = computed(() => {
  if (tagsExpanded.value) return sortedTags.value
  if (!tag.value || coreTags.value.some(item => item.name === tag.value)) return coreTags.value
  const selected = sortedTags.value.find(item => item.name === tag.value)
  return selected ? [...coreTags.value, selected] : coreTags.value
})

const hasFilters = computed(() => Boolean(keyword.value || difficulty.value || tag.value || progress.value))
const totalProblems = computed(() => stats.value?.difficultyProgress.reduce((sum, item) => sum + item.total, 0) ?? 0)
const solvedProblems = computed(() => stats.value?.solvedCount ?? 0)
const practicePercent = computed(() => totalProblems.value ? Math.min(100, solvedProblems.value / totalProblems.value * 100) : 0)

function difficultyTotal(value: Difficulty): number | string {
  return stats.value?.difficultyProgress.find(item => item.difficulty === value)?.total ?? ''
}

async function loadProblems() {
  const generation = ++requestGeneration
  loading.value = true
  error.value = ''
  try {
    const data = await listProblems({
      page: currentPage.value,
      pageSize,
      keyword: keyword.value.trim() || undefined,
      difficulty: difficulty.value || undefined,
      tag: tag.value || undefined,
      progress: progress.value || undefined,
    })
    if (generation !== requestGeneration) return
    pageItems.value = data.items
    total.value = data.total
    if (data.total > 0 && data.items.length === 0 && currentPage.value > 1) currentPage.value = data.pages
  } catch (caught) {
    if (generation !== requestGeneration) return
    error.value = caught instanceof ApiError ? caught.message : '题目加载失败'
    pageItems.value = []
    total.value = 0
  } finally {
    if (generation === requestGeneration) loading.value = false
  }
}

async function loadStats() {
  if (!session.loggedIn) {
    stats.value = null
    return
  }
  try { stats.value = await getUserStats() } catch { stats.value = null }
}

function resetFilters() {
  keyword.value = ''
  difficulty.value = ''
  tag.value = ''
  progress.value = ''
  currentPage.value = 1
  void loadProblems()
}
function selectTag(value: string) {
  tag.value = tag.value === value ? '' : value
  currentPage.value = 1
  void loadProblems()
}
function setDifficulty(value: Difficulty | '') {
  difficulty.value = value
  currentPage.value = 1
  void loadProblems()
}
async function openRandom() {
  try {
    const problem = await getRandomProblem()
    await router.push(`/problems/${problem.id}`)
  } catch (caught) {
    ElMessage.error(caught instanceof ApiError ? caught.message : '随机选题失败')
  }
}

watch([keyword, progress], () => { currentPage.value = 1; void loadProblems() })
watch(currentPage, () => { void loadProblems() })
watch(() => session.loggedIn, (loggedIn) => {
  if (!loggedIn) progress.value = ''
  void loadStats()
  void loadProblems()
})
onMounted(() => {
  void loadProblems()
  void loadStats()
  void listTags().then(items => { allTags.value = items }).catch(() => {})
})
</script>

<template>
  <div class="problem-page">
    <header class="library-hero">
      <div class="hero-copy"><span class="hero-kicker">算法学习路径</span><h1>把知识点，练成解题能力。</h1><p>从基础语法到综合算法，按自己的节奏积累每一次进步。</p></div>
      <div class="learning-streak">
        <img src="/images/xinbaoyan-mark.png" alt="新保研猫头鹰" />
        <div class="streak-content"><span>连续学习</span><strong>{{ session.loggedIn ? `已坚持 ${stats?.streak ?? 0} 天` : '登录后记录学习进度' }}</strong><div v-if="session.loggedIn" class="week-dots" aria-label="连续学习记录"><i v-for="day in 7" :key="day" :class="{ done: day <= Math.min(7, stats?.streak ?? 0) }">{{ ['一','二','三','四','五','六','日'][day - 1] }}</i></div></div>
      </div>
    </header>

    <div class="library-layout">
      <button class="mobile-filter-toggle" :class="{ active: filtersOpen || hasFilters }" @click="filtersOpen = !filtersOpen"><el-icon><Operation /></el-icon>筛选题目<span v-if="hasFilters">已设置</span><el-icon class="toggle-arrow"><ArrowDown v-if="!filtersOpen" /><ArrowUp v-else /></el-icon></button>
      <aside class="filter-rail" :class="{ open: filtersOpen }">
        <section class="practice-overview">
          <div class="rail-heading"><h2>我的练习</h2><span>真实提交统计</span></div>
          <div class="practice-count"><strong>{{ session.loggedIn ? solvedProblems : '—' }}</strong><span>/ {{ session.loggedIn ? totalProblems : '未登录' }} 题</span></div>
          <div class="practice-progress"><i :style="{ width: `${practicePercent}%` }" /></div>
          <div class="practice-legend"><span><i class="solved" />已通过 <strong>{{ session.loggedIn ? stats?.acceptedCount ?? 0 : '—' }}</strong></span><span><i class="attempted" />累计提交 <strong>{{ session.loggedIn ? stats?.submissionCount ?? 0 : '—' }}</strong></span></div>
        </section>

        <section class="rail-section">
          <div class="rail-heading"><h2>难度</h2></div>
          <div class="difficulty-filter">
            <button :class="{ active: difficulty === '' }" @click="setDifficulty('')">全部难度<span>{{ session.loggedIn ? totalProblems : '' }}</span></button>
            <button :class="{ active: difficulty === '简单' }" @click="setDifficulty('简单')"><i class="easy" />简单<span>{{ difficultyTotal('简单') }}</span></button>
            <button :class="{ active: difficulty === '中等' }" @click="setDifficulty('中等')"><i class="medium" />中等<span>{{ difficultyTotal('中等') }}</span></button>
            <button :class="{ active: difficulty === '困难' }" @click="setDifficulty('困难')"><i class="hard" />困难<span>{{ difficultyTotal('困难') }}</span></button>
          </div>
        </section>

        <section class="rail-section tag-section">
          <div class="rail-heading"><h2>知识点</h2><span>{{ tag ? '已选 1 项' : '可单选' }}</span></div>
          <div class="tag-list"><button v-for="item in visibleTags" :key="item.id" :class="{ active: tag === item.name }" @click="selectTag(item.name)">{{ item.name }}<el-icon v-if="tag === item.name"><Check /></el-icon></button></div>
          <button v-if="hiddenTagCount" class="tag-toggle" @click="tagsExpanded = !tagsExpanded">
            {{ tagsExpanded ? '收起' : `展开全部 ${allTags.length} 个` }}
            <el-icon><ArrowUp v-if="tagsExpanded" /><ArrowDown v-else /></el-icon>
          </button>
        </section>
        <button class="clear-filters" :disabled="!hasFilters" @click="resetFilters"><el-icon><RefreshLeft /></el-icon>清空筛选条件</button>
      </aside>

      <section class="library-main">
        <div class="library-toolbar">
          <el-input v-model="keyword" class="search-input" placeholder="搜索题目名称" clearable>
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="progress" placeholder="全部完成状态" clearable :disabled="!session.loggedIn" @change="currentPage = 1">
            <el-option label="已通过" value="solved" /><el-option label="尝试过" value="attempted" /><el-option label="未开始" value="untouched" />
          </el-select>
          <el-button class="random-button" @click="openRandom"><el-icon><MagicStick /></el-icon>随机一题</el-button>
        </div>

        <div class="catalog-card" v-loading="loading">
          <div class="catalog-heading"><div><h2>题目目录</h2><span>共 {{ total }} 道符合条件的题目</span></div><span class="catalog-tip">点击题目开始练习</span></div>
          <div class="problem-grid problem-grid-head"><span>状态</span><span>题目</span><span>难度</span><span>知识点</span><span>通过率</span><span>提交数</span><span /></div>
          <div v-if="error" class="empty-state"><h3>题目加载失败</h3><p>{{ error }}</p><el-button type="primary" @click="loadProblems">重新加载</el-button></div>
          <div v-else-if="pageItems.length" class="problem-rows">
            <button v-for="problem in pageItems" :key="problem.id" class="problem-grid problem-row" @click="router.push(`/problems/${problem.id}`)">
              <span class="progress-status"><el-icon v-if="problem.progress === 'solved'" class="solved"><CircleCheckFilled /></el-icon><el-icon v-else-if="problem.progress === 'attempted'" class="attempted"><Clock /></el-icon><i v-else /></span>
              <span class="problem-name"><span><small>{{ problem.id }}</small><strong>{{ problem.title }}</strong></span></span>
              <span><DifficultyTag :difficulty="problem.difficulty" /></span>
              <span class="problem-tags"><i v-for="item in problem.tags.slice(0, 3)" :key="item">{{ item }}</i></span>
              <span class="acceptance"><strong>{{ problem.acceptance }}%</strong><i><b :style="{ width: `${problem.acceptance}%` }" /></i></span>
              <span class="submission-count">{{ formatNumber(problem.submissionCount) }}</span>
              <span class="row-arrow"><el-icon><ArrowRight /></el-icon></span>
            </button>
          </div>
          <div v-else class="empty-state"><div class="empty-icon"><el-icon :size="28"><Search /></el-icon></div><h3>没有找到匹配的题目</h3><p>调整关键词或减少筛选条件后再试一次</p><el-button type="primary" plain @click="resetFilters">清空筛选</el-button></div>
          <div class="catalog-footer"><span>第 {{ currentPage }} 页，共 {{ total }} 道题</span><el-pagination v-model:current-page="currentPage" layout="prev, pager, next" :total="total" :page-size="pageSize" :pager-count="5" background /></div>
        </div>
        <div class="study-note"><el-icon><InfoFilled /></el-icon><span>建议先独立完成，再查看提交结果。隐藏测试点不会展示输入和标准答案。</span></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.library-hero { display: flex; align-items: center; justify-content: space-between; gap: 32px; padding: 24px 0; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
.hero-copy { position: relative; z-index: 1; }
.hero-kicker { color: var(--primary); font-size: 12px; font-weight: 600; }
.hero-copy h1 { margin: 9px 0 10px; color: #123668; font-size: 29px; letter-spacing: -.8px; }
.hero-copy p { margin: 0; color: #5f7695; font-size: 13px; }
.learning-streak { display: flex; align-items: center; gap: 15px; min-width: 320px; }
.learning-streak > img { width: 70px; height: 66px; object-fit: contain; }
.streak-content { flex: 1; }
.streak-content > span { color: var(--text-tertiary); font-size: 10px; }
.streak-content > strong { display: block; margin: 3px 0 10px; color: var(--text-strong); font-size: 16px; }
.week-dots { display: flex; gap: 5px; }
.week-dots i { width: 23px; height: 23px; display: grid; place-items: center; border-radius: 50%; background: #edf1f6; color: #91a1b4; font-size: 9px; font-style: normal; }
.week-dots i.done { background: var(--primary); color: #fff; }
.week-dots i.done:last-child { background: var(--accent); }
.library-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 22px; align-items: start; }
.mobile-filter-toggle { display: none; }
.filter-rail { background: #fff; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.practice-overview { padding: 20px; background: #fbfdff; border-bottom: 1px solid var(--border); }
.rail-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.rail-heading h2 { margin: 0; color: var(--text-strong); font-size: 13px; }
.rail-heading > span { color: var(--text-tertiary); font-size: 9px; }
.practice-count { display: flex; align-items: baseline; gap: 5px; margin: 14px 0 10px; }
.practice-count strong { color: var(--primary); font-size: 29px; line-height: 1; }
.practice-count span { color: var(--text-tertiary); font-size: 11px; }
.practice-progress { height: 5px; border-radius: 5px; background: #e5edf6; overflow: hidden; }
.practice-progress i { display: block; width: 36.7%; height: 100%; background: var(--primary); }
.practice-legend { display: flex; flex-direction: column; gap: 8px; margin-top: 15px; }
.practice-legend > span { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 10px; }
.practice-legend i { width: 6px; height: 6px; border-radius: 50%; }
.practice-legend i.solved { background: var(--success); }.practice-legend i.attempted { background: var(--warning); }
.practice-legend strong { margin-left: auto; color: var(--text); }
.rail-section { padding: 18px 16px; border-bottom: 1px solid var(--border); }
.difficulty-filter { display: flex; flex-direction: column; gap: 3px; margin-top: 11px; }
.difficulty-filter button { display: flex; align-items: center; gap: 8px; border: 0; border-radius: 6px; background: transparent; color: var(--text-secondary); padding: 8px 9px; font-size: 11px; text-align: left; cursor: pointer; }
.difficulty-filter button:hover { background: var(--surface-soft); }
.difficulty-filter button.active { color: var(--primary); background: var(--primary-soft); font-weight: 600; }
.difficulty-filter button > span { margin-left: auto; color: var(--text-tertiary); font-size: 9px; }
.difficulty-filter i { width: 6px; height: 6px; border-radius: 50%; }.difficulty-filter i.easy { background: var(--success); }.difficulty-filter i.medium { background: var(--warning); }.difficulty-filter i.hard { background: var(--danger); }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.tag-list button { display: flex; align-items: center; gap: 3px; border: 1px solid #e4ebf3; border-radius: 5px; background: #fff; color: var(--text-secondary); padding: 5px 7px; font-size: 10px; cursor: pointer; }
.tag-list button:hover, .tag-list button.active { color: var(--primary); border-color: #a9c5f2; background: var(--primary-soft); }
.tag-toggle { display: inline-flex; align-items: center; gap: 3px; margin-top: 10px; border: 0; background: transparent; color: var(--primary); padding: 2px 0; font-size: 10px; cursor: pointer; }
.tag-toggle:hover { text-decoration: underline; }
.clear-filters { width: calc(100% - 32px); margin: 13px 16px; display: flex; align-items: center; justify-content: center; gap: 5px; border: 0; background: transparent; color: var(--primary); padding: 6px; font-size: 10px; cursor: pointer; }
.clear-filters:disabled { color: #b2bdca; cursor: default; }
.library-main { min-width: 0; }
.library-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.search-input { max-width: 440px; margin-right: auto; }
.library-toolbar .el-select { width: 155px; }
.random-button { color: #a46119; background: var(--accent-soft); border-color: #f4d5ae; }
.random-button:hover { color: #884e10; background: #ffead0; border-color: #eeb97b; }
.catalog-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.catalog-heading { min-height: 62px; padding: 14px 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); }
.catalog-heading > div { display: flex; align-items: baseline; gap: 10px; }
.catalog-heading h2 { margin: 0; font-size: 15px; }
.catalog-heading span { color: var(--text-tertiary); font-size: 10px; }
.problem-grid { display: grid; grid-template-columns: 50px minmax(230px, 1.35fr) 82px minmax(160px, .85fr) 110px 90px 20px; gap: 12px; align-items: center; }
.problem-grid-head { min-height: 41px; padding: 0 18px; background: #f7faff; color: var(--text-tertiary); font-size: 10px; border-bottom: 1px solid var(--border); }
.problem-row { width: 100%; min-height: 59px; padding: 9px 18px; border: 0; border-bottom: 1px solid #edf2f7; background: #fff; color: var(--text); text-align: left; cursor: pointer; transition: background .15s; }
.problem-row:last-child { border-bottom: 0; }
.problem-row:hover { background: #f6faff; }
.problem-row:hover .problem-name strong { color: var(--primary); }
.progress-status { display: flex; justify-content: center; color: #c2cdd9; font-size: 17px; }
.progress-status .solved { color: var(--success); }.progress-status .attempted { color: var(--warning); }
.progress-status > i { width: 13px; height: 13px; border: 1.5px solid #d0dbe7; border-radius: 50%; }
.problem-name > span { display: flex; align-items: center; gap: 7px; min-width: 0; }
.problem-name small { color: var(--text-tertiary); font-size: 10px; }
.problem-name strong { color: var(--text-strong); font-size: 12px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.problem-name em { flex: none; padding: 2px 5px; border-radius: 4px; background: var(--accent-soft); color: #b16c20; font-size: 8px; font-style: normal; }
.problem-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.problem-tags i { padding: 3px 6px; border-radius: 4px; background: #f0f4f8; color: var(--text-secondary); font-size: 9px; font-style: normal; white-space: nowrap; }
.acceptance { display: flex; align-items: center; gap: 7px; }
.acceptance strong { width: 39px; color: var(--text-secondary); font-size: 10px; font-weight: 500; }
.acceptance > i { width: 38px; height: 3px; border-radius: 3px; background: #e5edf5; overflow: hidden; }
.acceptance b { display: block; height: 100%; background: #78a5e9; }
.submission-count { color: var(--text-tertiary); font-size: 10px; text-align: right; }
.row-arrow { color: #a8b6c5; }
.catalog-footer { min-height: 56px; padding: 10px 18px; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid var(--border); }
.catalog-footer > span { color: var(--text-tertiary); font-size: 10px; }
.study-note { display: flex; align-items: center; gap: 6px; margin-top: 13px; color: var(--text-tertiary); font-size: 10px; }
@media (max-width: 1200px) {
  .problem-grid { grid-template-columns: 45px minmax(210px, 1.3fr) 75px minmax(130px, .8fr) 100px 20px; }
  .problem-grid > *:nth-child(6) { display: none; }
}
@media (max-width: 960px) {
  .library-layout { grid-template-columns: 200px minmax(0, 1fr); gap: 16px; }
  .learning-streak { min-width: 285px; }
  .problem-grid { grid-template-columns: 40px minmax(190px, 1fr) 70px 90px 18px; }
  .problem-grid > *:nth-child(4) { display: none; }
}
@media (max-width: 760px) {
  .library-hero { padding: 20px 0; }
  .hero-copy h1 { font-size: 25px; line-height: 1.45; }
  .learning-streak { display: none; }
  .library-layout { grid-template-columns: 1fr; }
  .mobile-filter-toggle { display: flex; align-items: center; gap: 7px; width: 100%; border: 1px solid var(--border); border-radius: 8px; background: #fff; color: var(--text-secondary); padding: 11px 13px; font-size: 12px; cursor: pointer; }
  .mobile-filter-toggle.active { color: var(--primary); border-color: #bdd3f3; }
  .mobile-filter-toggle > span { margin-left: auto; font-size: 10px; }
  .mobile-filter-toggle .toggle-arrow { margin-left: auto; }
  .mobile-filter-toggle > span + .toggle-arrow { margin-left: 0; }
  .filter-rail { display: none; grid-template-columns: 1fr 1fr; }
  .filter-rail.open { display: grid; }
  .practice-overview { grid-column: 1 / -1; }
  .rail-section { border-bottom: 0; }
  .tag-section { border-left: 1px solid var(--border); }
  .clear-filters { grid-column: 1 / -1; }
  .difficulty-filter { display: grid; grid-template-columns: 1fr 1fr; }
  .library-toolbar { flex-wrap: wrap; }
  .search-input { max-width: none; flex-basis: 100%; }
  .problem-grid { grid-template-columns: 34px minmax(170px, 1fr) 62px 16px; gap: 8px; }
  .problem-grid > *:nth-child(4), .problem-grid > *:nth-child(5), .problem-grid > *:nth-child(6) { display: none; }
  .problem-grid-head { padding: 0 12px; }
  .problem-row { padding: 11px 12px; }
  .problem-name em { display: none; }
  .catalog-tip { display: none; }
}
@media (max-width: 480px) {
  .filter-rail.open { display: block; }
  .tag-section { border-left: 0; border-top: 1px solid var(--border); }
  .practice-legend { flex-direction: row; gap: 20px; }
  .library-toolbar .el-select { flex: 1; }
  .random-button { flex: 1; }
  .catalog-heading { padding: 13px; }
  .catalog-heading > div { flex-direction: column; gap: 4px; }
  .study-note { align-items: flex-start; line-height: 1.7; }
}
</style>
