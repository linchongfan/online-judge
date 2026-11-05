<script setup lang="ts">
withDefaults(defineProps<{ inverse?: boolean; compact?: boolean }>(), { inverse: false, compact: false })
</script>

<template>
  <router-link to="/problems" class="brand" :class="{ inverse, compact }" aria-label="新保研首页">
    <span class="brand-mark" aria-hidden="true"><img src="/images/xinbaoyan-mark.png" alt="" /></span>
    <span v-if="!compact" class="brand-type">
      <strong>新保研</strong>
      <small>算法学习与在线判题</small>
    </span>
  </router-link>
</template>

<style scoped>
.brand { display: inline-flex; align-items: center; gap: 10px; color: var(--text-strong); text-decoration: none; flex: none; }
.brand-mark { width: 46px; height: 46px; display: grid; place-items: center; border-radius: 10px; background: #fff; overflow: hidden; flex: none; }
.brand-mark img { width: 43px; height: 41px; object-fit: contain; display: block; }
.brand-type { display: flex; flex-direction: column; gap: 3px; line-height: 1; }
.brand-type strong { color: #124fb9; font-size: 23px; font-weight: 800; letter-spacing: 1px; }
.brand-type small { color: var(--text-tertiary); font-size: 9px; font-weight: 500; letter-spacing: .5px; }
.inverse { color: #fff; }
.inverse .brand-type strong { color: #fff; }
.inverse .brand-type small { color: rgba(255,255,255,.55); }
@media (max-width: 480px) {
  .brand-mark { width: 40px; height: 40px; }
  .brand-mark img { width: 37px; height: 35px; }
  .brand-type strong { font-size: 20px; }
  .brand-type small { display: none; }
}
</style>
