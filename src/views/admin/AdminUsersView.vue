<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminErrorMessage,
  isAdminRequestCancelled,
  listAdminUsers,
  sendAdminPasswordReset,
  updateAdminUser,
} from '../../api/admin'
import { session } from '../../stores/session'
import type { AdminUser, UserRole } from '../../types'
import { formatDateTime, formatNumber } from '../../utils/format'

const users = ref<AdminUser[]>([])
const keyword = ref('')
const roleFilter = ref<'all' | UserRole>('all')
const statusFilter = ref<'all' | AdminUser['status']>('all')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const pendingIds = ref<Set<number>>(new Set())
let controller: AbortController | null = null
let searchTimer: ReturnType<typeof setTimeout> | null = null

const selfId = computed(() => session.profile?.id ?? null)
const activeCount = computed(() => users.value.filter(user => user.status === 'active').length)
const adminCount = computed(() => users.value.filter(user => user.role === 'admin').length)
const hasFilters = computed(() => Boolean(keyword.value || roleFilter.value !== 'all' || statusFilter.value !== 'all'))
const pageSolved = computed(() => users.value.reduce((sum, user) => sum + user.solved, 0))

function setPending(userId: number, pending: boolean) {
  const next = new Set(pendingIds.value)
  if (pending) next.add(userId)
  else next.delete(userId)
  pendingIds.value = next
}

async function loadUsers() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listAdminUsers({
      page: page.value,
      pageSize: pageSize.value,
      keyword: keyword.value.trim() || undefined,
      role: roleFilter.value === 'all' ? undefined : roleFilter.value,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    }, { signal: current.signal })
    if (current.signal.aborted) return
    users.value = result.items
    total.value = result.total
    pages.value = result.pages
    if (!result.items.length && result.total > 0 && result.pages > 0 && page.value > result.pages) {
      page.value = result.pages
      await loadUsers()
    }
  } catch (error) {
    if (!isAdminRequestCancelled(error)) {
      users.value = []
      errorMessage.value = adminErrorMessage(error, '用户列表加载失败')
    }
  } finally {
    if (controller === current) {
      loading.value = false
      controller = null
    }
  }
}

function scheduleFilterLoad() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    void loadUsers()
  }, 350)
}

function resetFilters() {
  const hadFilters = hasFilters.value
  keyword.value = ''
  roleFilter.value = 'all'
  statusFilter.value = 'all'
  if (!hadFilters) {
    page.value = 1
    void loadUsers()
  }
}

function changePage(value: number) {
  page.value = value
  void loadUsers()
}

function changePageSize(value: number) {
  pageSize.value = value
  page.value = 1
  void loadUsers()
}

async function toggleUserStatus(user: AdminUser) {
  if (user.id === selfId.value || pendingIds.value.has(user.id)) return
  const nextStatus = user.status === 'active' ? 'disabled' : 'active'
  if (nextStatus === 'disabled') {
    try {
      await ElMessageBox.confirm(`禁用后，${user.nickname} 的现有会话将被撤销，无法继续登录和提交代码。`, `禁用用户 ${user.username}`, {
        confirmButtonText: '确认禁用', cancelButtonText: '取消', type: 'warning',
      })
    } catch {
      return
    }
  }
  setPending(user.id, true)
  try {
    const updated = await updateAdminUser(user.id, { status: nextStatus })
    Object.assign(user, updated)
    ElMessage.success(nextStatus === 'disabled' ? `已禁用 ${user.nickname}` : `已恢复 ${user.nickname} 的账号`)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '账号状态更新失败'))
  } finally {
    setPending(user.id, false)
  }
}

async function changeRole(user: AdminUser, role: UserRole) {
  if (user.id === selfId.value || role === user.role || pendingIds.value.has(user.id)) return
  setPending(user.id, true)
  try {
    const updated = await updateAdminUser(user.id, { role })
    Object.assign(user, updated)
    ElMessage.success(`已将 ${user.nickname} 设置为${role === 'admin' ? '管理员' : '普通用户'}，其会话需要重新登录`)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '用户角色更新失败'))
  } finally {
    setPending(user.id, false)
  }
}

async function resetPassword(user: AdminUser) {
  if (pendingIds.value.has(user.id)) return
  try {
    await ElMessageBox.confirm(`将向 ${user.nickname}（${user.email}）发送密码重置验证码邮件。`, '确认发送重置邮件', {
      confirmButtonText: '发送重置邮件', cancelButtonText: '取消', type: 'warning',
      confirmButtonClass: 'el-button--primary',
    })
  } catch {
    return
  }
  setPending(user.id, true)
  try {
    const response = await sendAdminPasswordReset(user.id)
    ElMessage.success(response.message || `密码重置邮件已发送至 ${user.email}`)
  } catch (error) {
    ElMessage.error(adminErrorMessage(error, '重置邮件发送失败'))
  } finally {
    setPending(user.id, false)
  }
}

