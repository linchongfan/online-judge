<script setup lang="ts">
import type { JudgeStatus } from '../types'
import { judgeStatusMap } from '../utils/format'

const props = defineProps<{ status: JudgeStatus; compact?: boolean }>()
</script>

<template>
  <span class="judge-status" :class="[`is-${judgeStatusMap[props.status].tone}`, { compact }]">
    <span class="status-dot" />{{ judgeStatusMap[props.status].label }}
  </span>
</template>

<style scoped>
.judge-status { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.is-success { color: var(--success); }
.is-danger { color: var(--danger); }
.is-warning { color: var(--warning); }
.is-pending, .is-judging { color: var(--primary); }
.is-judging .status-dot, .is-pending .status-dot { animation: status-pulse 1.2s infinite; }
.is-neutral { color: var(--text-tertiary); }
.compact { font-size: 12px; }
@keyframes status-pulse { 50% { opacity: .25; } }
</style>
