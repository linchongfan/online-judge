<script setup lang="ts">
import { useRoute } from 'vue-router'
import AppHeader from '../components/AppHeader.vue'
const route = useRoute()
</script>

<template>
  <div class="user-layout" :class="{ 'is-workspace': route.meta.workspace }">
    <AppHeader />
    <main :class="route.meta.workspace ? 'workspace-container' : 'page-container'">
      <slot />
    </main>
    <footer v-if="!route.meta.workspace" class="app-footer">
      <span><strong>新保研</strong> · 保研更有方向，上岸更有把握</span>
      <span>算法学习与真实在线判题服务</span>
    </footer>
  </div>
</template>

<style scoped>
.user-layout { min-height: 100vh; display: flex; flex-direction: column; }
.page-container { width: 100%; max-width: var(--content-max); margin: 0 auto; padding: 32px var(--content-gutter) 52px; flex: 1; }
.workspace-container { flex: 1; min-height: 0; }
.is-workspace { height: 100vh; height: 100dvh; overflow: hidden; }
.app-footer { border-top: 1px solid var(--border); padding: 24px max(var(--content-gutter), calc((100vw - var(--content-max)) / 2 + var(--content-gutter))); display: flex; justify-content: space-between; color: var(--text-tertiary); font-size: 12px; background: #fff; }
.app-footer strong { color: var(--text-secondary); }
@media (max-width: 760px) {
  .page-container { padding: 20px 16px 40px; }
  .app-footer { flex-direction: column; gap: 8px; padding: 20px 16px; }
  .is-workspace { height: auto; overflow: visible; }
}
</style>
