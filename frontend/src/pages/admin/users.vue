<route lang="yaml">
meta:
  layout: admin
</route>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import UserCreateDialog from '../../components/admin/UserCreateDialog.vue'
import UserEditDialog from '../../components/admin/UserEditDialog.vue'
import { useAdmin, useAdminAccess } from '../../composables/useAdmin'
import type { AdminUser, Department } from '../../composables/useAdmin'

const { listUsers, listDepartments, updateUser } = useAdmin()
const { checking, allowed, check } = useAdminAccess()
const toast = useToast()

const users = ref<AdminUser[]>([])
const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')

const searchQuery = ref('')
const activeFilter = ref<'all' | 'admin' | 'user' | 'disabled'>('all')

const showCreate = ref(false)
const editingUser = ref<AdminUser | null>(null)

const departmentNameById = computed(() => {
  const map = new Map<string, string>()
  for (const d of departments.value) map.set(d.id, d.name)
  return map
})

function deptNames(ids: string[]): string {
  return ids.map(id => departmentNameById.value.get(id) ?? id).join(', ') || '—'
}

const filteredUsers = computed(() => {
  let list = users.value
  if (activeFilter.value === 'admin') {
    list = list.filter(u => u.role === 'admin')
  } else if (activeFilter.value === 'user') {
    list = list.filter(u => u.role !== 'admin' && !u.disabled)
  } else if (activeFilter.value === 'disabled') {
    list = list.filter(u => u.disabled)
  }

  if (!searchQuery.value.trim()) return list
  const q = searchQuery.value.toLowerCase().trim()
  return list.filter(u =>
    (u.name && u.name.toLowerCase().includes(q)) ||
    (u.username && u.username.toLowerCase().includes(q)) ||
    (u.email && u.email.toLowerCase().includes(q)) ||
    u.departmentIds.some(id => (departmentNameById.value.get(id) || '').toLowerCase().includes(q))
  )
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [u, d] = await Promise.all([listUsers(), listDepartments()])
    users.value = u
    departments.value = d
  }
  catch (e: any) {
    error.value = e?.data?.message || e?.message || 'Failed to load users'
  }
  finally {
    loading.value = false
  }
}

function onCreated() {
  toast.add({ title: 'User created successfully', color: 'success' })
  load()
}

function onUpdated() {
  toast.add({ title: 'User updated successfully', color: 'success' })
  load()
}

