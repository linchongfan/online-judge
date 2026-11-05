<script setup lang="ts">
import type { Difficulty } from '../types'
import { difficultyTone } from '../utils/format'
defineProps<{ difficulty: Difficulty }>()
</script>

<template>
  <span class="difficulty" :class="difficultyTone[difficulty]">{{ difficulty }}</span>
</template>

<style scoped>
.difficulty { display: inline-flex; align-items: center; border-radius: 5px; padding: 3px 8px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.easy { color: #238562; background: #eaf7f1; }
.medium { color: #b87520; background: #fff5e6; }
.hard { color: #d05b66; background: #fff0f1; }
</style>
