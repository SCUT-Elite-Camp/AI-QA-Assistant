<route lang="yaml">
meta:
  layout: admin
</route>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { $fetch } from 'ofetch'
import { useAdmin, useAdminAccess } from '../../composables/useAdmin'
import type { AdminUser, Department } from '../../composables/useAdmin'

const { listUsers, listDepartments } = useAdmin()
const { checking, allowed, check } = useAdminAccess()

const users = ref<AdminUser[]>([])
const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')

const stats = reactive({
  userCount: 0,
  adminCount: 0,
  disabledCount: 0,
  departmentCount: 0,
  fileCount: 0,
})

async function load() {
  if (!allowed.value) return
  loading.value = true
  error.value = ''
  try {
    const [u, d, f] = await Promise.all([
      listUsers(),
      listDepartments(),
      $fetch<any[]>('/api/files').catch(() => [])
    ])
    users.value = u
    departments.value = d
    stats.userCount = u.length
    stats.adminCount = u.filter(x => x.role === 'admin').length
    stats.disabledCount = u.filter(x => x.disabled).length
    stats.departmentCount = d.length
    stats.fileCount = f.length
  }
  catch (e: any) {
    error.value = e?.data?.message || e?.message || 'Failed to load overview'
  }
  finally {
    loading.value = false
  }
}

onMounted(async () => {
  await check()
  if (allowed.value) await load()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header Title -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-zinc-200 dark:border-zinc-800">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">系统总览</h1>
        <p class="text-sm text-zinc-500 dark:text-zinc-400 mt-1">查看系统用户、部门与平台运行状态</p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          @click="load"
        >
          刷新数据
        </UButton>
      </div>
    </div>

    <!-- Loading State -->
    <template v-if="checking || loading && !users.length">
      <div class="flex flex-col items-center justify-center py-20 gap-3">
        <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-primary-500" />
        <p class="text-sm text-zinc-400">正在载入系统数据...</p>
      </div>
    </template>

    <!-- Content -->
    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

      <!-- Metrics Cards -->
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <div class="flex items-center gap-3">
            <div class="rounded-xl bg-blue-500/10 p-3 text-blue-500">
              <UIcon name="i-lucide-users" class="size-6" />
            </div>
            <div>
              <p class="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">总用户数</p>
              <p class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5">{{ stats.userCount }}</p>
            </div>
          </div>
        </UCard>

        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <div class="flex items-center gap-3">
            <div class="rounded-xl bg-emerald-500/10 p-3 text-emerald-500">
              <UIcon name="i-lucide-shield-check" class="size-6" />
            </div>
            <div>
              <p class="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">管理员</p>
              <p class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5">{{ stats.adminCount }}</p>
            </div>
          </div>
        </UCard>

        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <div class="flex items-center gap-3">
            <div class="rounded-xl bg-purple-500/10 p-3 text-purple-500">
              <UIcon name="i-lucide-building-2" class="size-6" />
            </div>
            <div>
              <p class="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">组织部门</p>
              <p class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5">{{ stats.departmentCount }}</p>
            </div>
          </div>
        </UCard>

        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <div class="flex items-center gap-3">
            <div class="rounded-xl bg-indigo-500/10 p-3 text-indigo-500">
              <UIcon name="i-lucide-library" class="size-6" />
            </div>
            <div>
              <p class="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">知识库文档</p>
              <p class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5">{{ stats.fileCount }}</p>
            </div>
          </div>
        </UCard>

        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <div class="flex items-center gap-3">
            <div class="rounded-xl bg-amber-500/10 p-3 text-amber-500">
              <UIcon name="i-lucide-user-x" class="size-6" />
            </div>
            <div>
              <p class="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">已禁用用户</p>
              <p class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5">{{ stats.disabledCount }}</p>
            </div>
          </div>
        </UCard>
      </div>

      <!-- Quick Actions & Recent Users -->
      <div class="grid md:grid-cols-2 gap-6">
        <UCard class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs">
          <template #header>
            <div class="flex items-center justify-between">
              <h3 class="font-semibold text-zinc-900 dark:text-white">快捷操作</h3>
              <UIcon name="i-lucide-sparkles" class="size-4 text-zinc-400" />
            </div>
          </template>
          <div class="flex flex-col gap-3">
            <UButton
              label="用户与角色管理"
              icon="i-lucide-user-cog"
              color="neutral"
              variant="outline"
              class="justify-start py-2.5 text-sm font-medium"
              to="/admin/users"
            />
            <UButton
              label="组织与部门架构管理"
              icon="i-lucide-building-2"
              color="neutral"
              variant="outline"
              class="justify-start py-2.5 text-sm font-medium"
              to="/admin/departments"
            />
            <UButton
              label="文档与知识库权限"
              icon="i-lucide-folder-lock"
              color="neutral"
              variant="outline"
              class="justify-start py-2.5 text-sm font-medium"
              to="/files"
            />
          </div>
        </UCard>

        <UCard v-if="users.length" :ui="{ body: 'p-0' }" class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs overflow-hidden">
          <template #header>
            <div class="flex items-center justify-between">
              <h3 class="font-semibold text-zinc-900 dark:text-white">最近用户</h3>
              <UButton label="查看全部" size="xs" color="neutral" variant="ghost" to="/admin/users" />
            </div>
          </template>
          <div class="divide-y divide-zinc-200 dark:divide-zinc-800">
            <div v-for="u in users.slice(0, 5)" :key="u.id" class="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors">
              <UAvatar :src="u.avatar ?? undefined" :alt="u.name" size="sm" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{{ u.name || u.username }}</p>
                <p class="truncate text-xs text-zinc-500">{{ u.email }}</p>
              </div>
              <UBadge v-if="u.role === 'admin'" color="primary" variant="soft" size="sm">管理员</UBadge>
              <UBadge v-else-if="u.disabled" color="warning" variant="soft" size="sm">已禁用</UBadge>
              <UBadge v-else color="neutral" variant="subtle" size="sm">普通用户</UBadge>
            </div>
          </div>
        </UCard>
      </div>
    </template>
  </div>
</template>
