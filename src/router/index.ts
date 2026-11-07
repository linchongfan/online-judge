import { createRouter, createWebHistory } from 'vue-router'
import { initializeSession, session } from '../stores/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/problems' },
    { path: '/problems', component: () => import('../views/ProblemListView.vue'), meta: { title: '题库' } },
    { path: '/plans', component: () => import('../views/StudyPlanListView.vue'), meta: { title: '学习计划' } },
    { path: '/plans/:id', component: () => import('../views/StudyPlanDetailView.vue'), meta: { title: '学习计划详情' } },
    { path: '/problems/:id', component: () => import('../views/ProblemWorkspaceView.vue'), meta: { title: '在线做题', workspace: true } },
    { path: '/contests', component: () => import('../views/ContestListView.vue'), meta: { title: '竞赛' } },
    { path: '/contests/:id', component: () => import('../views/ContestDetailView.vue'), meta: { title: '竞赛详情' } },
    { path: '/submissions', component: () => import('../views/SubmissionListView.vue'), meta: { title: '提交记录', requiresAuth: true } },
    { path: '/profile', component: () => import('../views/ProfileView.vue'), meta: { title: '个人中心', requiresAuth: true } },
    { path: '/login', component: () => import('../views/AuthView.vue'), meta: { title: '登录', bare: true, mode: 'login' } },
    { path: '/register', component: () => import('../views/AuthView.vue'), meta: { title: '创建账号', bare: true, mode: 'register' } },
    { path: '/forgot', component: () => import('../views/AuthView.vue'), meta: { title: '找回密码', bare: true, mode: 'forgot' } },
    { path: '/admin', redirect: '/admin/dashboard' },
    { path: '/admin/dashboard', component: () => import('../views/admin/AdminDashboardView.vue'), meta: { title: '数据概览', admin: true } },
    { path: '/admin/users', component: () => import('../views/admin/AdminUsersView.vue'), meta: { title: '用户管理', admin: true } },
    { path: '/admin/problems', component: () => import('../views/admin/AdminProblemsView.vue'), meta: { title: '题目管理', admin: true } },
    { path: '/admin/plans', component: () => import('../views/admin/AdminStudyPlansView.vue'), meta: { title: '学习计划', admin: true } },
    { path: '/admin/contests', component: () => import('../views/admin/AdminContestsView.vue'), meta: { title: '竞赛管理', admin: true } },
    { path: '/admin/judge', component: () => import('../views/admin/AdminJudgeView.vue'), meta: { title: '判题任务', admin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/problems' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

const CHUNK_RELOAD_KEY = 'xinbaoyan-chunk-reloaded'
router.onError((error) => {
  const message = error instanceof Error ? error.message : String(error)
  if (!/dynamically imported module|module script failed|Importing a module script/i.test(message)) return
  try {
    if (sessionStorage.getItem(CHUNK_RELOAD_KEY)) return
    sessionStorage.setItem(CHUNK_RELOAD_KEY, '1')
  } catch { /* sessionStorage unavailable: still reload once per failed navigation */ }
  window.location.reload()
})

router.afterEach(() => {
  try { sessionStorage.removeItem(CHUNK_RELOAD_KEY) } catch { /* ignore */ }
})

router.beforeEach(async (to) => {
  document.title = `${String(to.meta.title ?? '页面')} · 新保研`
  await initializeSession()

  if ((to.meta.requiresAuth || to.meta.admin) && !session.loggedIn) {
    return {
      path: '/login',
      query: {
        redirect: to.fullPath,
        ...(to.meta.admin ? { role: 'admin' } : {}),
      },
    }
  }
  if (to.meta.admin && session.role !== 'admin') return { path: '/problems' }
})

export default router
