<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppLogo from '../components/AppLogo.vue'
import { session } from '../stores/session'

const route = useRoute()
const router = useRouter()
const title = computed(() => String(route.meta.title ?? '管理后台'))
const navItems = [
  { path: '/admin/dashboard', label: '数据概览', icon: 'DataAnalysis' },
  { path: '/admin/users', label: '用户管理', icon: 'User' },
  { path: '/admin/problems', label: '题目管理', icon: 'Document' },
  { path: '/admin/contests', label: '竞赛管理', icon: 'Trophy' },
  { path: '/admin/judge', label: '判题任务', icon: 'Cpu' },
]
</script>

<template>
  <div class="admin-layout">
    <aside class="admin-sidebar">
      <div class="admin-brand"><AppLogo inverse /><span class="admin-edition">教学管理</span></div>
      <nav class="admin-nav" aria-label="管理后台导航">
        <span class="nav-section-label">管理导航</span>
        <router-link v-for="item in navItems" :key="item.path" :to="item.path" :class="{ active: route.path === item.path }" :title="item.label">
          <el-icon :size="19"><component :is="item.icon" /></el-icon><span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-bottom">
        <button type="button" @click="router.push('/problems')"><el-icon><Back /></el-icon><span>返回用户端</span></button>
        <div class="admin-user"><span class="avatar">管</span><div><strong>{{ session.profile?.nickname ?? '管理员' }}</strong><span>超级管理员</span></div></div>
      </div>
    </aside>
    <section class="admin-content">
      <header class="admin-topbar">
        <div><span class="admin-breadcrumb">新保研 / 教学管理</span><h1>{{ title }}</h1></div>
        <div class="topbar-right"><el-button circle aria-label="查看判题任务" @click="router.push('/admin/judge')"><el-icon><Bell /></el-icon></el-button></div>
      </header>
      <main class="admin-main"><slot /></main>
    </section>
  </div>
</template>

