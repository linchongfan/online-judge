<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import UserLayout from './layouts/UserLayout.vue'
import AdminLayout from './layouts/AdminLayout.vue'

const route = useRoute()
const layout = computed(() => route.meta.admin ? 'admin' : route.meta.bare ? 'bare' : 'user')
</script>

<template>
  <router-view v-if="layout === 'bare'" />
  <AdminLayout v-else-if="layout === 'admin'">
    <router-view />
  </AdminLayout>
  <UserLayout v-else>
    <router-view />
  </UserLayout>
</template>
