<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Navbar from '../../components/Navbar.vue'
import AdminNav from '../../components/admin/AdminNav.vue'
import { useAdmin, useAdminAccess } from '../../composables/useAdmin'
import type { AdminUser, Department } from '../../composables/useAdmin'

const { listUsers, listDepartments } = useAdmin()
const { checking, allowed, check } = useAdminAccess()

const users = ref<AdminUser[]>([])
const departments = ref<Department[]>([])
const loading = ref(false)
const error = ref('')

const stats = {
  userCount: 0,
  adminCount: 0,
  disabledCount: 0,
  departmentCount: 0,
}

async function load() {
  if (!allowed.value) return
  loading.value = true
  error.value = ''
  try {
    const [u, d] = await Promise.all([listUsers(), listDepartments()])
    users.value = u
    departments.value = d
    stats.userCount = u.length
    stats.adminCount = u.filter(x => x.role === 'admin').length
    stats.disabledCount = u.filter(x => x.disabled).length
    stats.departmentCount = d.length
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
  <UDashboardPanel
    id="admin"
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

          <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <UCard>
              <div class="flex items-center gap-3">
                <div class="rounded-lg bg-(--ui-primary)/10 p-2.5">
                  <UIcon name="i-lucide-users" class="size-5 text-(--ui-primary)" />
                </div>
                <div>
                  <p class="text-sm text-(--ui-text-muted)">Users</p>
                  <p class="text-2xl font-bold">{{ stats.userCount }}</p>
                </div>
              </div>
            </UCard>

            <UCard>
              <div class="flex items-center gap-3">
                <div class="rounded-lg bg-(--ui-success)/10 p-2.5">
                  <UIcon name="i-lucide-shield-check" class="size-5 text-(--ui-success)" />
                </div>
                <div>
                  <p class="text-sm text-(--ui-text-muted)">Admins</p>
                  <p class="text-2xl font-bold">{{ stats.adminCount }}</p>
                </div>
              </div>
            </UCard>

            <UCard>
              <div class="flex items-center gap-3">
                <div class="rounded-lg bg-(--ui-warning)/10 p-2.5">
                  <UIcon name="i-lucide-user-x" class="size-5 text-(--ui-warning)" />
                </div>
                <div>
                  <p class="text-sm text-(--ui-text-muted)">Disabled</p>
                  <p class="text-2xl font-bold">{{ stats.disabledCount }}</p>
                </div>
              </div>
            </UCard>

            <UCard>
              <div class="flex items-center gap-3">
                <div class="rounded-lg bg-(--ui-info)/10 p-2.5">
                  <UIcon name="i-lucide-building-2" class="size-5 text-(--ui-info)" />
                </div>
                <div>
                  <p class="text-sm text-(--ui-text-muted)">Departments</p>
                  <p class="text-2xl font-bold">{{ stats.departmentCount }}</p>
                </div>
              </div>
            </UCard>
          </div>

          <div class="grid md:grid-cols-2 gap-4">
            <UCard>
              <template #header>
                <div class="flex items-center justify-between">
                  <h3 class="font-semibold">Quick actions</h3>
                  <UIcon name="i-lucide-sparkles" class="size-4 text-(--ui-text-muted)" />
                </div>
              </template>
              <div class="flex flex-col gap-2">
                <UButton
                  label="Manage users"
                  icon="i-lucide-user-cog"
                  color="neutral"
                  variant="outline"
                  class="justify-start"
                  to="/admin/users"
                />
                <UButton
                  label="Manage departments"
                  icon="i-lucide-building-2"
                  color="neutral"
                  variant="outline"
                  class="justify-start"
                  to="/admin/departments"
                />
              </div>
            </UCard>

            <UCard v-if="users.length" :ui="{ body: 'p-0' }">
              <template #header>
                <div class="flex items-center justify-between">
                  <h3 class="font-semibold">Recent users</h3>
                  <UButton label="View all" size="xs" color="neutral" variant="ghost" to="/admin/users" />
                </div>
              </template>
              <div class="divide-y divide-(--ui-border)">
                <div v-for="u in users.slice(0, 5)" :key="u.id" class="flex items-center gap-3 px-4 py-3">
                  <UAvatar :src="u.avatar ?? undefined" :alt="u.name" size="sm" />
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium">{{ u.name || u.username }}</p>
                    <p class="truncate text-xs text-(--ui-text-muted)">{{ u.email }}</p>
                  </div>
                  <UBadge v-if="u.role === 'admin'" color="primary" variant="soft" size="sm">Admin</UBadge>
                  <UBadge v-else-if="u.disabled" color="warning" variant="soft" size="sm">Disabled</UBadge>
                </div>
              </div>
            </UCard>
          </div>
        </template>
      </UContainer>
    </template>
  </UDashboardPanel>
</template>