watch([keyword, roleFilter, statusFilter], scheduleFilterLoad)
onMounted(() => void loadUsers())
onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
  controller?.abort()
})
</script>

<template>
  <div class="users-page">
    <div class="page-heading">
      <div><h1>用户管理</h1><p>管理平台账号、访问权限与登录状态，角色和状态变更由服务端实时保存。</p></div>
      <span class="prototype-note">共 {{ formatNumber(total) }} 个账号</span>
    </div>

    <section class="user-summary surface-card" aria-label="用户统计">
      <div><span class="summary-icon primary"><el-icon><User /></el-icon></span><p>全部用户<strong>{{ formatNumber(total) }}</strong></p></div>
      <i />
      <div><span class="summary-icon green"><el-icon><CircleCheck /></el-icon></span><p>本页正常<strong>{{ activeCount }}</strong></p></div>
      <i />
      <div><span class="summary-icon blue"><el-icon><Avatar /></el-icon></span><p>本页管理员<strong>{{ adminCount }}</strong></p></div>
      <span class="summary-note"><el-icon><Lock /></el-icon>权限变更后撤销目标用户会话</span>
    </section>

    <el-alert v-if="errorMessage" class="request-alert" :title="errorMessage" type="error" show-icon :closable="false" role="alert">
      <el-button size="small" @click="loadUsers">重新加载</el-button>
    </el-alert>

    <section class="surface-card table-card">
      <div class="filter-bar">
        <el-input v-model="keyword" class="search-input" clearable placeholder="搜索用户名、昵称或邮箱">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="roleFilter" class="filter-select" aria-label="筛选角色">
          <el-option label="全部角色" value="all" /><el-option label="普通用户" value="user" /><el-option label="管理员" value="admin" />
        </el-select>
        <el-select v-model="statusFilter" class="filter-select" aria-label="筛选账号状态">
          <el-option label="全部状态" value="all" /><el-option label="正常" value="active" /><el-option label="已禁用" value="disabled" />
        </el-select>
        <el-button v-if="hasFilters" text @click="resetFilters"><el-icon><RefreshLeft /></el-icon>重置</el-button>
        <span class="filter-result">{{ formatNumber(total) }} 条服务端结果</span>
      </div>

      <div class="table-scroll">
        <el-table v-loading="loading" :data="users" row-key="id" class="admin-table">
          <el-table-column label="用户" min-width="230">
            <template #default="{ row }">
              <div class="user-cell">
                <span class="avatar" :class="`tone-${row.id % 4}`">{{ row.nickname.slice(0, 1) }}</span>
                <div><strong>{{ row.nickname }}<span v-if="row.id === selfId" class="self-badge">当前账号</span></strong><span class="mono">@{{ row.username }}</span></div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="邮箱" prop="email" min-width="220" show-overflow-tooltip />
          <el-table-column label="角色" width="140">
            <template #default="{ row }">
              <el-select :model-value="row.role" size="small" class="role-select" :disabled="row.id === selfId || pendingIds.has(row.id)" :loading="pendingIds.has(row.id)" @change="changeRole(row, $event)">
                <el-option label="普通用户" value="user" /><el-option label="管理员" value="admin" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="已解决" width="100" align="right"><template #default="{ row }"><strong class="solved-count">{{ row.solved }}</strong><span class="muted"> 题</span></template></el-table-column>
          <el-table-column label="最近活跃" width="180"><template #default="{ row }">{{ formatDateTime(row.lastActive) }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><span class="status-pill" :class="row.status === 'active' ? 'success' : 'neutral'"><i />{{ row.status === 'active' ? '正常' : '已禁用' }}</span></template></el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button text type="primary" :loading="pendingIds.has(row.id)" @click="resetPassword(row)">重置密码</el-button>
                <el-tooltip :disabled="row.id !== selfId" content="不能修改自己的账号状态" placement="top">
                  <span><el-button text :type="row.status === 'active' ? 'danger' : 'success'" :disabled="row.id === selfId || pendingIds.has(row.id)" @click="toggleUserStatus(row)">{{ row.status === 'active' ? '禁用' : '启用' }}</el-button></span>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty-state"><div class="empty-icon"><el-icon :size="26"><Search /></el-icon></div><h3>{{ hasFilters ? '没有找到匹配的用户' : '暂无用户' }}</h3><p>{{ hasFilters ? '请尝试更换关键词或清除筛选条件。' : '用户数据将在创建账号后显示。' }}</p><el-button v-if="hasFilters" type="primary" plain @click="resetFilters">清除筛选</el-button></div>
          </template>
        </el-table>
      </div>
      <div class="table-footer"><span>当前页 {{ users.length }} / 共 {{ formatNumber(total) }} 位用户</span><span>本页累计解题 {{ formatNumber(pageSolved) }} 题</span></div>
      <div class="pagination-bar">
        <el-pagination background :current-page="page" :page-size="pageSize" :page-sizes="[10, 20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next, jumper" :disabled="loading" @current-change="changePage" @size-change="changePageSize" />
        <span v-if="pages">共 {{ pages }} 页</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.users-page :deep(.page-heading) { margin-bottom: 22px; }
