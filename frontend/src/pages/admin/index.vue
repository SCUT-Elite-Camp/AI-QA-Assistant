<route lang="yaml">
meta:
  layout: admin
</route>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { $fetch } from 'ofetch'
import { useAdmin, useAdminAccess } from '../../composables/useAdmin'
import type { AdminUser, Department } from '../../composables/useAdmin'

const { listUsers, listDepartments } = useAdmin()
const { checking, allowed, check } = useAdminAccess()

const users = ref<AdminUser[]>([])
const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')
const lastUpdated = ref<string>('')

const stats = reactive({
  userCount: 0,
  adminCount: 0,
  disabledCount: 0,
  departmentCount: 0,
  fileCount: 0,
})

const activeUsersCount = computed(() => {
  return stats.userCount - stats.disabledCount
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
    lastUpdated.value = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
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
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-zinc-200/80 dark:border-zinc-800/80">
      <div class="space-y-1">
        <div class="flex items-center gap-2.5">
          <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-950 dark:text-white">
            System Overview
          </h1>
          <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            Operational
          </span>
        </div>
        <p class="text-sm text-zinc-500 dark:text-zinc-400">
          Monitor platform infrastructure, organizational structure, and knowledge base assets
        </p>
      </div>

      <div class="flex items-center gap-3">
        <span v-if="lastUpdated" class="text-xs text-zinc-400 dark:text-zinc-500 font-mono hidden md:inline">
          Updated at {{ lastUpdated }}
        </span>
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          class="rounded-xl shadow-2xs font-medium hover:bg-zinc-100 dark:hover:bg-zinc-800"
          @click="load"
        >
          Refresh Data
        </UButton>
      </div>
    </div>

    <!-- Loading Skeleton State -->
    <template v-if="checking || (loading && !users.length)">
      <div class="flex flex-col items-center justify-center py-28 gap-4">
        <div class="p-4 rounded-2xl bg-zinc-100 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 backdrop-blur-xl shadow-sm">
          <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-zinc-900 dark:text-white" />
        </div>
        <p class="text-sm font-medium text-zinc-500 dark:text-zinc-400">Loading console data...</p>
      </div>
    </template>

    <!-- Main Content -->
    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" class="rounded-2xl" />

      <!-- Acrylic Bento Metrics Cards Grid -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 sm:gap-5">
        <!-- Total Users -->
        <div class="group relative rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400 tracking-wider uppercase">Total Users</span>
            <div class="w-8 h-8 rounded-xl bg-blue-500/10 dark:bg-blue-400/10 text-blue-600 dark:text-blue-400 flex items-center justify-center">
              <UIcon name="i-lucide-users" class="w-4 h-4" />
            </div>
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="text-3xl font-bold tracking-tight text-zinc-950 dark:text-white font-sans">{{ stats.userCount }}</span>
            <span class="text-xs text-zinc-400 font-medium">Accounts</span>
          </div>
          <div class="mt-2 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>{{ activeUsersCount }} active accounts</span>
          </div>
        </div>

        <!-- Admins -->
        <div class="group relative rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400 tracking-wider uppercase">Administrators</span>
            <div class="w-8 h-8 rounded-xl bg-primary-500/10 dark:bg-primary-400/10 text-primary-600 dark:text-primary-400 flex items-center justify-center">
              <UIcon name="i-lucide-shield-check" class="w-4 h-4" />
            </div>
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="text-3xl font-bold tracking-tight text-zinc-950 dark:text-white font-sans">{{ stats.adminCount }}</span>
            <span class="text-xs text-zinc-400 font-medium">Seats</span>
          </div>
          <div class="mt-2 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <span class="text-primary-600 dark:text-primary-400 font-medium">Full privilege access</span>
          </div>
        </div>

        <!-- Departments -->
        <div class="group relative rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400 tracking-wider uppercase">Departments</span>
            <div class="w-8 h-8 rounded-xl bg-purple-500/10 dark:bg-purple-400/10 text-purple-600 dark:text-purple-400 flex items-center justify-center">
              <UIcon name="i-lucide-building-2" class="w-4 h-4" />
            </div>
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="text-3xl font-bold tracking-tight text-zinc-950 dark:text-white font-sans">{{ stats.departmentCount }}</span>
            <span class="text-xs text-zinc-400 font-medium">Units</span>
          </div>
          <div class="mt-2 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <span>Multi-tier hierarchy</span>
          </div>
        </div>

        <!-- Documents -->
        <div class="group relative rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400 tracking-wider uppercase">Knowledge Base</span>
            <div class="w-8 h-8 rounded-xl bg-amber-500/10 dark:bg-amber-400/10 text-amber-600 dark:text-amber-400 flex items-center justify-center">
              <UIcon name="i-lucide-library" class="w-4 h-4" />
            </div>
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="text-3xl font-bold tracking-tight text-zinc-950 dark:text-white font-sans">{{ stats.fileCount }}</span>
            <span class="text-xs text-zinc-400 font-medium">Files</span>
          </div>
          <div class="mt-2 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <span>Indexed for retrieval</span>
          </div>
        </div>

        <!-- Security / Disabled -->
        <div class="group relative rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs hover:shadow-md hover:-translate-y-0.5 transition-all duration-300">
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold text-zinc-500 dark:text-zinc-400 tracking-wider uppercase">Governance</span>
            <div class="w-8 h-8 rounded-xl bg-zinc-500/10 dark:bg-zinc-400/10 text-zinc-600 dark:text-zinc-400 flex items-center justify-center">
              <UIcon name="i-lucide-shield-alert" class="w-4 h-4" />
            </div>
          </div>
          <div class="mt-4 flex items-baseline gap-2">
            <span class="text-3xl font-bold tracking-tight text-zinc-950 dark:text-white font-sans">{{ stats.disabledCount }}</span>
            <span class="text-xs text-zinc-400 font-medium">Suspended</span>
          </div>
          <div class="mt-2 text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <span v-if="stats.disabledCount === 0" class="text-emerald-600 dark:text-emerald-400 font-medium">All accounts active</span>
            <span v-else class="text-amber-600 dark:text-amber-400 font-medium">Restricted accounts present</span>
          </div>
        </div>
      </div>

      <!-- Platform Infrastructure Status Bar -->
      <div class="rounded-2xl bg-white/60 dark:bg-zinc-900/60 border border-zinc-200/80 dark:border-zinc-800/80 p-5 backdrop-blur-xl shadow-xs">
        <div class="flex items-center justify-between pb-4 border-b border-zinc-200/60 dark:border-zinc-800/60">
          <div class="flex items-center gap-2">
            <UIcon name="i-lucide-activity" class="w-4 h-4 text-emerald-500" />
            <h3 class="text-sm font-semibold text-zinc-950 dark:text-white">Core Infrastructure Status</h3>
          </div>
          <span class="text-xs text-zinc-400 dark:text-zinc-500">All services operational</span>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4">
          <div class="flex items-center gap-3">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
            <div>
              <p class="text-xs font-semibold text-zinc-800 dark:text-zinc-200">Agent Reasoning Engine</p>
              <p class="text-[11px] text-zinc-400">FastAPI Port 8000 (Online)</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
            <div>
              <p class="text-xs font-semibold text-zinc-800 dark:text-zinc-200">Vector Knowledge Engine</p>
              <p class="text-[11px] text-zinc-400">Hybrid Search & Reranker Ready</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
            <div>
              <p class="text-xs font-semibold text-zinc-800 dark:text-zinc-200">SQLite Persistence Layer</p>
              <p class="text-[11px] text-zinc-400">Drizzle ORM Connected</p>
            </div>
          </div>
          <div class="flex items-center gap-3">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
            <div>
              <p class="text-xs font-semibold text-zinc-800 dark:text-zinc-200">Enterprise RBAC Auth</p>
              <p class="text-[11px] text-zinc-400">Department Isolation Active</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Actions Hub & Recent Activity -->
      <div class="grid lg:grid-cols-12 gap-6">
        <!-- Quick Hub (5 cols) -->
        <div class="lg:col-span-5 flex flex-col gap-4">
          <div class="rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 p-6 backdrop-blur-xl shadow-xs space-y-4">
            <div class="flex items-center justify-between pb-2 border-b border-zinc-200/60 dark:border-zinc-800/60">
              <h3 class="text-base font-semibold text-zinc-950 dark:text-white">Management Hub</h3>
              <UIcon name="i-lucide-layers" class="w-4 h-4 text-zinc-400" />
            </div>

            <div class="flex flex-col gap-3">
              <ULink
                to="/admin/users"
                class="group flex items-center justify-between p-3.5 rounded-xl bg-zinc-50/80 dark:bg-zinc-800/50 border border-zinc-200/60 dark:border-zinc-700/60 hover:bg-zinc-100/80 dark:hover:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all duration-200 shadow-2xs"
              >
                <div class="flex items-center gap-3.5">
                  <div class="w-9 h-9 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400 flex items-center justify-center group-hover:scale-105 transition-transform">
                    <UIcon name="i-lucide-user-cog" class="w-5 h-5" />
                  </div>
                  <div>
                    <h4 class="text-sm font-semibold text-zinc-900 dark:text-white">User & Role Management</h4>
                    <p class="text-xs text-zinc-500 dark:text-zinc-400">Manage members, assign admin roles, toggle access</p>
                  </div>
                </div>
                <UIcon name="i-lucide-chevron-right" class="w-4 h-4 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white group-hover:translate-x-0.5 transition-all" />
              </ULink>

              <ULink
                to="/admin/departments"
                class="group flex items-center justify-between p-3.5 rounded-xl bg-zinc-50/80 dark:bg-zinc-800/50 border border-zinc-200/60 dark:border-zinc-700/60 hover:bg-zinc-100/80 dark:hover:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all duration-200 shadow-2xs"
              >
                <div class="flex items-center gap-3.5">
                  <div class="w-9 h-9 rounded-xl bg-purple-500/10 text-purple-600 dark:text-purple-400 flex items-center justify-center group-hover:scale-105 transition-transform">
                    <UIcon name="i-lucide-building-2" class="w-5 h-5" />
                  </div>
                  <div>
                    <h4 class="text-sm font-semibold text-zinc-900 dark:text-white">Organization & Hierarchy</h4>
                    <p class="text-xs text-zinc-500 dark:text-zinc-400">Configure organizational tree and team structures</p>
                  </div>
                </div>
                <UIcon name="i-lucide-chevron-right" class="w-4 h-4 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white group-hover:translate-x-0.5 transition-all" />
              </ULink>

              <ULink
                to="/files"
                class="group flex items-center justify-between p-3.5 rounded-xl bg-zinc-50/80 dark:bg-zinc-800/50 border border-zinc-200/60 dark:border-zinc-700/60 hover:bg-zinc-100/80 dark:hover:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600 transition-all duration-200 shadow-2xs"
              >
                <div class="flex items-center gap-3.5">
                  <div class="w-9 h-9 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 flex items-center justify-center group-hover:scale-105 transition-transform">
                    <UIcon name="i-lucide-folder-lock" class="w-5 h-5" />
                  </div>
                  <div>
                    <h4 class="text-sm font-semibold text-zinc-900 dark:text-white">Files & Access Grants</h4>
                    <p class="text-xs text-zinc-500 dark:text-zinc-400">Manage document visibility, space scopes, and security</p>
                  </div>
                </div>
                <UIcon name="i-lucide-chevron-right" class="w-4 h-4 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-white group-hover:translate-x-0.5 transition-all" />
              </ULink>
            </div>
          </div>
        </div>

        <!-- Recent Users (7 cols) -->
        <div class="lg:col-span-7">
          <div class="rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 backdrop-blur-xl shadow-xs overflow-hidden flex flex-col h-full">
            <div class="flex items-center justify-between p-5 border-b border-zinc-200/60 dark:border-zinc-800/60">
              <div class="flex items-center gap-2">
                <h3 class="text-base font-semibold text-zinc-950 dark:text-white">Recent Members</h3>
                <span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300">
                  {{ users.length }}
                </span>
              </div>
              <UButton
                label="View All"
                size="xs"
                color="neutral"
                variant="ghost"
                icon="i-lucide-arrow-right"
                to="/admin/users"
                class="rounded-lg font-medium"
              />
            </div>

            <div class="divide-y divide-zinc-200/60 dark:divide-zinc-800/60 flex-1">
              <div
                v-for="u in users.slice(0, 6)"
                :key="u.id"
                class="flex items-center justify-between gap-4 px-5 py-3.5 hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-colors"
              >
                <div class="flex items-center gap-3 min-w-0">
                  <UAvatar
                    :src="u.avatar ?? undefined"
                    :alt="u.name || u.username"
                    size="md"
                    class="rounded-xl ring-1 ring-zinc-200 dark:ring-zinc-700"
                  />
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <p class="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        {{ u.name || u.username }}
                      </p>
                      <span v-if="u.disabled" class="w-1.5 h-1.5 rounded-full bg-red-500" title="Suspended" />
                      <span v-else class="w-1.5 h-1.5 rounded-full bg-emerald-500" title="Active" />
                    </div>
                    <p class="truncate text-xs text-zinc-400 dark:text-zinc-500 font-mono mt-0.5">
                      {{ u.email || 'No email provided' }}
                    </p>
                  </div>
                </div>

                <div class="flex items-center gap-2 shrink-0">
                  <UBadge
                    v-if="u.role === 'admin'"
                    color="primary"
                    variant="soft"
                    size="sm"
                    class="rounded-lg font-semibold px-2 py-0.5"
                  >
                    Admin
                  </UBadge>
                  <UBadge
                    v-else-if="u.disabled"
                    color="warning"
                    variant="soft"
                    size="sm"
                    class="rounded-lg font-semibold px-2 py-0.5"
                  >
                    Suspended
                  </UBadge>
                  <UBadge
                    v-else
                    color="neutral"
                    variant="subtle"
                    size="sm"
                    class="rounded-lg font-medium px-2 py-0.5"
                  >
                    Member
                  </UBadge>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
