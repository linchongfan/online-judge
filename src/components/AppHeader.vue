<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppLogo from './AppLogo.vue'
import { listContests } from '../api/contests'
import { logout, session } from '../stores/session'

const route = useRoute()
const router = useRouter()
const activeContestIds = ref<number[]>([])
const readContestIds = ref<number[]>(loadReadContests())
const showContestDot = computed(() => activeContestIds.value.some(id => !readContestIds.value.includes(id)))
let refreshTimer: ReturnType<typeof setInterval> | undefined
let refreshingContests = false

function loadReadContests(): number[] {
  try {
    const value = JSON.parse(localStorage.getItem('xinbaoyan-read-contests') ?? '[]')
    return Array.isArray(value) ? value.filter(item => typeof item === 'number') : []
  } catch { return [] }
}
function markContestsRead() {
  if (!activeContestIds.value.length) return
  readContestIds.value = [...new Set([...readContestIds.value, ...activeContestIds.value])]
  try { localStorage.setItem('xinbaoyan-read-contests', JSON.stringify(readContestIds.value)) } catch { /* 内存中的已读状态仍然生效 */ }
}
async function refreshContestNotifications() {
  if (refreshingContests) return
  refreshingContests = true
  try {
    const [ongoing, upcoming] = await Promise.all([
      listContests({ status: 'ongoing', page: 1, pageSize: 100 }),
      listContests({ status: 'upcoming', page: 1, pageSize: 100 }),
    ])
    activeContestIds.value = [...ongoing.items, ...upcoming.items]
      .filter(contest => contest.publicationStatus === 'published')
      .map(contest => contest.id)
    if (route.path.startsWith('/contests')) markContestsRead()
  } catch { activeContestIds.value = [] } finally { refreshingContests = false }
}

onMounted(() => {
  void refreshContestNotifications()
  refreshTimer = setInterval(() => void refreshContestNotifications(), 60_000)
})
watch(() => route.path, path => { if (path.startsWith('/contests')) markContestsRead() })
onBeforeUnmount(() => { if (refreshTimer) clearInterval(refreshTimer) })
const active = computed(() => {
  if (route.path.startsWith('/problems')) return '/problems'
  if (route.path.startsWith('/curriculum')) return '/curriculum'
  if (route.path.startsWith('/contests')) return '/contests'
  if (route.path.startsWith('/submissions')) return '/submissions'
  return ''
})

async function signOut() {
  try { await logout() } catch { /* 本地会话始终清理 */ }
  await router.push('/problems')
  ElMessage.success('已退出登录')
}
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <AppLogo />
      <nav class="main-nav" aria-label="主导航">
        <router-link to="/problems" :class="{ active: active === '/problems' }">题库</router-link>
        <router-link to="/curriculum" :class="{ active: active === '/curriculum' }">C 语言题单</router-link>
        <router-link to="/contests" :class="{ active: active === '/contests' }" @click="markContestsRead">竞赛<span v-if="showContestDot" class="live-dot" /></router-link>
        <router-link v-if="session.loggedIn" to="/submissions" :class="{ active: active === '/submissions' }">提交记录</router-link>
      </nav>
      <div class="header-actions">
        <button class="icon-button help-button" title="使用指南" @click="ElMessage.info('选择题后开始练习；公开样例与正式提交均由真实判题服务处理')">
          <el-icon :size="19"><QuestionFilled /></el-icon>
        </button>
        <template v-if="session.loggedIn">
          <el-dropdown trigger="click" popper-class="user-dropdown">
            <button class="profile-trigger">
              <span class="avatar avatar-small">{{ session.profile?.nickname.slice(0, 1) }}</span>
              <span class="profile-name">{{ session.profile?.nickname }}</span>
              <el-icon class="muted"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <div class="dropdown-user">
                  <strong>{{ session.profile?.nickname }}</strong>
                  <span>@{{ session.profile?.username }}</span>
                </div>
                <el-dropdown-item @click="router.push('/profile')"><el-icon><User /></el-icon>个人中心</el-dropdown-item>
                <el-dropdown-item v-if="session.role === 'admin'" @click="router.push('/admin/dashboard')"><el-icon><Setting /></el-icon>管理后台</el-dropdown-item>
                <el-dropdown-item divided @click="signOut"><el-icon><SwitchButton /></el-icon>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <template v-else>
          <el-button text @click="router.push('/login')">登录</el-button>
          <el-button type="primary" round @click="router.push('/register')">注册账号</el-button>
        </template>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header { height: 72px; background: rgba(255,255,255,.96); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; backdrop-filter: blur(16px); box-shadow: 0 2px 12px rgba(25, 69, 130, .025); }
.header-inner { height: 100%; max-width: var(--content-max); padding: 0 var(--content-gutter); margin: auto; display: flex; align-items: center; gap: 44px; }
.main-nav { align-self: stretch; display: flex; align-items: stretch; gap: 34px; }
.main-nav a { position: relative; display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 14px; font-weight: 500; text-decoration: none; transition: color .2s; white-space: nowrap; }
.main-nav a:hover, .main-nav a.active { color: var(--primary); }
.main-nav a.active::after { content: ''; position: absolute; left: 50%; bottom: 0; width: 20px; height: 3px; border-radius: 3px 3px 0 0; background: var(--accent); transform: translateX(-50%); }
.live-dot { width: 5px; height: 5px; border-radius: 50%; background: #ef6d78; box-shadow: 0 0 0 3px #fff0f1; }
.header-actions { margin-left: auto; display: flex; align-items: center; gap: 12px; }
.icon-button { border: 0; background: transparent; width: 34px; height: 34px; display: grid; place-items: center; color: var(--text-tertiary); cursor: pointer; border-radius: 8px; }
.icon-button:hover { background: var(--surface-soft); color: var(--primary); }
.profile-trigger { display: flex; align-items: center; gap: 9px; border: 0; background: none; cursor: pointer; color: var(--text); padding: 4px 0 4px 5px; }
.profile-name { font-size: 13px; font-weight: 500; }
.dropdown-user { display: flex; flex-direction: column; padding: 10px 16px 8px; min-width: 155px; }
.dropdown-user strong { font-size: 14px; }
.dropdown-user span { font-size: 12px; color: var(--text-tertiary); margin-top: 3px; }
@media (max-width: 760px) {
  .app-header { height: auto; position: relative; }
  .header-inner { padding: 12px 16px 0; flex-wrap: wrap; gap: 10px; }
  .main-nav { order: 3; width: 100%; height: 42px; gap: 28px; }
  .help-button, .profile-name { display: none; }
  .header-actions { gap: 5px; }
}
</style>