.prototype-note::before { background: #9bb5d4; }
.request-alert { margin-bottom: 16px; }
.user-summary { display: flex; align-items: center; gap: 30px; padding: 19px 24px; margin-bottom: 16px; border-radius: 8px; box-shadow: none; }
.user-summary > div { display: flex; align-items: center; gap: 12px; min-width: 130px; }
.user-summary > i { width: 1px; height: 36px; background: var(--border); }
.summary-icon { width: 38px; height: 38px; border-radius: 7px; display: grid; place-items: center; font-size: 18px; }
.summary-icon.primary, .summary-icon.blue { background: var(--primary-soft); color: var(--primary); }
.summary-icon.green { background: #eaf7f1; color: var(--success); }
.user-summary p { margin: 0; display: flex; flex-direction: column; gap: 4px; color: var(--text-secondary); font-size: 11px; }
.user-summary strong { color: var(--text-strong); font-size: 22px; line-height: 1.2; }
.summary-note { margin-left: auto; display: flex; align-items: center; gap: 7px; color: var(--text-secondary); font-size: 11px; }
.table-card { overflow: hidden; border-radius: 8px; box-shadow: none; }
.filter-bar { display: flex; align-items: center; gap: 10px; padding: 16px 20px; border-bottom: 1px solid var(--border); background: #f8fbff; }
.filter-bar :deep(.el-input__wrapper), .filter-bar :deep(.el-select__wrapper), .role-select :deep(.el-select__wrapper) { border-radius: 6px; background: #fff; }
.search-input { width: 310px; }
.filter-select { width: 132px; }
.filter-bar :deep(.el-button) { border-radius: 6px; }
.filter-result { margin-left: auto; color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.table-scroll { width: 100%; overflow-x: auto; }
.admin-table { min-width: 1110px; width: 100%; --el-table-header-bg-color: #f4f8fd; --el-table-row-hover-bg-color: #f5f8ff; --el-table-header-text-color: var(--text-secondary); }
.admin-table :deep(th.el-table__cell) { height: 44px; color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.admin-table :deep(td.el-table__cell) { padding: 13px 0; }
.admin-table :deep(.cell) { color: var(--text); }
.user-cell { display: flex; align-items: center; gap: 12px; }
.user-cell > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.user-cell strong { color: var(--text-strong); font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 7px; }
.user-cell .mono { color: var(--text-secondary); font-size: 10px; }
.avatar { border-radius: 8px; background: #e5efff; }
.avatar.tone-0 { color: #237786; background: #e6f3f5; }
.avatar.tone-1 { color: var(--primary); background: #e5efff; }
.avatar.tone-2 { color: #35668f; background: #eaf1f8; }
.avatar.tone-3 { color: #176f69; background: #e6f3f0; }
.self-badge { padding: 2px 6px; border: 1px solid #cfdef4; border-radius: 4px; background: var(--primary-soft); color: var(--primary); font-size: 9px; font-weight: 500; }
.role-select { width: 112px; }
.solved-count { color: var(--text-strong); font-weight: 600; }
.status-pill { border-radius: 5px; padding: 4px 8px; }
.status-pill.success { color: var(--success); background: #eaf7f1; }
.status-pill.neutral { color: #687b91; background: #eef2f6; }
.row-actions { display: flex; align-items: center; gap: 2px; }
.row-actions :deep(.el-button) { border-radius: 5px; }
.table-footer { display: flex; justify-content: space-between; padding: 13px 20px; border-top: 1px solid var(--border); background: #fbfdff; color: var(--text-secondary); font-size: 11px; }
.pagination-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; border-top: 1px solid var(--border); overflow-x: auto; }
.pagination-bar > span { color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.empty-state .empty-icon { border-radius: 10px; color: #8da5c1; background: var(--primary-soft); }
@media (max-width: 1100px) {
  .summary-note { display: none; }
  .filter-bar { flex-wrap: wrap; }
  .filter-result { margin-left: 0; }
}
@media (max-width: 760px) {
  .user-summary { gap: 18px; padding: 16px; justify-content: space-between; }
  .user-summary > div { min-width: 0; gap: 8px; }
  .summary-icon { width: 32px; height: 32px; }
  .search-input { width: 100%; }
  .filter-select { flex: 1; min-width: 120px; }
}
@media (max-width: 600px) {
  .user-summary { gap: 10px; }
  .summary-icon, .user-summary > i { display: none; }
  .filter-bar { padding: 14px; gap: 9px; }
  .table-footer { gap: 8px; flex-direction: column; }
  .pagination-bar { padding: 12px 14px; }
}
</style>
