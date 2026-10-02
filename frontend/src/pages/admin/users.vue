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
  toast.add({ title: '用户创建成功', color: 'success' })
  load()
}

function onUpdated() {
  toast.add({ title: '用户信息更新成功', color: 'success' })
  load()
}

async function toggleDisabled(user: AdminUser) {
  try {
    await updateUser(user.id, { disabled: !user.disabled })
    user.disabled = !user.disabled
    toast.add({
      title: user.disabled ? '已禁用该用户账号' : '已启用该用户账号',
      color: 'neutral',
    })
  }
  catch (e: any) {
    toast.add({ title: e?.data?.message || '更新用户状态失败', color: 'error' })
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
        <h1 class="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">用户管理</h1>
        <p class="text-sm text-zinc-500 dark:text-zinc-400 mt-1">创建、编辑和管理平台用户角色与部门权限</p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          label="添加用户"
          icon="i-lucide-user-plus"
          color="primary"
          size="sm"
          class="shadow-xs font-medium"
          @click="showCreate = true"
        />
        <UButton
          icon="i-lucide-refresh-cw"
          color="neutral"
          variant="outline"
          size="sm"
          :loading="loading"
          @click="load"
        />
      </div>
    </div>

    <!-- Loading State -->
    <template v-if="checking || loading && !users.length">
      <div class="flex flex-col items-center justify-center py-20 gap-3">
        <UIcon name="i-lucide-loader-circle" class="size-8 animate-spin text-primary-500" />
        <p class="text-sm text-zinc-400">正在载入用户列表...</p>
      </div>
    </template>

    <template v-else>
      <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

      <!-- Users Table Card -->
      <UCard :ui="{ body: 'p-0' }" class="border border-zinc-200 dark:border-zinc-800/80 shadow-xs overflow-hidden">
        <UTable
          :data="users"
          :columns="[
            { id: 'user', accessorKey: 'name', header: '用户' },
            { accessorKey: 'email', header: '邮箱' },
            { accessorKey: 'role', header: '角色' },
            { id: 'departments', accessorKey: 'departmentIds', header: '所属部门' },
            { id: 'status', accessorKey: 'disabled', header: '状态' },
            { id: 'actions', header: '操作' },
          ]"
          :loading="loading"
          :ui="{ td: 'whitespace-nowrap py-3' }"
        >
          <template #user-cell="{ row }">
            <div class="flex items-center gap-3">
              <UAvatar :src="row.original.avatar ?? undefined" :alt="row.original.name" size="sm" />
              <div>
                <p class="text-sm font-medium text-zinc-900 dark:text-zinc-100">{{ row.original.name || row.original.username }}</p>
                <p class="text-xs text-zinc-500">@{{ row.original.username }}</p>
              </div>
            </div>
          </template>

          <template #role-cell="{ row }">
            <UBadge v-if="row.original.role === 'admin'" color="primary" variant="soft" size="sm">管理员</UBadge>
            <UBadge v-else color="neutral" variant="subtle" size="sm">普通用户</UBadge>
          </template>

          <template #departments-cell="{ row }">
            <span class="text-sm text-zinc-600 dark:text-zinc-400">{{ deptNames(row.original.departmentIds) }}</span>
          </template>

          <template #status-cell="{ row }">
            <UBadge
              :color="row.original.disabled ? 'warning' : 'success'"
              variant="soft"
              size="sm"
            >
              {{ row.original.disabled ? '已禁用' : '正常' }}
            </UBadge>
          </template>

          <template #actions-cell="{ row }">
            <div class="flex items-center justify-end gap-1">
              <UButton
                :icon="row.original.disabled ? 'i-lucide-check-circle' : 'i-lucide-ban'"
                color="neutral"
                variant="ghost"
                size="sm"
                :title="row.original.disabled ? '启用账号' : '禁用账号'"
                @click="toggleDisabled(row.original)"
              />
              <UButton
                icon="i-lucide-pencil"
                color="neutral"
                variant="ghost"
                size="sm"
                title="编辑用户"
                @click="editingUser = row.original"
              />
            </div>
          </template>
        </UTable>
      </UCard>

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
