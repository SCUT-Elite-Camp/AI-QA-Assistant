<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import Navbar from '../../components/Navbar.vue'
import AdminNav from '../../components/admin/AdminNav.vue'
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
  toast.add({ title: 'User created', color: 'success' })
  load()
}

function onUpdated() {
  toast.add({ title: 'User updated', color: 'success' })
  load()
}

async function toggleDisabled(user: AdminUser) {
  try {
    await updateUser(user.id, { disabled: !user.disabled })
    user.disabled = !user.disabled
    toast.add({
      title: user.disabled ? 'User disabled' : 'User enabled',
      color: 'neutral',
    })
  }
  catch (e: any) {
    toast.add({ title: e?.data?.message || 'Failed to update user', color: 'error' })
  }
}

onMounted(async () => {
  await check()
  if (allowed.value) await load()
})
</script>

<template>
  <UDashboardPanel
    id="admin-users"
    class="min-h-0"
    :ui="{ body: 'p-0 sm:p-0' }"
  >
    <template #header>
      <Navbar />
    </template>

    <template #body>
      <UContainer class="flex-1 py-6 sm:py-8 space-y-6">
        <AdminNav />

        <template v-if="checking">
          <div class="flex justify-center py-16">
            <UIcon name="i-lucide-loader-circle" class="size-6 animate-spin text-(--ui-text-muted)" />
          </div>
        </template>

        <template v-else-if="!allowed">
          <UCard>
            <div class="flex flex-col items-center gap-3 py-12 text-center">
              <UIcon name="i-lucide-shield-alert" class="size-10 text-(--ui-text-muted)" />
              <h2 class="text-lg font-semibold">Access denied</h2>
              <p class="text-sm text-(--ui-text-muted)">You need administrator privileges to view this page.</p>
            </div>
          </UCard>
        </template>

        <template v-else>
          <UAlert v-if="error" :title="error" color="error" variant="soft" icon="i-lucide-circle-alert" />

          <div class="flex items-center justify-between">
            <div>
              <h2 class="text-lg font-semibold">Users</h2>
              <p class="text-sm text-(--ui-text-muted)">Create, edit and manage user accounts.</p>
            </div>
            <UButton
              label="Create user"
              icon="i-lucide-user-plus"
              @click="showCreate = true"
            />
          </div>

          <UCard :ui="{ body: 'p-0' }">
            <UTable
              :data="users"
              :columns="[
                { id: 'user', accessorKey: 'name', header: 'User' },
                { accessorKey: 'email', header: 'Email' },
                { accessorKey: 'role', header: 'Role' },
                { id: 'departments', accessorKey: 'departmentIds', header: 'Departments' },
                { id: 'status', accessorKey: 'disabled', header: 'Status' },
                { id: 'actions', header: ' ' },
              ]"
              :loading="loading"
              :ui="{ td: { base: 'whitespace-nowrap' } }"
            >
              <template #user-cell="{ row }">
                <div class="flex items-center gap-3">
                  <UAvatar :src="row.original.avatar ?? undefined" :alt="row.original.name" size="sm" />
                  <div>
                    <p class="text-sm font-medium">{{ row.original.name || row.original.username }}</p>
                    <p class="text-xs text-(--ui-text-muted)">@{{ row.original.username }}</p>
                  </div>
                </div>
              </template>

              <template #role-cell="{ row }">
                <UBadge v-if="row.original.role === 'admin'" color="primary" variant="soft" size="sm">Admin</UBadge>
                <UBadge v-else color="neutral" variant="soft" size="sm">User</UBadge>
              </template>

              <template #departments-cell="{ row }">
                <span class="text-sm text-(--ui-text-muted)">{{ deptNames(row.original.departmentIds) }}</span>
              </template>

              <template #status-cell="{ row }">
                <UBadge
                  :color="row.original.disabled ? 'warning' : 'success'"
                  variant="soft"
                  size="sm"
                >
                  {{ row.original.disabled ? 'Disabled' : 'Active' }}
                </UBadge>
              </template>

              <template #actions-cell="{ row }">
                <div class="flex items-center justify-end gap-1">
                  <UButton
                    icon="i-lucide-toggle-right"
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    :title="row.original.disabled ? 'Enable user' : 'Disable user'"
                    @click="toggleDisabled(row.original)"
                  />
                  <UButton
                    icon="i-lucide-pencil"
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    title="Edit user"
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
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