<style scoped>
.admin-layout { min-height: 100vh; background: var(--page); }
.admin-sidebar { position: fixed; inset: 0 auto 0 0; width: 240px; background: #102f5f; color: #fff; display: flex; flex-direction: column; z-index: 30; border-right: 1px solid #234672; }
.admin-brand { min-height: 92px; padding: 18px 20px; display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid rgba(197, 218, 246, .13); }
.admin-brand :deep(.brand) { gap: 9px; min-width: 0; }
.admin-brand :deep(.brand-mark) { width: 40px; height: 40px; border-radius: 8px; box-shadow: 0 0 0 1px rgba(255,255,255,.14); }
.admin-brand :deep(.brand-mark img) { width: 38px; height: 36px; }
.admin-brand :deep(.brand-type strong) { font-size: 21px; letter-spacing: .5px; }
.admin-brand :deep(.brand-type small) { color: rgba(224, 235, 251, .58); font-size: 8px; letter-spacing: .2px; white-space: nowrap; }
.admin-edition { flex: none; padding-left: 10px; border-left: 1px solid rgba(255,255,255,.18); color: #c2d5ef; font-size: 11px; letter-spacing: 1px; white-space: nowrap; }
.admin-nav { display: flex; flex-direction: column; gap: 4px; padding: 25px 14px; }
.nav-section-label { color: #91a9ca; font-size: 11px; font-weight: 500; letter-spacing: 1px; padding: 0 12px 10px; }
.admin-nav a { position: relative; display: flex; align-items: center; gap: 12px; min-height: 44px; color: #b8c9e1; text-decoration: none; padding: 11px 13px; border: 1px solid transparent; border-radius: 6px; font-size: 13px; font-weight: 500; transition: background-color .18s, color .18s, border-color .18s; }
.admin-nav a:hover { background: rgba(255,255,255,.06); color: #fff; }
.admin-nav a.active { color: #fff; background: #1b4b87; border-color: rgba(142, 183, 239, .18); box-shadow: inset 3px 0 #83b2ff; }
.admin-nav a.active :deep(.el-icon) { color: #a9cbff; }
.nav-badge { margin-left: auto; min-width: 20px; height: 20px; padding: 0 5px; border-radius: 5px; display: grid; place-items: center; font-size: 10px; font-weight: 700; font-style: normal; background: #38bdf8; color: #0c355b; }
.sidebar-bottom { margin-top: auto; padding: 14px 14px 20px; }
.sidebar-bottom > button { width: 100%; min-height: 40px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: #a9bdd8; display: flex; align-items: center; gap: 12px; padding: 10px 13px; cursor: pointer; font-size: 12px; text-align: left; transition: background-color .18s, color .18s; }
.sidebar-bottom > button:hover { background: rgba(255,255,255,.06); color: #fff; }
.admin-user { display: flex; gap: 10px; align-items: center; border-top: 1px solid rgba(197, 218, 246, .13); padding: 18px 8px 0; margin-top: 10px; }
.admin-user .avatar { width: 36px; height: 36px; border-radius: 8px; background: #dce9fb; color: #102f5f; font-size: 13px; }
.admin-user div { display: flex; flex-direction: column; gap: 4px; }
.admin-user strong { color: #f4f8ff; font-size: 12px; font-weight: 600; }
.admin-user span:not(.avatar) { font-size: 10px; color: #91a9ca; }
.admin-content { margin-left: 240px; min-height: 100vh; }
.admin-topbar { height: 92px; padding: 0 32px; background: #fff; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.admin-breadcrumb { color: var(--text-secondary); font-size: 11px; }
.admin-topbar h1 { margin: 7px 0 0; color: var(--text-strong); font-size: 21px; font-weight: 700; letter-spacing: -.4px; }
.topbar-right { display: flex; align-items: center; gap: 20px; }
.system-normal { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.system-normal i { width: 7px; height: 7px; background: var(--success); border-radius: 50%; box-shadow: 0 0 0 4px #e9f7f1; }
.topbar-right :deep(.el-button.is-circle) { width: 36px; height: 36px; color: var(--text-secondary); border-color: var(--border); background: var(--surface-soft); }
.topbar-right :deep(.el-button.is-circle:hover) { color: var(--primary); border-color: #b9d0f5; background: var(--primary-soft); }
.admin-main { padding: 28px 30px 44px; max-width: var(--content-max); margin: auto; }
@media (max-width: 1100px) {
  .admin-edition { display: none; }
}
@media (max-width: 900px) {
  .admin-sidebar { width: 76px; }
  .admin-brand { min-height: 84px; justify-content: center; padding: 18px; }
  .admin-brand :deep(.brand-type), .admin-edition, .nav-section-label, .admin-nav a span, .nav-badge, .sidebar-bottom button span, .admin-user div { display: none; }
  .admin-nav { padding: 22px 10px; gap: 7px; }
  .admin-nav a { justify-content: center; padding: 12px; }
  .admin-nav a.active { box-shadow: inset 3px 0 #83b2ff; }
  .admin-content { margin-left: 76px; }
  .sidebar-bottom > button { justify-content: center; padding-inline: 0; }
  .admin-user { justify-content: center; padding: 16px 0 0; }
  .admin-topbar { padding: 0 22px; }
  .admin-main { padding: 22px 18px 36px; }
  .system-normal { display: none; }
}
@media (max-width: 600px) {
  .admin-sidebar { width: 60px; }
  .admin-brand { padding: 16px 10px; }
  .admin-brand :deep(.brand-mark) { width: 38px; height: 38px; }
  .admin-nav { padding: 20px 6px; }
  .admin-content { margin-left: 60px; }
  .admin-topbar { height: 82px; padding: 0 16px; }
  .admin-topbar h1 { font-size: 18px; }
  .admin-breadcrumb { font-size: 10px; }
  .admin-main { padding: 18px 12px 32px; }
  .topbar-right { display: none; }
}
</style>