async function toggleDisabled(user: AdminUser) {
  try {
    await updateUser(user.id, { disabled: !user.disabled })
    user.disabled = !user.disabled
    toast.add({
      title: user.disabled ? 'Account suspended' : 'Account activated',
      color: 'neutral',
    })
  }
  catch (e: any) {
    toast.add({ title: e?.data?.message || 'Failed to update user status', color: 'error' })
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
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-6 border-b border-zinc-200/80 dark:border-zinc-800/80">
      <div class="space-y-1">
        <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-950 dark:text-white">
          User & Role Management
        </h1>
        <p class="text-sm text-zinc-500 dark:text-zinc-400">
          Manage platform members, assign administrator privileges, and allocate departments
        </p>
      </div>
      <div class="flex items-center gap-2.5">
        <UButton
          label="Add User"
          icon="i-lucide-user-plus"
          color="primary"
          size="sm"
          class="rounded-xl shadow-xs font-semibold px-4 py-2"
          @click="showCreate = true"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          class="rounded-xl shadow-2xs font-medium"
          @click="load"
        />
      </div>
    </div>

    <!-- Loading State -->
    <template v-if="checking || (loading && !users.length)">
      <div class="flex flex-col items-center justify-center py-24 gap-3">
        <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-zinc-900 dark:text-white" />
        <p class="text-sm text-zinc-400">Loading users...</p>
      </div>
    </template>

    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" class="rounded-2xl" />

      <!-- Search and Filter Control Bar -->
      <div class="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <!-- Search input -->
        <div class="relative flex-1 max-w-md">
          <UIcon name="i-lucide-search" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Search name, username, email, or department..."
            class="w-full pl-9 pr-4 py-2 text-sm bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 rounded-xl outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 backdrop-blur-md transition-all"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
            @click="searchQuery = ''"
          >
            <UIcon name="i-lucide-x" class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- Filter Segmented Pills -->
        <div class="flex items-center gap-1 p-1 bg-zinc-200/50 dark:bg-zinc-800/50 rounded-xl border border-zinc-300/40 dark:border-zinc-700/40 backdrop-blur-md self-start sm:self-auto">
          <button
            type="button"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-lg transition-all',
              activeFilter === 'all'
                ? 'bg-white dark:bg-zinc-900 text-zinc-950 dark:text-white shadow-xs font-semibold'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
            ]"
            @click="activeFilter = 'all'"
          >
            All ({{ users.length }})
          </button>
          <button
            type="button"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-lg transition-all',
              activeFilter === 'admin'
                ? 'bg-white dark:bg-zinc-900 text-primary-600 dark:text-primary-400 shadow-xs font-semibold'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
            ]"
            @click="activeFilter = 'admin'"
          >
            Admins ({{ users.filter(u => u.role === 'admin').length }})
          </button>
          <button
            type="button"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-lg transition-all',
              activeFilter === 'user'
                ? 'bg-white dark:bg-zinc-900 text-zinc-950 dark:text-white shadow-xs font-semibold'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
            ]"
            @click="activeFilter = 'user'"
          >
            Members
          </button>
          <button
            type="button"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-lg transition-all',
              activeFilter === 'disabled'
                ? 'bg-white dark:bg-zinc-900 text-red-600 dark:text-red-400 shadow-xs font-semibold'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
            ]"
            @click="activeFilter = 'disabled'"
          >
            Suspended ({{ users.filter(u => u.disabled).length }})
          </button>
        </div>
      </div>

      <!-- Users Acrylic Table Card -->
      <div class="rounded-2xl bg-white/80 dark:bg-zinc-900/80 border border-zinc-200/90 dark:border-zinc-800/80 backdrop-blur-xl shadow-xs overflow-hidden">
        <UTable
          :data="filteredUsers"
          :columns="[
            { id: 'user', accessorKey: 'name', header: 'Member' },
            { accessorKey: 'email', header: 'Email Address' },
            { accessorKey: 'role', header: 'Role' },
            { id: 'departments', accessorKey: 'departmentIds', header: 'Departments' },
            { id: 'status', accessorKey: 'disabled', header: 'Status' },
            { id: 'actions', header: 'Actions' },
          ]"
          :loading="loading"
          :ui="{
            thead: 'bg-zinc-50/70 dark:bg-zinc-900/50 border-b border-zinc-200/80 dark:border-zinc-800/80 text-xs font-semibold text-zinc-500 uppercase tracking-wider',
            td: 'whitespace-nowrap py-3.5 px-4 text-sm'
          }"
        >
          <template #user-cell="{ row }">
            <div class="flex items-center gap-3">
              <UAvatar
                :src="row.original.avatar ?? undefined"
                :alt="row.original.name"
                size="sm"
                class="rounded-xl ring-1 ring-zinc-200/80 dark:ring-zinc-700/80"
              />
              <div class="min-w-0">
                <p class="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {{ row.original.name || row.original.username }}
                </p>
                <p class="text-xs text-zinc-400 dark:text-zinc-500 font-mono">
                  @{{ row.original.username }}
                </p>
              </div>
            </div>
          </template>

          <template #email-cell="{ row }">
            <span class="text-sm font-mono text-zinc-600 dark:text-zinc-400">
              {{ row.original.email || '—' }}
            </span>
          </template>

          <template #role-cell="{ row }">
            <UBadge
              v-if="row.original.role === 'admin'"
              color="primary"
              variant="soft"
              size="sm"
              class="rounded-lg font-semibold px-2 py-0.5"
            >
              <UIcon name="i-lucide-shield-check" class="w-3.5 h-3.5 mr-1" />
              Admin
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
          </template>

          <template #departments-cell="{ row }">
            <div class="flex flex-wrap gap-1 items-center">
              <span
                v-if="row.original.departmentIds && row.original.departmentIds.length"
                class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-zinc-100 dark:bg-zinc-800 text-xs text-zinc-700 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60"
              >
                <UIcon name="i-lucide-building" class="w-3 h-3 text-zinc-400" />
                {{ deptNames(row.original.departmentIds) }}
              </span>
              <span v-else class="text-xs text-zinc-400">Unassigned</span>
            </div>
          </template>

          <template #status-cell="{ row }">
            <div class="flex items-center gap-1.5">
              <span
                class="w-2 h-2 rounded-full"
                :class="row.original.disabled ? 'bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.7)]' : 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.7)]'"
              />
              <span class="text-xs font-medium" :class="row.original.disabled ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'">
                {{ row.original.disabled ? 'Suspended' : 'Active' }}
              </span>
            </div>
          </template>

          <template #actions-cell="{ row }">
            <div class="flex items-center justify-end gap-1.5">
              <UButton
                :icon="row.original.disabled ? 'i-lucide-check-circle-2' : 'i-lucide-ban'"
                :color="row.original.disabled ? 'success' : 'neutral'"
                variant="ghost"
                size="sm"
                class="rounded-lg"
                :title="row.original.disabled ? 'Activate Account' : 'Suspend Account'"
                @click="toggleDisabled(row.original)"
              />
              <UButton
                icon="i-lucide-pencil"
                color="neutral"
                variant="ghost"
                size="sm"
                class="rounded-lg"
                title="Edit User Details"
                @click="editingUser = row.original"
              />
            </div>
          </template>
        </UTable>

        <!-- Empty search result fallback -->
        <div v-if="!filteredUsers.length" class="flex flex-col items-center justify-center py-16 text-center space-y-2">
          <UIcon name="i-lucide-user-x" class="w-10 h-10 text-zinc-300 dark:text-zinc-600" />
          <p class="text-sm font-medium text-zinc-600 dark:text-zinc-400">No matching members found</p>
          <p class="text-xs text-zinc-400">Try adjusting your search query or filter criteria</p>
        </div>
      </div>

      <UserCreateDialog
        v-if="showCreate"
        :departments="departments"
        @close="showCreate = false"
        @created="onCreated"
      />

      <UserEditDialog
        v-if="editingUser"
        :user="editingUser"
        :departments="departments"
        @close="editingUser = null"
        @updated="onUpdated"
      />
    </template>
  </div>
</template>
